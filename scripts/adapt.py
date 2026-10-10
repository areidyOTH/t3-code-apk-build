"""The only source adaptation: own identity, version code, and no OTA.

No upstream code is imported or executed. Fail if the reviewed source shape
changes. The public environment also disables OTA; pin it in native config.
"""
import difflib
from pathlib import Path


def adapted(text, version_code, package):
    replacements = {
        "name: variant.appName,": 'name: "T3 Code Unofficial",',
        "package: variant.androidPackage,": f'package: "{package}",\n    versionCode: {version_code},',
        'enabled: repoEnv.T3CODE_MOBILE_UPDATES_ENABLED !== "0",': "enabled: false,",
    }
    for old, new in replacements.items():
        if text.count(old) != 1:
            raise ValueError("reviewed source adaptation no longer applies: " + old)
        text = text.replace(old, new)
    return text


def patch(before, after):
    path = "apps/mobile/app.config.ts"
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                      fromfile="a/" + path, tofile="b/" + path))


def apply(source, version_code, package):
    path = Path(source) / "apps/mobile/app.config.ts"
    before = path.read_text()
    after = adapted(before, version_code, package)
    path.write_text(after)
    return patch(before, after)
