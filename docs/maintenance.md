# Maintainer guide

This guide covers repository operation. For downloading and checking the app, see the [README](../readme.md) and [verification guide](verification.md).

## Support and release policy

Support runs from 10 October 2026 until the start of 10 November 2026 in Australia/Melbourne because of the upcoming v2 orchestrator release. The exclusive cutoff is `2026-11-10T00:00:00+11:00`. Current execution time is checked before building and publishing; neither may start at or after the cutoff.

Only source mapped to an observed, publicly released Google Play beta is eligible. Review the full commit, Play availability evidence, source mapping, configuration, and permitted adaptations in [the release manifest](../policy/release.json). A source branch, tag, internal EAS build, or version-number match alone does not establish eligibility. The published build 82 is not asserted to be the latest beta. See [release evidence](release-evidence.md) for the accepted mapping and build history.

Upstream security audits, backports, and vulnerability fixes are outside this project's support scope. Do not turn them into a build gate or silently patch upstream.

## Repository and signing identity

The destination is `areidyOTH/t3-code-apk-build`. Review the workflow and release manifest before enabling builds. The default branch is protected and the public repository has immutable releases enabled. Publication uploads and checks a draft before making it public; published assets and tags are protected from replacement.

The app package is `io.github.areidyoth.t3code`, displayed as **T3 Code Unofficial**, with an independently managed RSA-3072 signing key. Its certificate SHA-256 is:

```text
1343d6833fa4c08c4bc6deb67180be48c7cee46a5e67f838390847854052d11c
```

The trusted signing script requires these secrets:

| Secret | Purpose |
| --- | --- |
| `APK_KEYSTORE_B64` | Base64-encoded rebuild keystore. |
| `APK_STORE_PASSWORD` | Keystore password. |
| `APK_KEY_PASSWORD` | Signing-key password. |
| `APK_KEY_ALIAS` | Alias of the rebuild signing key. |

Store them in the GitHub environment **`apk-signing`**, restricted to the protected default branch. Keep the keystore and passwords outside Git, retain an independent backup for signer continuity, and pin the public certificate SHA-256 in the reviewed release manifest. Upstream build code receives none of these secrets. No upstream Expo, Clerk, Google Play, or observability credentials are required by the default recipe; do not fetch upstream private EAS environment variables.

## Build controls and retained history

Source, reviewed build tools, and actions are pinned. pnpm uses its frozen upstream lockfile. Android/Maven dependencies are resolved during the build and their available artifact hashes are inventoried; they are not checked against an independently frozen inventory. Retain the tool and dependency records with the output.

Upstream build code runs in an isolated, non-root container without signing credentials or publishing permissions. A separate job uses trusted scripts to sign and publish. All events share one workflow concurrency group. Job reruns cannot grant another build.

A persistent GitHub Deployments ledger records a claim before every actual build, including bootstrap attempts. Preserve it and the corresponding Actions workflow/job/step histories throughout support. Deleting them prevents reliable quota verification. Missing, malformed, or incomplete history blocks admission. These controls assume trusted maintainers: a repository administrator can change policy or enforcement.

Before the first complete signed and attested publication, completed failed or cancelled bootstrap attempts did not impose the daily limit or cooldown. An unsigned compile alone did not establish success. The first successful publication has now occurred; a later artifact-upload or housekeeping failure would not undo that milestone.

After that milestone, the successful attempt and subsequent attempts—including failures and cancellations—consume the allowance. Admission requires both an unused Melbourne calendar day and 24 hours since the preceding admitted workflow completed. Earlier failed bootstrap claims remain audit history but are exempt from those limits. The schedule may therefore skip days because of cooldowns, runner delays, missing release evidence, failures, or expiry.

A complete release for an exact source commit is not rebuilt. An incomplete existing release requires review and recovery rather than an automatic rebuild.

## Commands

Validate local policy and regression checks without compiling an APK:

```sh
python3 scripts/policy.py --check
python3 -m unittest discover -s tests -v
```

These commands do not independently establish Play publication or verify hosted CI operation.

The [build workflow](../.github/workflows/build-apk.yml) checks daily at `14:15 UTC` (`01:15` the following Melbourne day during support). A maintainer can request a default-branch eligibility check:

```sh
gh workflow run build-apk.yml --repo areidyOTH/t3-code-apk-build
gh run list --workflow build-apk.yml --repo areidyOTH/t3-code-apk-build
```

**Dispatch is not a dry run:** it can perform the actual build when all gates pass. A successful publication creates a GitHub prerelease containing the signed APK and its attested evidence. Follow the [verification guide](verification.md) to verify the downloaded output.
