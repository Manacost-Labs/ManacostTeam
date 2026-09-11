#!/usr/bin/env python3
"""Tests for deterministic research operations."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "scripts/research_ops.py"
RUN = ROOT.parent / "evaluation/benchmark/runs/BENCH-001"
sys.path.insert(0, str(ROOT / "scripts"))

from research_ops import effective_output_profile  # noqa: E402


class ResearchOpsTest(unittest.TestCase):
    def test_effective_output_profile_is_total_for_invalid_json_types(self) -> None:
        for invalid_profile in ([], {}):
            with self.subTest(invalid_profile=invalid_profile):
                self.assertEqual(
                    effective_output_profile(
                        {
                            "output_profile": invalid_profile,
                            "modifiers": ["current-patch-only"],
                        }
                    ),
                    ("research-report", True),
                )

    def test_resume_reports_research_identity(self) -> None:
        result = subprocess.run(
            [sys.executable, str(OPS), "resume", str(RUN)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        json_start = result.stdout.find("{")
        summary = json.loads(result.stdout[json_start:])
        self.assertIn("research_id", summary)
        self.assertEqual(summary["output_profile"], "research-report")
        self.assertFalse(summary["output_profile_inferred"])
        self.assertIsInstance(summary["modifiers"], list)

    def test_export_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            one, two = Path(temp) / "one.zip", Path(temp) / "two.zip"
            for output in (one, two):
                result = subprocess.run(
                    [sys.executable, str(OPS), "export", str(RUN), str(output)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                hashlib.sha256(one.read_bytes()).hexdigest(),
                hashlib.sha256(two.read_bytes()).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
