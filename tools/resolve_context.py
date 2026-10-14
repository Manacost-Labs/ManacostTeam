#!/usr/bin/env python3
"""Resolve portable task metadata; does not execute workflows or install skills."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for runtime in (
    Path(__file__).resolve().parents[1] / "shared",
    Path(__file__).resolve().parents[1] / "python",
):
    if (runtime / "manacost_context.py").is_file():
        sys.path.insert(0, str(runtime))
        break
from manacost_context import ROOT, load_catalog, resolve_context, validate_context  # noqa: E402

__all__ = ["ROOT", "load_catalog", "resolve_context", "validate_context"]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--game", help="Canonical game ID; omit for tasks unrelated to games"
    )
    parser.add_argument("--profile", help="Editorial profile; default: manacost for games, neutral otherwise")
    parser.add_argument("--execution", choices=("agent", "server"), default="agent")
    parser.add_argument(
        "--patch", help="User-supplied patch/build; not independently verified"
    )
    args = parser.parse_args()
    try:
        context = resolve_context(ROOT, **vars(args))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(context, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
