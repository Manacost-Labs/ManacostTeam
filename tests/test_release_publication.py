import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_team_skills as builder  # noqa: E402
import publish_team_skills as publisher  # noqa: E402


class ReleasePublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="manacost-publication-")
        self.addCleanup(temporary.cleanup)
        self.manifest = Path(temporary.name) / "1.0.0"
        self.manifest.mkdir()
        self.archive = self.manifest / "example-1.0.0.zip"
        self.archive.write_bytes(b"archive")
        digest = builder.sha256(self.archive)
        (self.manifest / "index.json").write_text(
            json.dumps({"version": "1.0.0", "archives": {self.archive.name: digest}}),
            encoding="utf-8",
        )
        (self.manifest / "SHA256SUMS").write_text(
            f"{digest}  {self.archive.name}\n", encoding="utf-8"
        )
        self.digests = publisher.manifest_digests(self.manifest)

    def test_manifest_lists_archives_and_its_own_files(self):
        self.assertEqual(
            sorted(self.digests), ["SHA256SUMS", "example-1.0.0.zip", "index.json"]
        )
        (self.manifest / "SHA256SUMS").write_text("0  other.zip\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA256SUMS differs"):
            publisher.manifest_digests(self.manifest)

    def test_existing_assets_are_verified_and_never_replaced(self):
        with patch.object(publisher, "remote_digests", return_value=None):
            self.assertEqual(
                publisher.missing_assets("v1.0.0", self.digests),
                (False, sorted(self.digests)),
            )
        partial = {"index.json": self.digests["index.json"]}
        with patch.object(publisher, "remote_digests", return_value=partial):
            self.assertEqual(
                publisher.missing_assets("v1.0.0", self.digests),
                (True, ["SHA256SUMS", "example-1.0.0.zip"]),
            )
        changed = {"example-1.0.0.zip": "0" * 64}
        with (
            patch.object(publisher, "remote_digests", return_value=changed),
            self.assertRaisesRegex(ValueError, "never replaced"),
        ):
            publisher.missing_assets("v1.0.0", self.digests)

    def test_dry_run_plans_without_github_writes(self):
        with (
            patch.object(publisher, "remote_digests", return_value=None),
            patch.object(publisher, "manifest_commit", return_value="a" * 40),
            patch.object(publisher, "run") as run,
        ):
            self.assertFalse(publisher.publish(self.manifest, self.manifest, execute=False))
        run.assert_not_called()

    def test_local_archive_must_match_the_manifest_before_upload(self):
        self.archive.write_bytes(b"changed")
        with (
            patch.object(publisher, "remote_digests", return_value=None),
            patch.object(publisher, "run") as run,
            self.assertRaisesRegex(ValueError, "differs from manifest"),
        ):
            publisher.publish(self.manifest, self.manifest, execute=True)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
