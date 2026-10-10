"""Consumer regression probes with local stand-ins for cryptographic tools.

These test verifier orchestration and tamper rejection, not gh/apksigner crypto.
"""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
PIN = "a" * 64
REPO = "owner/repo"
FILES = {"t3-code.apk", "build-manifest.json", "source-diff.patch", "public-environment.json", "apk-signature.txt",
         "android-badging.txt", "android-manifest.txt", "dependency-inventory.json", "toolchain.json", "image-id.txt",
         "unsigned.gradle", "container-build-recipe.py", "builder.Dockerfile"}


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in FILES:
            (self.root / name).write_bytes(b"fixture:" + name.encode())
        manifest = {"apk_sha256": self.hash("t3-code.apk"), "builder_repository": REPO,
                    "source_diff_sha256": self.hash("source-diff.patch"),
                    "release": {"build": {"signer_certificate_sha256": PIN, "public_environment_sha256": self.hash("public-environment.json")}}}
        (self.root / "build-manifest.json").write_text(json.dumps(manifest))
        (self.root / "provenance.json").write_text("mock trusted provenance")
        self.sums()
        self.trusted_sums = self.hash("SHA256SUMS")
        self.trusted_manifest = self.hash("build-manifest.json")
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def hash(self, name):
        return hashlib.sha256((self.root / name).read_bytes()).hexdigest()

    def sums(self):
        (self.root / "SHA256SUMS").write_text("".join(self.hash(name) + "  " + name + "\n" for name in sorted(FILES)))

    def gh(self, args, check):
        self.calls.append(args)
        self.assertEqual(args[:3], ["gh", "attestation", "verify"])
        self.assertIn("--deny-self-hosted-runners", args)
        self.assertEqual(args[args.index("--repo") + 1], REPO)
        self.assertEqual(args[args.index("--signer-workflow") + 1], REPO + "/.github/workflows/build-apk.yml")
        name = Path(args[3]).name
        if (name == "SHA256SUMS" and self.hash(name) != self.trusted_sums) or (name == "build-manifest.json" and self.hash(name) != self.trusted_manifest):
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0)

    def invoke(self, crypto=None, signature=None):
        args = ["verify.py", str(self.root), "--repo", REPO, "--signer-sha256", PIN]
        with patch.object(sys, "argv", args), patch("subprocess.run", side_effect=crypto or self.gh), patch("subprocess.check_output", return_value=signature or "Signer #1 certificate SHA-256 digest: " + PIN + "\n"):
            runpy.run_path(str(ROOT / "scripts/verify.py"), run_name="__main__")

    def test_authenticates_sums_manifest_and_apk(self):
        self.invoke()
        self.assertEqual([Path(call[3]).name for call in self.calls], ["SHA256SUMS", "t3-code.apk", "build-manifest.json"])

    def test_build_tools37_scheme_signer_accepted_but_second_signer_denied(self):
        signature = "Number of signers: 1\nV3.0 Signer: certificate SHA-256 digest: " + PIN + "\n"
        self.invoke(signature=signature)
        for altered in (signature + "V3.0 Signer #2: certificate SHA-256 digest: " + "b" * 64 + "\n",
                        "Number of signers: 1\nV3.0 Signer: certificate SHA-256 digest: " + "b" * 64 + "\n"):
            with self.subTest(altered=altered), self.assertRaises(SystemExit):
                self.invoke(signature=altered)

    def test_tampered_manifest_and_recomputed_sums_fail_attestation(self):
        (self.root / "build-manifest.json").write_text('{"source_sha":"forged"}')
        self.sums()
        with self.assertRaises(subprocess.CalledProcessError):
            self.invoke()

    def test_tampered_sidecar_fails_checksums(self):
        (self.root / "source-diff.patch").write_text("forged patch")
        with self.assertRaises(SystemExit):
            self.invoke()

    def test_empty_and_duplicate_checksums_rejected_even_if_gh_accepts(self):
        for altered in ("", (self.root / "SHA256SUMS").read_text() * 2):
            (self.root / "SHA256SUMS").write_text(altered)
            with self.subTest(altered=altered[:20]), self.assertRaises(SystemExit):
                self.invoke(crypto=lambda *args, **kwargs: subprocess.CompletedProcess(args, 0))

    def test_primary_symlink_rejected_before_crypto(self):
        (self.root / "SHA256SUMS").unlink()
        (self.root / "SHA256SUMS").symlink_to(self.root / "provenance.json")
        with self.assertRaises(SystemExit):
            self.invoke()
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
