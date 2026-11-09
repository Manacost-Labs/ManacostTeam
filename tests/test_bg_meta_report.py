import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/bg-meta-report/scripts/bg_meta_report.py"
sys.path.insert(0, str(SCRIPT.parent))
from bg_meta_report import (  # noqa: E402
    COMMUNITY_LANES, GLOBAL_LANES, RACE_LANES, audit_coverage, check_article, initialize,
)

# Synthetic text exercising the format gates; it makes no Battlegrounds claims.
GOOD = """# Синтетический заголовок. Мета-отчет по Полям Сражений #1

Вступление с крючком.

Приятного чтения!

## Характеристика меты и Темные дары

Абзац. Игрок на стриме показал деталь.

## Как патч повлиял на мету

- **Карта** стала сильнее.

## Тир-лист рас

| Тир | Расы |
|---|---|
| S | Альфа |

## Баланс рас и стратегий

### Альфа

Крючок про расу, история со стрима.

#### Через Кор-карту

![Альфа через Кор-карту](images/alpha.png)

Проза о сборке, третий стрим.

## Повторяющиеся советы сильных игроков

1. **Совет.** Пояснение.

## Тир-лист героев

**Тир-1:** [hs_bg id="TB_BaconShop_HERO_37"]Герой[/hs_bg], Другой герой.

Финал.

Удачи в таверне!
"""


class BgMetaReportTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "images").mkdir()
        (self.root / "images/alpha.png").write_bytes(b"png")

    def article(self, text):
        path = self.root / "article.md"
        path.write_bytes(text.encode("utf-8"))
        return path

    def test_init_creates_brief_and_full_matrix(self):
        run = self.root / "run"
        brief = json.loads(initialize(run, "2026-11-07", "37.0.2", 13, ("Альфа", "Бета"))
                           .read_text(encoding="utf-8"))
        self.assertEqual(brief["research"]["depth"], "exhaustive")
        self.assertEqual(brief["races"], ["Альфа", "Бета"])
        matrix = json.loads((run / "search-matrix.json").read_text(encoding="utf-8"))
        self.assertEqual(set(matrix["global"]), set(GLOBAL_LANES))
        self.assertEqual(set(matrix["races"]["Бета"]["lanes"]), set(RACE_LANES))
        with self.assertRaises(FileExistsError):
            initialize(run, "2026-11-07")
        with self.assertRaises(ValueError):
            initialize(self.root / "bad", "07.11.2026")

    def test_coverage_requires_every_cell_and_both_lane_kinds(self):
        run = self.root / "run"
        initialize(run, "2026-11-07", races=("Альфа",))
        result = audit_coverage(run)
        self.assertFalse(result["ok"])
        self.assertTrue(any("pending" in e for e in result["errors"]))

        matrix = json.loads((run / "search-matrix.json").read_text(encoding="utf-8"))
        done = {"status": "inspected", "queries": ["q"], "urls": ["https://example.test"],
                "reason": "", "findings": ["f"]}
        empty = {"status": "no_relevant_results", "queries": ["q"], "urls": [],
                 "reason": "nothing new", "findings": []}
        matrix["global"] = {lane: dict(done) for lane in GLOBAL_LANES}
        race = matrix["races"]["Альфа"]
        race["lanes"] = {lane: dict(empty) for lane in RACE_LANES}
        (run / "search-matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
        errors = audit_coverage(run)["errors"]
        self.assertTrue(any("community" in e for e in errors))
        self.assertTrue(any("data lane" in e for e in errors))
        self.assertTrue(any("saturation" in e for e in errors))

        race["lanes"]["reddit"] = dict(done)
        race["lanes"]["statistics"] = dict(done)
        race["saturation"] = "волна 3 без новых условий"
        (run / "search-matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
        self.assertTrue(audit_coverage(run)["ok"])
        self.assertIn("reddit", COMMUNITY_LANES)

        race["lanes"]["x"] = {"status": "blocked", "queries": [], "urls": [], "reason": ""}
        (run / "search-matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
        self.assertTrue(any("without reason" in e for e in audit_coverage(run)["errors"]))

    def test_good_article_passes_with_shortcodes_and_crlf(self):
        result = check_article(self.article(GOOD.replace("\n", "\r\n")), ("Альфа",))
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["ok"])

    def test_format_check_does_not_require_stream_anecdotes(self):
        text = GOOD.replace("Игрок на стриме показал деталь.", "")
        text = text.replace("история со стрима", "изменение после патча")
        text = text.replace("третий стрим", "условие выбора")
        result = check_article(self.article(text), ("Альфа",))
        self.assertTrue(result["ok"])
        self.assertFalse(any("стрим" in warning for warning in result["warnings"]))

    def test_format_success_is_not_editorial_approval(self):
        # Intentionally empty advice can pass structural checks. Do not certify it.
        text = GOOD.replace("Проза о сборке, третий стрим.", "Покупайте полезных существ.")
        result = check_article(self.article(text), ("Альфа",))
        self.assertTrue(result["ok"])
        self.assertEqual(result["scope"], "structure_and_style_signals")
        self.assertIs(result["publication_ready"], False)
        self.assertEqual(result["required_reviews"], ["fact_review", "literary_review"])

    def test_article_gates(self):
        cases = {
            "нет раздела расы": GOOD.replace("### Альфа", "### Гамма"),
            "нет ленты карт": GOOD.replace("![Альфа через Кор-карту](images/alpha.png)", ""),
            "файл картинки не найден": GOOD.replace("images/alpha.png", "images/missing.png"),
            "процент": GOOD.replace("Проза о сборке", "Проза о сборке, 27,5%"),
            "среднее место": GOOD.replace("Абзац.", "Среднее место 3,4."),
            "таблиц": GOOD.replace("Финал.", "| a | b |\n|---|---|\n| 1 | 2 |"),
            "чек-листовый подзаголовок": GOOD.replace("Проза о сборке", "##### Когда переходить\n\nтекст"),
            "числа в тир-листе героев": GOOD.replace("Другой герой.", "Другой герой (3,9)."),
            "Приятного чтения": GOOD.replace("Приятного чтения!", "Начнем."),
            "нет раздела «тир-лист героев»": GOOD.replace("## Тир-лист героев", "## Герои"),
        }
        for label, text in cases.items():
            with self.subTest(label):
                result = check_article(self.article(text), ("Альфа",))
                self.assertFalse(result["ok"])
                self.assertTrue(any(label in error for error in result["errors"]), result["errors"])

    def test_cli_check_uses_brief_races(self):
        run = self.root / "run"
        brief = initialize(run, "2026-11-07", races=("Альфа", "Бета"))
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "check", str(self.article(GOOD)), "--brief", str(brief)],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Бета", completed.stdout)


if __name__ == "__main__":
    unittest.main()
