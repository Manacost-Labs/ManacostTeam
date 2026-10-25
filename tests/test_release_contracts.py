import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_team_skills as builder


class ReleaseContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="manacost-release-contract-"
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "teams/example"
        self.source.mkdir(parents=True)
        (self.source / "SKILL.md").write_text(
            '---\nname: example\ndescription: "Example."\nmetadata:\n'
            '  version: "1.0.0"\n---\n\nRead the provided text.\n',
            encoding="utf-8",
        )
        (self.source / "skill.yaml").write_text(
            'name: example\nversion: "1.0.0"\nteam: ExampleTeam\nentrypoint: SKILL.md\n',
            encoding="utf-8",
        )
        self.registry = {
            "schema_version": 1,
            "release_version": "1.0.0",
            "skills": [
                {
                    "name": "example",
                    "team": "ExampleTeam",
                    "module": "example",
                    "version": "1.0.0",
                    "source": "teams/example",
                    "resources": [],
                }
            ],
        }
        self.history = self.root / "release/team-skills"
        self.manifest = self.history / "1.0.0"
        self.builds = self.root / "build/team-skills"
        self.output = self.builds / "1.0.0"
        self.write_registry(self.registry)

    def write_registry(self, registry):
        (self.root / "teams/registry.json").write_text(
            json.dumps(registry), encoding="utf-8"
        )

    def test_new_release_and_unchanged_rebuild_have_identical_bytes(self):
        builder.build(self.root, self.output)
        before = {file.name: file.read_bytes() for file in self.output.iterdir()}
        builder.build(self.root, self.output)
        builder.build(self.root, self.output, check=True)
        self.assertEqual(
            before, {file.name: file.read_bytes() for file in self.output.iterdir()}
        )

    def test_tracked_release_holds_only_the_manifest_with_asset_links(self):
        index = builder.build(self.root, self.output)
        self.assertEqual(
            sorted(file.name for file in self.manifest.iterdir()),
            ["SHA256SUMS", "index.json"],
        )
        self.assertEqual(
            index["download_base"],
            "https://github.com/Manacost-Labs/ManacostTeam/releases/download/v1.0.0/",
        )
        for name in ("index.json", "SHA256SUMS"):
            self.assertEqual(
                (self.manifest / name).read_bytes(), (self.output / name).read_bytes()
            )
        self.assertEqual(
            set(index["archives"]),
            {file.name for file in self.output.iterdir()} - {"index.json", "SHA256SUMS"},
        )

    def test_check_needs_only_the_manifest_and_accepts_identical_legacy_archives(self):
        builder.build(self.root, self.output)
        shutil.rmtree(self.builds)
        builder.build(self.root, self.output, check=True)
        self.assertFalse(self.output.exists())
        legacy = self.manifest / "example-1.0.0.zip"
        builder.build(self.root, self.root / "elsewhere")
        shutil.copyfile(self.root / "elsewhere/example-1.0.0.zip", legacy)
        builder.build(self.root, self.output, check=True)
        legacy.write_bytes(b"changed archive")
        with self.assertRaisesRegex(ValueError, "differs from sources"):
            builder.build(self.root, self.output, check=True)

    def test_check_without_a_manifest_fails(self):
        with self.assertRaisesRegex(ValueError, "manifest missing"):
            builder.build(self.root, self.output, check=True)
        self.assertFalse(self.output.exists())

    def test_changed_skill_cannot_reuse_its_version_in_a_new_release(self):
        builder.build(self.root, self.output)
        previous = (self.manifest / "index.json").read_bytes()
        self.registry["release_version"] = "1.0.1"
        self.write_registry(self.registry)
        with (self.source / "SKILL.md").open("a", encoding="utf-8") as stream:
            stream.write("A changed instruction.\n")
        next_output = self.builds / "1.0.1"
        with self.assertRaisesRegex(ValueError, "immutable across releases"):
            builder.build(self.root, next_output)
        self.assertFalse(next_output.exists())
        self.assertFalse((self.history / "1.0.1").exists())
        self.assertEqual((self.manifest / "index.json").read_bytes(), previous)

    def test_unchanged_skill_can_be_included_in_a_new_plugin_release(self):
        builder.build(self.root, self.output)
        self.registry["release_version"] = "1.0.1"
        self.write_registry(self.registry)
        next_output = self.builds / "1.0.1"
        builder.build(self.root, next_output)
        self.assertEqual(
            (self.output / "example-1.0.0.zip").read_bytes(),
            (next_output / "example-1.0.0.zip").read_bytes(),
        )
        self.assertTrue((next_output / "manacost-team-1.0.1-plugin.zip").exists())
        self.assertTrue((self.history / "1.0.1/index.json").exists())

    def test_check_rejects_unexpected_files_and_nested_directories(self):
        builder.build(self.root, self.output)
        for name, directory in [("unintended.txt", False), ("private", True)]:
            with self.subTest(name=name):
                extra = self.manifest / name
                if directory:
                    extra.mkdir()
                else:
                    extra.write_bytes(b"unintended")
                with self.assertRaisesRegex(ValueError, "unexpected"):
                    builder.build(self.root, self.output, check=True)
                extra.rmdir() if directory else extra.unlink()

    def test_incomplete_existing_release_is_never_modified(self):
        for directory in (self.manifest, self.output):
            with self.subTest(directory=directory):
                directory.mkdir(parents=True)
                original = directory / "example-1.0.0.skill"
                original.write_bytes(b"existing archive")
                with self.assertRaises(ValueError):
                    builder.build(self.root, self.output)
                self.assertEqual(list(directory.iterdir()), [original])
                self.assertEqual(original.read_bytes(), b"existing archive")
                shutil.rmtree(directory)
                self.assertFalse(self.manifest.exists())

    def test_copy_failure_does_not_publish_or_leave_a_staging_directory(self):
        real_copy = builder.shutil.copyfile
        copied = 0

        def failing_copy(source, destination, *args, **kwargs):
            nonlocal copied
            if Path(destination).parent.parent == self.builds:
                copied += 1
                if copied == 2:
                    raise OSError("simulated disk failure")
            return real_copy(source, destination, *args, **kwargs)

        with (
            patch.object(builder.shutil, "copyfile", side_effect=failing_copy),
            self.assertRaisesRegex(OSError, "simulated disk failure"),
        ):
            builder.build(self.root, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.builds.iterdir()), [])
        self.assertFalse(self.history.exists())

    def test_registry_schema_versions_and_required_fields_are_validated(self):
        invalid = [
            {**self.registry, "schema_version": 2},
            {**self.registry, "schema_version": True},
            {**self.registry, "release_version": "../outside"},
            {**self.registry, "skills": {}},
            {**self.registry, "skills": []},
            {**self.registry, "skills": [None]},
        ]
        for field, value in [
            ("team", None),
            ("module", "../../outside"),
            ("name", "Bad_Name"),
            ("version", "latest"),
            ("resources", {}),
            ("resources", [{}]),
        ]:
            registry = copy.deepcopy(self.registry)
            registry["skills"][0][field] = value
            invalid.append(registry)
        for registry in invalid:
            with self.subTest(registry=registry):
                self.write_registry(registry)
                with self.assertRaises((ValueError, TypeError)):
                    builder.build(self.root, self.output)
                self.assertFalse(self.output.exists())
                self.assertFalse(self.manifest.exists())

    def test_skill_metadata_version_and_identity_must_agree_with_registry(self):
        for filename, before, after in [
            ("SKILL.md", 'version: "1.0.0"', 'version: "1.0.1"'),
            ("skill.yaml", 'version: "1.0.0"', 'version: "1.0.1"'),
            ("skill.yaml", "team: ExampleTeam", "team: OtherTeam"),
            ("skill.yaml", "entrypoint: SKILL.md", "entrypoint: missing.md"),
            ("skill.yaml", 'version: "1.0.0"', 'version: "1.0.0"\nversion: "1.0.1"'),
            (
                "SKILL.md",
                '  version: "1.0.0"',
                '  version: "1.0.0"\n  version: "1.0.1"',
            ),
        ]:
            with self.subTest(filename=filename, after=after):
                path = self.source / filename
                original = path.read_text(encoding="utf-8")
                path.write_text(original.replace(before, after), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "differs from registry"):
                    builder.build(self.root, self.output)
                self.assertFalse(self.output.exists())
                path.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
