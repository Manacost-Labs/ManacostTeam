"""Regression checks for the copy-ready Battlegrounds hero guide gate."""

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "skills/battlegrounds-hero-guides/scripts/validate_copy.py"
spec = importlib.util.spec_from_file_location("battlegrounds_hero_guide_validator", VALIDATOR)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)

VALID_GUIDE = """### Герой

**Сила:** 3 из 5
**Сложность:** 2 из 5
**Бан типов существ:** нет
**Стартовая кривая:** классическая

На третьем ходу купите полезное существо в таверне, если стол уже слабый.

На четвёртом ходу повышайте таверну, когда стол выдерживает следующий бой.
"""


class BattlegroundsHeroGuideValidatorTests(unittest.TestCase):
    def test_accepts_copy_ready_guide(self):
        self.assertEqual(validator.validate(VALID_GUIDE), [])

    def test_requires_four_fields_in_order_at_the_start(self):
        switched = VALID_GUIDE.replace(
            "**Сила:** 3 из 5\n**Сложность:** 2 из 5",
            "**Сложность:** 2 из 5\n**Сила:** 3 из 5",
        )
        issues = validator.validate(switched)
        self.assertTrue(any("позиции" in issue for issue in issues), issues)

    def test_headings_do_not_count_as_gameplay_paragraphs(self):
        headings_only = VALID_GUIDE.split("На третьем ходу")[0] + "## Начало\n\n## Конец\n"
        issues = validator.validate(headings_only)
        self.assertTrue(any("игровых абзаца" in issue for issue in issues), issues)

    def test_rejects_links_and_unwanted_battlegrounds_terms(self):
        bad = VALID_GUIDE.replace("существо в таверне", "существо в магазине")
        bad += "\nТёмный подарок улучшит доску. [Источник](https://example.com)\n"
        issues = validator.validate(bad)
        self.assertEqual(sum("нежелательный термин" in issue.lower() for issue in issues), 3)
        self.assertTrue(any("ссылка" in issue for issue in issues), issues)

    def test_rejects_bare_domain_and_source_citation(self):
        guide = VALID_GUIDE + "\nИсточник hsreplay.net и цитата 【1†карта】.\n"
        issues = validator.validate(guide)
        self.assertTrue(any("ссылка" in issue for issue in issues), issues)

    def test_does_not_flag_the_verb_podarit(self):
        guide = VALID_GUIDE.replace("купите полезное", "подарите себе полезное")
        self.assertEqual(validator.validate(guide), [])

    def test_unrelated_present_is_not_a_dark_gift_error(self):
        guide = VALID_GUIDE.replace("купите полезное", "получите подарок в тёмном лесу и купите полезное")
        self.assertEqual(validator.validate(guide), [])


if __name__ == "__main__":
    unittest.main()
