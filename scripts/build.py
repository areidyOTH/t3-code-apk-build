"""Trusted source-build entrypoint; refuses reruns and checks live expiry."""
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
from policy import Denied, ROOT, POLICY, check_time, day, digest, now, release, timestamp
from gate import GitHub


def checked(*args):
    return subprocess.run(args, check=True)


def extract_outputs(archive, destination):
    expected = {"unsigned.apk", "dependency-inventory.json", "toolchain.json"}
    with tarfile.open(archive) as bundle:
        files = {}
        for member in bundle.getmembers():
            if member.isdir() and member.name == "out":
                continue
            if not member.isfile() or member.name not in {"out/" + x for x in expected}:
                raise Denied("unexpected or unsafe sandbox output")
            if member.name in files or member.size > 1024 * 1024 * 1024:
                raise Denied("duplicate or oversized sandbox output")
            files[member.name] = member
        if set(files) != {"out/" + x for x in expected}:
            raise Denied("missing sandbox output")
        destination.mkdir(parents=True, exist_ok=True)
        for name, member in files.items():
            with bundle.extractfile(member) as src, (destination / Path(name).name).open("wb") as target:
                shutil.copyfileobj(src, target)


def main():
    check_time(now())
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise Denied("only first-attempt public GitHub-hosted runs may build")
    data = release()
    if not data["enabled"] or not data["build"]["signer_certificate_sha256"]:
        raise Denied("release/signing is not configured")
    work = ROOT / ".work"
    work.mkdir(exist_ok=True)
    # Context contains trusted recipe only; never the repository or secrets.
    context = work / "recipe"
    context.mkdir(exist_ok=True)
    for name in ("Dockerfile", "container_build.py", "unsigned.gradle"):
        shutil.copyfile(ROOT / "build" / name, context / name)
    shutil.copyfile(ROOT / "scripts/adapt.py", context / "adapt.py")
    shutil.copyfile(ROOT / "policy/public-environment.json", context / "public-environment.json")
    checked("docker", "build", "--platform", "linux/amd64", "--tag", "t3-apk-builder:local", str(context))
    (work / "image-id.txt").write_text(subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", "t3-apk-builder:local"], text=True))
    # Check immediately before source execution, after toolchain provisioning.
    check_time(now())
    claim = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"]).request("/deployments/" + str(int(os.environ["QUOTA_CLAIM_ID"])))
    payload = claim.get("payload")
    if (claim.get("environment") != POLICY["quota_environment"] or claim.get("task") != POLICY["quota_task"]
            or not isinstance(payload, dict) or payload.get("run_id") != int(os.environ["GITHUB_RUN_ID"])
            or payload.get("run_attempt") != 1 or payload.get("source_sha") != data["source_sha"]
            or payload.get("manifest_sha256") != digest(ROOT / "policy/release.json")
            or payload.get("melbourne_day") != day(now())):
        raise Denied("no matching current-day irreversible build claim")
    container = subprocess.check_output(["docker", "create", "--name", "t3-apk-source", "--user", "1000:1000",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "4096", "--memory", "12g", "--cpus", "4",
        "t3-apk-builder:local", data["source_sha"], str(data["version_code"]), data["android_package"]], text=True).strip()
    try:
        # Recheck after all API/provisioning latency; never start after cutoff/midnight.
        current = now()
        check_time(current)
        if payload["melbourne_day"] != day(current):
            raise Denied("allowance day ended before actual build")
        remaining = (timestamp(POLICY["expires_at"]) - current).total_seconds()
        subprocess.run(["docker", "start", "--attach", container], check=True, timeout=remaining)
        status = subprocess.check_output(["docker", "inspect", "--format", "{{.State.ExitCode}}", container], text=True).strip()
        if status != "0":
            raise Denied("source build failed")
        archive = work / "outputs.tar"
        with archive.open("wb") as target:
            subprocess.run(["docker", "cp", container + ":/work/out", "-"], stdout=target, check=True)
        extract_outputs(archive, ROOT / "dist")
        shutil.copyfile(work / "image-id.txt", ROOT / "dist/image-id.txt")
    finally:
        subprocess.run(["docker", "rm", "--force", container], check=False)


if __name__ == "__main__":
    main()
