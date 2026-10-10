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
from policy import Denied, POLICY, check_time, day, digest, release, timestamp, tag
from gate import GitHub, reserve, WORKFLOW, RELEASE_FILES, SIGN_STEP, ATTEST_STEP, PUBLISH_STEP
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
        self.repository = "owner/repo"
        self.other_releases = []
        self.documents = {}
        self.original_runs = {}

    def request(self, path, payload=None, missing=False):
        if path == "":
            return {"private": self.private}
        if path.startswith("/releases/tags/"):
            return self.published
        if path.startswith("/actions/runs/"):
            key = int(path.split("/")[3])
            if key not in self.runs:
                raise Denied("missing workflow")
            return self.original_runs[key] if "/attempts/" in path else self.runs[key]
        if path == "/deployments" and payload:
            self.posts.append(payload)
            claim = {"id": len(self.claims) + 1, "sha": payload["ref"], "task": payload["task"],
                     "environment": payload["environment"], "payload": copy.deepcopy(payload["payload"])}
            self.claims.append(claim)
            self.runs[payload["payload"]["run_id"]] = {"status": "in_progress"}
            return claim
        raise AssertionError(path)

    def asset_json(self, asset):
        return copy.deepcopy(self.documents[asset["id"]])

    def pages(self, path, field=None):
        if path == "/releases":
            return self.other_releases + ([] if self.published is None else [self.published])
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

    def prior(self, claimed="2026-10-11T10:00:00+11:00", completed="2026-10-11T11:00:00+11:00", status="completed",
              conclusion="failure", run_id=11, source_sha=None, append=False):
        claim = {"id": run_id, "sha": "b" * 40, "task": POLICY["quota_task"], "environment": POLICY["quota_environment"],
                 "payload": {"schema": 1, "run_id": run_id, "run_attempt": 1,
            "source_sha": source_sha or self.manifest["source_sha"], "melbourne_day": day(timestamp(claimed)), "claimed_at": claimed,
            "manifest_sha256": "a" * 64}}
        if append:
            self.api.claims.append(claim)
        else:
            self.api.claims = [claim]
        self.api.runs[run_id] = {"id":run_id,"head_sha":claim["sha"],"path":WORKFLOW,"run_attempt":1,
                                 "status": status, "conclusion": conclusion, "updated_at": completed}
        self.api.jobs[run_id] = [{"name":"gate","run_attempt":1,"status":"completed","conclusion":"success","completed_at":completed},
                                 {"name":"build","run_attempt":1,"status":"completed","conclusion":"failure","completed_at":completed},
                                 {"name":"sign-publish","run_attempt":1,"status":"completed","conclusion":"skipped","completed_at":None}]
        return claim

    def success(self, run_id=10, claimed="2026-10-10T10:00:00+11:00", completed="2026-10-10T11:00:00+11:00", conclusion="success",
                source_sha="c" * 40, append=False, publish_conclusion="success"):
        claim = self.prior(claimed, completed, conclusion=conclusion, run_id=run_id, source_sha=source_sha, append=append)
        jobs = self.api.jobs[run_id]
        jobs[1]["conclusion"] = "success"
        jobs[2].update(conclusion="success" if conclusion == "success" else conclusion, completed_at=completed,
                       steps=[{"name":SIGN_STEP,"status":"completed","conclusion":"success"},{"name":ATTEST_STEP,"status":"completed","conclusion":"success"},
                              {"name":PUBLISH_STEP,"status":"completed","conclusion":publish_conclusion}])
        released = copy.deepcopy(self.manifest)
        released["source_sha"] = source_sha
        document = {"run_id":run_id,"run_attempt":1,"quota_claim_id":claim["id"],"builder_repository":self.api.repository,
                    "builder_commit":claim["sha"],"workflow":WORKFLOW,"release":released,"apk_sha256":"d"*64}
        assets = [{"name":name,"id":run_id*100+index,"digest":"sha256:"+"d"*64} for index,name in enumerate(sorted(RELEASE_FILES))]
        self.api.documents[next(asset["id"] for asset in assets if asset["name"] == "build-manifest.json")] = document
        publication = {"tag_name":tag(released),"draft":False,"prerelease":True,"assets":assets}
        self.api.other_releases.append(publication)
        return publication

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

    def test_bootstrap_failure_allows_immediate_retry_and_preserves_audit(self):
        self.prior(claimed="2026-10-12T11:58:00+11:00", completed="2026-10-12T11:59:00+11:00")
        old = copy.deepcopy(self.api.claims[0])
        result = self.call()
        self.assertTrue(result["allowed"])
        self.assertEqual(result["quota_mode"], "bootstrap")
        self.assertEqual(self.api.claims[0], old)
        self.assertEqual(len(self.api.claims), 2)
        self.assertEqual(self.api.claims[1]["payload"]["schema"], 1)

    def test_first_success_establishes_calendar_and_rolling_cooldown(self):
        self.success(claimed="2026-10-12T09:00:00+11:00", completed="2026-10-12T10:00:00+11:00")
        self.assertFalse(self.call()["allowed"])
        self.clock = timestamp("2026-10-13T09:59:59+11:00")
        self.assertFalse(self.call()["allowed"])
        self.clock = timestamp("2026-10-13T10:00:00+11:00")
        self.assertEqual(self.call()["quota_mode"], "limited")

    def test_post_success_failure_consumes_rolling_cooldown(self):
        self.success()
        self.prior(claimed="2026-10-11T11:00:00+11:00", completed="2026-10-11T13:00:00+11:00", append=True)
        self.assertFalse(self.call()["allowed"])

    def test_success_publication_counts_despite_housekeeping_failure_or_cancellation(self):
        for conclusion in ("failure", "cancelled"):
            self.setUp()
            self.success(claimed="2026-10-12T09:00:00+11:00", completed="2026-10-12T10:00:00+11:00",
                         conclusion=conclusion, publish_conclusion="cancelled" if conclusion == "cancelled" else "success")
            with self.subTest(conclusion=conclusion):
                self.assertFalse(self.call()["allowed"])

    def test_success_publication_missing_cannot_reset_to_bootstrap(self):
        self.success()
        self.api.other_releases = []
        with self.assertRaises(Denied):
            self.call()

    def test_failed_publish_without_deliverable_does_not_establish_first_success(self):
        self.prior(claimed="2026-10-12T11:00:00+11:00", completed="2026-10-12T11:59:00+11:00")
        self.api.jobs[11][1]["conclusion"] = "success"
        self.api.jobs[11][2].update(conclusion="failure",completed_at="2026-10-12T11:59:00+11:00",
                                  steps=[{"name":PUBLISH_STEP,"status":"completed","conclusion":"failure"}])
        self.assertEqual(self.call()["quota_mode"], "bootstrap")

    def test_old_bootstrap_failure_rerun_after_success_stays_exempt(self):
        self.prior(claimed="2026-10-10T09:00:00+11:00", completed="2026-10-10T09:30:00+11:00")
        self.api.original_runs[11] = copy.deepcopy(self.api.runs[11])
        self.api.runs[11].update(run_attempt=2,conclusion="success",updated_at="2026-10-12T11:59:00+11:00")
        self.api.jobs[11].append({"name":"gate","run_attempt":2,"status":"completed","conclusion":"skipped","completed_at":"2026-10-12T11:59:00+11:00"})
        self.success(append=True)
        self.assertEqual(self.call()["quota_mode"], "limited")

    def test_later_rerun_success_cannot_create_bootstrap_success(self):
        self.prior(claimed="2026-10-12T09:00:00+11:00", completed="2026-10-12T09:30:00+11:00")
        self.api.original_runs[11] = copy.deepcopy(self.api.runs[11])
        self.api.runs[11].update(run_attempt=2,conclusion="success",updated_at="2026-10-12T11:59:00+11:00")
        self.api.jobs[11].extend([{"name":name,"run_attempt":2,"status":"completed","conclusion":"success","completed_at":"2026-10-12T11:59:00+11:00"}
                                 for name in ("build","sign-publish")])
        self.assertEqual(self.call()["quota_mode"], "bootstrap")

    def test_mismatched_publication_bindings_and_conflicting_success_deny(self):
        mutations = (lambda doc: doc.update(quota_claim_id=999), lambda doc: doc.update(builder_commit="e"*40),
                     lambda doc: doc["release"].update(source_sha="f"*40), lambda doc: doc.update(run_id=999),
                     lambda doc: doc["release"]["build"].update(signer_certificate_sha256=None),
                     lambda doc: doc.update(apk_sha256="e"*64))
        for change in mutations:
            self.setUp()
            self.success()
            change(next(iter(self.api.documents.values())))
            with self.subTest(change=change), self.assertRaises(Denied):
                self.call()
        self.setUp()
        self.success()
        self.api.jobs[10][1]["conclusion"] = "failure"
        with self.assertRaises(Denied):
            self.call()

    def test_terminal_unstarted_cancelled_job_can_retry_but_started_missing_completion_denies(self):
        self.prior()
        self.api.jobs[11][1].update(conclusion="cancelled",started_at=None,completed_at=None)
        self.assertEqual(self.call()["quota_mode"], "bootstrap")
        self.setUp()
        self.prior()
        self.api.jobs[11][1].update(conclusion="cancelled",started_at="2026-10-11T10:30:00+11:00",completed_at=None)
        with self.assertRaises(Denied):
            self.call()
        self.setUp()
        self.prior()
        self.api.jobs[11][1].update(conclusion="cancelled",completed_at=None)
        with self.assertRaises(Denied):
            self.call() # Absent started_at is unknown, not verified unstarted.

    def test_unknown_or_running_step_outcome_is_not_a_bootstrap_failure(self):
        for status, conclusion in (("completed",None),("in_progress","success")):
            self.setUp()
            self.prior()
            self.api.jobs[11][1]["steps"] = [{"name":"source build","status":status,"conclusion":conclusion}]
            with self.subTest(status=status,conclusion=conclusion), self.assertRaises(Denied):
                self.call()

    def test_all_histories_validate_before_short_circuiting_cooldown(self):
        self.success(claimed="2026-10-12T09:00:00+11:00", completed="2026-10-12T10:00:00+11:00")
        self.prior(append=True)
        self.api.claims[-1]["payload"] = "bad-json"
        with self.assertRaises(Denied):
            self.call()

    def test_same_calendar_day_consumed_even_after_failure(self):
        self.success()
        self.prior(claimed="2026-10-12T00:01:00+11:00", completed="2026-10-12T00:02:00+11:00", append=True)
        self.api.runs[11]["conclusion"] = "failure"
        self.assertFalse(self.call()["allowed"])

    def test_rolling_limit_uses_completion_not_claim(self):
        self.success(claimed="2026-10-10T10:00:00+11:00", completed="2026-10-11T13:00:00+11:00")
        self.assertFalse(self.call()["allowed"])
        self.clock = timestamp("2026-10-12T13:00:00+11:00")
        self.assertTrue(self.call()["allowed"])

    def test_failed_next_day_retry_after_cooldown(self):
        self.success()
        self.prior(append=True)
        self.api.runs[11]["conclusion"] = "cancelled"
        self.assertTrue(self.call()["allowed"])

    def test_missing_incomplete_malformed_history_fails_closed(self):
        for kind in ("missing", "incomplete", "no_jobs", "bad_job", "bad_payload", "unknown_conclusion", "wrong_workflow", "wrong_builder_sha"):
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
            elif kind == "unknown_conclusion":
                self.api.runs[11]["conclusion"] = None
            elif kind == "wrong_workflow":
                self.api.runs[11]["path"] = ".github/workflows/other.yml"
            elif kind == "wrong_builder_sha":
                self.api.runs[11]["head_sha"] = "e"*40
            else:
                self.api.claims[0]["payload"] = "not-json"
            with self.subTest(kind=kind), self.assertRaises(Denied):
                self.call()
            self.assertFalse(self.api.posts)

    def test_old_attempt_jobs_are_included_conservatively(self):
        self.success()
        self.prior(append=True)
        self.api.jobs[11].append({"name":"gate","run_attempt":2,"status":"completed","conclusion":"skipped","completed_at":"2026-10-12T01:00:00+11:00"})
        self.assertFalse(self.call()["allowed"])

    def test_failed_build_with_unexecuted_skipped_signer_can_retry(self):
        self.prior()
        self.api.jobs[11][0]["conclusion"] = "failure"
        self.api.jobs[11].append({"name":"extra","run_attempt":1,"status":"completed","conclusion":"skipped","completed_at":None})
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
        self.api.published = self.success(source_sha=self.manifest["source_sha"])
        self.api.other_releases = []
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
    def test_public_success_manifest_requires_small_digest_verified_json(self):
        api = GitHub("owner/repo", "unused-token")
        content = b'{"run_id": 1}'
        asset = {"browser_download_url":"https://github.com/owner/repo/releases/download/play-beta-82-abcdefabcdef/build-manifest.json",
                 "digest":"sha256:" + __import__("hashlib").sha256(content).hexdigest()}
        with patch("urllib.request.urlopen", return_value=io.BytesIO(content)) as request:
            self.assertEqual(api.asset_json(asset), {"run_id":1})
            self.assertIsInstance(request.call_args[0][0], str) # No token-bearing Request object.
        for body in (b"tampered", b"x"*(1024*1024+1)):
            with patch("urllib.request.urlopen", return_value=io.BytesIO(body)), self.assertRaises(Denied):
                api.asset_json(asset)
        with patch("urllib.request.urlopen") as request, self.assertRaises(Denied):
            api.asset_json({**asset,"browser_download_url":"https://other.example/build-manifest.json"})
        request.assert_not_called()

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

    def test_build_tools37_scheme_signer_matches_actual_public_output(self):
        pin = "1343d6833fa4c08c4bc6deb67180be48c7cee46a5e67f838390847854052d11c"
        output = (Path(__file__).parent / "fixtures/apksigner37.txt").read_text()
        self.assertEqual(signer_fingerprints(output), [pin])
        for scheme in ("V1", "V2", "V3.0", "V3.1"):
            with self.subTest(scheme=scheme):
                self.assertEqual(signer_fingerprints(f"Number of signers: 1\n{scheme} Signer: certificate SHA-256 digest: {pin}\n"), [pin])

    def test_unknown_malformed_and_additional_signers_never_hide(self):
        valid = "Number of signers: 1\nV3.0 Signer: certificate SHA-256 digest: " + "a" * 64 + "\n"
        for altered in ("V9 Signer: certificate SHA-256 digest: " + "b" * 64,
                        "V3.0 Signer: certificate SHA-256 digest: " + "b" * 64 + "junk",
                        "Signer #2 certificate SHA-256 digest: " + "B" * 64):
            with self.subTest(altered=altered):
                self.assertEqual(signer_fingerprints(valid + altered + "\n"), [])
        self.assertEqual(signer_fingerprints(valid + "V3.0 Signer #2: certificate SHA-256 digest: " + "b" * 64), ["a" * 64, "b" * 64])
        for altered in (valid.replace("Number of signers: 1", "Number of signers: 2"),
                        valid.replace("Number of signers: 1\n", ""), valid + "Number of signers: 1\n"):
            self.assertEqual(signer_fingerprints(altered), [])

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
