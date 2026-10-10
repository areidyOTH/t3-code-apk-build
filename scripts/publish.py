"""Upload a draft, validate all remote digests, then expose the complete release."""
import json
import os
import subprocess
from policy import Denied, ROOT, check_time, digest, now, release, tag


def validate_assets(files, remote):
    expected = {path.name: "sha256:" + digest(path) for path in files}
    assets = remote.get("assets", [])
    if len(assets) != len(expected) or {item.get("name") for item in assets} != set(expected):
        raise Denied("draft release asset set is incomplete or unexpected")
    if any(item.get("digest") != expected[item["name"]] for item in assets):
        raise Denied("draft release asset digest mismatch")


def main():
    check_time(now())
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise Denied("reruns cannot publish")
    data = release()
    if not data["enabled"]:
        raise Denied("release disabled")
    out = ROOT / "dist"
    notes = ROOT / ".work/release-notes.md"
    notes.parent.mkdir(exist_ok=True)
    notes.write_text(f"Unofficial rebuild of user-observed Google Play beta {data['version_code']} ({data['version_name']}).\n\n"
                    f"Exact upstream source: `{data['source_sha']}`. Own APK signing identity; Expo OTA disabled.\n\n"
                    "Verify the APK using the repository's verification instructions. Provenance records who built the artifact; it does not establish code safety or Play signature equivalence.\n")
    files = sorted(out.iterdir())
    if any(not path.is_file() or path.is_symlink() for path in files):
        raise Denied("unexpected publication file")
    repository = os.environ["GITHUB_REPOSITORY"]
    check_time(now())
    subprocess.run(["gh", "release", "create", tag(data), "--repo", repository, "--draft",
                    "--target", os.environ["GITHUB_SHA"], "--prerelease", "--title", f"Unofficial Play beta {data['version_code']} rebuild",
                    "--notes-file", str(notes), *map(str, files)], check=True)
    # The REST tag endpoint does not retrieve drafts. gh release view implements
    # draft-aware lookup; then fetch assets using the immutable release ID.
    release_id = subprocess.check_output(["gh", "release", "view", tag(data), "--repo", repository,
                                          "--json", "databaseId", "--jq", ".databaseId"], text=True).strip()
    if not release_id.isdigit():
        raise Denied("draft release ID unavailable")
    remote = json.loads(subprocess.check_output(["gh", "api", "repos/" + repository + "/releases/" + release_id], text=True))
    if remote.get("draft") is not True:
        raise Denied("release unexpectedly already public")
    validate_assets(files, remote)
    check_time(now())
    subprocess.run(["gh", "release", "edit", tag(data), "--repo", repository, "--draft=false"], check=True)


if __name__ == "__main__":
    main()
