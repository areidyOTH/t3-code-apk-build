# Verify a rebuild

The [published Play beta 82 rebuild](https://github.com/areidyOTH/t3-code-apk-build/releases/tag/play-beta-82-b38aa18365fe) passed downloaded-file verification: all 13 checksums and 15 remote asset digests, expected GitHub repository/workflow provenance, pinned APK signing certificate, and APK/manifest bindings. The exact released bytes also passed basic installation and launch checks on an Android 16 x86_64 emulator. These results do not establish actual pairing, production-service behavior, physical-device compatibility, or byte-for-byte reproducibility.

## Evidence to retain

For each accepted release, retain the signed APK, its SHA-256 digest, signing-certificate SHA-256 fingerprint, the unsigned APK digest, the source/build manifest, the permitted adaptation diff, and provenance attestation bundles. The manifest must distinguish the builder repository/commit from the external upstream repository/commit and bind the public Play release evidence to that upstream commit.

The manifest must also record the version code and name, official and rebuilt package identities, pinned tool and dependency information, build workflow/run/attempt, ledger claim, support cutoff, and the explicit OTA-disabling adaptation. Missing evidence blocks publication.

## Reviewer checks

1. Read [release evidence](release-evidence.md). Confirm the candidate was observed as a released Play beta and that the release-to-source link identifies the exact commit. Neither a source branch nor an EAS production profile alone proves Google Play publication.
2. Confirm the workflow uses a public standard GitHub-hosted runner and pins third-party actions by full commit. Inspect the trusted builder code at the workflow's attested commit, including source checkout, container isolation, signing, and publication.
3. Verify the APK's actual digest against the published checksums and its attestation. Require the expected repository and signer workflow and reject self-hosted runner provenance.
4. Verify the source/build manifest and adaptation diff attestations too. Check that the APK digest, source commit, configuration, and signer fingerprint agree across all evidence. The normal builder attestation does not by itself identify an external upstream checkout.
5. Inspect the APK's package, version code/name, and signing-certificate fingerprint. The independently managed fingerprint must match the documented rebuild signer; it is not the Google Play fingerprint.
6. Check the adaptation disables Expo OTA and that the built bundle derives from the pinned source. This does not reproduce any downloaded official OTA update.
7. Inspect the persistent claims and full workflow/job/step history. Determine whether successful building, signing, attestation, and complete publication have occurred. A subsequent artifact-upload or housekeeping failure does not undo that milestone. Before it, completed failed/cancelled bootstrap claims remain audit history without imposing the daily limit or cooldown. After it, all reserved attempts, including failures/cancellations, count toward the 24-hour cooldown and Melbourne day limit. Confirm no rerun performs a build, incomplete or missing history blocks a claim, and execution precedes the exclusive cutoff.

## Verify downloaded files

Use the verifier from a reviewed checkout of this builder repository, with Python 3.11 or later, GitHub CLI (`gh`), and Android `apksigner` on `PATH`. Download every release asset together. The initial candidate's expected release tag is `play-beta-82-b38aa18365fe`:

```sh
gh release download play-beta-82-b38aa18365fe \
  --repo areidyOTH/t3-code-apk-build --dir download
```

Expected assets are `t3-code.apk`, `SHA256SUMS`, `build-manifest.json`, `source-diff.patch`, `public-environment.json`, `apk-signature.txt`, `android-badging.txt`, `android-manifest.txt`, `dependency-inventory.json`, `toolchain.json`, `image-id.txt`, `unsigned.gradle`, `container-build-recipe.py`, `builder.Dockerfile`, and `provenance.json`.

The initial rebuild certificate SHA-256 is pinned below. Confirm it against the independently reviewed repository policy or another trusted maintainer channel. Do not learn the expected signing identity only from the download being checked:

```sh
python3 scripts/verify.py ./download \
  --repo areidyOTH/t3-code-apk-build \
  --signer-sha256 1343d6833fa4c08c4bc6deb67180be48c7cee46a5e67f838390847854052d11c
```

The expected attestation signer workflow is `areidyOTH/t3-code-apk-build/.github/workflows/build-apk.yml`. The verifier requires that workflow identity and rejects self-hosted runner attestations. GitHub identity and transparency checks may need network access even though APK signature verification is local.

The script authenticates the checksum file before comparing all required file hashes, separately verifies APK and build-manifest provenance, verifies the APK signature against the pinned certificate, and checks manifest bindings for the APK, adaptation diff, and public environment. It rejects missing required files and missing or duplicate checksum entries. Human review must still assess the attested builder code, source mapping, dependency/tool records, and configuration differences.

The verifier passed on the release from [workflow run 38050314520](https://github.com/areidyOTH/t3-code-apk-build/actions/runs/38050314520). The signed APK SHA-256 is `caef567fa2d8b9ac530d69db2e0c5ca24df43473bcfcfe81f5eeb4fa61c0914b`. Independent APK inspection confirmed package `io.github.areidyoth.t3code`, version code `82`, version name `2.0.0`, minimum SDK `24`, target SDK `36`, disabled native Expo OTA flag, and 16 KB ZIP alignment. The reviewed recipe/environment files matched their published attested copies. The adaptation diff's workflow attestation was also verified directly.

The real Deployments and Actions history recognized the first successful publication. A read-only probe confirmed that the exact source skips as already published, a hypothetical different candidate on the claimed Melbourne day is denied, and a next-midnight attempt is denied by the 24-hour cooldown. Every POST was prohibited during that probe; no extra build was dispatched.

The exact signed APK bytes were installed and cold-launched on Pixel_9_API_36 (Android 16, x86_64 emulator). Threads, manual Host/Pairing Code fields, and Local Settings rendered and responded. No app fatal, React Native, or native-library loading error was captured. No credentials were entered or actual pairing performed.

## Meaning and limits

Checksums detect differing bytes when compared with a trusted value. APK signatures establish the rebuild key's identity. Provenance attestations bind artifact bytes to the stated builder execution; consumers must verify the expected repository/workflow and inspect its behavior.

These checks do not certify upstream security, absence of malware, equivalence to Google's signing key, equality to a Play-generated split APK, or byte-for-byte reproducibility. The two hosted unsigned builds differed in APK bytes, with `assets/app.manifest` the sole differing uncompressed ZIP entry; its JSON differed only in `id` and `commitTime`. Signing-key continuity across future releases, actual pairing, production services, ARM64 runtime behavior, and physical-device compatibility remain untested.
