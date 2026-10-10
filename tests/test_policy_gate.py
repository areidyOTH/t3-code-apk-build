import copy
import datetime as dt
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from policy import Denied, check_time, day, digest, release, timestamp, tag
from gate import GitHub, reserve
from build import extract_outputs
from sign import ota_disabled, signer_fingerprints
from adapt import adapted
from publish import validate_assets


class MockAPI:
    def __init__(self):
        self.claims = []
        self.runs = {}
        self.jobs = {}
        self.published = None
        self.private = False
        self.posts = []

    def request(self, path, payload=None, missing=False):
        if path == "":
            return {"private": self.private}
        if path.startswith("/releases/tags/"):
            return self.published
        if path.startswith("/actions/runs/"):
            key = int(path.rsplit("/", 1)[1])
            if key not in self.runs:
                raise Denied("missing workflow")
            return self.runs[key]
        if path == "/deployments" and payload:
            self.posts.append(payload)
            claim = {"id": len(self.claims) + 1, "payload": copy.deepcopy(payload["payload"])}
            self.claims.append(claim)
            self.runs[payload["payload"]["run_id"]] = {"status": "in_progress"}
            return claim
        raise AssertionError(path)

    def pages(self, path, field=None):
        if path == "/releases":
            return [] if self.published is None else [self.published]
        if path.startswith("/deployments?"):
            return copy.deepcopy(self.claims)
        if path.startswith("/actions/runs/"):
            return self.jobs[int(path.split("/")[3])]
        raise AssertionError(path)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.manifest = release()

    def changed_manifest(self, change):
        data = copy.deepcopy(self.manifest)
        change(data)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.json"
            path.write_text(json.dumps(data))
            return release(path)

    def test_valid_reviewed_release(self):
        self.assertEqual(self.manifest["version_code"], 82)

    def test_mapping_must_match_play_observation(self):
        for change in (lambda x: x["source_mapping"].update(version_code=83),
                       lambda x: x["play_beta"].update(channel="internal"),
                       lambda x: x["play_beta"].update(evidence=""),
                       lambda x: x.update(source_sha="main"),
                       lambda x: x.update(extra="force"),
                       lambda x: x["build"].update(public_environment_sha256="0" * 64)):
            with self.subTest(change=change), self.assertRaises(Denied):
                self.changed_manifest(change)

    def test_support_cutoff_live_boundary(self):
        check_time(timestamp("2026-10-10T00:00:00+11:00"))
        check_time(timestamp("2026-11-09T23:59:59+11:00"))
        for value in ("2026-10-09T23:59:59+11:00", "2026-11-10T00:00:00+11:00"):
            with self.assertRaises(Denied):
                check_time(timestamp(value))

    def test_melbourne_calendar_day_not_utc(self):
        self.assertEqual(day(timestamp("2026-10-10T14:00:00Z")), "2026-10-11")


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.api = MockAPI()
        self.manifest = release()
        self.manifest["enabled"] = True
        self.manifest["build"]["signer_certificate_sha256"] = "a" * 64
        self.context = {"run_id": 22, "run_attempt": 1, "ref": "refs/heads/main", "default_branch": "main", "sha": "b" * 40}
        self.clock = timestamp("2026-10-12T12:00:00+11:00")

    def prior(self, claimed="2026-10-11T10:00:00+11:00", completed="2026-10-11T11:00:00+11:00", status="completed"):
        self.api.claims = [{"id": 1, "payload": {"schema": 1, "run_id": 11, "run_attempt": 1,
            "source_sha": self.manifest["source_sha"], "melbourne_day": day(timestamp(claimed)), "claimed_at": claimed,
            "manifest_sha256": "a" * 64}}]
        self.api.runs[11] = {"status": status, "updated_at": completed}
        self.api.jobs[11] = [{"status": "completed", "completed_at": completed}]

    def call(self):
        return reserve(self.api, self.manifest, self.context, self.clock)

    def test_reservation_consumes_before_build_and_cannot_race(self):
        result = self.call()
        self.assertTrue(result["allowed"])
        post = self.api.posts[0]
        self.assertFalse(post["auto_merge"])
        self.assertEqual(post["required_contexts"], [])
        self.assertFalse(post["production_environment"])
        self.assertFalse(post["transient_environment"])
        self.context["run_id"] = 23
        with self.assertRaises(Denied):
            self.call() # Current serialized next run sees durable incomplete claim.
        self.assertEqual(len(self.api.posts), 1)

    def test_same_calendar_day_consumed_even_after_failure(self):
        self.prior(claimed="2026-10-12T00:01:00+11:00", completed="2026-10-12T00:02:00+11:00")
        self.api.runs[11]["conclusion"] = "failure"
        self.assertFalse(self.call()["allowed"])

    def test_rolling_limit_uses_completion_not_claim(self):
        self.prior(claimed="2026-10-10T10:00:00+11:00", completed="2026-10-11T13:00:00+11:00")
        self.assertFalse(self.call()["allowed"])
        self.clock = timestamp("2026-10-12T13:00:00+11:00")
        self.assertTrue(self.call()["allowed"])

    def test_failed_next_day_retry_after_cooldown(self):
        self.prior()
        self.api.runs[11]["conclusion"] = "cancelled"
        self.assertTrue(self.call()["allowed"])

    def test_missing_incomplete_malformed_history_fails_closed(self):
        for kind in ("missing", "incomplete", "no_jobs", "bad_job", "bad_payload"):
            self.api = MockAPI()
            self.prior()
            if kind == "missing":
                self.api.runs.clear()
            elif kind == "incomplete":
                self.api.runs[11]["status"] = "in_progress"
            elif kind == "no_jobs":
                self.api.jobs[11] = []
            elif kind == "bad_job":
                self.api.jobs[11][0]["completed_at"] = None
            else:
                self.api.claims[0]["payload"] = "not-json"
            with self.subTest(kind=kind), self.assertRaises(Denied):
                self.call()
            self.assertFalse(self.api.posts)

    def test_old_attempt_jobs_are_included_conservatively(self):
        self.prior()
        self.api.jobs[11].append({"status": "completed", "completed_at": "2026-10-12T01:00:00+11:00"})
        self.assertFalse(self.call()["allowed"])

    def test_failed_build_with_unexecuted_skipped_signer_can_retry(self):
        self.prior()
        self.api.jobs[11][0]["conclusion"] = "failure"
        self.api.jobs[11].append({"status": "completed", "conclusion": "skipped", "completed_at": None})
        self.assertTrue(self.call()["allowed"])

    def test_rerun_ref_private_and_expiry_denied(self):
        for change in (lambda: self.context.update(run_attempt=2),
                       lambda: self.context.update(ref="refs/heads/other"),
                       lambda: setattr(self.api, "private", True),
                       lambda: setattr(self, "clock", timestamp("2026-11-10T00:00:00+11:00"))):
            self.setUp()
            change()
            with self.assertRaises(Denied):
                self.call()
            self.assertFalse(self.api.posts)

    def test_disabled_unconfigured_and_published_skip_without_claim(self):
        self.manifest["enabled"] = False
        self.assertFalse(self.call()["allowed"])
        self.manifest["enabled"] = True
        self.manifest["build"]["signer_certificate_sha256"] = None
        self.assertFalse(self.call()["allowed"])
        self.manifest["build"]["signer_certificate_sha256"] = "a" * 64
        names = ("t3-code.apk", "SHA256SUMS", "build-manifest.json", "source-diff.patch", "apk-signature.txt", "provenance.json")
        self.api.published = {"tag_name": tag(self.manifest), "draft": False, "prerelease": True, "assets": [{"name": x} for x in names]}
        self.assertFalse(self.call()["allowed"])
        self.assertFalse(self.api.posts)

    def test_incomplete_publication_requires_recovery(self):
        self.api.published = {"tag_name": tag(self.manifest), "draft": False, "prerelease": True, "assets": []}
        with self.assertRaises(Denied):
            self.call()

    def test_existing_draft_is_detected_before_claim_even_without_tag_endpoint(self):
        self.api.published = {"tag_name": tag(self.manifest), "draft": True, "assets": []}
        with self.assertRaises(Denied):
            self.call()
        self.assertFalse(self.api.posts)


class BoundariesTests(unittest.TestCase):
    def test_draft_publication_requires_exact_asset_set_and_digests(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "t3-code.apk"
            file.write_bytes(b"APK fixture")
            remote = {"assets": [{"name": file.name, "digest": "sha256:" + digest(file)}]}
            validate_assets([file], remote)
            for altered in ({"assets": []}, {"assets": [{"name": file.name, "digest": "sha256:" + "0" * 64}]}):
                with self.assertRaises(Denied):
                    validate_assets([file], altered)

    def test_exact_ota_boolean_not_hex_prefix(self):
        prefix = '\n  E: meta-data\n    A: android:name(0x01010003)="expo.modules.updates.ENABLED"\n    A: android:value(0x01010024)='
        self.assertTrue(ota_disabled(prefix + "0x00000000\n"))
        self.assertTrue(ota_disabled(prefix + "(type 0x12)0x0\n"))
        self.assertFalse(ota_disabled(prefix + "0x00000001\n"))
        self.assertFalse(ota_disabled(prefix + "(type 0x12)0x00000001\n"))
        self.assertFalse(ota_disabled(""))

    def test_apk_signers_are_exact(self):
        self.assertEqual(signer_fingerprints("Signer #1 certificate SHA-256 digest: " + "a" * 64 + "\n"), ["a" * 64])
        self.assertEqual(signer_fingerprints("Signer #1 certificate SHA-256 digest: " + "a" * 64 + "junk\n"), [])

    def test_source_adaptation_fails_if_source_shape_changes(self):
        with self.assertRaises(ValueError):
            adapted("new source format", 82, "io.github.areidyoth.t3code")

    def test_sandbox_output_symlink_and_traversal_rejected(self):
        for filename, type_ in (("out/unsigned.apk", tarfile.SYMTYPE), ("out/../escape", tarfile.REGTYPE)):
            with tempfile.TemporaryDirectory() as directory:
                archive = Path(directory) / "outputs.tar"
                with tarfile.open(archive, "w") as bundle:
                    item = tarfile.TarInfo(filename)
                    item.type = type_
                    item.linkname = "/etc/passwd"
                    bundle.addfile(item, io.BytesIO())
                with self.assertRaises(Denied):
                    extract_outputs(archive, Path(directory) / "dist")

    def test_pagination_reads_all_full_pages(self):
        api = GitHub("owner/repo", "unused")
        with patch.object(api, "request", side_effect=[list(range(100)), [100]]) as request:
            self.assertEqual(len(api.pages("/deployments?environment=x")), 101)
            self.assertIn("page=2", request.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
