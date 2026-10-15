"""Honest execution metadata for nightly/editor scoring; no model calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def skipped_report(reason: str) -> dict:
    return {
        "run_status": "not_run",
        "reason": reason,
        "requested": 0,
        "cases": 0,
        "accepted": 0,
        "share": None,
        "model_evaluation_completed": False,
        "quality_validated": False,
    }


def execution_summary(rows: list[dict], source: str, model: str | None) -> dict:
    scored = [row for row in rows if row.get("candidate")] if source != "inputs" else rows
    accepted = sum(
        bool((row.get("candidate") or row["input"])["accepted"])
        and (source != "gateway" or row.get("gateway", {}).get("accepted") is True)
        for row in scored
    )
    requested = len(rows)
    complete = requested > 0 and len(scored) == requested
    status = "completed" if complete else "partial" if scored else "failed"
    return {
        "requested": requested,
        "cases": len(scored),
        "accepted": accepted,
        "missing": requested - len(scored),
        "share": round(accepted / requested, 3) if requested else None,
        "run_status": status,
        "model_evaluation_completed": complete and source == "gateway" and bool(model),
        "quality_validated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skipped", required=True, help="Explicit reason, e.g. no_provider_key")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(skipped_report(args.skipped), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
