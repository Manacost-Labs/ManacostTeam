"""Regression checks for the copy-ready Battlegrounds hero guide gate."""

import copy
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
REVIEW_GUIDE = VALID_GUIDE.replace("**Сила:** 3 из 5", "**Сила:** 3 из 5, оценка редакции") + "\nЕсли стол начнёт проигрывать, откажитесь от повышения и купите существо.\n"
REVIEW = {
    "schema_version": 1,
    "checked_on": "2026-10-20",
    "patch": "37.0.1",
    "mode": "solo",
    "heroes": [{
        "name": "Герой",
        "strength": 3,
        "difficulty": 2,
        "confidence": "low",
        "probes": [
            {
                "phase": "early",
                "state": "Третий ход, пять золотых, стол слабый и в таверне есть полезное существо.",
                "options": ["Купить полезное существо.", "Обновить таверну за один золотой."],
                "decision": "Купить полезное существо.",
                "reason": "Покупка сразу улучшает слабый стол на этом ходу.",
                "source_note": "Цена покупки и обновления проверена в журнале источников.",
                "guide_quote": "На третьем ходу купите полезное существо в таверне, если стол уже слабый.",
            },
            {
                "phase": "mid",
                "state": "Четвёртый ход, шесть золотых, второй уровень таверны и сильный стол.",
                "options": ["Повысить уровень таверны.", "Купить ещё одно существо."],
                "decision": "Повысить уровень таверны.",
                "reason": "Текущий стол выдерживает бой без дополнительной покупки.",
                "source_note": "Цена повышения и условие сильного стола проверены в журнале.",
                "guide_quote": "На четвёртом ходу повышайте таверну, когда стол выдерживает следующий бой.",
            },
            {
                "phase": "fallback",
                "state": "Позднее стол начал проигрывать, в таверне есть полезное существо.",
                "options": ["Купить полезное существо.", "Повысить уровень таверны."],
                "decision": "Купить полезное существо.",
                "reason": "Покупка укрепляет стол до следующего боя, а повышение не помогает сейчас.",
                "source_note": "Оба варианта и риск слабого стола описаны в журнале источников.",
                "guide_quote": "Если стол начнёт проигрывать, откажитесь от повышения и купите существо.",
            },
        ],
    }],
}


class BattlegroundsHeroGuideValidatorTests(unittest.TestCase):
    def test_accepts_copy_ready_guide(self):
        self.assertEqual(validator.validate(VALID_GUIDE), [])

    def test_accepts_editorial_strength_label(self):
        guide = VALID_GUIDE.replace("**Сила:** 3 из 5", "**Сила:** 3 из 5, оценка редакции")
        self.assertEqual(validator.validate(guide), [])

    def test_rejects_out_of_range_or_ambiguous_ratings(self):
        for field, value in (
            ("Сила", "0 из 5"),
            ("Сила", "6 из 5"),
            ("Сила", "3 из 10"),
            ("Сила", "3,5 из 5"),
            ("Сложность", "сложно"),
        ):
            with self.subTest(field=field, value=value):
                original = "3 из 5" if field == "Сила" else "2 из 5"
                guide = VALID_GUIDE.replace(f"**{field}:** {original}", f"**{field}:** {value}")
                issues = validator.validate(guide)
                self.assertTrue(any(f"«{field}» должна" in issue for issue in issues), issues)

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

    def test_review_matches_three_distinct_decisions_to_the_guide(self):
        self.assertEqual(validator.validate_review(REVIEW_GUIDE, REVIEW), [])

    def test_review_rejects_score_drift_and_missing_phase(self):
        review = copy.deepcopy(REVIEW)
        review["heroes"][0]["strength"] = 4
        review["heroes"][0]["probes"][2]["phase"] = "early"
        issues = validator.validate_review(REVIEW_GUIDE, review)
        self.assertTrue(any("не совпадает" in issue for issue in issues), issues)
        self.assertTrue(any("early, mid и fallback" in issue for issue in issues), issues)

    def test_review_rejects_quote_removed_from_guide(self):
        guide = REVIEW_GUIDE.replace("откажитесь от повышения", "отложите повышение")
        issues = validator.validate_review(guide, REVIEW)
        self.assertTrue(any("цитата не найдена" in issue for issue in issues), issues)

    def test_review_cannot_use_a_template_field_as_gameplay_evidence(self):
        review = copy.deepcopy(REVIEW)
        review["heroes"][0]["probes"][0]["guide_quote"] = "**Стартовая кривая:** классическая"
        issues = validator.validate_review(REVIEW_GUIDE, review)
        self.assertTrue(any("цитата не найдена" in issue for issue in issues), issues)

    def test_review_rejects_wrong_mode_and_unlabelled_strength(self):
        review = copy.deepcopy(REVIEW)
        review["mode"] = ["solo"]
        guide = REVIEW_GUIDE.replace(", оценка редакции", "")
        issues = validator.validate_review(guide, review)
        self.assertTrue(any("mode" in issue for issue in issues), issues)
        self.assertTrue(any("помечена" in issue for issue in issues), issues)


if __name__ == "__main__":
    unittest.main()
