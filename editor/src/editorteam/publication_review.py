"""Deterministic gates for independent native Codex publication reviews.

Literal quotes bind a model's semantic assessment to candidate text; they do not
prove its truth. Sources must already have passed the research evidence checks.
This module makes no network/model calls and never approves human gold data.
"""

from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit


def article_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def handoff_hash(handoff: dict) -> str:
    encoded = json.dumps(
        handoff, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strings(value: object, *, nonempty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (bool(value) or not nonempty)
        and all(_text(item) for item in value)
        and len(set(value)) == len(value)
    )


def _url(value: object) -> bool:
    if not _text(value) or any(char.isspace() or ord(char) < 32 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and "\\" not in value
        )
    except ValueError:
        return False


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


def _decision_cards(chapter: dict, claims: dict, ready: bool) -> list[str]:
    errors, seen = [], set()
    cards = chapter.get("decision_cards", [])
    if not isinstance(cards, list) or len(cards) > 32:
        return ["handoff: invalid decision_cards"]
    for card in cards:
        if not isinstance(card, dict):
            errors.append("handoff: invalid decision card")
            continue
        identity, fields = card.get("card_id"), card.get("fields")
        if not _text(identity) or identity in seen:
            errors.append("handoff: invalid or duplicate card_id")
            continue
        seen.add(identity)
        if (
            card.get("kind") not in {"observed", "derived", "illustrative"}
            or card.get("status") not in {"supported", "inference", "disputed", "unknown"}
            or not _text(card.get("question"))
        ):
            errors.append(f"handoff: {identity} invalid card kind/status/question")
        gaps = card.get("gaps", [])
        if (
            not _strings(gaps)
            or (gaps and ready)
            or (card.get("status") in {"disputed", "unknown"} and not gaps)
        ):
            errors.append(f"handoff: {identity} unresolved/invalid card gaps")
        if (
            not isinstance(fields, dict)
            or (not fields and card.get("status") in {"supported", "inference"})
            or fields.keys() - CARD_FIELDS
        ):
            errors.append(f"handoff: {identity} invalid card fields")
            continue
        for name, field in fields.items():
            if not isinstance(field, dict) or not _text(field.get("text")):
                errors.append(f"handoff: {identity}/{name} text required")
                continue
            ids, refs = field.get("claim_ids"), field.get("evidence_refs")
            if not _strings(ids, nonempty=True) or any(
                cid not in chapter["required_claim_ids"] or cid not in claims for cid in ids
            ):
                errors.append(f"handoff: {identity}/{name} invalid claim_ids")
                continue
            approved = {
                ref
                for cid in ids
                for ref in claims[cid].get("evidence_refs", [])
                if isinstance(ref, str)
            }
            if not _strings(refs, nonempty=True) or any(ref not in approved for ref in refs):
                errors.append(f"handoff: {identity}/{name} invalid evidence_refs")
    return errors


def _research_context(claim: dict) -> list[str]:
    context = claim.get("research_context", {})
    if not isinstance(context, dict):
        return ["handoff: research_context must be an object"]
    rows = context.get("counterevidence", [])
    if not isinstance(rows, list) or len(rows) > 128:
        return ["handoff: invalid counterevidence"]
    errors, seen = [], set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or not _text(row.get("evidence_id"))
            or row["evidence_id"] in seen
            or not _text(row.get("original_source_id"))
            or not _url(row.get("url"))
            or not _text(row.get("quote"))
        ):
            errors.append("handoff: invalid counterevidence record")
            continue
        seen.add(row["evidence_id"])
        if not isinstance(row.get("content_sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", row["content_sha256"]
        ):
            errors.append("handoff: counterevidence source hash required")
    refs = context.get("challenging_evidence_ids", [])
    if not _strings(refs) or set(refs) != seen:
        errors.append("handoff: counterevidence does not match challenging_evidence_ids")
    return errors


def validate_handoff(handoff: dict, current_patch: str) -> list[str]:
    """Check the Go v1 handoff shape and required reader decision coverage."""
    errors = []
    if not isinstance(handoff, dict):
        return ["handoff: expected an object"]
    try:
        handoff_hash(handoff)
    except (TypeError, ValueError, UnicodeError):
        return ["handoff: expected finite UTF-8 JSON data"]
    if type(handoff.get("schema_version")) is not int or handoff["schema_version"] != 1:
        errors.append("handoff: schema_version must be 1")
    for field in ("brief", "patch", "style_profile"):
        if not _text(handoff.get(field)):
            errors.append(f"handoff: missing {field}")
    if "editorial_context" in handoff and not isinstance(handoff["editorial_context"], dict):
        errors.append("handoff: editorial_context must be an object")
    if not _text(current_patch) or handoff.get("patch") != current_patch:
        errors.append("handoff: current patch mismatch")
    if handoff.get("status") not in ("research_ready", "research_ready_with_gaps"):
        errors.append("handoff: research is not ready")
    for field, limit in (("sources", 128), ("claims", 128), ("chapters", 20), ("decisions", 128)):
        items = handoff.get(field)
        if (
            not isinstance(items, list)
            or not 1 <= len(items) <= limit
            or not all(isinstance(item, dict) for item in items)
        ):
            errors.append(f"handoff: invalid {field}")
    if errors:
        return errors
    sources, claims, chapters, questions = {}, {}, {}, set()
    for source in handoff["sources"]:
        sid = source.get("source_id")
        if (
            not _text(sid)
            or sid in sources
            or not _url(source.get("url"))
            or not _text(source.get("quote"))
        ):
            errors.append("handoff: invalid or duplicate source")
            continue
        sources[sid] = source
        for key in ("source_context", "evidence_context", "claim_hashes"):
            if key in source and not isinstance(source[key], dict):
                errors.append(f"handoff: {key} must be an object")
        if "semantic_reviews" in source and (
            not isinstance(source["semantic_reviews"], list)
            or not all(isinstance(row, dict) for row in source["semantic_reviews"])
        ):
            errors.append("handoff: semantic_reviews must be an array of objects")
    for claim in handoff["claims"]:
        cid = claim.get("claim_id")
        if not _text(cid) or cid in claims:
            errors.append("handoff: invalid or duplicate claim ID")
            continue
        claims[cid] = claim
        errors.extend(_research_context(claim))
        if not _text(claim.get("meaning")) or claim.get("patch") != current_patch:
            errors.append(f"handoff: {cid} missing meaning or wrong patch")
        if claim.get("status") not in ("supported", "supported_with_conditions"):
            errors.append(f"handoff: {cid} is unsupported")
        if claim.get("confidence") not in ("high", "medium", "low"):
            errors.append(f"handoff: {cid} invalid confidence")
        for field in ("action", "condition", "exception"):
            if field in claim and not isinstance(claim[field], str):
                errors.append(f"handoff: {cid} invalid {field}")
        if claim.get("status") == "supported_with_conditions" and not _text(claim.get("condition")):
            errors.append(f"handoff: {cid} missing condition")
        refs = claim.get("evidence_refs")
        if not _strings(refs, nonempty=True) or any(ref not in sources for ref in refs):
            errors.append(f"handoff: {cid} invalid evidence_refs")
    for chapter in handoff["chapters"]:
        chid, required = chapter.get("chapter_id"), chapter.get("required_claim_ids")
        if (
            not _text(chid)
            or chid in chapters
            or not _text(chapter.get("title"))
            or not _strings(required, nonempty=True)
        ):
            errors.append("handoff: invalid or duplicate chapter")
            continue
        chapters[chid] = set(required)
        if any(cid not in claims for cid in required):
            errors.append(f"handoff: {chid} unknown required claim")
        for field in ("decision_examples", "counterexamples", "unresolved_questions"):
            if field in chapter and not _strings(chapter[field]):
                errors.append(f"handoff: {chid} invalid {field}")
        approved_examples = {
            claims[cid].get("meaning")
            for cid in required
            if cid in claims and _text(claims[cid].get("meaning"))
        }
        for field in ("decision_examples", "counterexamples"):
            if _strings(chapter.get(field, [])) and any(
                example not in approved_examples for example in chapter.get(field, [])
            ):
                errors.append(f"handoff: {chid} unverified {field}")
        if chapter.get("unresolved_questions") and handoff["status"] == "research_ready":
            errors.append(f"handoff: {chid} unresolved questions")
        errors.extend(_decision_cards(chapter, claims, handoff["status"] == "research_ready"))
    covered = set()
    for question in handoff["decisions"]:
        qid, chid = question.get("question_id"), question.get("chapter_id")
        if (
            not _text(qid)
            or qid in questions
            or not _text(chid)
            or chid not in chapters
            or not _text(question.get("question"))
        ):
            errors.append("handoff: invalid or duplicate reader question")
            continue
        questions.add(qid)
        refs = question.get("claim_ids")
        if (
            type(question.get("required")) is not bool
            or question.get("status") not in ("answered", "open", "excluded")
            or not _strings(refs)
        ):
            errors.append(f"handoff: {qid} invalid decision contract")
            continue
        if any(cid not in chapters[chid] for cid in refs):
            errors.append(f"handoff: {qid} answer is outside its chapter")
        if question["required"]:
            covered.add(chid)
            if question["status"] != "answered" or not refs:
                errors.append(f"handoff: {qid} required question unanswered")
        elif question["status"] == "answered" and not refs:
            errors.append(f"handoff: {qid} answered without claims")
        if question["status"] == "open" and handoff["status"] == "research_ready":
            errors.append(f"handoff: {qid} open question requires ready_with_gaps")
    for chid in chapters.keys() - covered:
        errors.append(f"handoff: {chid} has no required reader question")
    return errors


_URL = re.compile(r"https?://[^\s<>\[\]\"')]+", re.IGNORECASE)
_NUMBER = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?\s*%?(?!\w)")
_CARD = re.compile(
    r"\[(?:card|cardlink|hs_card|hs_bg)\b[^\]]*\].*?\[/(?:card|cardlink|hs_card|hs_bg)\]",
    re.IGNORECASE | re.DOTALL,
)
_CARD_OPEN = re.compile(r"\[(card|cardlink|hs_card|hs_bg)\b([^\]]*)\]", re.IGNORECASE)
_CARD_ID = re.compile(r"(?:^|\s)id\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s\]]+))", re.IGNORECASE)
_NAME = re.compile(r"(?<!\w)[A-ZА-ЯЁ][a-zа-яё]+(?:[ \t]+[A-ZА-ЯЁ][a-zа-яё]+)+(?!\w)")


def _urls(text: str) -> set[str]:
    return {match.rstrip(".,;!?:") for match in _URL.findall(text)}


def _entities(text: str) -> dict[str, set[str]]:
    # URL digits and ordered-list markers are not new factual numeric claims.
    prose = _URL.sub("", text)
    prose = re.sub(r"(?m)^\s*\d+[.)]\s+", "", prose)
    return {
        "number": {match.strip() for match in _NUMBER.findall(prose)},
        "card_id": {
            f"{tag.group(1).lower()}:{next(value for value in identity if value)}"
            for tag in _CARD_OPEN.finditer(prose)
            for identity in _CARD_ID.findall(tag.group(2))
        },
    }


def _approved_text(handoff: dict) -> str:
    required = {cid for chapter in handoff["chapters"] for cid in chapter["required_claim_ids"]}
    return "\n".join(
        claim.get(field, "")
        for claim in handoff["claims"]
        if claim["claim_id"] in required
        for field in ("meaning", "action", "condition", "exception")
    )


def entity_hints(handoff: dict, text: str) -> list[str]:
    """Give the semantic reviewer untrusted name/ID-less-card hints.

    Capitalization cannot establish an entity's identity: Russian names inflect,
    and ordinary headings also capitalize words. Hints are neither errors nor
    approved evidence. The reviewer must still inspect every candidate claim.
    Stable shortcode type/IDs, numbers and exact URLs remain hard gates.
    """
    if not _text(text) or validate_handoff(
        handoff, handoff.get("patch") if isinstance(handoff, dict) else ""
    ):
        return []
    prose, approved = _URL.sub("", text), _URL.sub("", _approved_text(handoff))
    hints = [
        f"review named phrase (may be an inflection): {name}"
        for name in sorted(set(_NAME.findall(prose)) - set(_NAME.findall(approved)))
    ]
    for tag in _CARD.finditer(prose):
        opening = _CARD_OPEN.match(tag.group())
        if opening and not _CARD_ID.search(opening.group(2)):
            hints.append(f"review ID-less card shortcode against evidence: {tag.group()}")
    return hints


def _report(text: str, report: dict) -> list[str]:
    if not _text(text):
        return ["review: candidate is empty or malformed"]
    if not isinstance(report, dict):
        return ["review: expected an object"]
    errors = []
    from .integrity import arithmetic_issues

    errors.extend(
        f"review: {issue['message']} {issue['suggestion']}" for issue in arithmetic_issues(text)
    )
    try:
        expected_hash = article_hash(text)
    except UnicodeError:
        return ["review: candidate is not UTF-8 text"]
    if report.get("article_sha256") != expected_hash:
        errors.append("review: article hash mismatch")
    if report.get("status") != "pass":
        errors.append("review: status must be pass")
    return errors


def validate_factual(
    handoff: dict,
    text: str,
    report: dict,
    *,
    require_practices: bool = False,
    original: str | None = None,
    snapshots: list | None = None,
) -> list[str]:
    """Require supported literal attestations, provenance and model judgments."""
    errors = validate_handoff(handoff, handoff.get("patch") if isinstance(handoff, dict) else "")
    errors += _report(text, report)
    if errors:
        return errors
    try:
        if report.get("handoff_sha256") != handoff_hash(handoff):
            errors.append("factual: handoff hash mismatch")
    except (TypeError, ValueError, UnicodeError):
        return errors + ["factual: handoff is not JSON serializable"]
    for field in ("candidate_checked", "confidence_preserved", "patch_matches"):
        if report.get(field) is not True:
            errors.append(f"factual: {field} must be true")
    if (
        any(chapter.get("decision_cards") for chapter in handoff["chapters"])
        and report.get("decision_cards_checked") is not True
    ):
        errors.append(
            "factual: decision_cards_checked must be true; verify every field and inference against evidence"
        )
    for field in ("unsupported_claims", "conflicts"):
        if report.get(field) != []:
            errors.append(f"factual: {field} must be an empty list")
    rows = report.get("claims")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return errors + ["factual: malformed claim attestations"]
    required = {cid for chapter in handoff["chapters"] for cid in chapter["required_claim_ids"]}
    claims = {
        claim["claim_id"]: claim for claim in handoff["claims"] if claim["claim_id"] in required
    }
    sources = {source["source_id"]: source for source in handoff["sources"]}
    cited, seen = _urls(text), set()
    for row in rows:
        cid = row.get("claim_id")
        if not _text(cid) or cid in seen or cid not in claims:
            errors.append("factual: duplicate, unknown or malformed claim_id")
            continue
        seen.add(cid)
        claim = claims[cid]
        if row.get("status") != "supported":
            errors.append(f"factual: {cid} is not supported")
        for field in ("action", "condition", "exception", "confidence"):
            needed = (
                field == "action"
                or (field == "confidence" and claim["confidence"] != "high")
                or (field in {"condition", "exception"} and bool(claim.get(field, "").strip()))
            )
            quote = row.get(f"{field}_quote", "")
            if (
                not isinstance(quote, str)
                or (needed and not _text(quote))
                or (quote and quote not in text)
            ):
                errors.append(f"factual: {cid} missing or invented {field}_quote")
        refs = row.get("evidence_refs")
        if not _strings(refs, nonempty=True) or any(
            ref not in claim["evidence_refs"] for ref in refs
        ):
            errors.append(f"factual: {cid} invalid evidence_refs")
            continue
        if any(sources[ref]["url"] not in cited for ref in refs):
            errors.append(f"factual: {cid} approved evidence not cited exactly")
    for cid in required - seen:
        errors.append(f"factual: missing attestation for {cid}")
    if require_practices:
        from .editorial_practices import validate

        errors += validate(
            text,
            report,
            owner="fact_review",
            handoff=handoff,
            original=original,
            snapshots=snapshots,
        )
    approved = _approved_text(handoff)
    approved_urls = {
        sources[ref]["url"] for claim in claims.values() for ref in claim["evidence_refs"]
    }
    for url in sorted(cited - approved_urls):
        errors.append(f"factual: unapproved URL {url}")
    before, after = _entities(approved), _entities(text)
    for kind in before:
        for value in sorted(after[kind] - before[kind]):
            errors.append(f"factual: new {kind}: {value}")
    return errors


def validate_literary(
    text: str,
    report: dict,
    *,
    keep_spans: list[dict] | None = None,
    require_extended: bool = False,
    require_practices: bool = False,
    original: str | None = None,
    handoff: dict | None = None,
    snapshots: list | None = None,
) -> list[str]:
    """Check the independent whole-article assessment and quoted findings."""
    errors = _report(text, report)
    if not isinstance(report, dict) or not _text(text):
        return errors
    for key, explanation in (("strengths", "reason"), ("paragraph_functions", "function")):
        if key not in report and not require_extended:
            continue
        rows = report.get(key)
        if not isinstance(rows, list) or len(rows) > 256:
            errors.append(f"literary: invalid {key}")
            continue
        for row in rows:
            if (
                not isinstance(row, dict)
                or not _text(row.get("quote"))
                or row["quote"] not in text
                or not _text(row.get(explanation))
            ):
                errors.append(f"literary: {key} needs a real quote and {explanation}")
    if require_extended:
        if report.get("whole_article_checked") is not True:
            errors.append("literary: whole_article_checked must be true")
        reader = report.get("reader_check")
        if not isinstance(reader, dict) or any(
            not _text(reader.get(key)) for key in ("action", "reason", "conditions", "alternative")
        ):
            errors.append(
                "literary: reader_check requires action/reason/conditions/alternative (explain non-applicable fields)"
            )
        if not report.get("paragraph_functions"):
            errors.append("literary: paragraph_functions required for whole-article review")
    if require_practices:
        from .editorial_practices import validate

        errors += validate(
            text,
            report,
            owner="literary_review",
            original=original,
            handoff=handoff,
            snapshots=snapshots,
        )
    changes = report.get("strength_changes", [])
    if not isinstance(changes, list) or any(not isinstance(row, dict) for row in changes):
        errors.append("literary: malformed strength_changes")
        changes = []
    for span in keep_spans or []:
        quote = span["quote"]
        if quote in text:
            continue
        reasons = [row for row in changes if row.get("quote") == quote]
        if (
            len(reasons) != 1
            or not _text(reasons[0].get("reason"))
            or not isinstance(reasons[0].get("replacement_quote", ""), str)
            or (reasons[0].get("replacement_quote") and reasons[0]["replacement_quote"] not in text)
        ):
            errors.append(
                "literary: lost keep_span requires a concrete reason and an exact replacement quote, or an explained deletion"
            )
    dimensions = report.get("dimensions")
    if not isinstance(dimensions, dict):
        errors.append("literary: missing dimensions")
    else:
        for field in ("usefulness", "coherence", "natural_russian", "author_voice"):
            if dimensions.get(field) != "pass":
                errors.append(f"literary: {field} must pass")
    findings = report.get("findings")
    if not isinstance(findings, list) or not all(isinstance(item, dict) for item in findings):
        return errors + ["literary: malformed findings"]
    for finding in findings:
        severity = finding.get("severity")
        if severity not in ("info", "warning", "error", "blocker"):
            errors.append("literary: invalid finding severity")
        for field in ("category", "quote", "reason", "suggestion"):
            if not _text(finding.get(field)):
                errors.append(f"literary: finding missing {field}")
        if require_extended:
            for field in ("benefit", "meaning_risk"):
                if not _text(finding.get(field)):
                    errors.append(f"literary: finding missing {field}")
        if _text(finding.get("quote")) and finding["quote"] not in text:
            errors.append("literary: finding quote is absent from candidate")
        if severity in ("warning", "error", "blocker"):
            errors.append("literary: unresolved finding requires repair")
    return errors


def validate_reviews(
    handoff: dict,
    text: str,
    factual: dict,
    literary: dict,
    *,
    keep_spans: list[dict] | None = None,
    require_extended: bool = False,
    require_practices: bool = False,
    original: str | None = None,
    snapshots: list | None = None,
) -> list[str]:
    """Gate both reviews of exactly the same article and evidence handoff."""
    errors = validate_factual(
        handoff,
        text,
        factual,
        require_practices=require_practices,
        original=original,
        snapshots=snapshots,
    ) + validate_literary(
        text,
        literary,
        keep_spans=keep_spans,
        require_extended=require_extended,
        require_practices=require_practices,
        original=original,
        handoff=handoff,
        snapshots=snapshots,
    )
    if isinstance(handoff, dict) and isinstance(literary, dict):
        try:
            if literary.get("handoff_sha256") != handoff_hash(handoff):
                errors.append("literary: handoff hash mismatch")
        except (TypeError, ValueError, UnicodeError):
            errors.append("literary: handoff is not JSON serializable")
    return errors
