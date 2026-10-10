"""Verify downloaded release files. Requires gh and Android apksigner on PATH.

APK cryptographic verification is local. GitHub identity/transparency verification
may need network unless gh's trust material and attestation are already available.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from sign import signer_fingerprints


parser = argparse.ArgumentParser()
parser.add_argument("directory", type=Path)
parser.add_argument("--repo", required=True)
parser.add_argument("--signer-sha256", required=True, help="fingerprint from a separately trusted repository/maintainer source")
args = parser.parse_args()
if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo) or not re.fullmatch(r"[0-9a-f]{64}", args.signer_sha256):
    raise SystemExit("invalid repository or certificate fingerprint")
root = args.directory
required = {"t3-code.apk", "build-manifest.json", "source-diff.patch", "public-environment.json", "apk-signature.txt",
            "android-badging.txt", "android-manifest.txt", "dependency-inventory.json", "toolchain.json", "image-id.txt",
            "unsigned.gradle", "container-build-recipe.py", "builder.Dockerfile"}
for filename in required | {"SHA256SUMS", "provenance.json"}:
    if (root / filename).is_symlink() or not (root / filename).is_file():
        raise SystemExit("missing or unsafe release file: " + filename)
subprocess.run(["gh", "attestation", "verify", str(root / "SHA256SUMS"), "--bundle", str(root / "provenance.json"),
    "--repo", args.repo, "--signer-workflow", args.repo + "/.github/workflows/build-apk.yml", "--deny-self-hosted-runners"], check=True)
seen = set()
for line in (root / "SHA256SUMS").read_text().splitlines():
    match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
    if not match:
        raise SystemExit("invalid checksum entry")
    expected, filename = match.groups()
    if filename in seen:
        raise SystemExit("duplicate checksum entry")
    seen.add(filename)
    path = root / filename
    if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit("checksum mismatch: " + filename)
if seen != required:
    raise SystemExit("missing required checksums")
apk = root / "t3-code.apk"
for primary in (apk, root / "build-manifest.json"):
    subprocess.run(["gh", "attestation", "verify", str(primary), "--bundle", str(root / "provenance.json"),
        "--repo", args.repo, "--signer-workflow", args.repo + "/.github/workflows/build-apk.yml", "--deny-self-hosted-runners"], check=True)
signature = subprocess.check_output(["apksigner", "verify", "--verbose", "--print-certs", str(apk)], text=True)
if signer_fingerprints(signature) != [args.signer_sha256]:
    raise SystemExit("APK signer does not match independently trusted certificate")
manifest = json.loads((root / "build-manifest.json").read_text())
if manifest["apk_sha256"] != hashlib.sha256(apk.read_bytes()).hexdigest() or manifest["builder_repository"] != args.repo:
    raise SystemExit("build manifest does not describe APK/repository")
if (manifest["release"]["build"]["signer_certificate_sha256"] != args.signer_sha256
        or manifest["source_diff_sha256"] != hashlib.sha256((root / "source-diff.patch").read_bytes()).hexdigest()
        or manifest["release"]["build"]["public_environment_sha256"] != hashlib.sha256((root / "public-environment.json").read_bytes()).hexdigest()):
    raise SystemExit("build manifest signer/diff/environment mismatch")
print("Verified APK checksum, GitHub workflow provenance, and pinned APK signing certificate.")
