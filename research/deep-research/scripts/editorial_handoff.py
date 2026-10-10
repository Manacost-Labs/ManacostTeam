#!/usr/bin/env python3
"""Compile inspected evidence into a chapter handoff and a bounded gap queue.

This checks data completeness, not the truth of a source. Run the existing bundle
and semantic validators first; human review is still needed for publication.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SUPPORTED = {"supported", "supported_with_conditions"}


def records(root: Path, name: str) -> dict[str, dict[str, Any]]:
    result = {}
    key = {"claims": "claim_id", "sources": "source_id", "evidence": "evidence_id"}[
        name
    ]
    for line in (root / f"{name}.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if (
            not isinstance(item, dict)
            or not isinstance(item.get(key), str)
            or not item[key].strip()
            or item[key] in result
        ):
            raise ValueError(f"invalid or duplicate {key}")
        result[item[key]] = item
    return result


def decision_coverage(plan: dict[str, Any], supported_ids: set[str]) -> dict[str, Any]:
    blocking, warnings, gaps = [], [], []
    chapters = {}
    for chapter in plan.get("chapters", []):
        cid = chapter.get("chapter_id")
        ids = chapter.get("required_claim_ids", [])
        if (
            not cid
            or cid in chapters
            or not chapter.get("title")
            or not isinstance(ids, list)
            or not ids
        ):
            blocking.append(f"invalid or empty chapter {cid}")
            continue
        chapters[cid] = set(ids)
        if chapter.get("unresolved_questions"):
            warnings.append(f"{cid}: unresolved chapter questions")
        for claim_id in ids:
            if claim_id not in supported_ids:
                blocking.append(f"{cid}: unsupported required claim {claim_id}")
    seen, covered = set(), set()
    required, answered = 0, 0
    for question in plan.get("decisions", []):
        qid, cid = question.get("question_id"), question.get("chapter_id")
        if (
            not qid
            or qid in seen
            or cid not in chapters
            or not question.get("question")
        ):
            blocking.append(f"invalid or duplicate question {qid}")
            continue
        seen.add(qid)
        status, ids = question.get("status"), question.get("claim_ids", [])
        if not isinstance(ids, list) or status not in {"answered", "open", "excluded"}:
            blocking.append(f"{qid}: invalid status or claim_ids")
            continue
        is_required = question.get("required") is True
        if is_required:
            required += 1
            covered.add(cid)
        valid_answer = (
            status == "answered"
            and bool(ids)
            and set(ids) <= supported_ids
            and set(ids) <= chapters[cid]
        )
        if is_required and valid_answer:
            answered += 1
        elif is_required:
            blocking.append(f"{qid}: required decision unanswered")
            gaps.append(
                {
                    **question,
                    "reason": "missing_supported_answer",
                    "search_rounds_remaining": 1,
                }
            )
        elif status == "open":
            warnings.append(f"{qid}: optional question open")
            gaps.append(
                {**question, "reason": "optional_gap", "search_rounds_remaining": 1}
            )
        elif status == "answered" and not valid_answer:
            blocking.append(f"{qid}: answer is not in the chapter handoff")
    if not chapters or not required:
        blocking.append("chapters and required reader decisions are mandatory")
    for cid in chapters.keys() - covered:
        blocking.append(f"{cid}: no required reader question")
    return {
        "required_questions": required,
        "answered_required_questions": answered,
        "required_coverage": answered / required if required else None,
        "blocking": blocking,
        "warnings": warnings,
        "gap_queue": gaps,
        "stop_rules": {
            "max_gap_search_rounds": 1,
            "max_debate_rounds": 2,
            "max_editor_repairs": 2,
        },
    }


def compile_handoff(
    root: Path, plan: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    claims, evidence, sources = (
        records(root, name) for name in ("claims", "evidence", "sources")
    )
    patch = plan.get("patch")
    output_claims, output_sources, issues = [], {}, []
    requested = {
        cid
        for ch in plan.get("chapters", [])
        for cid in ch.get("required_claim_ids", [])
    }
    for cid in sorted(requested):
        claim = claims.get(cid, {})
        confidence = str(claim.get("confidence", "")).lower()
        if (
            claim.get("status") not in SUPPORTED
            or claim.get("patch") != patch
            or confidence not in {"high", "medium", "low"}
        ):
            issues.append(f"{cid}: unsupported, uncalibrated or wrong patch")
            continue
        if (
            claim.get("status") == "supported_with_conditions"
            and not str(claim.get("condition", "")).strip()
        ):
            issues.append(f"{cid}: condition must be explicit")
            continue
        refs = []
        for eid in claim.get("supporting_evidence_ids", []):
            item = evidence.get(eid, {})
            sid = item.get("source_id")
            source = sources.get(sid, {})
            quote = item.get("quote") or item.get("verbatim_quote")
            parsed = urlsplit(source.get("url", ""))
            if (
                not isinstance(quote, str)
                or not quote.strip()
                or source.get("access_integrity")
                not in {"full_text", "full", "inspected"}
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
            ):
                issues.append(
                    f"{cid}/{eid}: inspected source and verbatim quote required"
                )
                continue
            # Evidence IDs retain distinct locators and quotes from the same source.
            refs.append(eid)
            output_sources[eid] = {
                "source_id": eid,
                "original_source_id": sid,
                "url": source["url"],
                "quote": quote,
                "locator": item.get("locator", ""),
            }
        meaning = claim.get("meaning") or claim.get("claim")
        if not refs or not isinstance(meaning, str) or not meaning.strip():
            issues.append(f"{cid}: no supported meaning/evidence")
            continue
        output_claims.append(
            {
                "claim_id": cid,
                "meaning": meaning,
                "action": claim.get("action", ""),
                "condition": claim.get("condition", ""),
                "exception": claim.get("exception", ""),
                "confidence": confidence,
                "patch": patch,
                "status": claim["status"],
                "evidence_refs": refs,
            }
        )
    report = decision_coverage(plan, {claim["claim_id"] for claim in output_claims})
    report["blocking"].extend(issues)
    if not all(
        isinstance(plan.get(key), str) and plan[key].strip()
        for key in ("brief", "patch", "style_profile")
    ):
        report["blocking"].append("brief, patch and style_profile are mandatory")
    handoff = {
        "schema_version": 1,
        "brief": plan.get("brief", ""),
        "patch": patch or "",
        "style_profile": plan.get("style_profile", ""),
        "status": "research_blocked"
        if report["blocking"]
        else "research_ready_with_gaps"
        if report["warnings"]
        else "research_ready",
        "claims": output_claims,
        "sources": list(output_sources.values()),
        "chapters": plan.get("chapters", []),
        "decisions": plan.get("decisions", []),
    }
    return handoff, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--plan",
        type=Path,
        required=True,
        help="Editorial plan with reader questions and verified claim IDs",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        handoff, report = compile_handoff(
            args.directory, json.loads(args.plan.read_text(encoding="utf-8"))
        )
        if args.output.resolve() == args.report.resolve():
            raise ValueError("handoff and coverage report need separate new files")
        for path, value in ((args.output, handoff), (args.report, report)):
            if path.exists():
                raise ValueError(f"refusing to overwrite {path}")
        for path, value in ((args.output, handoff), (args.report, report)):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        print(
            json.dumps(
                {
                    "status": handoff["status"],
                    "required_coverage": report["required_coverage"],
                    "gaps": len(report["gap_queue"]),
                },
                ensure_ascii=False,
            )
        )
        return 1 if report["blocking"] else 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
