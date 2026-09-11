#!/usr/bin/env python3
"""Tests for semantic gold scoring."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCORE = ROOT / "scripts/score_semantic_gold.py"
GOLD_ROOT = ROOT.parent / "evaluation" / "gold"


class SemanticGoldTest(unittest.TestCase):
    def test_reference_predictions_pass(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCORE),
                str(GOLD_ROOT / "semantic-cases.jsonl"),
                str(GOLD_ROOT / "semantic-predictions.jsonl"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("20 cases", result.stdout)

    def test_p0_misclassification_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            predictions = []
            for line in (GOLD_ROOT / "semantic-predictions.jsonl").read_text(
                encoding="utf-8"
            ).splitlines():
                predictions.append(json.loads(line))
            predictions[0]["semantic_support"] = "none"
            target = Path(temp) / "predictions.jsonl"
            target.write_text(
                "".join(json.dumps(item) + "\n" for item in predictions), encoding="utf-8"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCORE),
                    str(GOLD_ROOT / "semantic-cases.jsonl"),
                    str(target),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("P0 failures: GOLD-001", result.stdout)


if __name__ == "__main__":
    unittest.main()

