"""Executed only as non-root inside the credential-free source container."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from adapt import apply


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


sha, code, package = sys.argv[1:]
if not re.fullmatch(r"[0-9a-f]{40}", sha) or not code.isdigit() or not re.fullmatch(r"[a-z][a-z0-9_.]+", package):
    raise SystemExit("invalid reviewed source parameters")
source = Path("/work/source")
out = Path("/work/out")
out.mkdir()
run("git", "init", str(source))
run("git", "-C", str(source), "remote", "add", "origin", "https://github.com/pingdotgg/t3code.git")
run("git", "-C", str(source), "fetch", "--depth=1", "origin", sha)
run("git", "-C", str(source), "checkout", "--detach", "FETCH_HEAD")
actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
if actual != sha:
    raise SystemExit("source commit mismatch")
env = json.loads(Path("/recipe/public-environment.json").read_text())
os.environ.update(env)
apply(source, int(code), package)
run("pnpm", "install", "--frozen-lockfile", cwd=source)
mobile = source / "apps/mobile"
run("./node_modules/.bin/expo", "prebuild", "--clean", "--platform", "android", "--no-install", cwd=mobile)
run("bash", "modules/t3-terminal/scripts/build-libghostty-android.sh", cwd=mobile)
native = mobile / "android"
wrapper = native / "gradle/wrapper/gradle-wrapper.properties"
# Verify the downloaded Gradle distribution via its official checksum endpoint.
import urllib.request
props = wrapper.read_text()
url = re.search(r"^distributionUrl=(.+)$", props, re.M).group(1).replace("\\:", ":")
if not re.fullmatch(r"https://services.gradle.org/distributions/gradle-[0-9.]+-(bin|all)\.zip", url):
    raise SystemExit("unexpected Gradle distribution")
if url != "https://services.gradle.org/distributions/gradle-9.4.1-bin.zip":
    raise SystemExit("unreviewed Gradle version")
checksum = "2ab2958f2a1e51120c326cad6f385153bb11ee93b3c216c5fccebfdfbb7ec6cb"
if not re.fullmatch(r"[0-9a-f]{64}", checksum):
    raise SystemExit("invalid Gradle distribution checksum")
if "distributionSha256Sum=" in props:
    raise SystemExit("upstream introduced its own Gradle pin; review recipe")
wrapper.write_text(props + "\ndistributionSha256Sum=" + checksum + "\n")
run("./gradlew", "--no-daemon", "--max-workers=2", "-Dorg.gradle.jvmargs=-Xmx6g -XX:MaxMetaspaceSize=1g", "-I", "/recipe/unsigned.gradle", "app:assembleRelease", cwd=native)
apk = native / "app/build/outputs/apk/release/app-release-unsigned.apk"
if not apk.is_file() or apk.is_symlink():
    raise SystemExit("unsigned release APK was not produced")
shutil.copyfile(apk, out / "unsigned.apk")
inventory = []
for directory in (Path.home() / ".gradle/caches", source / "node_modules/.pnpm"):
    for item in sorted(directory.rglob("*")):
        if item.is_file() and not item.is_symlink() and item.suffix in {".jar", ".aar", ".pom", ".module", ".so"}:
            inventory.append({"path": str(item.relative_to(directory)), "root": directory.name,
                              "sha256": hashlib.sha256(item.read_bytes()).hexdigest()})
(out / "dependency-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
tools = {"node": subprocess.check_output(["node", "--version"], text=True).strip(),
         "pnpm": subprocess.check_output(["pnpm", "--version"], text=True).strip(),
         "gradle_distribution_url": url, "gradle_distribution_sha256": checksum,
         "dpkg": subprocess.check_output(["dpkg-query", "-W"], text=True),
         "android_source_properties": {str(item.relative_to('/opt/android')): item.read_text() for item in Path('/opt/android').rglob('source.properties')},
         "reviewed_native_versions": {"compile_sdk":37,"target_sdk":36,"min_sdk":24,"build_tools":"37.0.0","agp":"9.2.1","kotlin_catalog":"2.2.0","kotlin_configuration_probe":"2.2.10","ndk":"27.1.12297006"}}
(out / "toolchain.json").write_text(json.dumps(tools, indent=2) + "\n")
