#!/usr/bin/env python3
"""Tests for the 1.0 benchmark release gate."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "scripts/validate_benchmark.py"
BENCHMARK = ROOT.parent / "evaluation" / "benchmark"


class BenchmarkValidationTest(unittest.TestCase):
    def test_real_benchmark_plan_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATE), str(BENCHMARK), "--stage", "plan"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("22 cases, 20 live", result.stdout)

    def test_real_benchmark_release_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATE), str(BENCHMARK), "--stage", "release"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_release_without_results_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "benchmark"
            shutil.copytree(BENCHMARK, target)
            (target / "results.jsonl").unlink()
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(target), "--stage", "release"],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("results.jsonl", result.stdout)

    def test_release_rejects_self_reported_metric_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "benchmark"
            shutil.copytree(BENCHMARK, target)
            lines = (target / "results.jsonl").read_text(encoding="utf-8").splitlines()
            record = json.loads(lines[0])
            record["critical_claims_total"] += 1
            lines[0] = json.dumps(record)
            (target / "results.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(target), "--stage", "release"],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match bundle", result.stdout)

    def test_duplicate_case_id_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            cases = (BENCHMARK / "cases.jsonl").read_text(encoding="utf-8")
            first = cases.splitlines()[0]
            (target / "cases.jsonl").write_text(cases + first + "\n", encoding="utf-8")
            (target / "fixtures").mkdir()
            for name in ("prompt-injection.html", "duplicate-lineage.html"):
                (target / "fixtures" / name).write_text(
                    (BENCHMARK / "fixtures" / name).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(target), "--stage", "plan"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate case_id", result.stdout)


if __name__ == "__main__":
    unittest.main()
