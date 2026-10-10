"""Pinned official Android signing tools, independent of hosted runner SDK state."""
import hashlib
from pathlib import Path
import urllib.request
import zipfile

URL = "https://dl.google.com/android/repository/build-tools_r37_linux.zip"
SHA256 = "01af179347cbcd9c208b7f8171f7b21f6dd1d2f85bcd15e88caa51d5d7b86060"


def install(parent):
    parent = Path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    archive = parent / "build-tools.zip"
    urllib.request.urlretrieve(URL, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError("official Android signing tools checksum mismatch")
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            name = Path(member.filename)
            if name.is_absolute() or ".." in name.parts or name.parts[0] != "android-37.0":
                raise ValueError("unsafe pinned signing tools archive")
            target = parent / name
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(member))
                target.chmod((member.external_attr >> 16) & 0o777 or 0o644)
    return parent / "android-37.0"
