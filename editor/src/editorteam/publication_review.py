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
    for claim in handoff["claims"]:
        cid = claim.get("claim_id")
        if not _text(cid) or cid in claims:
            errors.append("handoff: invalid or duplicate claim ID")
            continue
        claims[cid] = claim
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
        if chapter.get("unresolved_questions") and handoff["status"] == "research_ready":
            errors.append(f"handoff: {chid} unresolved questions")
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
    try:
        expected_hash = article_hash(text)
    except UnicodeError:
        return ["review: candidate is not UTF-8 text"]
    if report.get("article_sha256") != expected_hash:
        errors.append("review: article hash mismatch")
    if report.get("status") != "pass":
        errors.append("review: status must be pass")
    return errors


def validate_factual(handoff: dict, text: str, report: dict) -> list[str]:
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
    for field in ("confidence_preserved", "patch_matches"):
        if report.get(field) is not True:
            errors.append(f"factual: {field} must be true")
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


def validate_literary(text: str, report: dict) -> list[str]:
    """Check the independent whole-article assessment and quoted findings."""
    errors = _report(text, report)
    if not isinstance(report, dict) or not _text(text):
        return errors
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
        if _text(finding.get("quote")) and finding["quote"] not in text:
            errors.append("literary: finding quote is absent from candidate")
        if severity in ("warning", "error", "blocker"):
            errors.append("literary: unresolved finding requires repair")
    return errors


def validate_reviews(handoff: dict, text: str, factual: dict, literary: dict) -> list[str]:
    """Gate both reviews of exactly the same article and evidence handoff."""
    errors = validate_factual(handoff, text, factual) + validate_literary(text, literary)
    if isinstance(handoff, dict) and isinstance(literary, dict):
        try:
            if literary.get("handoff_sha256") != handoff_hash(handoff):
                errors.append("literary: handoff hash mismatch")
        except (TypeError, ValueError, UnicodeError):
            errors.append("literary: handoff is not JSON serializable")
    return errors
