import tempfile
import unittest
from pathlib import Path

from app.core import (
    append_translation_memory,
    changed_segment_ids,
    load_glossary,
    load_translation_memory,
    protect_terms,
    qa_translation,
    segment_markdown,
)


class CoreTests(unittest.TestCase):
    def test_glossary_protects_multiword_name_and_manual_single_word(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            glossary = Path(temporary) / "terms.tsv"
            glossary.write_text(
                "Armor Up\t«Поднять щит!»\nRagnaros\tРагнарос\tmanual=true\nArmor\tБроня\n",
                encoding="utf-8",
            )
            loaded = load_glossary([glossary])
        protected, replacements = protect_terms("Armor Up and Ragnaros.", loaded)
        self.assertEqual(protected, "[[[TERM_1]]] and [[[TERM_2]]].")
        self.assertEqual(list(replacements.values()), ["«Поднять щит!»", "Рагнарос"])

    def test_segments_are_stable_and_diff_marks_only_changed_content(self) -> None:
        original = "First paragraph.\n\nSecond paragraph."
        updated = "First paragraph.\n\nChanged paragraph."
        self.assertEqual(len(segment_markdown(original)), 2)
        self.assertEqual(len(changed_segment_ids(original, updated)), 1)

    def test_memory_persists_only_approved_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            memory = Path(temporary) / "memory.tsv"
            append_translation_memory(memory, "Power Word: Fortitude", "Слово силы: Стойкость", "raid")
            self.assertEqual(load_translation_memory(memory)["Power Word: Fortitude"], "Слово силы: Стойкость")

    def test_qa_reports_lost_number_link_and_term(self) -> None:
        source = "Use [[[TERM_1]]] for 20%. [link](https://example.com/a)"
        report = qa_translation(source, "Используйте другое усиление.", {"[[[TERM_1]]]": "Нужное усиление"})
        self.assertFalse(report["ready_for_editor"])
        self.assertEqual(report["missing_numbers"], ["20%"])
        self.assertEqual(report["missing_links"], ["https://example.com/a"])
        self.assertEqual(report["missing_terms"], ["Нужное усиление"])
