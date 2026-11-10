"""Additive claim semantics shared by bundle validation and editorial handoff.

These are provenance checks. Exact semantic support still needs an auditor.
Decision-card ``kind`` describes the card's origin, not the claim's meaning.
"""

import re
import math
from datetime import date
from urllib.parse import urlsplit

CLAIM_CONTRACT_VERSION = "1.0"
CLAIM_KINDS = {"mechanic", "observation", "opinion"}
RULE_TYPES = {"card_text", "game_rule", "patch_note", "rules_reference"}
RULE_SOURCE_TYPES = {"official", "documentation", "wiki", "reference", "card_catalog", "card_database"}
NO_REASON = "в источниках не найдено"
ADVICE_GAP = "блок советов писать не из чего"
TIMECODE = re.compile(r"(?:\d{1,3}:)?\d{1,2}:\d{2}")


def text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def inspected(source: dict) -> bool:
    if source.get("source_type") in {"author_note", "xml_replay"}:
        return source.get("fingerprint_status") == "verified" and text(source.get("snapshot_path")) and source.get("access_integrity") in {"full", "full_text", "inspected", "transcript"}
    url = source.get("url") or source.get("final_url") or source.get("requested_url")
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and parsed.username is None
                and source.get("access_integrity") in
                ("full_text", "full", "inspected", "transcript"))
    except ValueError:
        return False


def timed_or_transcript(item: dict, source: dict) -> bool:
    locator = item.get("locator")
    if isinstance(locator, dict):
        locator = locator.get("timestamp") or locator.get("timecode")
    timed = isinstance(locator, str) and TIMECODE.search(locator) is not None
    quote = item.get("exact_excerpt") or item.get("quote") or item.get("verbatim_quote")
    return timed or source.get("access_integrity") == "transcript" and text(quote)


def claim_errors(claim: dict, evidence: dict, sources: dict, *, required: bool = False) -> list[str]:
    kind = claim.get("claim_kind")
    if kind is None and not required and "claim_kind" not in claim:
        return []  # Legacy records are not silently assigned a type.
    if not isinstance(kind, str) or kind not in CLAIM_KINDS:
        return ["claim_kind must be mechanic, observation or opinion"]
    errors = []
    support = claim.get("supporting_evidence_ids", [])
    support = support if isinstance(support, list) else []
    linked = [evidence[eid] for eid in support if isinstance(eid, str) and eid in evidence]
    if kind == "observation":
        scope = claim.get("observation_scope")
        if (not isinstance(scope, dict)
                or type(scope.get("sample_size")) is not int
                or scope["sample_size"] <= 0
                or not text(scope.get("unit")) or not text(scope.get("slice"))):
            errors.append("observation requires observation_scope: positive sample_size, unit and slice")
        if claim.get("reason", "") not in ("", NO_REASON):
            errors.append("observation reason must be empty or 'в источниках не найдено'")
        if claim.get("inference_steps"):
            errors.append("observation cannot carry causal inference_steps; split an attributed opinion")
    elif kind == "opinion":
        attribution = claim.get("attribution")
        if (not isinstance(attribution, dict) or not text(attribution.get("name"))
                or not isinstance(attribution.get("source_id"), str)):
            errors.append("opinion requires attribution.name and attribution.source_id")
        else:
            sid = attribution["source_id"]
            if (not inspected(sources.get(sid, {}))
                    or not any(item.get("source_id") == sid and item.get("relationship") == "supports"
                               for item in linked)):
                errors.append("opinion attribution source must be inspected supporting evidence")
    else:
        refs = claim.get("rule_evidence_ids")
        if (not isinstance(refs, list) or not refs
                or any(not isinstance(eid, str) or eid not in support for eid in refs)):
            errors.append("mechanic requires rule_evidence_ids from supporting_evidence_ids")
        else:
            for eid in refs:
                item = evidence.get(eid, {})
                source = sources.get(item.get("source_id"), {}) if isinstance(item.get("source_id"), str) else {}
                if (not isinstance(item.get("evidence_type"), str)
                        or item["evidence_type"] not in RULE_TYPES
                        or item.get("relationship") != "supports"
                        or not isinstance(item.get("claim_ids"), list)
                        or claim.get("claim_id") not in item["claim_ids"]
                        or not isinstance(source.get("source_type"), str)
                        or source["source_type"] not in RULE_SOURCE_TYPES
                        or not inspected(source)):
                    errors.append(f"mechanic {eid}: inspected card text or rule source required")
    return errors


def strategy_decision_coverage(plan: dict, claims: dict, evidence: dict, sources: dict) -> dict:
    """Use existing observed decision cards, without inventing another ledger."""
    if plan.get("strategy_review") is not True:
        return {"required": False, "covered_chapters": [], "gaps": []}
    covered, gaps = [], []
    chapters = plan.get("chapters", [])
    if not isinstance(chapters, list):
        return {"required": True, "covered_chapters": [], "gaps": [f"{ADVICE_GAP}; invalid chapters"]}
    for chapter in chapters:
        if (not isinstance(chapter, dict)
                or not isinstance(chapter.get("decision_cards", []), list)
                or not isinstance(chapter.get("required_claim_ids", []), list)):
            gaps.append(f"{ADVICE_GAP}; invalid strategy chapter")
            continue
        chapter_id = chapter.get("chapter_id", "?")
        found = False
        for card in chapter.get("decision_cards", []):
            if not isinstance(card, dict):
                continue
            fields = card.get("fields", {})
            if (card.get("kind") != "observed" or card.get("status") != "supported"
                    or not text(card.get("card_id")) or not text(card.get("question"))
                    or not text(card.get("player")) or not text(card.get("player_basis"))
                    or not isinstance(fields, dict)):
                continue
            valid = True
            for name in ("situation", "options", "action", "outcome"):
                field = fields.get(name, {})
                if not isinstance(field, dict) or not text(field.get("text")):
                    valid = False
                    continue
                ids, refs = field.get("claim_ids"), field.get("evidence_refs")
                if (not isinstance(ids, list) or not ids or not isinstance(refs, list) or not refs
                        or any(not isinstance(cid, str) or cid not in chapter.get("required_claim_ids", [])
                               or claims.get(cid, {}).get("status") not in ("supported", "supported_with_conditions")
                               for cid in ids)):
                    valid = False
                    continue
                for eid in refs:
                    item = evidence.get(eid, {}) if isinstance(eid, str) else {}
                    sid = item.get("source_id")
                    source = sources.get(sid, {}) if isinstance(sid, str) else {}
                    if (not inspected(source) or item.get("relationship") != "supports"
                            or not isinstance(item.get("claim_ids"), list)
                            or not any(isinstance(claims[cid].get("supporting_evidence_ids"), list)
                                       and eid in claims[cid]["supporting_evidence_ids"]
                                       and cid in item["claim_ids"] for cid in ids)
                            or not timed_or_transcript(item, source)):
                        valid = False
            # The moment must be explicit, not reconstructed from a final board.
            moment = card.get("moment")
            if (not isinstance(moment, dict) or not moment
                    or any(key not in {"turn", "gold", "tavern_tier", "mana"}
                           or type(value) is not int or value < 0 for key, value in moment.items())):
                valid = False
            found |= valid
        if found:
            covered.append(chapter_id)
        else:
            gaps.append(f"{chapter_id}: {ADVICE_GAP}; нет проверенного решения сильного игрока")
    if not chapters:
        gaps.append(f"{ADVICE_GAP}; главы стратегии не заданы")
    return {"required": True, "covered_chapters": covered, "gaps": gaps}


ADVICE_FORMS = ("threshold", "order", "prohibition", "fallback", "trap", "skill_gated")
MASTERY_GAP = "раздел мастерства писать не из чего"
NO_ADVICE_REASON = "причина не названа"


def experience_errors(card: dict, claims: dict, evidence: dict, sources: dict) -> list[str]:
    """Validate an opt-in experience card and its linked provenance."""
    if "advice_form" not in card:
        return []
    errors = []
    form = card.get("advice_form")
    if form not in ADVICE_FORMS:
        errors.append("invalid advice_form")
    fields = card.get("fields")
    fields = fields if isinstance(fields, dict) else {}
    action = fields.get("action")
    if not isinstance(action, dict) or not text(action.get("text")):
        errors.append("experience action required")
    if not text(card.get("condition")) or not text(card.get("reason")):
        errors.append("experience condition and reason required")
    if "error_cost" in card and not text(card["error_cost"]):
        errors.append("error_cost must be text when present")
    if form == "order" and (not isinstance(card.get("steps"), list) or not card["steps"] or any(not text(x) for x in card["steps"])):
        errors.append("order requires steps")
    if form == "threshold":
        number = card.get("threshold")
        if not isinstance(number, dict) or type(number.get("value")) not in (int, float) or not math.isfinite(number["value"]) or not text(number.get("unit")):
            errors.append("threshold requires numeric value and unit")
    if form == "skill_gated" and not text(card.get("audience")):
        errors.append("skill_gated requires audience")
    provenance = card.get("experience_source")
    if not isinstance(provenance, dict):
        return errors + ["experience_source required"]
    kind = provenance.get("kind")
    if kind not in ("author_note", "transcript", "xml_replay"):
        errors.append("invalid experience source kind")
    if type(card.get("first_person")) is not bool or card.get("first_person") != (kind == "author_note"):
        errors.append("first_person must be true only for author_note")
    eid, sid = provenance.get("evidence_id"), provenance.get("source_id")
    item = evidence.get(eid, {}) if isinstance(eid, str) else {}
    source = sources.get(sid, {}) if isinstance(sid, str) else {}
    refs = action.get("evidence_refs", []) if isinstance(action, dict) else []
    ids = action.get("claim_ids", []) if isinstance(action, dict) else []
    if (not isinstance(refs, list) or eid not in refs or item.get("source_id") != sid
            or item.get("relationship") != "supports" or not isinstance(ids, list) or not ids
            or not isinstance(item.get("claim_ids"), list)
            or not any(cid in item["claim_ids"] and eid in claims.get(cid, {}).get("supporting_evidence_ids", []) for cid in ids if isinstance(cid, str))):
        errors.append("experience source requires linked supporting action evidence")
    quote = item.get("exact_excerpt") or item.get("quote") or item.get("verbatim_quote")
    if kind == "author_note":
        try:
            date.fromisoformat(provenance.get("date", ""))
        except (ValueError, TypeError):
            errors.append("author_note requires ISO date")
        if not text(provenance.get("author")) or not text(provenance.get("quote")) or provenance.get("quote") != quote:
            errors.append("author_note requires author and verbatim evidence quote")
        if source.get("source_type") != "author_note":
            errors.append("author_note requires author_note source")
    elif kind == "transcript":
        if not inspected(source) or not timed_or_transcript(item, source):
            errors.append("transcript requires inspected video and timecode or transcript quote")
        if source.get("source_type") not in ("video", "stream", "video_transcript"):
            errors.append("transcript requires video or stream source")
    elif kind == "xml_replay":
        if source.get("source_type") != "xml_replay" or provenance.get("result_ref") != source.get("snapshot_path") or not text(provenance.get("result_ref")) or type(provenance.get("turn")) is not int or provenance["turn"] < 0 or not text(provenance.get("action")):
            errors.append("xml_replay requires XMLTeam result_ref, turn and action")
    if kind in ("author_note", "xml_replay") and (source.get("fingerprint_status") != "verified" or not text(source.get("snapshot_path")) or not text(quote)):
        errors.append("local experience source requires verified snapshot and quote")
    return errors


def experience_coverage(plan: dict, claims: dict, evidence: dict, sources: dict) -> dict:
    required = (plan.get("strategy_review") is True or any(plan.get(k) == "constructed-guide" for k in ("profile", "genre", "article_type", "style_profile")))
    grouped = {form: [] for form in ADVICE_FORMS}
    for chapter in plan.get("chapters", []) if isinstance(plan.get("chapters", []), list) else []:
        if not isinstance(chapter, dict):
            continue
        for card in chapter.get("decision_cards", []) if isinstance(chapter.get("decision_cards", []), list) else []:
            if isinstance(card, dict) and card.get("advice_form") in ADVICE_FORMS and card.get("status") == "supported" and card.get("kind") == "observed" and not experience_errors(card, claims, evidence, sources):
                grouped[card["advice_form"]].append(card)
    counts = {form: len(cards) for form, cards in grouped.items()}
    return {"required": required, "counts": counts, "missing_forms": [form for form, count in counts.items() if not count], "gaps": [MASTERY_GAP] if required and not any(counts.values()) else [], "by_form": grouped}
