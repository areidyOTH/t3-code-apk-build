"""Trusted signing job. Never execute or import anything from build outputs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request
from adapt import adapted, patch
from android_tools import install as install_tools, SHA256 as SIGNING_TOOLS_SHA256
from policy import Denied, ROOT, check_time, digest, now, release, tag


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def signer_fingerprints(text):
    # Build Tools37 prefixes certificates with their verified signature scheme;
    # older apksigner versions use numbered signers without a scheme prefix.
    pattern = r"(?:Signer #[1-9]\d*|(?:V1|V2|V3\.0|V3\.1) Signer(?: #[1-9]\d*)?:) certificate SHA-256 digest: ([0-9a-f]{64})"
    fingerprints = []
    counts = []
    scheme_label = False
    for line in text.splitlines():
        if line.startswith("Number of signers:"):
            match = re.fullmatch(r"Number of signers: ([1-9]\d*)", line)
            if not match:
                return []
            counts.append(int(match[1]))
        if "certificate SHA-256 digest:" in line:
            match = re.fullmatch(pattern, line)
            if not match:
                return []  # Never ignore an unrecognized or malformed certificate.
            fingerprints.append(match[1])
            scheme_label = scheme_label or line.startswith("V")
    if (counts and counts != [1]) or (scheme_label and counts != [1]):
        return []
    return fingerprints


def ota_disabled(text):
    entries = re.split(r"\n\s*E: meta-data", text)
    for entry in entries[1:]:
        if '"expo.modules.updates.ENABLED"' in entry:
            match = re.search(r"android:value[^\n]*=\s*(?:\(type 0x12\))?(false|0x[0-9a-fA-F]+)(?:\s|$)", entry)
            return bool(match and (match[1] == "false" or int(match[1], 16) == 0))
    return False


def main():
    check_time(now())
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise Denied("only first-attempt public GitHub-hosted runs may sign")
    data = release()
    if not data["enabled"] or data["build"]["signer_certificate_sha256"] is None:
        raise Denied("release/signing disabled")
    out = ROOT / "dist"
    allowed = {"unsigned.apk", "dependency-inventory.json", "toolchain.json", "image-id.txt"}
    if {x.name for x in out.iterdir()} != allowed or any(not x.is_file() or x.is_symlink() for x in out.iterdir()):
        raise Denied("unexpected unsigned artifact contents")
    unsigned_sha = digest(out / "unsigned.apk")
    tools = install_tools(ROOT / ".work/signing-tools")
    apksigner = str(tools / "apksigner")
    # Never use shell arguments or command files for passwords.
    with tempfile.TemporaryDirectory() as private:
        private = Path(private)
        key = private / "signer.jks"
        key.write_bytes(base64.b64decode(os.environ["APK_KEYSTORE_B64"], validate=True))
        key.chmod(0o600)
        for env in ("APK_STORE_PASSWORD", "APK_KEY_PASSWORD"):
            (private / env).write_text(os.environ[env])
            (private / env).chmod(0o600)
        aligned = private / "aligned.apk"
        run(str(tools / "zipalign"), "-P", "16", "-f", "4", str(out / "unsigned.apk"), str(aligned))
        run(apksigner, "sign", "--v4-signing-enabled", "false", "--ks", str(key), "--ks-key-alias", os.environ["APK_KEY_ALIAS"],
            "--ks-pass", "file:" + str(private / "APK_STORE_PASSWORD"),
            "--key-pass", "file:" + str(private / "APK_KEY_PASSWORD"),
            "--out", str(out / "t3-code.apk"), str(aligned))
    signature = subprocess.check_output([apksigner, "verify", "--verbose", "--print-certs", str(out / "t3-code.apk")], text=True)
    if signer_fingerprints(signature) != [data["build"]["signer_certificate_sha256"]]:
        raise Denied("APK signer differs from reviewed manifest")
    (out / "apk-signature.txt").write_text(signature)
    badging = subprocess.check_output([str(tools / "aapt"), "dump", "badging", str(out / "t3-code.apk")], text=True)
    package = re.search(r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", badging, re.M)
    if not package or package.groups() != (data["android_package"], str(data["version_code"]), data["version_name"]):
        raise Denied("final APK package/version differs from release manifest")
    manifest_xml = subprocess.check_output([str(tools / "aapt2"), "dump", "xmltree", str(out / "t3-code.apk"), "--file", "AndroidManifest.xml"], text=True)
    # Native OTA enable flag must be present and false (aapt2 renders boolean false as0).
    if not ota_disabled(manifest_xml):
        raise Denied("cannot verify Expo OTA is disabled in final APK")
    (out / "android-badging.txt").write_text(badging)
    (out / "android-manifest.txt").write_text(manifest_xml)
    url = f"https://raw.githubusercontent.com/pingdotgg/t3code/{data['source_sha']}/apps/mobile/app.config.ts"
    before = urllib.request.urlopen(url, timeout=30).read().decode()
    after = adapted(before, data["version_code"], data["android_package"])
    (out / "source-diff.patch").write_text(patch(before, after))
    (out / "unsigned.gradle").write_bytes((ROOT / "build/unsigned.gradle").read_bytes())
    (out / "container-build-recipe.py").write_bytes((ROOT / "build/container_build.py").read_bytes())
    (out / "builder.Dockerfile").write_bytes((ROOT / "build/Dockerfile").read_bytes())
    metadata = {"schema": 1, "release": data, "support_policy": json.loads((ROOT / "policy/support.json").read_text()),
        "public_environment": json.loads((ROOT / "policy/public-environment.json").read_text()),
        "builder_repository": os.environ["GITHUB_REPOSITORY"], "builder_commit": os.environ["GITHUB_SHA"],
        "workflow": ".github/workflows/build-apk.yml", "run_id": int(os.environ["GITHUB_RUN_ID"]),
        "run_attempt": 1, "quota_claim_id": int(os.environ["QUOTA_CLAIM_ID"]),
        "unsigned_apk_sha256": unsigned_sha, "apk_sha256": digest(out / "t3-code.apk"),
        "source_diff_sha256": digest(out / "source-diff.patch"), "build_image_id": (out / "image-id.txt").read_text().strip(),
        "apksigner_jar_sha256": digest(tools / "lib/apksigner.jar"), "signing_tools_archive_sha256": SIGNING_TOOLS_SHA256, "signed_at": now().isoformat(),
        "adaptations": ["own Android package and display name", "explicit Play version code", "Expo OTA disabled", "unsigned release init script before trusted signing", "generated Gradle wrapper SHA256 pinned to official9.4.1 checksum"],
        "dependency_inventory_origin": "source build container; observed resolved files, not a preverified dependency lock",
        "parity_limits": "No upstream private EAS environment; managed T3 Connect and production services may differ. No reproducibility or malware-free claim."}
    (out / "build-manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (out / "public-environment.json").write_bytes((ROOT / "policy/public-environment.json").read_bytes())
    (out / "unsigned.apk").unlink()
    with (out / "SHA256SUMS").open("w") as sums:
        for item in sorted(out.iterdir()):
            if item.name != "SHA256SUMS":
                sums.write(digest(item) + "  " + item.name + "\n")


if __name__ == "__main__":
    main()
