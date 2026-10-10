import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from editorteam.editorial_tools import evaluation_exports, grounded_extractions


class EditorialToolTests(unittest.TestCase):
    def test_unaligned_advice_and_invented_conditions_rejected(self):
        source = "Совет при условии."
        item = SimpleNamespace(
            char_interval=SimpleNamespace(start_pos=0, end_pos=len(source)),
            extraction_text=source,
            attributes={"action": "Совет", "condition": "при условии"},
        )
        self.assertEqual(
            grounded_extractions(SimpleNamespace(extractions=[item]), source)[0]["confidence"],
            "unassessed",
        )
        item.attributes["exception"] = "неизвестное исключение"
        with self.assertRaises(ValueError):
            grounded_extractions(SimpleNamespace(extractions=[item]), source)
        item.char_interval = None
        with self.assertRaises(ValueError):
            grounded_extractions(SimpleNamespace(extractions=[item]), source)

    def test_optimizer_cannot_train_on_holdout_or_unreviewed_articles(self):
        train = {
            "case_id": "train",
            "question": "Вопрос",
            "response": "Ответ",
            "reference": "Эталон",
            "review_status": "approved",
            "split": "train",
            "retrieved_context": [{"text": "Источник"}],
        }
        holdout = {**train, "case_id": "holdout", "split": "holdout"}
        result = evaluation_exports([train, holdout])
        self.assertEqual([r["case_id"] for r in result["dspy_train"]], ["train"])
        self.assertEqual(result["ragchecker"]["results"][0]["gt_answer"], "Эталон")
        with self.assertRaises(ValueError):
            evaluation_exports([{**train, "review_status": "candidate"}])


if __name__ == "__main__":
    unittest.main()
