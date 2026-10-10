"""Reserve an irreversible quota claim before a source build can begin.

The fixed workflow concurrency group is the lock; the Deployments API is the
durable ledger. No retrying POST: an ambiguous write fails closed.
"""
import datetime as dt
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from policy import Denied, POLICY, ROOT, check_time, day, digest, now, release, tag, timestamp

WORKFLOW = ".github/workflows/build-apk.yml"
CONCLUSIONS = {"success", "failure", "cancelled", "timed_out", "skipped", "neutral", "stale", "action_required", "startup_failure"}
RELEASE_FILES = {"t3-code.apk", "SHA256SUMS", "build-manifest.json", "source-diff.patch", "public-environment.json",
                 "apk-signature.txt", "android-badging.txt", "android-manifest.txt", "dependency-inventory.json",
                 "toolchain.json", "image-id.txt", "unsigned.gradle", "container-build-recipe.py", "builder.Dockerfile", "provenance.json"}
SIGN_STEP = "Sign and inspect final APK with trusted tools"
ATTEST_STEP = "Attest final APK and every verification file"
PUBLISH_STEP = "Check support interval again and publish"


class GitHub:
    def __init__(self, repository, token):
        if not __import__("re").fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise Denied("invalid repository")
        self.base = "https://api.github.com/repos/" + repository
        self.repository = repository
        self.token = token

    def asset_json(self, asset):
        # Public download without credentials: do not forward the gate token on
        # GitHub's asset redirects. Only this small evidence file is downloaded.
        url = asset.get("browser_download_url", "")
        prefix = "https://github.com/" + self.repository + "/releases/download/"
        if not isinstance(url, str) or not url.lower().startswith(prefix.lower()) or not url.endswith("/build-manifest.json"):
            raise Denied("unexpected public build-manifest URL")
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024 or asset.get("digest") != "sha256:" + hashlib.sha256(data).hexdigest():
            raise Denied("published build-manifest digest mismatch")
        try:
            document = json.loads(data)
        except ValueError as exc:
            raise Denied("malformed published build manifest") from exc
        if not isinstance(document, dict):
            raise Denied("malformed published build manifest")
        return document

    def request(self, path, payload=None, missing=False):
        req = urllib.request.Request(self.base + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2026-03-10", "Content-Type": "application/json"},
            method="GET" if payload is None else "POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                if payload is not None and response.status != 201:
                    raise Denied("claim was not definitively created")
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if missing and exc.code == 404:
                return None
            raise Denied(f"GitHub API unavailable ({exc.code})") from exc

    def pages(self, path, field=None):
        values = []
        for page in range(1, 10001):
            response = self.request(path + ("&" if "?" in path else "?") + f"per_page=100&page={page}")
            batch = response[field] if field else response
            if not isinstance(batch, list):
                raise Denied("invalid paginated API response")
            values.extend(batch)
            if len(batch) < 100:
                return values
        raise Denied("quota history too large to verify")


def histories(api):
    path = "/deployments?" + urllib.parse.urlencode({"environment": POLICY["quota_environment"], "task": POLICY["quota_task"]})
    return api.pages(path)


def prior_completion(api, claim):
    payload = claim.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as exc:
            raise Denied("malformed quota claim") from exc
    fields = {"schema", "run_id", "run_attempt", "source_sha", "melbourne_day", "claimed_at", "manifest_sha256"}
    if not isinstance(payload, dict) or set(payload) != fields or type(payload["schema"]) is not int or payload["schema"] != 1:
        raise Denied("malformed quota claim")
    if type(payload["run_id"]) is not int or payload["run_id"] <= 0 or type(payload["run_attempt"]) is not int or payload["run_attempt"] != 1:
        raise Denied("invalid quota run")
    if (not isinstance(payload["source_sha"], str) or not re.fullmatch(r"[a-f0-9]{40}", payload["source_sha"])
            or not isinstance(payload["manifest_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", payload["manifest_sha256"])):
        raise Denied("invalid quota source/manifest hash")
    claimed = timestamp(payload["claimed_at"])
    if payload["melbourne_day"] != day(claimed):
        raise Denied("invalid quota day")
    if (type(claim.get("id")) is not int or not isinstance(claim.get("sha"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", claim["sha"])
            or claim.get("task") != POLICY["quota_task"] or claim.get("environment") != POLICY["quota_environment"]):
        raise Denied("invalid deployment audit record")
    run = api.request(f"/actions/runs/{payload['run_id']}")
    if (run.get("status") != "completed" or run.get("conclusion") not in CONCLUSIONS
            or type(run.get("run_attempt")) is not int or run["run_attempt"] < 1):
        raise Denied("prior admitted workflow is still incomplete")
    original = run if run["run_attempt"] == 1 else api.request(f"/actions/runs/{payload['run_id']}/attempts/1")
    if (original.get("status") != "completed" or original.get("conclusion") not in CONCLUSIONS
            or original.get("id") != payload["run_id"] or original.get("head_sha") != claim["sha"] or original.get("path") != WORKFLOW):
        raise Denied("admitted workflow identity or original outcome cannot be verified")
    jobs = api.pages(f"/actions/runs/{payload['run_id']}/jobs?filter=all", "jobs")
    if not jobs or any(job.get("status") != "completed" or job.get("conclusion") not in CONCLUSIONS
                       or type(job.get("run_attempt")) is not int or job["run_attempt"] < 1
                       or (not job.get("completed_at") and not (job["conclusion"] == "skipped"
                           or (job["conclusion"] == "cancelled" and "started_at" in job and job["started_at"] is None))) for job in jobs):
        raise Denied("prior job completion cannot be verified")
    for job in jobs:
        steps = job.get("steps", [])
        if not isinstance(steps, list) or any(not isinstance(step, dict) or not isinstance(step.get("name"), str)
                or step.get("status") != "completed" or step.get("conclusion") not in CONCLUSIONS for step in steps):
            raise Denied("prior step outcome cannot be verified")
    completed = max([timestamp(job["completed_at"]) for job in jobs if job.get("completed_at")] + [timestamp(run["updated_at"]), claimed])
    first_jobs = [job for job in jobs if job["run_attempt"] == 1]
    if not first_jobs:
        raise Denied("original admitted job history is missing")
    return {"claim": claim, "payload": payload, "completed": completed, "claimed": claimed, "run": original, "jobs": first_jobs}


def complete_publication(entry):
    assets = entry.get("assets", [])
    return (entry.get("draft") is False and entry.get("prerelease") is True and isinstance(assets, list)
            and len(assets) == len(RELEASE_FILES) and {asset.get("name") for asset in assets} == RELEASE_FILES)


def success_witnesses(api, releases, history):
    records = {item["payload"]["run_id"]: item for item in history}
    if len(records) != len(history):
        raise Denied("duplicate admitted workflow claims")
    witnessed = set()
    for entry in releases:
        if entry.get("draft") is True or not re.fullmatch(r"play-beta-[1-9][0-9]*-[0-9a-f]{12}", str(entry.get("tag_name", ""))):
            continue
        if not complete_publication(entry):
            raise Denied("incomplete prior public release; success history is ambiguous")
        asset = next(asset for asset in entry["assets"] if asset["name"] == "build-manifest.json")
        document = api.asset_json(asset)
        if not isinstance(document, dict):
            raise Denied("malformed published build manifest")
        run_id = document.get("run_id")
        if type(run_id) is not int or run_id not in records or run_id in witnessed:
            raise Denied("published success has no unique audit claim")
        item = records[run_id]
        released = document.get("release", {})
        if not isinstance(released, dict) or not isinstance(released.get("build"), dict):
            raise Denied("malformed published release metadata")
        certificate = released.get("build", {}).get("signer_certificate_sha256")
        if (type(document.get("quota_claim_id")) is not int or document["quota_claim_id"] != item["claim"]["id"]
                or type(document.get("run_attempt")) is not int or document["run_attempt"] != 1
                or document.get("builder_repository") != api.repository or document.get("builder_commit") != item["claim"]["sha"]
                or document.get("workflow") != WORKFLOW or released.get("source_sha") != item["payload"]["source_sha"]
                or released.get("upstream_repository") != POLICY["upstream_repository"]
                or type(released.get("version_code")) is not int or released["version_code"] <= 0
                or not isinstance(certificate, str) or not re.fullmatch(r"[0-9a-f]{64}", certificate)
                or not isinstance(document.get("apk_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", document["apk_sha256"])
                or entry["tag_name"] != tag(released)):
            raise Denied("published success does not bind its claimed source/run/signer")
        jobs = {job.get("name"): job for job in item["jobs"]}
        if (len(jobs) != len(item["jobs"]) or jobs.get("build", {}).get("conclusion") != "success"
                or jobs.get("sign-publish", {}).get("conclusion") not in {"success", "failure", "cancelled", "timed_out"}):
            raise Denied("published success lacks a successful original build")
        steps = {step.get("name"): step for step in jobs.get("sign-publish", {}).get("steps", [])}
        if (steps.get(SIGN_STEP, {}).get("conclusion") != "success" or steps.get(ATTEST_STEP, {}).get("conclusion") != "success"
                or steps.get(PUBLISH_STEP, {}).get("conclusion") not in {"success", "failure", "cancelled"}):
            raise Denied("published success lacks trusted signing/attestation/publication history")
        apk = next(asset for asset in entry["assets"] if asset["name"] == "t3-code.apk")
        if apk.get("digest") != "sha256:" + document["apk_sha256"]:
            raise Denied("published APK digest differs from success manifest")
        witnessed.add(run_id)
    for item in history:
        jobs = {job.get("name"): job for job in item["jobs"]}
        steps = jobs.get("sign-publish", {}).get("steps", [])
        expected_publication = (item["run"]["conclusion"] == "success" or jobs.get("sign-publish", {}).get("conclusion") == "success"
                                or any(step.get("name") == PUBLISH_STEP and step.get("conclusion") == "success" for step in steps))
        if expected_publication and item["payload"]["run_id"] not in witnessed:
            raise Denied("previous success publication is missing; cannot return to bootstrap")
    return [item for item in history if item["payload"]["run_id"] in witnessed]


def reserve(api, manifest, context, clock):
    check_time(clock)
    if context["run_attempt"] != 1:
        raise Denied("reruns cannot perform actual builds")
    if context["ref"] != "refs/heads/" + context["default_branch"]:
        raise Denied("only the default branch may build")
    if api.request("").get("private") is not False:
        raise Denied("only a public repository may build")
    if not manifest["enabled"]:
        return {"allowed": False, "reason": "reviewed release is disabled"}
    if manifest["build"]["signer_certificate_sha256"] is None:
        return {"allowed": False, "reason": "APK signer has not been provisioned and pinned"}
    # Drafts are absent from REST's tag endpoint. This trusted gate has push
    # access solely because GitHub requires it to list draft releases.
    releases = api.pages("/releases")
    candidates = [entry for entry in releases if entry.get("tag_name") == tag(manifest)]
    if len(candidates) > 1:
        raise Denied("ambiguous existing release")
    if candidates and not complete_publication(candidates[0]):
        raise Denied("existing release is incomplete; manual recovery required")
    history = [prior_completion(api, claim) for claim in histories(api)]
    for item in history:
        if item["payload"]["run_id"] == context["run_id"]:
            raise Denied("this run has already consumed its claim")
    successes = success_witnesses(api, releases, history)
    if candidates:
        return {"allowed": False, "reason": "this exact release source is already published"}
    if successes:
        first_success_claim = min(item["claimed"] for item in successes)
        for item in history:
            # Earlier failed bootstrap claims stay auditable and exempt, even
            # if a later bookkeeping rerun changes their updated_at timestamp.
            if item["claimed"] < first_success_claim:
                continue
            if item["payload"]["melbourne_day"] == day(clock):
                return {"allowed": False, "reason": "Melbourne calendar day already consumed after first success"}
            if clock < item["completed"] + dt.timedelta(hours=24):
                return {"allowed": False, "reason": "less than 24 hours after prior post-bootstrap workflow completion"}
    payload = {"schema": 1, "run_id": context["run_id"], "run_attempt": 1,
               "source_sha": manifest["source_sha"], "melbourne_day": day(clock),
               "claimed_at": clock.isoformat(), "manifest_sha256": digest(ROOT / "policy/release.json")}
    claim = api.request("/deployments", {"ref": context["sha"], "task": POLICY["quota_task"],
        "environment": POLICY["quota_environment"], "auto_merge": False, "required_contexts": [],
        "transient_environment": False, "production_environment": False, "payload": payload,
        "description": "Audited APK attempt; daily allowance applies after the first signed publication"})
    if type(claim.get("id")) is not int or claim.get("payload") != payload:
        raise Denied("created claim could not be verified")
    return {"allowed": True, "claim_id": claim["id"], "source_sha": manifest["source_sha"], "tag": tag(manifest),
            "quota_mode": "limited" if successes else "bootstrap"}


def main():
    context = {"run_id": int(os.environ["GITHUB_RUN_ID"]), "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
               "ref": os.environ["GITHUB_REF"], "sha": os.environ["GITHUB_SHA"],
               "default_branch": os.environ["DEFAULT_BRANCH"]}
    current = now()
    try:
        check_time(current)
    except Denied:
        result = {"allowed": False, "reason": "outside the one-month support interval"}
    else:
        result = reserve(GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"]), release(), context, current)
    print(json.dumps(result))
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        for key, value in result.items():
            output.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")


if __name__ == "__main__":
    main()
