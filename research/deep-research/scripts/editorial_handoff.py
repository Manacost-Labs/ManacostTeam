#!/usr/bin/env python3
"""Compile inspected evidence into a chapter handoff and a bounded gap queue.

This checks data completeness, not the truth of a source. Run the existing bundle
and semantic validators first; human review is still needed for publication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from search_support import quote_in_text

SUPPORTED = {"supported", "supported_with_conditions"}
CARD_FIELDS = {
    "situation",
    "options",
    "action",
    "reason",
    "tradeoff",
    "exception",
    "example",
    "counterexample",
}


def context_fields(record: dict, excluded: set[str]) -> dict:
    """Retain structured provenance without copying the full source body."""
    return {
        key: value
        for key, value in record.items()
        if key not in excluded | {"text", "html", "body", "content", "snapshot_path"}
    }


def decision_cards(chapter: dict, claims: dict) -> tuple[list[str], list[str]]:
    errors, gaps, seen = [], [], set()
    cards = chapter.get("decision_cards", [])
    if not isinstance(cards, list) or len(cards) > 32:
        return ["invalid decision_cards"], []
    allowed = set(chapter.get("required_claim_ids", []))
    for card in cards:
        if not isinstance(card, dict):
            errors.append("invalid decision card")
            continue
        identity, fields = card.get("card_id"), card.get("fields")
        if not isinstance(identity, str) or not identity.strip() or identity in seen:
            errors.append("invalid or duplicate card_id")
            continue
        seen.add(identity)
        if (
            card.get("kind") not in {"observed", "derived", "illustrative"}
            or card.get("status")
            not in {"supported", "inference", "disputed", "unknown"}
            or not isinstance(card.get("question"), str)
            or not card["question"].strip()
        ):
            errors.append(f"{identity}: invalid card kind/status/question")
        missing = card.get("gaps", [])
        if not isinstance(missing, list) or any(
            not isinstance(item, str) or not item.strip() for item in missing
        ):
            errors.append(f"{identity}: invalid gaps")
        else:
            gaps.extend(f"{identity}: {item}" for item in missing)
        if card.get("status") in {"disputed", "unknown"} and not missing:
            errors.append(f"{identity}: unresolved card requires gaps")
        if (
            not isinstance(fields, dict)
            or (not fields and card.get("status") in {"supported", "inference"})
            or fields.keys() - CARD_FIELDS
        ):
            errors.append(f"{identity}: invalid card fields")
            continue
        for name, field in fields.items():
            if (
                not isinstance(field, dict)
                or not isinstance(field.get("text"), str)
                or not field["text"].strip()
            ):
                errors.append(f"{identity}/{name}: text required")
                continue
            ids, refs = field.get("claim_ids"), field.get("evidence_refs")
            if (
                not isinstance(ids, list)
                or not ids
                or any(
                    not isinstance(cid, str) or cid not in allowed or cid not in claims
                    for cid in ids
                )
            ):
                errors.append(f"{identity}/{name}: chapter claim_ids required")
                continue
            approved = {ref for cid in ids for ref in claims[cid]["evidence_refs"]}
            if (
                not isinstance(refs, list)
                or not refs
                or any(not isinstance(ref, str) or ref not in approved for ref in refs)
            ):
                errors.append(f"{identity}/{name}: matching evidence_refs required")
    return errors, gaps


def record_sha256(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def source_proof(root: Path, source: dict, quote: str) -> str:
    relative = source.get("snapshot_path")
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("saved source snapshot required")
    path = (root / relative).resolve()
    if (
        Path(relative).is_absolute()
        or not path.is_relative_to(root.resolve())
        or not path.is_file()
    ):
        raise ValueError("source snapshot must be a file inside the bundle")
    payload = path.read_bytes().replace(b"\r\n", b"\n")
    digest = hashlib.sha256(payload).hexdigest()
    if source.get("content_sha256") != digest:
        raise ValueError("source snapshot hash mismatch")
    if not quote_in_text(payload.decode("utf-8"), quote):
        raise ValueError("verbatim quote not found in saved source")
    return digest


def semantic_reviews(root: Path) -> list[dict]:
    path = root / "semantic-audit.jsonl"
    if not path.is_file():
        return []
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("semantic audit must contain objects")
    return rows


def records(root: Path, name: str) -> dict[str, dict[str, Any]]:
    result = {}
    key = {
        "claims": "claim_id",
        "sources": "source_id",
        "evidence": "evidence_id",
        "contradictions": "contradiction_id",
    }[name]
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


def counterevidence_context(root, claim, evidence, sources, audits, ids=None):
    """Preserve objections as objections, including reviews still pending."""
    rows, errors = [], []
    ids = claim.get("challenging_evidence_ids", []) if ids is None else ids
    if not isinstance(ids, list) or any(not isinstance(eid, str) for eid in ids):
        return [], [f"{claim['claim_id']}: invalid challenging_evidence_ids"]
    for eid in dict.fromkeys(ids):
        item = evidence.get(eid, {})
        sid = item.get("source_id")
        source = sources.get(sid, {})
        quote = (
            item.get("exact_excerpt") or item.get("quote") or item.get("verbatim_quote")
        )
        parsed = urlsplit(source.get("url", ""))
        if (
            not isinstance(quote, str)
            or not quote.strip()
            or source.get("access_integrity")
            not in {"full_text", "full", "inspected", "transcript"}
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or claim["claim_id"] not in (item.get("claim_ids") or [])
        ):
            errors.append(
                f"{claim['claim_id']}/{eid}: inspected counterevidence and verbatim quote required"
            )
            continue
        try:
            digest = source_proof(root, source, quote)
        except (ValueError, OSError) as error:
            errors.append(f"{claim['claim_id']}/{eid}: {error}")
            continue
        rows.append(
            {
                "evidence_id": eid,
                "original_source_id": sid,
                "url": source["url"],
                "quote": quote,
                "locator": item.get("locator", ""),
                "content_sha256": digest,
                "evidence_sha256": record_sha256(item),
                "source_sha256": record_sha256(source),
                "source_context": context_fields(
                    source, {"source_id", "url", "content_sha256"}
                ),
                "evidence_context": context_fields(
                    item,
                    {
                        "evidence_id",
                        "source_id",
                        "quote",
                        "exact_excerpt",
                        "verbatim_quote",
                        "locator",
                    },
                ),
                "semantic_reviews": [
                    audit
                    for audit in audits
                    if audit.get("claim_id") == claim["claim_id"]
                    and audit.get("evidence_id") == eid
                    and audit.get("source_id") == sid
                    and audit.get("claim_sha256") == record_sha256(claim)
                    and audit.get("evidence_sha256") == record_sha256(item)
                    and audit.get("source_sha256") == record_sha256(source)
                ],
            }
        )
    return rows, errors


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
    audits = semantic_reviews(root)
    contradictions = (
        records(root, "contradictions")
        if (root / "contradictions.jsonl").is_file()
        else {}
    )
    contradiction_gaps = []
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
            quote = (
                item.get("exact_excerpt")
                or item.get("quote")
                or item.get("verbatim_quote")
            )
            parsed = urlsplit(source.get("url", ""))
            if (
                not isinstance(quote, str)
                or not quote.strip()
                or source.get("access_integrity")
                not in {"full_text", "full", "inspected", "transcript"}
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
            ):
                issues.append(
                    f"{cid}/{eid}: inspected source and verbatim quote required"
                )
                continue
            try:
                digest = source_proof(root, source, quote)
            except (ValueError, OSError) as error:
                issues.append(f"{cid}/{eid}: {error}")
                continue
            if item.get("relationship") != "supports" or cid not in (
                item.get("claim_ids") or []
            ):
                issues.append(
                    f"{cid}/{eid}: evidence must explicitly support this claim"
                )
                continue
            matching = [
                audit
                for audit in audits
                if audit.get("claim_id") == cid
                and audit.get("evidence_id") == eid
                and audit.get("source_id") == sid
            ]
            valid = [
                audit
                for audit in matching
                if audit.get("claim_sha256") == record_sha256(claim)
                and audit.get("evidence_sha256") == record_sha256(item)
                and audit.get("source_sha256") == record_sha256(source)
            ]
            if not valid or any(
                audit.get("semantic_support") != "exact"
                or audit.get("reviewer_status") != "pass"
                or not all(
                    audit.get(field) is True
                    for field in (
                        "scope_match",
                        "authority_match",
                        "freshness_match",
                        "evidence_type_match",
                    )
                )
                or not isinstance(audit.get("reviewer_basis"), str)
                or not audit["reviewer_basis"].strip()
                or not isinstance(audit.get("audited_at"), str)
                or not audit["audited_at"].strip()
                for audit in valid
            ):
                issues.append(
                    f"{cid}/{eid}: current exact passing semantic review required; narrow/review the claim"
                )
                continue
            # Evidence IDs retain distinct locators and quotes from the same source.
            refs.append(eid)
            previous_hashes = output_sources.get(eid, {}).get("claim_hashes", {})
            output_sources[eid] = {
                "source_id": eid,
                "original_source_id": sid,
                "url": source["url"],
                "quote": quote,
                "locator": item.get("locator", ""),
                "content_sha256": digest,
                "claim_sha256": record_sha256(claim),
                "evidence_sha256": record_sha256(item),
                "source_sha256": record_sha256(source),
                "claim_hashes": {**previous_hashes, cid: record_sha256(claim)},
                "source_context": context_fields(
                    source, {"source_id", "url", "content_sha256"}
                ),
                "evidence_context": context_fields(
                    item,
                    {
                        "evidence_id",
                        "source_id",
                        "quote",
                        "exact_excerpt",
                        "verbatim_quote",
                        "locator",
                    },
                ),
                "semantic_reviews": [
                    *output_sources.get(eid, {}).get("semantic_reviews", []),
                    *valid,
                ],
            }
        meaning = claim.get("meaning") or claim.get("claim")
        if not refs or not isinstance(meaning, str) or not meaning.strip():
            issues.append(f"{cid}: no supported meaning/evidence")
            continue
        context = context_fields(
            claim,
            {
                "claim_id",
                "claim",
                "meaning",
                "action",
                "condition",
                "exception",
                "confidence",
                "patch",
                "status",
                "supporting_evidence_ids",
                "counterevidence",
            },
        )
        related = [row for row in contradictions.values() if row.get("claim_id") == cid]
        ids = claim.get("challenging_evidence_ids", [])
        if not isinstance(ids, list) or any(not isinstance(eid, str) for eid in ids):
            issues.append(f"{cid}: invalid challenging_evidence_ids")
            ids = []
        if related:
            context["contradictions"] = [
                {**context_fields(row, set()), "record_sha256": record_sha256(row)}
                for row in related
            ]
            for row in related:
                counter_refs = row.get("counter_evidence_ids", [])
                if (
                    not isinstance(counter_refs, list)
                    or any(not isinstance(eid, str) for eid in counter_refs)
                    or not isinstance(row.get("outcome"), str)
                    or not row["outcome"].strip()
                ):
                    issues.append(f"{cid}: invalid contradiction context")
                    continue
                ids = [*ids, *counter_refs]
                if row["outcome"].lower() in {
                    "open",
                    "unresolved",
                    "disputed",
                    "unknown",
                }:
                    contradiction_gaps.append(
                        {
                            "claim_id": cid,
                            "question": f"Resolve {row['contradiction_id']}",
                            "reason": "unresolved_contradiction",
                            "search_rounds_remaining": 1,
                        }
                    )
        if "challenging_evidence_ids" in claim or ids:
            context["challenging_evidence_ids"] = list(dict.fromkeys(ids))
            context["counterevidence"], counter_errors = counterevidence_context(
                root, claim, evidence, sources, audits, ids=ids
            )
            issues.extend(counter_errors)
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
                "research_context": context,
            }
        )
    report = decision_coverage(plan, {claim["claim_id"] for claim in output_claims})
    report["gap_queue"].extend(contradiction_gaps)
    report["warnings"].extend(row["question"] for row in contradiction_gaps)
    by_id = {claim["claim_id"]: claim for claim in output_claims}
    for chapter in plan.get("chapters", []):
        card_errors, card_gaps = decision_cards(chapter, by_id)
        issues.extend(card_errors)
        report["warnings"].extend(card_gaps)
        report["gap_queue"].extend(
            {
                "chapter_id": chapter.get("chapter_id"),
                "question": gap,
                "reason": "decision_card_gap",
                "search_rounds_remaining": 1,
            }
            for gap in card_gaps
        )
        approved = {
            by_id[cid]["meaning"]
            for cid in chapter.get("required_claim_ids", [])
            if cid in by_id
        }
        for field in ("decision_examples", "counterexamples"):
            examples = chapter.get(field, [])
            if not isinstance(examples, list) or any(
                not isinstance(example, str) or example not in approved
                for example in examples
            ):
                issues.append(
                    f"{chapter.get('chapter_id')}: {field} must reuse a verified claim of this chapter"
                )
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
        "editorial_context": plan.get("editorial_context", {}),
    }
    return handoff, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--plan",
        type=Path,
        help="Editorial plan with reader questions and verified claim IDs",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--review-digests",
        action="store_true",
        help="Print record hashes for an independent reviewer; does not approve facts",
    )
    args = parser.parse_args()
    try:
        if args.review_digests:
            print(
                json.dumps(
                    {
                        name: {
                            key: record_sha256(value)
                            for key, value in records(args.directory, name).items()
                        }
                        for name in ("claims", "evidence", "sources")
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.plan is None or args.output is None or args.report is None:
            raise ValueError("--plan, --output and --report required for compilation")
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
