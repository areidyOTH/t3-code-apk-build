"""Small, strict release and time policy. No network or builds here."""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "policy/support.json").read_text())
UTC = dt.timezone.utc
SHA = re.compile(r"^[0-9a-f]{40}$")


class Denied(ValueError):
    pass


def timestamp(value):
    if not isinstance(value, str):
        raise Denied("timestamp must be a string")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Denied("invalid timestamp") from exc
    if parsed.tzinfo is None:
        raise Denied("timestamp requires timezone")
    return parsed.astimezone(UTC)


def now():
    return dt.datetime.now(UTC)


def check_time(value):
    if value.tzinfo is None:
        raise Denied("clock requires timezone")
    if not timestamp(POLICY["starts_at"]) <= value < timestamp(POLICY["expires_at"]):
        raise Denied("outside the one-month support interval")


def day(value):
    return value.astimezone(ZoneInfo(POLICY["timezone"])).date().isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def keys(obj, expected):
    if not isinstance(obj, dict) or set(obj) != set(expected):
        raise Denied("unexpected or missing manifest fields")


def release(path=ROOT / "policy/release.json"):
    data = json.loads(Path(path).read_text())
    keys(data, ("schema", "enabled", "upstream_repository", "source_sha", "version_name",
                "version_code", "android_package", "play_beta", "source_mapping", "review", "build"))
    if type(data["schema"]) is not int or data["schema"] != 1 or type(data["enabled"]) is not bool:
        raise Denied("invalid schema/enabled")
    if data["upstream_repository"] != POLICY["upstream_repository"]:
        raise Denied("unapproved upstream repository")
    if not isinstance(data["source_sha"], str) or not SHA.fullmatch(data["source_sha"]):
        raise Denied("source must be an exact commit SHA")
    if type(data["version_code"]) is not int or data["version_code"] <= 0:
        raise Denied("invalid Android version code")
    for name in ("version_name", "android_package"):
        if not isinstance(data[name], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", data[name]):
            raise Denied("invalid version or package")
    keys(data["play_beta"], ("channel", "observed_version_code", "evidence", "observed_at"))
    if data["play_beta"]["channel"] != "public-google-play-beta" or data["play_beta"]["observed_version_code"] != data["version_code"]:
        raise Denied("release is not the observed public Play beta")
    timestamp(data["play_beta"]["observed_at"])
    keys(data["source_mapping"], ("workflow_run_url", "eas_build_id", "source_sha", "version_code", "evidence"))
    mapping = data["source_mapping"]
    if mapping["source_sha"] != data["source_sha"] or mapping["version_code"] != data["version_code"]:
        raise Denied("source mapping mismatch")
    prefix = "https://github.com/" + POLICY["upstream_repository"] + "/actions/runs/"
    if not isinstance(mapping["workflow_run_url"], str) or not mapping["workflow_run_url"].startswith(prefix) or not mapping["workflow_run_url"][len(prefix):].isdigit():
        raise Denied("source mapping must identify an official upstream workflow run")
    if not isinstance(mapping["eas_build_id"], str) or not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", mapping["eas_build_id"]):
        raise Denied("invalid EAS build ID")
    for obj in (mapping, data["play_beta"]):
        if not isinstance(obj["evidence"], str) or len(obj["evidence"].strip()) < 30:
            raise Denied("missing release evidence")
    keys(data["review"], ("reviewed_by", "reviewed_at", "notes"))
    if not isinstance(data["review"]["reviewed_by"], str) or not data["review"]["reviewed_by"].strip() or not isinstance(data["review"]["notes"], str):
        raise Denied("missing review")
    timestamp(data["review"]["reviewed_at"])
    keys(data["build"], ("recipe", "public_environment_sha256", "signer_certificate_sha256"))
    if data["build"]["recipe"] != "expo-prebuild-gradle-release-v1":
        raise Denied("unapproved recipe")
    if data["build"]["public_environment_sha256"] != digest(ROOT / "policy/public-environment.json"):
        raise Denied("public environment hash mismatch")
    signer = data["build"]["signer_certificate_sha256"]
    if signer is not None and (not isinstance(signer, str) or not re.fullmatch(r"[0-9a-f]{64}", signer)):
        raise Denied("invalid pinned APK signer")
    return data


def tag(data):
    return f"play-beta-{data['version_code']}-{data['source_sha'][:12]}"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = release()
    if args.check:
        print(json.dumps({"valid": True, "enabled": data["enabled"], "tag": tag(data)}))
