import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import install  # noqa: E402


class InstallationTests(unittest.TestCase):
    def test_agent_cli_uses_explicit_utf8_for_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "Навыки"
            result = subprocess.run(
                [
                    sys.executable, "-X", "warn_default_encoding",
                    "-W", "error::EncodingWarning",
                    str(ROOT / "tools/install.py"), "agent",
                    "--directory", str(target), "--client", "codex",
                    "--skills", "translate-team", "--game", "deadlock",
                ],
                env={**os.environ, "PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0"},
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertEqual(json.loads(result.stdout)["directory"], str(target.absolute()))
            self.assertTrue((target / ".agents/skills/translate-team/SKILL.md").is_file())
            context = json.loads((target / ".manacost/context.json").read_text(encoding="utf-8"))
            self.assertEqual(context["game"]["id"], "deadlock")

    def test_cli_outputs_utf8_for_non_ascii_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "Плагин.zip"
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/install.py"), "wordpress", "--zip", str(target)],
                env={**os.environ, "PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0"},
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertEqual(json.loads(result.stdout)["zip"], str(target.absolute()))
            self.assertTrue(target.is_file())

    def test_agent_install_is_portable_repeatable_and_preserves_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            install.install_agent(target, "codex", ["translate-team"], "deadlock")
            entry = target / ".agents/skills/translate-team/SKILL.md"
            self.assertTrue(entry.is_file())
            self.assertEqual(
                json.loads((target / ".manacost/context.json").read_text(encoding="utf-8"))["game"][
                    "id"
                ],
                "deadlock",
            )
            install.install_agent(target, "codex", ["translate-team"], "deadlock")
            entry.write_text("user changes")
            with self.assertRaises(ValueError):
                install.install_agent(
                    target, "codex", ["translate-team", "job-team"], "deadlock"
                )
            self.assertEqual(entry.read_text(), "user changes")
            self.assertFalse((target / ".agents/skills/job-team").exists())

    def test_archive_traversal_is_rejected(self):
        for member in ("skill/../escape", "skill/\\escape", "/skill/escape"):
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w") as archive:
                archive.writestr(member, "unsafe")
            with self.assertRaises(ValueError):
                install.unpack_skill(payload.getvalue(), "skill")

    def test_symlink_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            try:
                (target / "link").symlink_to(target, target_is_directory=True)
            except OSError as error:
                if os.name == "nt" and error.winerror == 1314:
                    self.skipTest("Windows account lacks permission to create symlinks")
                raise
            with self.assertRaises(ValueError):
                install.install_files(target, {"link/file": b"unsafe"})

    def test_checksum_mismatch_fails_before_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "not-created"
            with patch.object(install.hashlib, "sha256") as hasher:
                hasher.return_value.hexdigest.return_value = "wrong"
                with self.assertRaises(ValueError):
                    install.install_agent(
                        target, "generic", ["translate-team"], "hearthstone"
                    )
            self.assertFalse(target.exists())

    def test_server_install_retains_token_and_binds_loopback(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            result = install.install_server(target, "league-of-legends", 8801)
            token = (target / "secrets/api-token.txt").read_bytes()
            self.assertGreaterEqual(len(token.strip()), 32)
            self.assertNotIn(token.decode().strip(), json.dumps(result))
            install.install_server(target, "league-of-legends", 8801)
            self.assertEqual((target / "secrets/api-token.txt").read_bytes(), token)
            self.assertIn("MANACOST_BIND=127.0.0.1", (target / ".env").read_text())
            self.assertNotIn("@@ROOT@@", (target / "compose.yaml").read_text())
            if os.name != "nt":
                self.assertEqual(
                    (target / "secrets/api-token.txt").stat().st_mode & 0o777, 0o600
                )

    def test_wordpress_zip_has_identical_metadata_on_windows(self):
        class WindowsZipInfo(zipfile.ZipInfo):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.create_system = 0

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "plugin.zip"
            with patch.object(zipfile, "ZipInfo", WindowsZipInfo):
                install.wordpress_zip(target)
            self.assertEqual(
                target.read_bytes(),
                (ROOT / "release/install/1.0.0/manacost-team-wordpress-1.0.0.zip").read_bytes(),
            )

    def test_wordpress_zip_is_reproducible_and_preserves_existing_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "plugin.zip"
            install.wordpress_zip(target)
            first = target.read_bytes()
            self.assertEqual(
                first,
                (
                    ROOT / "release/install/1.0.0/manacost-team-wordpress-1.0.0.zip"
                ).read_bytes(),
            )
            install.wordpress_zip(target)
            self.assertEqual(first, target.read_bytes())
            with zipfile.ZipFile(target) as archive:
                self.assertIn("manacost-team/manacost-team.php", archive.namelist())
            target.write_bytes(b"old upload")
            with self.assertRaises(ValueError):
                install.wordpress_zip(target)
            self.assertEqual(target.read_bytes(), b"old upload")
