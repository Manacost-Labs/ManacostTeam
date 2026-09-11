#!/usr/bin/env python3
"""Generate benchmark results from validated research bundles."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from validate_benchmark import derive_bundle_metrics, load_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Benchmark directory")
    parser.add_argument("--apply", action="store_true", help="Write results.jsonl")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.directory).expanduser().resolve()
    errors: list[str] = []
    cases = load_jsonl(root / "cases.jsonl", errors)
    records: list[dict[str, object]] = []
    validator = Path(__file__).with_name("validate_research_run.py")

    for case in cases:
        case_id = str(case.get("case_id", ""))
        bundle = root / "runs" / case_id
        checked = subprocess.run(
            [sys.executable, str(validator), str(bundle), "--stage", "final"],
            check=False,
            capture_output=True,
            text=True,
        )
        if checked.returncode != 0:
            errors.append(f"{case_id}: final validation failed: {checked.stdout.strip()}")
            continue
        metrics = derive_bundle_metrics(bundle, errors)
        p0: list[str] = []
        if metrics.get("delivery_status") != case.get("expected_delivery_status"):
            p0.append("delivery_status_mismatch")
        if metrics.get("critical_claims_traceable") != metrics.get("critical_claims_total"):
            p0.append("critical_claim_not_traceable")
        if metrics.get("mutable_sources_fingerprinted") != metrics.get("mutable_sources_total"):
            p0.append("mutable_source_not_fingerprinted")
        if metrics.get("snippet_evidence_count") != 0:
            p0.append("snippet_used_as_evidence")
        record: dict[str, object] = {
            "case_id": case_id,
            "run_id": metrics.pop("run_id"),
            "bundle_path": f"runs/{case_id}",
            "completed_at": metrics.pop("completed_at"),
            "delivery_status": metrics.pop("delivery_status"),
            "evaluator_status": "pass" if not p0 else "fail",
            **metrics,
            "p0_failures": p0,
        }
        records.append(record)

    if errors:
        print("Benchmark result generation: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    rendered = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n"
        for record in records
    )
    if args.apply:
        (root / "results.jsonl").write_text(rendered, encoding="utf-8")
        print(f"Wrote {len(records)} derived results to {root / 'results.jsonl'}")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
