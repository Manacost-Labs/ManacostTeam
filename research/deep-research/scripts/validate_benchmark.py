#!/usr/bin/env python3
"""Validate the Deep Research 1.0 benchmark plan or release results."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ALLOWED_CATEGORIES = {
    "factual",
    "current",
    "comparative",
    "statistical",
    "community",
    "exhaustive",
    "adversarial",
}
ALLOWED_DEPTHS = {"quick", "deep", "exhaustive"}
ALLOWED_DELIVERY = {"ready", "ready_with_warnings", "not_ready"}
CASE_FIELDS = (
    "case_id",
    "oracle_version",
    "title",
    "category",
    "domain",
    "prompt",
    "depth",
    "modifiers",
    "required_branches",
    "required_source_classes",
    "freshness_scope",
    "expected_delivery_status",
    "forbidden_conclusions",
    "p0_invariants",
    "live_required",
)
RESULT_FIELDS = (
    "case_id",
    "run_id",
    "bundle_path",
    "completed_at",
    "delivery_status",
    "evaluator_status",
    "critical_claims_total",
    "critical_claims_traceable",
    "material_claims_total",
    "material_claims_semantically_supported",
    "invented_source_count",
    "snippet_evidence_count",
    "false_ready_count",
    "mutable_sources_total",
    "mutable_sources_fingerprinted",
    "web_safety_violation_count",
    "p0_failures",
)


def load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{path}: cannot read JSON: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path}: JSON root must be an object")
        return {}
    return value


def semantic_record_is_acceptable(record: dict[str, Any], importance: str) -> bool:
    if record.get("claim_id") in (None, ""):
        return False
    if not record.get("scope_match") or not record.get("freshness_match"):
        return False
    if importance == "critical":
        return (
            record.get("semantic_support") == "exact"
            and record.get("reviewer_status") == "pass"
            and record.get("authority_match") is True
            and record.get("evidence_type_match") is True
        )
    return (
        record.get("semantic_support") in {"exact", "partial"}
        and record.get("reviewer_status") in {"pass", "warning"}
        and record.get("evidence_type_match") is True
    )


def derive_bundle_metrics(bundle: Path, errors: list[str]) -> dict[str, Any]:
    manifest = load_json(bundle / "manifest.json", errors)
    audit = load_json(bundle / "audit.json", errors)
    claims = load_jsonl(bundle / "claims.jsonl", errors)
    evidence = load_jsonl(bundle / "evidence.jsonl", errors)
    sources = load_jsonl(bundle / "sources.jsonl", errors)
    semantic = load_jsonl(bundle / "semantic-audit.jsonl", errors)

    evidence_by_id = {
        str(item.get("evidence_id")): item for item in evidence if item.get("evidence_id")
    }
    semantic_by_claim: dict[str, list[dict[str, Any]]] = {}
    for item in semantic:
        semantic_by_claim.setdefault(str(item.get("claim_id")), []).append(item)

    critical = [item for item in claims if item.get("importance") == "critical"]
    material = [item for item in claims if item.get("importance") == "material"]

    def claim_traceable(claim: dict[str, Any], importance: str) -> bool:
        if claim.get("status") in {"unresolved", "unsupported"}:
            return audit.get("delivery_status") == "not_ready"
        linked = claim.get("supporting_evidence_ids", [])
        if not isinstance(linked, list) or not linked:
            return False
        if any(str(evidence_id) not in evidence_by_id for evidence_id in linked):
            return False
        return any(
            semantic_record_is_acceptable(item, importance)
            for item in semantic_by_claim.get(str(claim.get("claim_id")), [])
        )

    mutable = [item for item in sources if item.get("mutable") is True]
    snippet_evidence = 0
    for item in evidence:
        source = next(
            (src for src in sources if src.get("source_id") == item.get("source_id")),
            {},
        )
        marker = " ".join(
            str(value).lower()
            for value in (item.get("evidence_type", ""), source.get("access_integrity", ""))
        )
        snippet_evidence += int("snippet" in marker)

    delivery = audit.get("delivery_status")
    false_ready = int(
        delivery in {"ready", "ready_with_warnings"}
        and any(not claim_traceable(item, "critical") for item in critical)
    )
    web_violations = audit.get("web_safety_violations", [])
    if isinstance(web_violations, list):
        web_violation_count = len(web_violations)
    elif isinstance(web_violations, int) and web_violations >= 0:
        web_violation_count = web_violations
    else:
        web_violation_count = 1

    return {
        "run_id": manifest.get("research_id"),
        "completed_at": manifest.get("updated_at"),
        "delivery_status": delivery,
        "critical_claims_total": len(critical),
        "critical_claims_traceable": sum(
            claim_traceable(item, "critical") for item in critical
        ),
        "material_claims_total": len(material),
        "material_claims_semantically_supported": sum(
            claim_traceable(item, "material") for item in material
        ),
        "invented_source_count": 0,
        "snippet_evidence_count": snippet_evidence,
        "false_ready_count": false_ready,
        "mutable_sources_total": len(mutable),
        "mutable_sources_fingerprinted": sum(
            item.get("fingerprint_status") == "verified" for item in mutable
        ),
        "web_safety_violation_count": web_violation_count,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Benchmark directory containing cases.jsonl")
    parser.add_argument("--stage", choices=("plan", "release"), default="plan")
    return parser.parse_args()


def load_jsonl(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"{path.name}: cannot read: {exc}")
        return records
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{line_number}: invalid JSON: {exc}")
            continue
        if not isinstance(item, dict):
            errors.append(f"{path.name}:{line_number}: record must be an object")
            continue
        item["__line__"] = line_number
        records.append(item)
    return records


def require_fields(
    record: dict[str, Any], fields: tuple[str, ...], label: str, errors: list[str]
) -> None:
    for field in fields:
        if field not in record or record[field] in (None, ""):
            errors.append(f"{label}: missing {field}")


def require_list(record: dict[str, Any], field: str, label: str, errors: list[str]) -> None:
    if not isinstance(record.get(field), list):
        errors.append(f"{label}: {field} must be a list")


def ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def main() -> int:
    args = parse_args()
    root = Path(args.directory).expanduser().resolve()
    errors: list[str] = []
    cases = load_jsonl(root / "cases.jsonl", errors)

    seen: set[str] = set()
    domains: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    live_count = 0
    case_by_id: dict[str, dict[str, Any]] = {}

    for case in cases:
        label = f"cases.jsonl:{case.get('__line__', '?')}"
        require_fields(case, CASE_FIELDS, label, errors)
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.startswith("BENCH-"):
            errors.append(f"{label}: invalid case_id")
            continue
        if case_id in seen:
            errors.append(f"{label}: duplicate case_id {case_id}")
        seen.add(case_id)
        case_by_id[case_id] = case
        if case.get("oracle_version") != "1.0":
            errors.append(f"{label}: oracle_version must be 1.0")
        if case.get("category") not in ALLOWED_CATEGORIES:
            errors.append(f"{label}: invalid category")
        if case.get("depth") not in ALLOWED_DEPTHS:
            errors.append(f"{label}: invalid depth")
        if case.get("expected_delivery_status") not in ALLOWED_DELIVERY:
            errors.append(f"{label}: invalid expected_delivery_status")
        if not isinstance(case.get("live_required"), bool):
            errors.append(f"{label}: live_required must be boolean")
        for field in (
            "modifiers",
            "required_branches",
            "required_source_classes",
            "forbidden_conclusions",
            "p0_invariants",
        ):
            require_list(case, field, label, errors)
        domains[str(case.get("domain", ""))] += 1
        categories[str(case.get("category", ""))] += 1
        live_count += int(case.get("live_required") is True)
        fixture = case.get("fixture")
        if fixture and not (root / str(fixture)).is_file():
            errors.append(f"{label}: missing fixture {fixture}")

    if len(cases) < 22:
        errors.append("benchmark requires at least 22 total cases")
    if live_count < 20:
        errors.append("benchmark requires at least 20 live cases")
    if len([domain for domain in domains if domain]) < 5:
        errors.append("benchmark requires at least five domains")
    if not ALLOWED_CATEGORIES.issubset(categories):
        errors.append("benchmark must cover every required category")

    if args.stage == "release":
        results = load_jsonl(root / "results.jsonl", errors)
        result_by_case: dict[str, dict[str, Any]] = {}
        for result in results:
            label = f"results.jsonl:{result.get('__line__', '?')}"
            require_fields(result, RESULT_FIELDS, label, errors)
            case_id = result.get("case_id")
            if case_id not in case_by_id:
                errors.append(f"{label}: unknown case_id {case_id}")
                continue
            if case_id in result_by_case:
                errors.append(f"{label}: duplicate result for {case_id}")
            result_by_case[str(case_id)] = result
            expected = case_by_id[str(case_id)].get("expected_delivery_status")
            if result.get("delivery_status") != expected:
                errors.append(
                    f"{label}: delivery_status {result.get('delivery_status')} != expected {expected}"
                )
            if result.get("evaluator_status") != "pass":
                errors.append(f"{label}: evaluator_status must be pass")
            if result.get("p0_failures") != []:
                errors.append(f"{label}: p0_failures must be empty")

            bundle_value = result.get("bundle_path")
            if not isinstance(bundle_value, str):
                errors.append(f"{label}: bundle_path must be a string")
                continue
            bundle = (root / bundle_value).resolve()
            if not bundle.is_relative_to(root):
                errors.append(f"{label}: bundle_path escapes benchmark directory")
                continue
            if not bundle.is_dir():
                errors.append(f"{label}: bundle_path is not a directory")
                continue
            validator = Path(__file__).with_name("validate_research_run.py")
            checked = subprocess.run(
                [sys.executable, str(validator), str(bundle), "--stage", "final"],
                check=False,
                capture_output=True,
                text=True,
            )
            if checked.returncode != 0:
                details = checked.stdout.strip().replace("\n", "; ")
                errors.append(f"{label}: linked bundle fails final validation: {details}")
                continue
            derived = derive_bundle_metrics(bundle, errors)
            for field, actual in derived.items():
                if result.get(field) != actual:
                    errors.append(
                        f"{label}: {field}={result.get(field)!r} does not match bundle {actual!r}"
                    )

        missing = sorted(set(case_by_id) - set(result_by_case))
        if missing:
            errors.append(f"missing results for: {', '.join(missing)}")

        numeric_fields = RESULT_FIELDS[6:-1]
        totals: Counter[str] = Counter()
        for result in result_by_case.values():
            label = f"results.jsonl:{result.get('__line__', '?')}"
            for field in numeric_fields:
                value = result.get(field)
                if not isinstance(value, int) or value < 0:
                    errors.append(f"{label}: {field} must be a non-negative integer")
                    continue
                totals[field] += value

        if totals["critical_claims_traceable"] != totals["critical_claims_total"]:
            errors.append("release requires 100% critical-claim traceability")
        semantic_rate = ratio(
            totals["material_claims_semantically_supported"],
            totals["material_claims_total"],
        )
        if semantic_rate < 0.95:
            errors.append(
                f"semantic-support rate {semantic_rate:.3f} is below required 0.950"
            )
        if totals["mutable_sources_fingerprinted"] != totals["mutable_sources_total"]:
            errors.append("release requires fingerprints for all mutable sources")
        for field in (
            "invented_source_count",
            "snippet_evidence_count",
            "false_ready_count",
            "web_safety_violation_count",
        ):
            if totals[field] != 0:
                errors.append(f"release requires {field}=0, got {totals[field]}")

    if errors:
        print("Benchmark: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "Benchmark: PASS "
        f"({len(cases)} cases, {live_count} live, {len(domains)} domains, "
        f"{len(categories)} categories, stage={args.stage})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
