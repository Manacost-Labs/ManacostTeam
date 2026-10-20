"""Synthetic article records test structural gates, not real gameplay claims."""

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/funmeta/scripts/funmeta.py"
sys.path.insert(0, str(SCRIPT.parent))
from deck_code import encode
from funmeta import validate
from material import audit, outline
from quality import CLASS_NAMES, export_material
from test_funmeta import FunmetaV2Fixture


class MaterialTests(FunmetaV2Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.data["material_policy"] = 1
        self.candidate["material_heading"] = "Синтетическая основная сборка"
        alternate = copy.deepcopy(self.candidate)
        alternate.update(id="alternate", name="Синтетическая альтернатива",
                         material_heading="Синтетическая альтернатива", plan_difference="Other synthetic resource loop")
        alternate["deck_list"]["cards"] = [[3, 1], [4, 1]]
        alternate["deck_code"] = encode(alternate["deck_list"])
        self.data["candidates"].append(alternate)

    def material(self):
        lines = ["# Антимета: 2 необычные колоды", "", "В этом выпуске 2 необычные колоды.", "",
                 "## Общее положение фан-колод в мете", "Синтетический обзор условий игры.", "",
                 "## Какие карты самые фановые в нынешней мете", "Синтетическое объяснение карты.", "",
                 "## Фановые колоды для каждого класса"]
        for class_name, (ru, _) in CLASS_NAMES.items():
            lines.extend(["", f"### {ru}", "", f"Синтетический обзор класса {ru}.", ""])
            for row in self.data["candidates"]:
                if row["class"] != class_name or row["decision"] != "include":
                    continue
                lines.extend([f"#### {row.get('material_heading', row['name'])}", "",
                    "Синтетическое объяснение: готовим связку, соблюдаем условие и получаем результат.", "",
                    "**Код колоды**", "", "```text", row["deck_code"], "```", "",
                    "Источник: [Автор](https://creator.example/source)", ""])
        return "\n".join(lines)

    def codes(self, material):
        return {row["code"] for row in audit(self.data, material)["findings"] if row["severity"] == "error"}

    def test_complete_structure_exports_without_rewriting(self):
        material = self.material()
        result = audit(self.data, material)
        self.assertEqual(result["errors"], 0, result["findings"])
        self.assertEqual(result["printed_selected_decks"], 2)
        self.assertEqual(result["classes_present"], 11)
        self.assertTrue(result["mechanical_checks_only"])
        selection = self.save_review(material)
        output = self.run / "final.md"
        export_material(selection, self.data, validate(self.data, self.run), output)
        self.assertEqual(output.read_bytes(), (self.run / "material.md").read_bytes())

    def test_swapped_codes_block_export(self):
        first, second = [row["deck_code"] for row in self.data["candidates"]]
        material = self.material().replace(first, "TEMP").replace(second, first).replace("TEMP", second)
        self.assertIn("deck_code_placement", self.codes(material))
        selection = self.save_review(material)
        output = self.run / "blocked.md"
        with self.assertRaisesRegex(ValueError, "material audit failed"):
            export_material(selection, self.data, validate(self.data, self.run), output)
        self.assertFalse(output.exists())
        # Explicitly preserve the old contract; global code presence alone used to pass.
        self.data.pop("material_policy")
        selection = self.save_review(material)
        export_material(selection, self.data, validate(self.data, self.run), self.run / "legacy.md")

    def test_counts_and_placeholders(self):
        material = self.material().replace("Антимета: 2", "Антимета: 30")
        material = material.replace("В этом выпуске 2", "В этом выпуске 26")
        result = audit(self.data, material + "\n[Источник](URL)\nПОЛНЫЙ_ПРОВЕРЕННЫЙ_КОД_ОДНОЙ_СТРОКОЙ\n")
        counts = [f for f in result["findings"] if f["code"] == "declared_deck_count"]
        self.assertEqual(len(counts), 2)
        self.assertEqual([f["line"] for f in counts], [1, 3])
        self.assertIn("template_placeholder", {f["code"] for f in result["findings"]})

    def test_approximate_and_per_class_counts_need_manual_review(self):
        for label, title in (("approximate", "Антимета: около 2 колод"),
                             ("per_class", "Антимета: 2 колоды для каждого класса")):
            with self.subTest(case=label):
                result = audit(self.data, self.material().replace("Антимета: 2 необычные колоды", title))
                self.assertEqual(result["errors"], 0, result["findings"])
                self.assertIn("scoped_count_review", {f["code"] for f in result["findings"]})

    def test_explicit_minimum_and_maximum_counts(self):
        cases = (("minimum_met", "2+ необычные колоды", False),
                 ("minimum_not_met", "50+ фановых колод", True),
                 ("strict_more_not_met", "более 2 колод", True),
                 ("strict_more_met", "более 1 колоды", False),
                 ("maximum_not_met", "до 1 колоды", True))
        for label, claim, error in cases:
            with self.subTest(case=label):
                material = self.material().replace("2 необычные колоды", claim, 1)
                self.assertEqual("declared_deck_count" in self.codes(material), error)

    def test_full_roster_and_multiple_decks_per_class(self):
        self.data["gaps"] = {}
        for class_name in CLASS_NAMES:
            if class_name == "mage":
                continue
            row = copy.deepcopy(self.candidate)
            row.update(id=class_name, **{"class": class_name})
            self.data["candidates"].append(row)
        material = self.material().replace("2 необычные колоды", "12 необычных колод")
        result = audit(self.data, material)
        self.assertEqual(result["errors"], 0, result["findings"])
        self.assertEqual(result["printed_selected_decks"], 12)
        self.assertEqual(result["classes_present"], 11)

    def test_title_and_unknown_class_boundaries(self):
        material = self.material() + "\n# Лишний заголовок\n"
        self.assertIn("title_count", self.codes(material))
        self.assertIn("unknown_class_heading", self.codes(self.material().replace("### Маг", "### Неизвестный класс")))
        self.assertIn("title_count", self.codes(""))

    def test_research_count_is_not_mistaken_for_delivered_decks(self):
        material = self.material().replace("В этом выпуске 2 необычные колоды.", "Мы рассмотрели 30 колод и оставили самые интересные.")
        result = audit(self.data, material)
        self.assertEqual(result["errors"], 0)
        self.assertIn("count_context_review", {f["code"] for f in result["findings"]})

    def test_missing_sections_classes_and_decks_are_reported_together(self):
        result = audit(self.data, "# Антимета\n")
        findings = {f["code"] for f in result["findings"]}
        self.assertTrue({"main_sections", "class_missing", "selected_deck_missing"} <= findings)
        self.assertEqual(sum(f["code"] == "class_missing" for f in result["findings"]), 11)

    def test_wrong_class_and_unknown_deck_do_not_satisfy_coverage(self):
        material = self.material().replace("### Маг", "### Воин")
        codes = self.codes(material)
        self.assertTrue({"unselected_deck_heading", "selected_deck_missing", "duplicate_class_heading", "class_missing"} <= codes)

    def test_duplicate_deck_heading_is_rejected(self):
        material = self.material()
        start = material.index("#### Синтетическая основная сборка")
        end = material.index("#### Синтетическая альтернатива")
        material = material[:end] + material[start:end] + material[end:]
        self.assertIn("duplicate_deck_section", self.codes(material))

    def test_distinct_candidates_need_unambiguous_headings(self):
        self.data["candidates"][1]["material_heading"] = self.candidate["material_heading"]
        self.assertIn("ambiguous_deck_heading", self.codes(self.material()))

    def test_class_overview_and_deck_explanation_are_required(self):
        material = self.material().replace("Синтетический обзор класса Маг.", "")
        material = material.replace("Синтетическое объяснение: готовим связку, соблюдаем условие и получаем результат.", "", 1)
        self.assertTrue({"class_overview_missing", "deck_explanation_missing"} <= self.codes(material))

    def test_source_and_reconstructed_disclosure_stay_with_deck(self):
        self.candidate["code_provenance"] = {"kind": "reconstructed-list", "source_ids": ["deck"]}
        material = self.material()
        self.assertIn("reconstructed_code_undisclosed", self.codes(material))
        material = material.replace("Источник: [Автор]", "Код восстановлен из опубликованного состава.\n\nИсточник: [Автор]", 1)
        self.assertEqual(audit(self.data, material)["errors"], 0)
        self.assertIn("deck_source_missing", self.codes(material.replace("https://creator.example/source", "https://unrelated.example/")))

    def test_fences_cannot_hide_wrong_code_or_fake_headings(self):
        for label, replacement in (("wrong_language", "```python"), ("unclosed", "```text\n```text")):
            material = self.material().replace("```text", replacement, 1)
            with self.subTest(case=label):
                self.assertGreater(audit(self.data, material)["errors"], 0)
        material = self.material() + "\n```text\n### Маг\n```\n"
        codes = self.codes(material)
        self.assertIn("unassigned_code_block", codes)
        self.assertNotIn("duplicate_class_heading", codes)

    def test_standard_fences_and_crlf_are_preserved(self):
        material = self.material().replace("```text", "~~~~plaintext").replace("```", "~~~~")
        material = material.replace("\n", "\r\n")
        self.assertEqual(audit(self.data, material)["errors"], 0)
        selection = self.save_review(material)
        export_material(selection, self.data, validate(self.data, self.run), self.run / "tilde.md")

    def test_extra_code_and_unverified_candidate_are_rejected(self):
        code = self.candidate["deck_code"]
        material = self.material().replace(code, code + "\ncomment", 1)
        self.assertIn("deck_code_placement", self.codes(material))
        self.candidate["deck_code_status"] = "unavailable"
        self.assertIn("candidate_code_unverified", self.codes(self.material()))

    def test_outline_groups_distinct_plans_without_writing_article(self):
        pending = copy.deepcopy(self.candidate)
        pending.update(id="pending", decision="pending", name="Unverified idea")
        self.data["candidates"].append(pending)
        before = copy.deepcopy(self.data)
        result = outline(self.data)
        mage = next(c for c in result["classes"] if c["class"] == "mage")
        self.assertEqual(result["selected_decks"], 2)
        self.assertEqual(len(mage["decks"]), 2)
        self.assertNotEqual(mage["decks"][0]["research"]["plan_difference"], mage["decks"][1]["research"]["plan_difference"])
        self.assertEqual(result["pending_candidates"], ["pending"])
        self.assertEqual(self.data, before)
        self.assertNotIn("material", result)

    def test_audit_is_independent_of_missing_meta_but_export_is_not(self):
        self.data["meta_source_ids"] = []
        self.assertEqual(audit(self.data, self.material())["errors"], 0)
        with self.assertRaisesRegex(ValueError, "meta_source_ids"):
            validate(self.data, self.run)

    def test_reused_plan_notes_require_editorial_comparison(self):
        self.data["candidates"][1]["plan_difference"] = self.candidate["plan_difference"]
        mage = next(c for c in outline(self.data)["classes"] if c["class"] == "mage")
        self.assertEqual(mage["review_tasks"][0]["kind"], "differentiate_game_plans")
        self.assertEqual(mage["review_tasks"][0]["candidates"], ["example", "alternate"])
        self.assertEqual(self.data["candidates"][1]["decision"], "include")

    def test_source_label_alone_is_not_an_explanation(self):
        material = self.material().replace("Синтетическое объяснение: готовим связку, соблюдаем условие и получаем результат.", "[Автор](https://creator.example/source)", 1)
        material = material.replace("**Код колоды**", "**Код колоды:**")
        self.assertIn("deck_explanation_missing", self.codes(material))

    def test_literal_author_underscores_do_not_merge_headings(self):
        self.candidate["material_heading"] = "Build from some_author"
        self.data["candidates"][1]["material_heading"] = "Build from someauthor"
        self.assertEqual(audit(self.data, self.material())["errors"], 0)

    def test_invalid_policy_and_multiline_heading_are_rejected(self):
        for value in (True, 0, 2, "1"):
            self.data["material_policy"] = value
            with self.subTest(case=str(value)), self.assertRaisesRegex(ValueError, "material_policy"):
                validate(self.data, self.run)
        self.candidate["material_heading"] = "Heading\nSecond line"
        with self.assertRaisesRegex(ValueError, "material_heading"):
            outline(self.data)

    def test_cli_is_read_only_and_returns_findings_with_failure_exit(self):
        selection = self.save_review(self.material())
        paths = [selection, self.run / "material.md", self.run / "review.json"]
        before = [p.read_bytes() for p in paths]
        for command in ("audit", "outline"):
            result = subprocess.run([sys.executable, str(SCRIPT), command, str(selection)], capture_output=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(json.loads(result.stdout)["status"], ("editorial_outline", "material_structure_valid"))
        self.assertEqual([p.read_bytes() for p in paths], before)
        (self.run / "material.md").write_text("# Черновик\n", encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "audit", str(selection)], capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertGreater(json.loads(result.stdout)["errors"], 1)
        self.assertEqual((self.run / "review.json").read_bytes(), before[2])
