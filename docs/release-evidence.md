# Public Play beta source evidence

The initial candidate is the observed T3 Code Google Play beta build 82. It is the first candidate identified for this project, not a claim about the latest available beta.

The reviewed release manifest must identify an exact public source commit and preserve both parts of the evidence: observation that this version reached Google Play, and an authoritative link between that released version and its source commit. A branch head, Git tag, internal EAS build, production profile, or version-number match by itself is insufficient.

## Build 82 evidence

| Item | Recorded evidence |
| --- | --- |
| Play availability | First-hand beta enrollment and installation through Google Play were reported on 10 October 2026. This is availability evidence, not an independently retrieved Play promotion record. |
| Installed native package | Inspection of the supplied official APK found `com.t3tools.t3code`, version name `2.0.0`, version code `82`. |
| Source commit | [`b38aa18365fe314e079d99670932bedfc7407e5a`](https://github.com/pingdotgg/t3code/tree/b38aa18365fe314e079d99670932bedfc7407e5a). |
| Official source-to-build link | [Upstream Actions run 37502942759](https://github.com/pingdotgg/t3code/actions/runs/37502942759) checked out that commit and invoked the production Android EAS build with version name `2.0.0` and version code `82`. |
| EAS build | [`3e6ed32c-a91c-4734-8e3e-41f3a9c1f9f2`](https://expo.dev/accounts/pingdotgg/projects/t3-code/builds/3e6ed32c-a91c-4734-8e3e-41f3a9c1f9f2). Official logs recorded submission queued to the `internal` track. |
| Original APK SHA-256 | `03f76825fb75ab504cbbcc203b63af634a03a1096437815b400ef7850194fa34` |
| Original APK signer SHA-256 | `b9f51ed5a76cd186c95108f21991b7d53a58fda98312a9e353e21a59b24203b6` |
| Verified Google source-stamp SHA-256 | `3257d599a49d2c961a471ca9843f59d341a405884583fc087df4237b733bbd6d` |
| Original APK SDK metadata | Minimum `32`, target `36`, compile `37`. |
| Embedded configuration SHA-256 | `assets/app.config`: `2d17acd7b28a9c6d996a6ae18961d700b07fe06f90214df16e2d652e0bec3c91` |
| Embedded manifest SHA-256 | `assets/app.manifest`: `ec2a24c120a18ae30098487c776cbb4505c631ecb578c0bf5879a31347505651` |
| Embedded JavaScript SHA-256 | `assets/index.android.bundle`: `5c42e264df32feb4fac408f47feffc2069f581a69054ce977d42f284f5b51f80` |

The recorded acceptance basis combines the first-hand Play-beta installation report, the inspected official version-82 APK, and the official CI source-to-version-82 build log. Internal-track submission alone does not prove public beta promotion. Anonymous access to the Expo build metadata was denied, and the public dashboard did not disclose its final submission state. No independently retrieved Play publication record or digest-level comparison against the EAS build artifact is claimed.

These original APK fingerprints are evidence about the inspected official artifact. They are not expected digests or signing identities for this unofficial rebuild. The source mapping identifies the version-82 native build and original embedded bundle, subject to the OTA limitation below.

The exact commit and this evidence must be entered into the reviewed manifest before a build can run. Configuration or dependency inputs that remain unproven still block building even after the source mapping is accepted.

## Configuration boundary

The official build 82 production configuration enables Expo OTA. The source commit describes the original embedded bundle; an installed official application may have downloaded a different OTA bundle. The rebuild intentionally disables OTA, and its manifest and adaptation diff must record that change.

Only public configuration from the reviewed source and release APK may be used. Do not fetch upstream private EAS environment variables. If a required input cannot be justified from that evidence, mark it missing and block the build rather than inventing it.

The recorded hashes describe the inspected original files without publishing their complete contents. Optional service configuration and observability credentials must not be copied wholesale from the APK. Managed T3 Connect configuration, direct pairing, and other service behavior require explicit configuration review and runtime testing; source and version provenance alone do not establish feature parity.

## Local recipe checks

On 10 October 2026, dependency installation with the upstream frozen pnpm lockfile and an Android Expo prebuild succeeded at the pinned version-82 commit using Node `24.21.0` and pnpm `11.10.0`. No Gradle compile or APK build was performed by these checks.

The generated project selected Gradle `9.4.1`, Android Gradle Plugin `9.2.1`, build tools `37.0.0`, compile SDK `37`, target SDK `36`, and NDK `27.1.12297006`. The upstream version catalog declares Kotlin `2.2.0`; a configuration-only Gradle probe resolved effective Kotlin `2.2.10` and confirmed the release signing configuration is null before variant creation. That probe stopped at a missing local NDK and did not compile an APK. The source minimum SDK was `24`, while the inspected signed Play APK declares `32`. The difference remains unresolved until the generated release manifest is built and inspected. External production service configuration also differs from the default reviewed rebuild environment; native or feature equivalence is not claimed.

## Acceptance boundary

An accepted release mapping covers only the pinned publicly released beta source and the documented package/name/signing/OTA adaptations. Later upstream source or internal releases need a fresh reviewed Play mapping. Upstream security issues are outside this project's support scope; provenance is not an assurance of malware freedom.

No APK has been built for this project and no remote publishing workflow has been activated.
