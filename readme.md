# T3 Code Unofficial for Android

An unofficial Android APK rebuilt from source linked to a **publicly released T3 Code Google Play beta**.

**[Download the APK](https://github.com/areidyOTH/t3-code-apk-build/releases/download/play-beta-82-b38aa18365fe/t3-code.apk)** · [Release files and build records](https://github.com/areidyOTH/t3-code-apk-build/releases/tag/play-beta-82-b38aa18365fe)

The published rebuild is **beta build 82, version 2.0.0**. This does not mean build 82 is the latest beta. Only versions shown to have reached the public Google Play beta qualify. A new source commit or an internal test build is not enough: each candidate needs reviewed evidence linking that Play release to an exact source commit.

**Support is limited to one month because of the upcoming v2 orchestrator release:** from 10 October 2026 until the start of 10 November 2026, Australia/Melbourne. No new build or publication may start at or after that cutoff.

## What to expect

The app is named **T3 Code Unofficial**, with package name `io.github.areidyoth.t3code`. It has its own signing key and should install alongside the official app. It cannot update the official app and is not signed by Google Play or T3 Tools.

The exact published APK was installed and opened on an Android 16 emulator on a PC. Threads, the manual Host/Pairing Code screen, and Local Settings responded without a captured app crash. **Real phones, actual pairing, and official online services have not been tested.**

Automatic Expo updates are disabled so a downloaded update cannot replace the app bundle tied to the recorded source. The rebuild also omits the official managed T3 Connect, account sign-in, and push-service configuration. Those differences mean it does not promise all the official app's features or behavior.

## When builds happen

The workflow checks daily; it does not promise a new APK every day.

- The first successful signed and attested release has been published, so the limits now apply: **at most one build attempt per Melbourne calendar day**, and **at least 24 hours since the previous counted build run finished**.
- Failed or cancelled attempts after that first success count toward both limits. Before the first success, failed setup attempts did not impose either limit, but were still recorded.
- An already published source version is skipped rather than rebuilt. New versions need fresh Play-release evidence.
- Missing or incomplete build history blocks another attempt. The support cutoff applies to every build and publication.

## Checking the download

The release includes checksums, the exact source and build information, a record of changes made for this rebuild, and signed GitHub build records (provenance). Together, these let you check that the downloaded files came from the expected workflow and that the APK uses this project's signing key.

Follow the [verification guide](docs/verification.md) to check the download. See [release evidence](docs/release-evidence.md) for the source mapping, configuration differences, and detailed test results.

These checks do not prove that the app is free of malware or vulnerabilities, or that its bytes match Google's APK. **Upstream security audits, backports, and fixes are outside this project's scope.** Separate builds are not guaranteed to produce identical APK files.

Repository setup, signing-key handling, workflow commands, and audit-history requirements are in the [maintainer guide](docs/maintenance.md).
