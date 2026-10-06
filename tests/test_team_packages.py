import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


class TeamPackageTests(unittest.TestCase):
    def test_registry_contains_every_team_and_shortcode_skill(self):
        import build_team_skills as builder

        entries = builder.load_registry(ROOT)
        self.assertEqual(len(entries), 8)
        self.assertEqual(len({entry["team"] for entry in entries}), 7)
        self.assertIn("card-shortcodes", {entry["name"] for entry in entries})

    def test_zip_is_reproducible_and_rejects_unsafe_resources(self):
        import build_team_skills as builder

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "example"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                '---\nname: example\ndescription: "A useful example."\n---\n\nInstructions.\n',
                encoding="utf-8",
            )
            first, second = root / "first.zip", root / "second.zip"
            builder.write_zip(skill, first, "example")
            builder.write_zip(skill, second, "example")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(archive.namelist(), ["example/SKILL.md"])
            (skill / ".env").write_text("PRIVATE=value", encoding="utf-8")
            with self.assertRaises(ValueError):
                builder.validate_bundle(skill)

    def test_duplicate_skill_entrypoints_are_rejected(self):
        import build_team_skills as builder

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "nested").mkdir()
            content = '---\nname: example\ndescription: "Example."\n---\n\nRun it.\n'
            (root / "SKILL.md").write_text(content, encoding="utf-8")
            (root / "nested" / "skill.md").write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                builder.validate_bundle(root)

    def test_resource_traversal_and_destination_collision_are_rejected(self):
        import build_team_skills as builder

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "escapes"):
                builder.confined(root, "../outside")
            source, target = root / "source.txt", root / "target.txt"
            source.write_text("source", encoding="utf-8")
            target.write_text("different", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "collision"):
                builder.copy_resource(source, target)

    def test_extensionless_metadata_is_normalized_and_binary_bytes_stay_exact(self):
        import build_team_skills as builder

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, binary = root / "METADATA", root / "image.png"
            metadata.write_bytes(b"Package: example\r\nLicense: MIT\r\n")
            binary.write_bytes(b"\x89PNG\r\n\x00binary\r\n")
            self.assertEqual(
                builder.portable_bytes(metadata), b"Package: example\nLicense: MIT\n"
            )
            self.assertEqual(builder.portable_bytes(binary), binary.read_bytes())

    def test_archive_member_order_uses_case_sensitive_portable_names(self):
        import build_team_skills as builder

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "source"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                '---\nname: example\ndescription: "Example."\n---\n', encoding="utf-8"
            )
            (skill / "a.txt").write_text("a", encoding="utf-8")
            (skill / "Z.txt").write_text("Z", encoding="utf-8")
            archive = root / "example.zip"
            builder.write_zip(skill, archive, "example")
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(bundle.namelist(), sorted(bundle.namelist()))


class PortableRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_team_skills as builder

        cls.temporary = tempfile.TemporaryDirectory(prefix="manacost-portable-smoke-")
        cls.root = Path(cls.temporary.name)
        cls.output = cls.root / "release"
        cls.index = builder.build(ROOT, cls.output)
        cls.unpacked = cls.root / "unpacked"
        for archive in cls.output.glob("*.zip"):
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(cls.unpacked)
        cls.env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        cls.env.pop("PYTHONPATH", None)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_helper(self, skill, script, *arguments, codes=(0,)):
        directory = self.unpacked / skill
        process = subprocess.run(
            [sys.executable, str(directory / script), *map(str, arguments)],
            cwd=directory,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        self.assertIn(process.returncode, codes, process.stdout + process.stderr)
        return process

    def test_real_archives_checksums_manifests_and_all_workflow_links(self):
        import build_team_skills as builder

        for name, digest in self.index["archives"].items():
            self.assertEqual(
                hashlib.sha256((self.output / name).read_bytes()).hexdigest(),
                digest,
                name,
            )
        for entry in builder.load_registry(ROOT):
            directory = self.unpacked / entry["name"]
            builder.validate_bundle(directory)
            manifest = json.loads(
                (directory / "MANIFEST.json").read_text(encoding="utf-8")
            )
            for filename, digest in manifest["files"].items():
                self.assertEqual(
                    hashlib.sha256((directory / filename).read_bytes()).hexdigest(),
                    digest,
                )
            base = f"{entry['name']}-{entry['version']}"
            self.assertEqual(
                (self.output / (base + ".zip")).read_bytes(),
                (self.output / (base + ".skill")).read_bytes(),
            )
        plugin = self.unpacked / "manacost-team"
        portable = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))
        claude = json.loads(
            (plugin / ".claude-plugin/plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(portable["name"], claude["name"])
        self.assertEqual(len(list((plugin / "skills").glob("*/SKILL.md"))), 8)

    def test_editor_config_and_audit_work_without_repository_or_installed_dependencies(
        self,
    ):
        self.run_helper("editor-team", "scripts/editor_team.py", "config", "validate")
        source = self.unpacked / "editor-team" / "sample.md"
        source.write_text(
            "# Гайд\n\nБранн Бронзобород даёт преимущество.\n", encoding="utf-8"
        )
        process = self.run_helper(
            "editor-team",
            "scripts/editor_team.py",
            "audit",
            source,
            "--format",
            "json",
            codes=(0, 1),
        )
        self.assertIsInstance(json.loads(process.stdout), dict)

    def test_editor_typography_and_second_audit_work_from_the_unpacked_archive(self):
        source = self.unpacked / "editor-team" / "typography-sample.md"
        source.write_text("Колода - сильная, в 2-3 хода.\n", encoding="utf-8")
        process = self.run_helper(
            "editor-team",
            "scripts/editor_team.py",
            "ru-audit",
            "prepare",
            source,
            "--format",
            "json",
        )
        brief = json.loads(process.stdout)
        self.assertTrue(Path(brief["procedure"]).is_file())
        self.assertTrue((Path(brief["corpus"]) / "references" / "addenda.md").is_file())
        self.assertIn("только на чтение", brief["prompt"])
        if shutil.which("node") is None:
            self.skipTest("Node.js нужен для Typograf")
        result = source.with_name("typography-result.md")
        process = self.run_helper(
            "editor-team",
            "scripts/editor_team.py",
            "typography",
            source,
            "--output",
            result,
            "--format",
            "json",
        )
        self.assertTrue(json.loads(process.stdout)["changed"])
        nbsp = chr(0xA0)
        self.assertEqual(
            result.read_text(encoding="utf-8"),
            f"Колода{nbsp}— сильная, в{nbsp}2-3 хода.\n",
        )

    def test_research_helpers_report_missing_access_and_invalid_ledgers(self):
        self.run_helper("research-team", "scripts/plan_queries.py", "--help")
        run = self.root / "research-run"
        run.mkdir()
        process = self.run_helper(
            "research-team", "scripts/platform_coverage.py", run, "--strict", codes=(1,)
        )
        self.assertEqual(json.loads(process.stdout)["verdict"], "partial")
        (run / "queries.jsonl").write_text("{broken\n", encoding="utf-8")
        process = self.run_helper(
            "research-team", "scripts/platform_coverage.py", run, codes=(2,)
        )
        self.assertEqual(json.loads(process.stdout)["verdict"], "invalid")
        self.assertNotIn("Traceback", process.stderr)

    def test_portable_editor_preserves_numeric_roles_and_citation_destinations(self):
        directory = self.unpacked / "editor-team"
        before, after = directory / "before.md", directory / "after.md"
        before.write_text(
            "Заклинание стоит 3 маны и наносит 5 урона. Источник: https://example.org/patch.\n",
            encoding="utf-8",
        )
        after.write_text(
            "Заклинание стоит 5 маны и наносит 3 урона.\n", encoding="utf-8"
        )
        result = self.run_helper(
            "editor-team", "scripts/semantic_diff.py", before, after, codes=(1,)
        )
        report = json.loads(result.stdout)
        self.assertFalse(report["accepted"])
        self.assertEqual(
            {item["field"] for item in report["violations"]},
            {"number_binding", "links"},
        )
        after.write_text(before.read_text(encoding="utf-8"), encoding="utf-8")
        self.run_helper("editor-team", "scripts/semantic_diff.py", before, after)

    def test_portable_research_builds_a_scoped_queue_with_breadth_targets(self):
        run = self.root / "gap-queue-run"
        run.mkdir()
        (run / "manifest.json").write_text(
            json.dumps(
                {
                    "main_question": "Hearthstone Arena",
                    "depth": "deep",
                    "coverage_contract_version": "1.0",
                    "as_of": "2026-10-03",
                }
            ),
            encoding="utf-8",
        )
        (run / "plan.json").write_text(
            json.dumps(
                {
                    "deliverable_outline": [
                        {"section_id": "SEC-1", "working_title": "Hearthstone Arena"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        args = (
            run,
            "--coverage-gaps",
            "--family",
            "youtube",
            "--language",
            "en",
            "--min-inspected",
            "youtube=2",
            "--json",
            "--apply",
        )
        first = self.run_helper("research-team", "scripts/plan_queries.py", *args)
        snapshot = (run / "query-plan.jsonl").read_bytes()
        second = self.run_helper("research-team", "scripts/plan_queries.py", *args)
        self.assertEqual(snapshot, (run / "query-plan.jsonl").read_bytes())
        self.assertEqual(first.stdout, second.stdout)
        records = [json.loads(line) for line in first.stdout.splitlines()]
        self.assertTrue(records)
        self.assertTrue(
            all(
                r["target_platform"] == "youtube" and r["status"] == "planned"
                for r in records
            )
        )
        result = self.run_helper(
            "research-team",
            "scripts/platform_coverage.py",
            run,
            "--require",
            "youtube",
            "--min-inspected",
            "youtube=2",
            "--strict",
            codes=(1,),
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["gap_details"][0]["minimum_inspected"], 2)
        self.assertEqual(report["platforms"]["youtube"]["executed_queries"], 0)

    def test_research_default_cli_preserves_unexecuted_planned_scopes(self):
        run = self.root / "scoped-run"
        run.mkdir()
        (run / "plan.json").write_text(
            json.dumps(
                {
                    "deliverable_outline": [
                        {"section_id": "SEC-1"},
                        {"section_id": "SEC-2"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        (run / "query-plan.jsonl").write_text(
            "\n".join(json.dumps({"language": language}) for language in ["en", "ru"])
            + "\n",
            encoding="utf-8",
        )
        query = {
            "query_id": "Q1",
            "family": "reddit",
            "language": "en",
            "status": "completed",
            "executed_at": "2026-10-03T12:00:00Z",
            "deliverable_section_ids": ["SEC-1"],
            "result_source_ids": ["S1"],
        }
        source = {
            "source_id": "S1",
            "canonical_url": "invalid",
            "final_url": "https://reddit.com/r/test/comments/1",
            "access_integrity": "full",
        }
        (run / "queries.jsonl").write_text(json.dumps(query) + "\n", encoding="utf-8")
        (run / "sources.jsonl").write_text(json.dumps(source) + "\n", encoding="utf-8")
        process = self.run_helper(
            "research-team",
            "scripts/platform_coverage.py",
            run,
            "--require",
            "reddit",
            "--strict",
            codes=(1,),
        )
        report = json.loads(process.stdout)
        self.assertEqual(report["platforms"]["reddit"]["inspected_sources"], 1)
        self.assertEqual(len(report["scopes"]), 4)
        self.assertEqual(len(report["gap_details"]), 3)

    def test_research_packaged_cli_deduplicates_videos_and_rejects_false_no_results(
        self,
    ):
        run = self.root / "video-run"
        run.mkdir()
        query = {
            "query_id": "Q1",
            "family": "youtube",
            "status": "completed",
            "executed_at": "2026-10-03",
            "result_source_ids": ["S1", "S2"],
        }
        sources = [
            {
                "source_id": "S1",
                "url": "https://www.youtube.com/watch?v=Video_A&t=10",
                "access_integrity": "transcript",
            },
            {
                "source_id": "S2",
                "url": "https://youtu.be/Video_A?t=20",
                "access_integrity": "transcript",
            },
        ]
        (run / "queries.jsonl").write_text(json.dumps(query) + "\n", encoding="utf-8")
        (run / "sources.jsonl").write_text(
            "\n".join(map(json.dumps, sources)) + "\n", encoding="utf-8"
        )
        process = self.run_helper(
            "research-team",
            "scripts/platform_coverage.py",
            run,
            "--require",
            "youtube",
            "--strict",
        )
        report = json.loads(process.stdout)
        self.assertEqual(report["platforms"]["youtube"]["inspected_sources"], 1)
        self.assertEqual(report["platforms"]["youtube"]["duplicate_source_ids"], ["S2"])
        self.assertEqual(report["unlinked_inspected_source_ids"], [])
        query["status"] = "no_results"
        (run / "queries.jsonl").write_text(json.dumps(query) + "\n", encoding="utf-8")
        process = self.run_helper(
            "research-team", "scripts/platform_coverage.py", run, codes=(2,)
        )
        self.assertEqual(json.loads(process.stdout)["verdict"], "invalid")
        self.assertNotIn("Traceback", process.stderr)

    def test_all_22_bundled_svg_examples_generate_valid_charts(self):
        examples = sorted((self.unpacked / "svg-team/examples/specs").glob("*.json"))
        self.assertEqual(len(examples), 22)
        for example in examples:
            with self.subTest(example=example.name):
                target = self.root / (example.stem + ".svg")
                self.run_helper(
                    "svg-team", "scripts/make_chart.py", example, "-o", target
                )
                self.run_helper("svg-team", "scripts/validate.py", target)
                self.assertIn("<svg", target.read_text(encoding="utf-8"))

    def test_translate_qa_detects_missing_numbers_links_and_terms(self):
        directory = self.unpacked / "translate-team"
        code = "import sys; sys.path.insert(0, 'scripts'); from translation_core import qa_translation; r=qa_translation('Use [[[TERM_1]]] for 20%. [link](https://example.com/a)', 'Перевод.', {'[[[TERM_1]]]':'Усиление'}); assert not r['ready_for_editor']; assert r['missing_numbers'] == ['20%']; assert r['missing_links'] == ['https://example.com/a']; assert r['missing_terms'] == ['Усиление']"
        process = subprocess.run(
            [sys.executable, "-c", code],
            cwd=directory,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_shortcode_cli_preserves_crlf_and_only_wraps_reviewed_card_mentions(self):
        source = self.root / "input.md"
        text = "Монетка лежит на столе.\r\nС Бранном сильнее.\r\n"
        source.write_bytes(text.encode("utf-8"))
        catalog = self.root / "catalog.json"
        catalog.write_text(
            json.dumps(
                [
                    {
                        "name": "Бранн Бронзобород",
                        "id": "CORE_LOE_077",
                        "formats": ["wild"],
                    }
                ]
            ),
            encoding="utf-8",
        )
        start = text.index("Бранном")
        mentions = self.root / "mentions.json"
        mentions.write_text(
            json.dumps(
                [
                    {
                        "start": start,
                        "end": start + 7,
                        "card_id": "CORE_LOE_077",
                        "text": "Бранном",
                    }
                ]
            ),
            encoding="utf-8",
        )
        output = self.root / "output.md"
        process = self.run_helper(
            "card-shortcodes",
            "scripts/apply_shortcodes.py",
            source,
            "--catalog",
            catalog,
            "--format",
            "wild",
            "--mentions",
            mentions,
            "--output",
            output,
        )
        self.assertEqual(json.loads(process.stdout)["inserted"], 1)
        expected = text.replace(
            "Бранном", '[hs_card id="CORE_LOE_077"]Бранном[/hs_card]'
        )
        self.assertEqual(output.read_bytes(), expected.encode("utf-8"))
        self.assertEqual(source.read_bytes(), text.encode("utf-8"))

    def test_xml_runtime_contains_build_configs_lockfile_and_source_entrypoints(self):
        runtime = self.unpacked / "xml-team/runtime"
        for name in [
            "package.json",
            "pnpm-lock.yaml",
            "tsconfig.json",
            "tsconfig.build.json",
            "src/index.ts",
            "src/node.ts",
            "LICENSE",
        ]:
            self.assertTrue((runtime / name).is_file(), name)
        build = json.loads(
            (runtime / "tsconfig.build.json").read_text(encoding="utf-8")
        )
        self.assertTrue((runtime / build["extends"]).is_file())

    def test_shortcode_cli_rejects_stale_ranges_and_bad_input_without_changing_output(
        self,
    ):
        source = self.root / "guard-input.md"
        source.write_text("С Бранном сильнее.", encoding="utf-8")
        catalog = self.root / "guard-catalog.json"
        catalog.write_text(
            json.dumps(
                [
                    {
                        "name": "Бранн Бронзобород",
                        "id": "CORE_LOE_077",
                        "formats": ["wild"],
                    }
                ]
            ),
            encoding="utf-8",
        )
        mentions = self.root / "guard-mentions.json"
        output = self.root / "guard-output.md"
        output.write_bytes(b"previous verified output")
        for payload in [
            "{broken",
            "null",
            "{}",
            json.dumps(
                [{"start": 2, "end": 7, "text": "Бранн", "card_id": "CORE_LOE_077"}]
            ),
            json.dumps(
                [{"start": 2, "end": 9, "text": "Бранн", "card_id": "CORE_LOE_077"}]
            ),
            json.dumps([{"start": 2, "end": 9, "card_id": "CORE_LOE_077"}]),
        ]:
            with self.subTest(payload=payload):
                mentions.write_text(payload, encoding="utf-8")
                process = self.run_helper(
                    "card-shortcodes",
                    "scripts/apply_shortcodes.py",
                    source,
                    "--catalog",
                    catalog,
                    "--format",
                    "wild",
                    "--mentions",
                    mentions,
                    "--output",
                    output,
                    codes=(2,),
                )
                self.assertNotIn("Traceback", process.stderr)
                self.assertEqual(output.read_bytes(), b"previous verified output")
        source.write_bytes(b"\xffinvalid utf8")
        process = self.run_helper(
            "card-shortcodes",
            "scripts/apply_shortcodes.py",
            source,
            "--catalog",
            catalog,
            "--format",
            "wild",
            "--output",
            output,
            codes=(2,),
        )
        self.assertNotIn("Traceback", process.stderr)
        self.assertEqual(output.read_bytes(), b"previous verified output")

    def test_shortcode_cli_preserves_every_input_including_hardlink_aliases(self):
        source = self.root / "collision-input.md"
        source.write_text("Бранн", encoding="utf-8")
        catalog = self.root / "collision-catalog.json"
        catalog.write_text(
            json.dumps(
                [
                    {
                        "name": "Бранн Бронзобород",
                        "id": "CORE_LOE_077",
                        "formats": ["wild"],
                    }
                ]
            ),
            encoding="utf-8",
        )
        mentions = self.root / "collision-mentions.json"
        mentions.write_text(
            json.dumps(
                [{"start": 0, "end": 5, "text": "Бранн", "card_id": "CORE_LOE_077"}]
            ),
            encoding="utf-8",
        )
        inputs = [source, catalog, mentions]
        original = {path: path.read_bytes() for path in inputs}
        for output in inputs:
            with self.subTest(output=output.name):
                process = self.run_helper(
                    "card-shortcodes",
                    "scripts/apply_shortcodes.py",
                    source,
                    "--catalog",
                    catalog,
                    "--format",
                    "wild",
                    "--mentions",
                    mentions,
                    "--output",
                    output,
                    codes=(2,),
                )
                self.assertNotIn("Traceback", process.stderr)
                self.assertIn("every input file", process.stderr)
                self.assertEqual(original, {path: path.read_bytes() for path in inputs})
        alias = self.root / "hardlink-input.md"
        os.link(source, alias)
        process = self.run_helper(
            "card-shortcodes",
            "scripts/apply_shortcodes.py",
            source,
            "--catalog",
            catalog,
            "--format",
            "wild",
            "--mentions",
            mentions,
            "--output",
            alias,
            codes=(2,),
        )
        self.assertIn("every input file", process.stderr)
        self.assertEqual(alias.read_bytes(), original[source])

    def test_shortcode_cli_runs_directly_from_checkout_outside_repository(self):
        source, catalog, output = (
            self.root / "checkout-input.md",
            self.root / "checkout-catalog.json",
            self.root / "checkout-output.md",
        )
        source.write_bytes("Бранн Бронзобород помогает.\r\n".encode())
        catalog.write_text(
            json.dumps(
                [
                    {
                        "name": "Бранн Бронзобород",
                        "id": "CORE_LOE_077",
                        "formats": ["wild"],
                    }
                ]
            ),
            encoding="utf-8",
        )
        process = subprocess.run(
            [
                sys.executable,
                str(ROOT / "teams/card-shortcodes/scripts/apply_shortcodes.py"),
                str(source),
                "--catalog",
                str(catalog),
                "--format",
                "wild",
                "--output",
                str(output),
            ],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(json.loads(process.stdout)["inserted"], 1)
        self.assertEqual(
            output.read_bytes(),
            '[hs_card id="CORE_LOE_077"]Бранн Бронзобород[/hs_card] помогает.\r\n'.encode(),
        )


if __name__ == "__main__":
    unittest.main()
