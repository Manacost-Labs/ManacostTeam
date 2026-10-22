"""Evidence-bound contextual review. No classifier, word bans or automatic pass."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

LOGIC = ("coherence", "causal_support", "scope_and_conditions", "reference_consistency", "information_gain")
PRESERVATION = ("facts_numbers", "conditions_exceptions_negation", "modality", "entities_roles",
                "author_voice", "quotations_markup", "strengths")


def catalog() -> dict:
    return json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def identifiers(text: str) -> dict:
    """Inventory only. ISBN checksum is not bibliographic or claim verification."""
    isbn = []
    for match in re.finditer(r"\bISBN(?:-1[03])?\s*:?\s*([\dXx][\dXx -]{8,25}[\dXx])", text):
        value = re.sub(r"[ -]", "", match[1]).upper()
        valid = False
        if len(value) == 10 and value[:9].isdigit() and (value[-1].isdigit() or value[-1] == "X"):
            valid = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(value)) % 11 == 0
        elif len(value) == 13 and value.isdigit():
            valid = value.startswith(("978", "979")) and sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(value)) % 10 == 0
        isbn.append({"value": value, "checksum_valid": valid})
    doi = list(dict.fromkeys(m.rstrip(".,;)") for m in re.findall(r"\b10\.\d{4,9}/[^\s<>\"]+", text)))
    return {"isbn": isbn, "doi": doi,
            "limitation": "Inventory requires catalog/resolver and metadata checks; DOI has no universal checksum. No network verification performed."}


def prepare(text: str, *, owner: str = "all", original: str | None = None, handoff: dict | None = None,
            snapshots: list | None = None) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("nonempty article required")
    if owner not in {"all", "fact_review", "literary_review"}:
        raise ValueError("invalid review owner")
    data = catalog()
    packet = {
        "contract_version": 3, "owner": owner, "article_sha256": _hash(text),
        "principles": data["principles"],
        "practices": [p for p in data["practices"] if owner == "all" or p["owner"] == owner],
        "logic_dimensions": list(LOGIC) if owner != "fact_review" else [],
        "preservation_dimensions": list(PRESERVATION) if owner != "fact_review" else [],
        "identifiers": identifiers(text),
        "review_schema": {
            "practice_checks": "One row per assigned id: {id,status:clear|not_applicable|issue|unverified,quote,reason}. clear/issue need an exact candidate quote. NA needs a concrete applicability reason, never a blanket exemption.",
            "logic_checks": "One row per logic dimension, same schema. Assess the entire article and inter-section contradictions. NA only for causal_support, with a reason.",
            "preservation_checks": "One row per preservation dimension, same schema. No NA; explain what was preserved, including absence of a feature. When original is supplied, original_quote must be exact and nonempty. For a new article use the brief and evidence; do not invent an original author voice.",
            "source_checks": "Factual owner: one row per handoff source {source_id,status:verified|unavailable|mismatch,evidence_quote,reason,identity_check,support_check,access:live|snapshot|archive}. evidence_quote must occur in approved source quote. Verify title/author/date/edition/DOI/ISBN and actual support, not just URL existence. Explain missing metadata; never invent it. Use saved source contents or retrieve the source; say which.",
            "issues": "issue requires reader_problem, benefit, meaning_risk, suggestion. An optional stylistic alternative is clear with explanation, not an issue. Unresolved issue/unverified cannot pass.",
            "hashes": "article_sha256 required; original_sha256 required if original supplied. Existing publication handoff_sha256 and independent review fields remain mandatory.",
        },
        "limitation": "This packet is a review assignment, not a verdict. Schema validation cannot establish semantic truth.",
    }
    if original is not None:
        packet["original_sha256"] = _hash(original)
    if handoff is not None:
        from .publication_review import handoff_hash, validate_handoff

        errors = validate_handoff(handoff, handoff.get("patch", "") if isinstance(handoff, dict) else "")
        if errors:
            raise ValueError("; ".join(errors))
        packet["handoff_sha256"] = handoff_hash(handoff)
        packet["sources"] = handoff.get("sources", [])
    if snapshots is not None:
        from .publication_review import handoff_hash

        packet["sources_sha256"] = handoff_hash(snapshots)
        packet["review_schema"]["hashes"] += " sources_sha256 required for supplied snapshots."
    return packet


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _checks(text: str, rows, expected: set[str], field: str, *, na: set[str], original: str | None = None) -> list[str]:
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
        if not isinstance(quote, str) or (quote and quote not in text) or (status in {"clear", "issue"} and not _nonempty(quote)):
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
    errors.extend(f"{field}: missing {key}" for key in sorted(expected - seen))
    return errors


def _sources(handoff, rows) -> list[str]:
    if not isinstance(handoff, dict) or not isinstance(handoff.get("sources"), list) or not handoff["sources"]:
        return ["source_checks: approved handoff sources required; preservation is not source verification"]
    sources = {s["source_id"]: s for s in handoff["sources"] if isinstance(s, dict) and isinstance(s.get("source_id"), str)}
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
        if not _nonempty(quote) or not isinstance(sources[key].get("quote"), str) or quote not in sources[key]["quote"]:
            errors.append(f"source_checks/{key}: exact approved evidence_quote required")
        for field in ("reason", "identity_check", "support_check"):
            if not _nonempty(row.get(field)):
                errors.append(f"source_checks/{key}: {field} required")
        if not isinstance(row.get("access"), str) or row["access"] not in {"live", "snapshot", "archive"}:
            errors.append(f"source_checks/{key}: actual access method required")
    errors.extend(f"source_checks: missing {key}" for key in sorted(sources.keys() - seen))
    return errors


def validate(text: str, report, *, owner: str = "all", handoff: dict | None = None, original: str | None = None,
             snapshots: list | None = None, require_snapshots: bool = False) -> list[str]:
    try:
        packet = prepare(text, owner=owner, original=original, handoff=handoff, snapshots=snapshots)
    except (ValueError, TypeError, UnicodeError) as error:
        return [f"editorial: invalid input: {error}"]
    if not isinstance(report, dict):
        return ["editorial review must be an object"]
    errors = []
    if "status" in report and report["status"] != "pass":
        errors.append("editorial: reviewer did not pass the article")
    for field in ("article_sha256", "original_sha256", "handoff_sha256", "sources_sha256"):
        if field in packet and report.get(field) != packet[field]:
            errors.append(f"editorial: {field} mismatch")
    ids = {p["id"] for p in packet["practices"]}
    errors += _checks(text, report.get("practice_checks"), ids, "practice_checks", na=ids)
    if owner != "fact_review":
        errors += _checks(text, report.get("logic_checks"), set(LOGIC), "logic_checks", na={"causal_support"})
        errors += _checks(text, report.get("preservation_checks"), set(PRESERVATION), "preservation_checks", na=set(), original=original)
    if owner != "literary_review":
        errors += _sources(handoff, report.get("source_checks"))
        if require_snapshots and snapshots is None:
            errors.append("source_checks: collected full snapshots required (--sources)")
        if snapshots is not None and isinstance(handoff, dict):
            from .publication_run import _ground_sources
            from .publication_run import _sources as validate_snapshots

            try:
                validate_snapshots(snapshots)
                errors += _ground_sources(handoff, snapshots)
            except (KeyError, TypeError, ValueError) as error:
                errors.append(f"source_checks: invalid snapshots: {error}")
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "validate"))
    parser.add_argument("--text", type=Path, required=True)
    parser.add_argument("--original", type=Path)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--sources", type=Path, help="collected full snapshots with provenance and SHA256")
    parser.add_argument("--review", type=Path)
    parser.add_argument("--owner", choices=("all", "fact_review", "literary_review"), default="all")
    args = parser.parse_args(argv)
    if args.action == "validate" and not args.review:
        parser.error("validate requires --review")
    try:
        text = args.text.read_text(encoding="utf-8-sig")
        original = args.original.read_text(encoding="utf-8-sig") if args.original else None
        handoff = json.loads(args.handoff.read_text(encoding="utf-8-sig")) if args.handoff else None
        snapshots = json.loads(args.sources.read_text(encoding="utf-8-sig")) if args.sources else None
        if args.action == "prepare":
            result = prepare(text, owner=args.owner, original=original, handoff=handoff, snapshots=snapshots)
        else:
            report = json.loads(args.review.read_text(encoding="utf-8-sig"))
            errors = validate(text, report, owner=args.owner, original=original, handoff=handoff,
                              snapshots=snapshots, require_snapshots=True)
            if args.owner != "literary_review" and not errors:
                from .publication_review import validate_factual

                errors += validate_factual(handoff, text, report)
            result = {"status": "blocked" if errors else "pass", "errors": errors,
                      "limitation": "Contract validation; semantic judgment remains the reviewer's responsibility."}
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        result = {"status": "blocked", "errors": [str(error)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result.get("status") == "blocked")


if __name__ == "__main__":
    raise SystemExit(main())
