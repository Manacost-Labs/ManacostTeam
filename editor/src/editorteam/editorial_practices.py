"""Evidence-bound contextual review. No classifier, word bans or automatic pass."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from .integrity import arithmetic_issues

LOGIC = (
    "coherence",
    "causal_support",
    "scope_and_conditions",
    "reference_consistency",
    "information_gain",
)
PRESERVATION = (
    "facts_numbers",
    "conditions_exceptions_negation",
    "modality",
    "entities_roles",
    "author_voice",
    "quotations_markup",
    "strengths",
)


def catalog() -> dict:
    data = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    _validate_research(data)
    return data


def _validate_research(data: dict) -> None:
    """Only read sources can support contextual guidance, never authorship claims."""
    sources = data.get("research_sources", [])
    if not isinstance(sources, list):
        raise ValueError("research_sources must be a list")
    by_id = {}
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("research source must be an object")
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id.strip() or source_id in by_id:
            raise ValueError("research source id must be nonempty and unique")
        for key in ("url", "access_url"):
            if key == "access_url" and source.get(key, "") == "":
                continue
            url = source.get(key)
            try:
                parsed = urlsplit(url) if isinstance(url, str) else None
                valid = (
                    parsed is not None
                    and parsed.scheme in ("http", "https")
                    and parsed.hostname
                    and not any(c.isspace() for c in url)
                )
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(
                    f"research source {source_id}: HTTP(S) URL with hostname required for {key}"
                )
        if source.get("status") not in ("read", "partial", "unavailable"):
            raise ValueError(f"research source {source_id}: invalid access status")
        if any(
            not isinstance(source.get(key), str) or not source[key].strip()
            for key in ("title", "scope", "review_coverage")
        ):
            raise ValueError(
                f"research source {source_id}: title, scope and review_coverage required"
            )
        coverage = source["review_coverage"]
        if coverage not in ("article", "selected_sections", "indexed_units", "unavailable") or (
            (source["status"] == "unavailable") != (coverage == "unavailable")
        ):
            raise ValueError(f"research source {source_id}: inconsistent review coverage")
        by_id[source_id] = source
    seen = set()
    for practice in data["practices"]:
        checks = practice.get("research_checks", [])
        if not isinstance(checks, list):
            raise ValueError("research_checks must be a list")
        for check in checks:
            if not isinstance(check, dict) or any(
                not isinstance(check.get(key), str) or not check[key].strip()
                for key in ("id", "question", "acceptable", "action", "scope")
            ):
                raise ValueError(
                    "research check requires id, question, acceptable, action and scope"
                )
            if check["id"] in seen:
                raise ValueError(f"duplicate research check {check['id']}")
            seen.add(check["id"])
            refs = check.get("source_ids")
            if (
                not isinstance(refs, list)
                or not refs
                or any(
                    not isinstance(ref, str) or ref not in by_id or by_id[ref]["status"] != "read"
                    for ref in refs
                )
                or len(set(refs)) != len(refs)
            ):
                raise ValueError(
                    f"research check {check['id']}: unique read source references required"
                )


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def identifiers(text: str) -> dict:
    """Inventory only. ISBN checksum is not bibliographic or claim verification."""
    isbn = []
    for match in re.finditer(r"\bISBN(?:-1[03])?\s*:?\s*([\dXx][\dXx -]{8,25}[\dXx])", text):
        value = re.sub(r"[ -]", "", match[1]).upper()
        valid = False
        if len(value) == 10 and value[:9].isdigit() and (value[-1].isdigit() or value[-1] == "X"):
            valid = (
                sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(value)) % 11 == 0
            )
        elif len(value) == 13 and value.isdigit():
            valid = (
                value.startswith(("978", "979"))
                and sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(value)) % 10 == 0
            )
        isbn.append({"value": value, "checksum_valid": valid})
    doi = list(
        dict.fromkeys(m.rstrip(".,;)") for m in re.findall(r"\b10\.\d{4,9}/[^\s<>\"]+", text))
    )
    return {
        "isbn": isbn,
        "doi": doi,
        "limitation": "Inventory requires catalog/resolver and metadata checks; DOI has no universal checksum. No network verification performed.",
    }


def prepare(
    text: str,
    *,
    owner: str = "all",
    original: str | None = None,
    handoff: dict | None = None,
    snapshots: list | None = None,
) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("nonempty article required")
    if original is not None and (not isinstance(original, str) or not original.strip()):
        raise ValueError("nonempty original text required when supplied")
    if owner not in {"all", "fact_review", "literary_review"}:
        raise ValueError("invalid review owner")
    data = catalog()
    packet = {
        "contract_version": 3,
        "owner": owner,
        "article_sha256": _hash(text),
        "principles": data["principles"],
        "research_sources": data.get("research_sources", []),
        "practices": [p for p in data["practices"] if owner == "all" or p["owner"] == owner],
        "logic_dimensions": list(LOGIC) if owner != "fact_review" else [],
        "preservation_dimensions": list(PRESERVATION) if owner != "fact_review" else [],
        "identifiers": identifiers(text),
        "original_integrity_hints": arithmetic_issues(original if original is not None else text),
        "review_scope": "supplied_sources" if handoff is not None else "source_and_candidate",
        "source_verification": "required" if handoff is not None else "not_performed",
        "review_schema": {
            "practice_checks": "One row per assigned id: {id,status:clear|not_applicable|issue|unverified,quote,reason}. clear/issue need an exact candidate quote. NA needs a concrete applicability reason, never a blanket exemption.",
            "logic_checks": "One row per logic dimension, same schema. Assess the entire article and inter-section contradictions. NA only for causal_support, with a reason.",
            "preservation_checks": "One row per preservation dimension, same schema. No NA; explain what was preserved, including absence of a feature. When original is supplied, original_quote must be exact and nonempty. Compare unique detail, evidence basis, threshold direction, comparison scope, causality and uncertainty, not only numbers. If versions differ, author_voice and strengths require change_evidence (1..16 changed spans): {original_quote,quote,disposition:preserved|justified|issue,reason,benefit,meaning_risk}. Quotes must be exact; candidate quote may be empty for a deletion. At least one pair must differ. Explain whether specificity, attribution, author vocabulary and useful qualifications survived; brevity alone is not a benefit. For a new article use the brief and evidence; do not invent an original author voice.",
            "source_checks": "Factual owner: one row per handoff source {source_id,status:verified|unavailable|mismatch,evidence_quote,reason,identity_check,support_check,access:snapshot}. evidence_quote must occur in approved source quote. Verify title/author/date/edition/DOI/ISBN and actual support, not just URL existence. Explain missing metadata; never invent it. Read the supplied full snapshots. Their retrieval provenance does not prove a live or archive retrieval by the reviewer; describe the actual review access as snapshot.",
            "issues": "issue requires reader_problem, benefit, meaning_risk, suggestion. An optional stylistic alternative is clear with explanation, not an issue. Unresolved issue/unverified cannot pass.",
            "hashes": "article_sha256 required; original_sha256 required if original supplied. Existing publication handoff_sha256 and independent review fields remain mandatory.",
        },
        "limitation": "This packet is a review assignment, not a verdict. Schema validation cannot establish semantic truth.",
    }
    if original is not None:
        packet["original_sha256"] = _hash(original)
        packet["review_schema"]["original_factual_checks"] = (
            "Required even when unchanged: {whole_text_checked:true,internal_consistency:clear|issue,"
            "source_agreement:not_performed|supplied_sources_checked|issue,issues:[{quote,reason,"
            "resolution:unresolved|corrected,correction_quote,source_id,evidence_quote}]}. "
            "Inspect original arithmetic, threshold direction, causality, comparison scope and confidence separately "
            "from preservation. quote must be exact original text. No sources means not_performed, not verified. "
            "Unresolved issues block acceptance; corrected requires an exact candidate correction and matching full "
            "source evidence. Do not silently decide which inconsistent number is true. Source agreement covers "
            "only supplied sources; unsupported factual scope stays explicit."
        )
    if handoff is not None:
        from .publication_review import handoff_hash, validate_handoff

        errors = validate_handoff(
            handoff, handoff.get("patch", "") if isinstance(handoff, dict) else ""
        )
        if errors:
            raise ValueError("; ".join(errors))
        packet["handoff_sha256"] = handoff_hash(handoff)
        packet["sources"] = handoff.get("sources", [])
    if snapshots is not None:
        from .publication_review import handoff_hash
        from .publication_run import _ground_sources
        from .publication_run import _sources as validate_snapshots

        validate_snapshots(snapshots)
        if handoff is not None:
            errors = _ground_sources(handoff, snapshots)
            if errors:
                raise ValueError("; ".join(errors))
        packet["sources_sha256"] = handoff_hash(snapshots)
        packet["review_schema"]["hashes"] += " sources_sha256 required for supplied snapshots."
    return packet


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _change_evidence(original: str, text: str, row: dict, field: str) -> list[str]:
    if row.get("id") not in {"author_voice", "strengths"}:
        return []
    entries = row.get("change_evidence")
    if original == text and entries is None:
        return []
    if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
        return [
            f"{field}/{row['id']}: change_evidence requires 1..16 contextual changed-span assessments"
        ]
    errors, changed = [], False
    for item in entries:
        if not isinstance(item, dict):
            errors.append(f"{field}: malformed change_evidence")
            continue
        before, after = item.get("original_quote"), item.get("quote")
        if not _nonempty(before) or before not in original:
            errors.append(f"{field}: change_evidence exact original_quote required")
        if not isinstance(after, str) or (after and after not in text):
            errors.append(
                f"{field}: change_evidence exact candidate quote required (empty for deletion)"
            )
        changed |= isinstance(before, str) and isinstance(after, str) and before != after
        if not isinstance(item.get("disposition"), str) or item["disposition"] not in {
            "preserved",
            "justified",
        }:
            errors.append(f"{field}: change_evidence unresolved or invalid disposition")
        for key in ("reason", "benefit", "meaning_risk"):
            if not _nonempty(item.get(key)):
                errors.append(f"{field}: change_evidence requires {key}")
    if original != text and not changed:
        errors.append(f"{field}: change_evidence must assess an actual changed pair")
    return errors


def _checks(
    text: str, rows, expected: set[str], field: str, *, na: set[str], original: str | None = None
) -> list[str]:
    errors, seen = [], set()
    if not isinstance(rows, list) or len(rows) > 256:
        return [f"{field}: expected bounded list"]
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            errors.append(f"{field}: malformed row")
            continue
        key = row["id"]
        if key not in expected or key in seen:
            errors.append(f"{field}: unknown or duplicate id {key}")
        seen.add(key)
        status, quote = row.get("status"), row.get("quote", "")
        if not isinstance(status, str):
            errors.append(f"{field}/{key}: invalid status type")
            continue
        if status not in {"clear", "not_applicable", "issue", "unverified"}:
            errors.append(f"{field}/{key}: invalid status")
        if not _nonempty(row.get("reason")):
            errors.append(f"{field}/{key}: concrete reason required")
        if (
            not isinstance(quote, str)
            or (quote and quote not in text)
            or (status in {"clear", "issue"} and not _nonempty(quote))
        ):
            errors.append(f"{field}/{key}: exact candidate quote required")
        if status == "not_applicable" and key not in na:
            errors.append(f"{field}/{key}: core check cannot be skipped")
        if status == "issue":
            for name in ("reader_problem", "benefit", "meaning_risk", "suggestion"):
                if not _nonempty(row.get(name)):
                    errors.append(f"{field}/{key}: issue requires {name}")
        if status in {"issue", "unverified"}:
            errors.append(f"{field}/{key}: unresolved {status}: {row.get('reason', '')}")
        if original is not None:
            before = row.get("original_quote")
            if not _nonempty(before) or before not in original:
                errors.append(f"{field}/{key}: exact original_quote required")
            errors += _change_evidence(original, text, row, field)
    errors.extend(f"{field}: missing {key}" for key in sorted(expected - seen))
    return errors


def _corrected_original(original: str, report: dict) -> str:
    """Apply an already validated correction ledger to a private diagnostic copy.

    This helper does not authorize corrections. Call it only after full review
    and source validation; the public review stays bound to the real original.
    Offsets are resolved once in the original so replacements cannot cascade.
    """
    spans = []
    for issue in report["original_factual_checks"]["issues"]:
        if not isinstance(issue, dict) or issue.get("resolution") != "corrected":
            continue
        quote, correction = issue.get("quote"), issue.get("correction_quote")
        if not _nonempty(quote) or not _nonempty(correction):
            raise ValueError("corrected original issue requires nonempty exact quotes")
        start = original.find(quote)
        if start < 0 or original.find(quote, start + 1) >= 0:
            raise ValueError("corrected original quote must identify one unique original span")
        spans.append((start, start + len(quote), correction))
    spans.sort()
    for previous, current in zip(spans, spans[1:]):
        if current[0] < previous[1]:
            raise ValueError("corrected original spans must not overlap or repeat")
    baseline = original
    for start, end, correction in reversed(spans):
        baseline = baseline[:start] + correction + baseline[end:]
    return baseline


def _original_facts(original: str, text: str, report: dict, handoff, snapshots) -> list[str]:
    row = report.get("original_factual_checks")
    if not isinstance(row, dict) or row.get("whole_text_checked") is not True:
        return [
            "original_factual_checks: whole original must be checked separately from preservation"
        ]
    errors = []
    if not isinstance(row.get("internal_consistency"), str) or row["internal_consistency"] not in {
        "clear",
        "issue",
    }:
        errors.append("original_factual_checks: internal_consistency required")
    agreement = row.get("source_agreement")
    expected = "supplied_sources_checked" if snapshots else "not_performed"
    if not isinstance(agreement, str) or agreement not in {expected, "issue"}:
        errors.append(f"original_factual_checks: source_agreement must be {expected} or issue")
    issues = row.get("issues")
    if not isinstance(issues, list) or len(issues) > 256:
        return errors + ["original_factual_checks: bounded issues list required"]
    if issues and row.get("internal_consistency") == "clear" and agreement != "issue":
        errors.append("original_factual_checks: clear checks contradict reported original issues")
    if not issues and (row.get("internal_consistency") == "issue" or agreement == "issue"):
        errors.append("original_factual_checks: issue status requires quoted findings")
    sources = {item.get("source_id"): item for item in (handoff or {}).get("sources", [])}
    source_texts = {item.get("id"): item.get("text", "") for item in snapshots or []}
    by_url = {item.get("url"): item.get("text", "") for item in snapshots or []}
    for source_id, source in sources.items():
        if source.get("url") in by_url:
            source_texts[source_id] = by_url[source["url"]]
    for issue in issues:
        if not isinstance(issue, dict):
            errors.append("original_factual_checks: malformed issue")
            continue
        quote = issue.get("quote")
        if not _nonempty(quote) or quote not in original or not _nonempty(issue.get("reason")):
            errors.append("original_factual_checks: exact original quote and reason required")
        if issue.get("resolution") != "corrected":
            errors.append("original_factual_checks: unresolved original issue")
            continue
        correction, evidence = issue.get("correction_quote"), issue.get("evidence_quote")
        if (
            not _nonempty(correction)
            or correction not in text
            or (_nonempty(quote) and quote in text)
        ):
            errors.append(
                "original_factual_checks: corrected issue requires changed candidate evidence"
            )
        source_id = issue.get("source_id")
        if (
            not isinstance(source_id, str)
            or not _nonempty(evidence)
            or evidence not in source_texts.get(source_id, "")
        ):
            errors.append(
                "original_factual_checks: correction requires verified full source evidence"
            )
    for hint in arithmetic_issues(original):
        if not any(
            isinstance(item, dict)
            and isinstance(item.get("quote"), str)
            and (hint["evidence"] in item["quote"] or item["quote"] in hint["evidence"])
            and item["quote"].strip()
            for item in issues
        ):
            errors.append(
                "original_factual_checks: original arithmetic inconsistency must be assessed explicitly"
            )
    try:
        _corrected_original(original, report)
    except ValueError as error:
        errors.append(f"original_factual_checks: {error}")
    return errors


def _sources(handoff, rows) -> list[str]:
    if (
        not isinstance(handoff, dict)
        or not isinstance(handoff.get("sources"), list)
        or not handoff["sources"]
    ):
        return [
            "source_checks: approved handoff sources required; preservation is not source verification"
        ]
    sources = {
        s["source_id"]: s
        for s in handoff["sources"]
        if isinstance(s, dict) and isinstance(s.get("source_id"), str)
    }
    if len(sources) != len(handoff["sources"]):
        return ["source_checks: malformed or duplicate handoff sources"]
    if not isinstance(rows, list) or len(rows) > 128:
        return ["source_checks: expected bounded list"]
    errors, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("source_id"), str):
            errors.append("source_checks: malformed row")
            continue
        key = row["source_id"]
        if key not in sources or key in seen:
            errors.append("source_checks: unknown or duplicate source")
            continue
        seen.add(key)
        if row.get("status") != "verified":
            errors.append(f"source_checks/{key}: unresolved source verification")
        quote = row.get("evidence_quote")
        if (
            not _nonempty(quote)
            or not isinstance(sources[key].get("quote"), str)
            or quote not in sources[key]["quote"]
        ):
            errors.append(f"source_checks/{key}: exact approved evidence_quote required")
        for field in ("reason", "identity_check", "support_check"):
            if not _nonempty(row.get(field)):
                errors.append(f"source_checks/{key}: {field} required")
        if not isinstance(row.get("access"), str) or row["access"] not in {
            "live",
            "snapshot",
            "archive",
        }:
            errors.append(f"source_checks/{key}: actual access method required")
    errors.extend(f"source_checks: missing {key}" for key in sorted(sources.keys() - seen))
    return errors


def validate(
    text: str,
    report,
    *,
    owner: str = "all",
    handoff: dict | None = None,
    original: str | None = None,
    snapshots: list | None = None,
    require_snapshots: bool = False,
) -> list[str]:
    try:
        packet = prepare(text, owner=owner, original=original, handoff=handoff, snapshots=snapshots)
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        return [f"editorial: invalid input: {error}"]
    if not isinstance(report, dict):
        return ["editorial review must be an object"]
    errors = []
    errors.extend(
        f"integrity: {issue['message']} {issue['suggestion']}" for issue in arithmetic_issues(text)
    )
    if report.get("status") != "pass":
        errors.append("editorial: reviewer did not pass the article")
    for field in ("article_sha256", "original_sha256", "handoff_sha256", "sources_sha256"):
        if field in packet and report.get(field) != packet[field]:
            errors.append(f"editorial: {field} mismatch")
    ids = {p["id"] for p in packet["practices"]}
    errors += _checks(text, report.get("practice_checks"), ids, "practice_checks", na=ids)
    if owner != "fact_review":
        errors += _checks(
            text, report.get("logic_checks"), set(LOGIC), "logic_checks", na={"causal_support"}
        )
        errors += _checks(
            text,
            report.get("preservation_checks"),
            set(PRESERVATION),
            "preservation_checks",
            na=set(),
            original=original,
        )
    if original is not None:
        errors += _original_facts(original, text, report, handoff, snapshots)
    preservation_only = (
        owner == "all" and handoff is None and snapshots is None and original is not None
    )
    if preservation_only:
        if (
            report.get("source_verification") != "not_performed"
            or report.get("source_checks") != []
        ):
            errors.append(
                "source_checks: preservation-only review must declare not_performed and an empty source_checks list"
            )
    elif owner != "literary_review":
        errors += _sources(handoff, report.get("source_checks"))
        if require_snapshots and snapshots is None:
            errors.append("source_checks: collected full snapshots required (--sources)")
    if snapshots is not None:
        from .publication_run import _ground_sources
        from .publication_run import _sources as validate_snapshots

        try:
            validate_snapshots(snapshots)
            if isinstance(handoff, dict):
                errors += _ground_sources(handoff, snapshots)
            for row in (
                report.get("source_checks", [])
                if isinstance(report.get("source_checks"), list)
                else []
            ):
                if isinstance(row, dict) and row.get("access") != "snapshot":
                    errors.append(
                        "source_checks: supplied snapshots do not prove a live or archive retrieval by the reviewer"
                    )
        except (KeyError, TypeError, ValueError) as error:
            errors.append(f"source_checks: invalid snapshots: {error}")
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "validate"))
    parser.add_argument("--text", type=Path, required=True)
    parser.add_argument("--original", type=Path)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument(
        "--sources", type=Path, help="collected full snapshots with provenance and SHA256"
    )
    parser.add_argument("--review", type=Path)
    parser.add_argument("--owner", choices=("all", "fact_review", "literary_review"), default="all")
    args = parser.parse_args(argv)
    if args.action == "validate" and not args.review:
        parser.error("validate requires --review")
    try:
        text = args.text.read_text(encoding="utf-8-sig")
        original = args.original.read_text(encoding="utf-8-sig") if args.original else None
        handoff = json.loads(args.handoff.read_text(encoding="utf-8-sig")) if args.handoff else None
        snapshots = (
            json.loads(args.sources.read_text(encoding="utf-8-sig")) if args.sources else None
        )
        if args.action == "prepare":
            result = prepare(
                text, owner=args.owner, original=original, handoff=handoff, snapshots=snapshots
            )
        else:
            report = json.loads(args.review.read_text(encoding="utf-8-sig"))
            errors = validate(
                text,
                report,
                owner=args.owner,
                original=original,
                handoff=handoff,
                snapshots=snapshots,
                require_snapshots=True,
            )
            if args.owner != "literary_review" and handoff is not None and not errors:
                from .publication_review import validate_factual

                errors += validate_factual(handoff, text, report)
            result = {
                "status": "blocked" if errors else "pass",
                "errors": errors,
                "review_scope": "supplied_sources"
                if handoff is not None
                else "source_and_candidate",
                "source_verification": "supplied_sources_checked"
                if handoff is not None and not errors
                else "not_performed",
                "limitation": "Contract validation; semantic judgment remains the reviewer's responsibility.",
            }
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        result = {"status": "blocked", "errors": [str(error)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result.get("status") == "blocked")


if __name__ == "__main__":
    raise SystemExit(main())
