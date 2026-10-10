#!/usr/bin/env python3
"""Portable entrypoint for native Codex publication runs and benchmark preparation."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

skill_root = Path(__file__).resolve().parents[1]
for runtime in (skill_root / "python", skill_root.parents[1] / "editor" / "src"):
    if (runtime / "editorteam").is_dir():
        sys.path.insert(0, str(runtime))
        break
else:
    raise SystemExit(
        "Не найден runtime editorteam. Используйте полный пакет manacost-publish."
    )

module = "publication_run"
if len(sys.argv) > 1 and sys.argv[1] == "benchmark":
    module = "publication_benchmark"
    del sys.argv[1]

if __name__ == "__main__":
    raise SystemExit(importlib.import_module(f"editorteam.{module}").main())
