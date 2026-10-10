# T3 Code APK rebuild

This project prepares an unofficial Android APK from source tied to an observed, publicly released T3 Code Google Play beta. **Support is limited to one month because of the upcoming v2 orchestrator release:** 10 October 2026 to the start of 10 November 2026 in Australia/Melbourne. The exclusive cutoff is `2026-11-10T00:00:00+11:00`.

The initial release candidate is the observed Play beta build 82. This is the first identified candidate for this project; it is not a claim that build 82 is the latest available beta. A branch head, tag, internal EAS build, or newly published source commit alone does not qualify for rebuilding. Each accepted candidate needs a reviewed exact source commit and evidence linking it to a beta that actually reached Google Play.

## Current status

Local preparation is in progress for the approved public repository [areidyOTH/t3-code-apk-build](https://github.com/areidyOTH/t3-code-apk-build). **No APK has been built, hosted CI has not been activated, and end-to-end CI, signing, attestation, and installation have not been verified.** The project must fail closed while its release mapping or required build inputs are incomplete.

The public repository has immutable releases enabled. Publication uploads and verifies a draft before making it public; once published, the release's assets and tag are protected from replacement.

See [release evidence](docs/release-evidence.md) for the candidate and its limitations, and [verification](docs/verification.md) for the evidence a completed rebuild must provide.

## Scope and identity

Upstream security issues are outside this project's support scope. We do not audit upstream, backport security changes, or fix upstream vulnerabilities. Build provenance identifies what was built and by which workflow; it does not establish that the application or its dependencies are free of malware or vulnerabilities.

The rebuild uses a separate application identity and an independently managed signing key. It is unofficial, is not signed by Google Play or T3 Tools, and does not claim equality with the Play signing certificate. It should install alongside the official application rather than update it. Package name, displayed name, signing certificate, and Expo OTA configuration are documented adaptations.

The rebuilt package is `io.github.areidyoth.t3code`, displayed as **T3 Code Unofficial**. Its RSA-3072 signing-certificate SHA-256 is:

```text
1343d6833fa4c08c4bc6deb67180be48c7cee46a5e67f838390847854052d11c
```

Build 82's production configuration enables Expo OTA updates. This rebuild disables OTA so a downloaded JavaScript update cannot silently replace the bundle tied to the attested source. That adaptation means the rebuild represents the pinned source's embedded bundle, not any subsequently downloaded official OTA bundle. Public configuration comes from the reviewed source or release APK evidence; upstream private EAS environment variables must not be fetched. The reviewed default environment omits external Clerk, managed T3 Connect, and push-service configuration. Those services and direct pairing have not been tested in the rebuild.

## Release and build rules

- A reviewed manifest pins the public upstream repository and full source commit, the observed Play version, evidence, build configuration, and permitted adaptations.
- Source, reviewed build tools, and actions are pinned, and pnpm uses its frozen upstream lockfile. Android/Maven dependencies are resolved during the build and their available artifact hashes are inventoried; they are not yet checked against an independently frozen inventory. Tool and dependency information must be retained with the output.
- Upstream build code runs in an isolated, non-root container without signing credentials or publishing permissions. A separate job uses trusted scripts to sign and publish the result.
- A persistent GitHub Deployments ledger reserves the allowance before build execution. All events share one workflow concurrency group. Failed or cancelled reserved attempts consume the allowance; rerunning a job cannot grant another build.
- An attempt is allowed only after 24 hours have elapsed since the prior reserved workflow completed, and only if no allowance has been consumed on the current Melbourne calendar day. An unavailable or malformed ledger, or missing history for a recorded run, blocks the build.
- The schedule checks eligibility daily. It may skip days because of the cooldown, absent release evidence, runner delays, failures, or the support cutoff. It does not promise a new APK every day.
- Once a complete release for an exact source commit is published, later checks skip that source. An incomplete existing release requires review and recovery rather than an automatic rebuild.
- Current execution time is checked before building and publishing. No source build or publication may start at or after the cutoff.

## Verification and reproducibility

A completed release must include the signed APK, SHA-256 checksums, a source/build manifest, the visible adaptation diff, signing-certificate fingerprint, and signed provenance attestations. Verification must check the actual APK bytes, the expected builder repository and workflow, the upstream source mapping, and the signer identity.

An attested rebuild is not automatically a byte-for-byte reproduction of Google's Play APK. Different signing keys, package identity, OTA policy, external service configuration, app-bundle splitting, hosted runner images, build timestamps, and dependency/tool resolution can change bytes. The inspected official APK declares minimum SDK 32; source prebuild without upstream's external environment generated minimum SDK 24. That discrepancy is unresolved until the generated release manifest is inspected. Independent repeated builds and installation tests remain pending.

## Maintainer setup

The destination is `areidyOTH/t3-code-apk-build`. Review the workflow and release manifest before enabling the initial build. Preserve the persistent Deployments ledger and its corresponding Actions job history throughout the support period; deleting them prevents reliable cooldown verification. Workflow and ledger protections assume trusted maintainers: a repository administrator can change the policy or its enforcement.

The trusted signing script requires these secrets:

| Secret | Purpose |
| --- | --- |
| `APK_KEYSTORE_B64` | Base64-encoded rebuild keystore. |
| `APK_STORE_PASSWORD` | Keystore password. |
| `APK_KEY_PASSWORD` | Signing-key password. |
| `APK_KEY_ALIAS` | Alias of the rebuild signing key. |

Store these secrets in the GitHub environment **`apk-signing`**, restricted to the protected default branch. Keep the keystore and passwords outside Git, retain an independent backup for signer continuity, and pin the public certificate SHA-256 in [the reviewed release manifest](policy/release.json). Upstream build code receives none of these secrets. No upstream Expo, Clerk, Google Play, or observability credentials are required by the default recipe.

Validate the reviewed local policy without compiling an APK:

```sh
python3 scripts/policy.py --check
python3 -m unittest discover -s tests -v
```

These commands validate manifest structure and exercise policy regression checks without compiling an APK. They do not independently establish Play publication or verify hosted CI operation.

The [build workflow](.github/workflows/build-apk.yml) checks daily at `14:15 UTC` (`01:15` the following Melbourne day during this support period). After repository setup and review, a maintainer can request a default-branch eligibility check:

```sh
gh workflow run build-apk.yml --repo areidyOTH/t3-code-apk-build
gh run list --workflow build-apk.yml --repo areidyOTH/t3-code-apk-build
```

This can perform the actual build when all gates pass; it is not a dry run. The workflow publishes a GitHub prerelease with its final attested files. Its initial end-to-end execution remains pending.
