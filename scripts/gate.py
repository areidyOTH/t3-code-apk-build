"""Reserve an irreversible quota claim before a source build can begin.

The fixed workflow concurrency group is the lock; the Deployments API is the
durable ledger. No retrying POST: an ambiguous write fails closed.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from policy import Denied, POLICY, ROOT, check_time, day, digest, now, release, tag, timestamp


class GitHub:
    def __init__(self, repository, token):
        if not __import__("re").fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise Denied("invalid repository")
        self.base = "https://api.github.com/repos/" + repository
        self.token = token

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
    run = api.request(f"/actions/runs/{payload['run_id']}")
    if run.get("status") != "completed":
        raise Denied("prior admitted workflow is still incomplete")
    jobs = api.pages(f"/actions/runs/{payload['run_id']}/jobs?filter=all", "jobs")
    if not jobs or any(job.get("status") != "completed" or (not job.get("completed_at") and job.get("conclusion") != "skipped") for job in jobs):
        raise Denied("prior job completion cannot be verified")
    completed = max([timestamp(job["completed_at"]) for job in jobs if job.get("completed_at")] + [timestamp(run["updated_at"]), claimed])
    return payload, completed


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
    candidates = [entry for entry in api.pages("/releases") if entry.get("tag_name") == tag(manifest)]
    if len(candidates) > 1:
        raise Denied("ambiguous existing release")
    if candidates:
        existing = candidates[0]
        if existing.get("draft") is False and existing.get("prerelease") is True and {x.get("name") for x in existing.get("assets", [])} >= {"t3-code.apk", "SHA256SUMS", "build-manifest.json", "source-diff.patch", "apk-signature.txt", "provenance.json"}:
            return {"allowed": False, "reason": "this exact release source is already published"}
        raise Denied("existing release is incomplete; manual recovery required")
    claims = histories(api)
    for claim in claims:
        payload, completed = prior_completion(api, claim)
        if payload["run_id"] == context["run_id"]:
            raise Denied("this run has already consumed its claim")
        if payload["melbourne_day"] == day(clock):
            return {"allowed": False, "reason": "Melbourne calendar day already consumed"}
        if clock < completed + __import__("datetime").timedelta(hours=24):
            return {"allowed": False, "reason": "less than 24 hours after prior workflow completion"}
    payload = {"schema": 1, "run_id": context["run_id"], "run_attempt": 1,
               "source_sha": manifest["source_sha"], "melbourne_day": day(clock),
               "claimed_at": clock.isoformat(), "manifest_sha256": digest(ROOT / "policy/release.json")}
    claim = api.request("/deployments", {"ref": context["sha"], "task": POLICY["quota_task"],
        "environment": POLICY["quota_environment"], "auto_merge": False, "required_contexts": [],
        "transient_environment": False, "production_environment": False, "payload": payload,
        "description": "Irreversible APK build allowance; failed and cancelled runs consume it"})
    if type(claim.get("id")) is not int or claim.get("payload") != payload:
        raise Denied("created claim could not be verified")
    return {"allowed": True, "claim_id": claim["id"], "source_sha": manifest["source_sha"], "tag": tag(manifest)}


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
