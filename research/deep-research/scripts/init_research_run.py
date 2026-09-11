#!/usr/bin/env python3
"""Initialize a persistent deep-research run without external dependencies."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


LEDGERS = (
    "queries.jsonl",
    "sources.jsonl",
    "evidence.jsonl",
    "claims.jsonl",
    "community.jsonl",
    "contradictions.jsonl",
    "checkpoints.jsonl",
    "semantic-audit.jsonl",
)

OUTPUT_PROFILES = ("editor-ready", "research-report", "raw-research")
COVERAGE_CONTRACT_VERSION = "1.0"


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="New or empty research-run directory")
    parser.add_argument("--question", required=True, help="Main research question")
    parser.add_argument(
        "--depth", choices=("quick", "deep", "exhaustive"), default="deep"
    )
    parser.add_argument(
        "--output-profile",
        choices=OUTPUT_PROFILES,
        default="research-report",
        help="Intended presentation profile for the completed research",
    )
    parser.add_argument("--domain", action="append", default=[], dest="domains")
    parser.add_argument("--modifier", action="append", default=[], dest="modifiers")
    parser.add_argument("--as-of", help="Research as-of date in YYYY-MM-DD")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target = Path(args.directory).expanduser().resolve()
    question = args.question.strip()
    if not question:
        print("error: --question must not be empty", file=sys.stderr)
        return 2
    if "raw-research" in args.modifiers:
        print(
            "error: raw-research is an output profile; use "
            "--output-profile raw-research instead of --modifier",
            file=sys.stderr,
        )
        return 2

    if target.exists() and not target.is_dir():
        print(f"error: target is not a directory: {target}", file=sys.stderr)
        return 2
    if target.exists() and any(target.iterdir()):
        print(f"error: refusing to overwrite non-empty directory: {target}", file=sys.stderr)
        return 2

    now = utc_now()
    as_of = args.as_of or now.date().isoformat()
    try:
        datetime.strptime(as_of, "%Y-%m-%d")
    except ValueError:
        print("error: --as-of must use YYYY-MM-DD", file=sys.stderr)
        return 2

    target.mkdir(parents=True, exist_ok=True)
    research_id = f"RES-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8].upper()}"
    timestamp = now.isoformat().replace("+00:00", "Z")

    manifest = {
        "schema_version": "1.2",
        "research_id": research_id,
        "main_question": question,
        "created_at": timestamp,
        "updated_at": timestamp,
        "as_of": as_of,
        "depth": args.depth,
        "output_profile": args.output_profile,
        "modifiers": list(dict.fromkeys(args.modifiers)),
        "domain_adapters": list(dict.fromkeys(args.domains)),
        "status": "planned",
        "current_context": {},
        "prior_research_ids": [],
        "provenance": {
            "fingerprint_policy": "when-permitted",
            "snapshot_policy": "local-only",
            "hash_algorithm": "sha256"
        },
    }
    coverage_enabled = args.output_profile == "editor-ready"
    useful_data_required = coverage_enabled and args.depth in {"deep", "exhaustive"}
    if coverage_enabled:
        manifest["coverage_contract_version"] = COVERAGE_CONTRACT_VERSION
    write_json(target / "manifest.json", manifest)
    for name in LEDGERS:
        (target / name).touch(exist_ok=False)

    audit = {
        "audit_status": "not_run",
        "critical_issues": [],
        "warnings": [],
        "claims_to_rewrite": [],
        "claims_to_remove": [],
        "additional_search_required": [],
        "clarity_review": {
            "status": (
                "not_run"
                if args.output_profile == "editor-ready"
                else "not_applicable"
            ),
            "claims_preserved": False,
            "numbers_preserved": False,
            "scope_preserved": False,
            "citations_preserved": False,
            "limitations_preserved": False,
            "contradictions_preserved": False,
            "reviewed_at": None,
            "reviewed_claim_ids": [],
            "report_sha256": None,
            "claims_sha256": None,
            "sources_sha256": None,
        },
    }
    if coverage_enabled:
        audit["coverage_review"] = {
            "status": "not_run",
            "sections_covered": False,
            "dispositions_preserved": False,
            "reviewed_at": None,
            "reviewed_record_ids": [],
            "omitted_record_ids": [],
            "section_results": [],
            "manifest_sha256": None,
            "plan_sha256": None,
            "queries_sha256": None,
            "sources_sha256": None,
            "evidence_sha256": None,
            "claims_sha256": None,
            "community_sha256": None,
            "contradictions_sha256": None,
            "checkpoints_sha256": None,
            "semantic_audit_sha256": None,
            "report_sha256": None,
            "useful_data_sha256": None,
            "appendix_sha256": None,
        }
        write_json(
            target / "plan.json",
            {
                "coverage_contract_version": COVERAGE_CONTRACT_VERSION,
                "research_id": research_id,
                "updated_at": timestamp,
                "deliverable_outline": [],
                "source_emphasis": {"x": "standard", "youtube": "standard"},
            },
        )
    write_json(target / "audit.json", audit)
    (target / "report.md").write_text(
        f"# Research Report\n\nResearch ID: `{research_id}`\n\n"
        "<!-- not-yet-synthesized -->\n",
        encoding="utf-8",
    )
    (target / "handoff.md").write_text(
        f"# Research Handoff\n\nResearch ID: `{research_id}`\n\n"
        f"Output profile: `{args.output_profile}`\n\n"
        "<!-- not-yet-audited -->\n",
        encoding="utf-8",
    )
    if useful_data_required:
        (target / "useful-data.md").write_text(
            "# Банк полезных данных\n\n"
            f"Research ID: `{research_id}`\n\n"
            "<!-- not-yet-populated -->\n",
            encoding="utf-8",
        )

    print(f"Initialized research run: {target}")
    print(f"Research ID: {research_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
