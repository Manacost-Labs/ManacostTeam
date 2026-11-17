"""Source-block coverage and a reader-oriented plan; not semantic classification."""

from __future__ import annotations

import hashlib
import re

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
LIST = re.compile(r"^ {0,3}(?:[-+*]|[0-9]+[.)])[ \t]+")
HTML_BLOCK = re.compile(r"</?(?:p|h[1-6]|li|div|section|blockquote|figure|figcaption|table|tr|td|th|ul|ol)(?:[ \t\r\n][^>]*|/?)>", re.I)


def inventory(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("nonempty article required")
    cuts, offset, fence = {0, len(text)}, 0, None
    for line_match in re.finditer(r"[^\n]*\n|[^\n]+$", text):
        line = line_match[0]
        end = offset + len(line)
        match = FENCE.match(line.rstrip("\r\n"))
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                cuts.add(end)
                fence = None
        elif match:
            cuts.add(offset)
            fence = match[1]
        elif not line.strip():
            cuts.update((offset, end))
        else:
            if HEADING.match(line.rstrip("\r\n")):
                cuts.update((offset, end))
            elif LIST.match(line.rstrip("\r\n")):
                cuts.add(offset)
            for tag in HTML_BLOCK.finditer(line):
                cuts.add(offset + (tag.end() if tag[0].startswith("</") else tag.start()))
        offset = end
    positions, blocks = sorted(cuts), []
    for start, end in zip(positions, positions[1:]):
        quote = text[start:end].strip()
        if not quote:
            continue
        kind = "text"
        if FENCE.match(quote.split("\n", 1)[0].rstrip("\r")):
            kind = "code"
        elif HEADING.match(quote) or re.match(r"<h[1-6][ \t\r\n/>]", quote, re.I):
            kind = "heading"
        elif LIST.match(quote) or re.match(r"<li[ \t\r\n/>]", quote, re.I):
            kind = "list"
        blocks.append({"id": f"b{len(blocks) + 1:03d}", "kind": kind, "quote": quote})
    if len(blocks) > 256:
        raise ValueError("structure review supports at most 256 blocks; never truncate the article")
    return {
        "article_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "blocks": blocks,
        "guidance": (
            "Review every source block in order, including headings, lists, captions and code. "
            "These are source boundaries, not a mandated paragraph length or section template. "
            "Explain each block's function, new information and connection to the previous one. "
            "Identify prerequisites and repeated points using earlier block IDs. A deliberate reprise "
            "can help navigation: explain its distinct function. Do not invent transitions or game facts. "
            "Check question-to-answer progression, unexplained terms, contradictory advice under the same "
            "conditions, and conclusions stronger than their premises; separate contrast from contradiction. "
            "A summary must not introduce an ungrounded new recommendation. Semantic judgments remain the reviewer's responsibility."
        ),
    }


def _text(value, limit=3000):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _refs(value, allowed):
    return (
        isinstance(value, list) and all(isinstance(x, str) for x in value)
        and len(value) == len(set(value)) and set(value) <= allowed
    )


def validate_review(text: str, report) -> list[str]:
    try:
        packet = inventory(text)
    except ValueError as error:
        return [f"structure_review: {error}"]
    if not isinstance(report, dict):
        return ["structure_review: complete article review required"]
    errors = []
    if report.get("article_sha256") != packet["article_sha256"]:
        errors.append("structure_review: article hash mismatch")
    for key in ("reader_question", "main_answer", "order_reason", "ending_reason"):
        if not _text(report.get(key)):
            errors.append(f"structure_review: {key} required")
    rows = report.get("blocks")
    if not isinstance(rows, list) or len(rows) != len(packet["blocks"]):
        return errors + ["structure_review: every block must be covered exactly once"]
    earlier = set()
    for block, row in zip(packet["blocks"], rows):
        prefix = f"structure_review/{block['id']}"
        if not isinstance(row, dict):
            errors.append(prefix + ": malformed assessment")
            earlier.add(block["id"])
            continue
        if row.get("id") != block["id"]:
            errors.append(prefix + ": block IDs must follow actual article order")
        if not _text(row.get("quote"), len(block["quote"])) or row["quote"] not in block["quote"]:
            errors.append(prefix + ": exact quote from this block required")
        for key in ("function", "new_information", "link_to_previous", "reason"):
            if not _text(row.get(key)):
                errors.append(prefix + f": {key} required")
        for key in ("depends_on", "repeat_of"):
            if not _refs(row.get(key), earlier):
                errors.append(prefix + f": {key} must name unique earlier blocks")
        if not isinstance(row.get("repeat_reason"), str) or (row.get("repeat_of") and not _text(row["repeat_reason"])):
            errors.append(prefix + ": explain the function of the reprise")
        if row.get("status") != "clear":
            errors.append(prefix + ": unresolved structure or logic issue")
        earlier.add(block["id"])
    return errors


DECK_GUIDE = "deck_guide"
# Жанры Полей сражений: тир-лист (рейтинг пула) и гайд по стратегии.
BG_TIERLIST = "bg_tierlist"
BG_GUIDE = "bg_guide"
GENRES = (DECK_GUIDE, BG_TIERLIST, BG_GUIDE)
# Роли разделов гайда по колоде в порядке решений читателя, не обязательные заголовки.
ROLES = ("intro", "mechanics", "cards", "builds", "mulligan", "early", "mastery", "against", "conclusion")
NEEDS_MECHANICS = frozenset({"cards", "builds", "mulligan", "early", "mastery", "against"})
# Роли разделов тир-листа Полей сражений: вступление, изменения пула, тиры, вывод.
TIERLIST_ROLES = ("intro", "changes", "tier", "conclusion")
# Формы советов в пакете опыта игрока (контракт с research). verdict — позиция
# игрока по одному существу тир-листа; в покрытие мастерства гайда по колоде не входит.
ADVICE_FORMS = ("threshold", "order", "prohibition", "fallback", "trap", "skill_gated", "verdict")
MASTERY_FORMS = frozenset({"threshold", "order"})
VERDICT_FIELDS = ("take_when", "skip_when", "pivot_or_sell_turn", "bad_alternative_omitted")
# Необязательные поля плана: сквозная мысль патча и асимметричный вес записей раздела.
META_THESIS_LIMIT = 600
ENTRY_WEIGHTS = ("full", "brief", "grouped")


def verdict_errors(card: dict) -> list[str]:
    """Карточка verdict: когда брать, когда не брать, ход продажи/выхода и опущенная плохая альтернатива."""
    if card.get("advice_form") != "verdict":
        return []
    verdict = card.get("verdict")
    if not isinstance(verdict, dict) or set(verdict) != set(VERDICT_FIELDS) or any(
        not _text(verdict[key], 800) for key in VERDICT_FIELDS
    ):
        return ["verdict requires take_when, skip_when, pivot_or_sell_turn and bad_alternative_omitted"]
    return []


def experience_cards(handoff) -> list[dict]:
    """Карточки решений с advice_form: пакет опыта игрока. В старых bundle их нет."""
    chapters = handoff.get("chapters") if isinstance(handoff, dict) else None
    return [
        card
        for chapter in (chapters if isinstance(chapters, list) else [])
        if isinstance(chapter, dict)
        for card in (chapter.get("decision_cards") or [])
        if isinstance(card, dict)
        and card.get("advice_form") in ADVICE_FORMS
        # как у research: в пакет попадают только подтверждённые наблюдения
        and card.get("status") == "supported"
        and card.get("kind") == "observed"
    ]


def experience_summary(handoff) -> dict:
    """Что можно писать из опыта игрока; считается по карточкам, не берётся на веру."""
    cards = experience_cards(handoff)
    coverage = {form: [] for form in ADVICE_FORMS}
    for card in cards:
        coverage[card["advice_form"]].append(card.get("card_id"))
    mastery = [c.get("card_id") for c in cards if c["advice_form"] in MASTERY_FORMS]
    return {
        "cards": len(cards),
        "coverage": coverage,
        "first_person_card_ids": [c.get("card_id") for c in cards if c.get("first_person") is True],
        "mastery_card_ids": mastery,
        "mastery_allowed": bool(mastery),
        # пробелы, которые research записал в handoff, показываются автору как есть
        "handoff_gaps": [
            gap
            for gap in (handoff.get("experience_coverage") or {}).get("gaps", [])
            if isinstance(gap, str)
        ]
        if isinstance(handoff, dict) and isinstance(handoff.get("experience_coverage"), dict)
        else [],
        "note": ""
        if mastery
        else "раздел мастерства писать не из чего: нет карточек с порогом или порядком действий",
    }


def _deck_guide_roles(rows: list[dict]) -> None:
    """«Как работает колода» идёт сразу после вступления и раньше всего, что на нём стоит."""
    if any(row.get("role") is None for row in rows):
        raise ValueError("deck guide plan: every section needs a role")
    mechanics = [i for i, row in enumerate(rows) if row["role"] == "mechanics"]
    if len(mechanics) != 1:
        raise ValueError("deck guide plan needs exactly one mechanics section (how the deck works)")
    if any(row["role"] != "intro" for row in rows[: mechanics[0]]) or mechanics[0] > 1:
        raise ValueError("deck guide plan: mechanics must follow the intro directly, before any other section")
    key = rows[mechanics[0]]["id"]
    ancestors: dict[str, set] = {}
    for row in rows:
        known = set(row["depends_on"])
        for dep in row["depends_on"]:
            known |= ancestors[dep]
        ancestors[row["id"]] = known
        if row["role"] in NEEDS_MECHANICS and key not in known:
            raise ValueError(
                f"deck guide plan: section {row['id']} ({row['role']}) must depend on the mechanics section {key}"
            )
        if row["role"] == "mastery" and not row["card_ids"]:
            raise ValueError(f"deck guide plan: mastery section {row['id']} must name its experience card_ids")


def _tierlist_roles(rows: list[dict]) -> None:
    """Тир-лист: у каждого раздела роль, хотя бы один тир, и тир называет claim_ids своих элементов."""
    if any(row.get("role") is None for row in rows):
        raise ValueError("bg tierlist plan: every section needs a role")
    tiers = [row for row in rows if row["role"] == "tier"]
    if not tiers:
        raise ValueError("bg tierlist plan needs at least one tier section")
    for row in tiers:
        if not row["claim_ids"]:
            raise ValueError(f"bg tierlist plan: tier section {row['id']} must name claim_ids of its entries")


def _entry_weights(rows: list[dict]) -> None:
    """Асимметричный объём записей: full — подробный разбор, brief — короткая запись,
    grouped — простые разменные существа одним явным блоком с единым правилом выбора.
    Один предмет получает один вес в одном разделе."""
    owner: dict[str, str] = {}
    for row in rows:
        if "entry_weights" not in row:
            continue
        weights = row["entry_weights"]
        if not isinstance(weights, dict) or not weights or set(weights) - set(ENTRY_WEIGHTS):
            raise ValueError(
                f"article_plan section {row['id']}: entry_weights must map " + "/".join(ENTRY_WEIGHTS) + " to names"
            )
        for weight, names in weights.items():
            if not isinstance(names, list) or not 1 <= len(names) <= 64 or any(not _text(x, 100) for x in names):
                raise ValueError(
                    f"article_plan section {row['id']}: entry_weights.{weight} must be a bounded list of names or IDs"
                )
            if weight == "grouped" and len(names) < 2:
                raise ValueError(
                    f"article_plan section {row['id']}: grouped needs at least two entries; one card is a brief entry"
                )
            for name in names:
                key = name.strip().casefold()
                if key in owner:
                    raise ValueError(
                        f"article_plan entry {name!r} has two weights or sections ({owner[key]} and {row['id']}.{weight})"
                    )
                owner[key] = f"{row['id']}.{weight}"


def validate_plan(plan) -> None:
    required = {"reader_question", "main_answer", "sections"}
    if not isinstance(plan, dict) or not required <= set(plan) <= required | {"genre", "meta_thesis"}:
        raise ValueError("article_plan requires reader_question, main_answer and sections")
    if "genre" in plan and plan["genre"] not in GENRES:
        raise ValueError("article_plan genre must be one of " + ", ".join(GENRES))
    if "meta_thesis" in plan and not _text(plan["meta_thesis"], META_THESIS_LIMIT):
        raise ValueError(f"article_plan meta_thesis must be a nonempty string up to {META_THESIS_LIMIT} characters")
    roles = TIERLIST_ROLES if plan.get("genre") == BG_TIERLIST else ROLES
    if any(not _text(plan.get(k), 800) for k in ("reader_question", "main_answer")):
        raise ValueError("article_plan needs a concrete reader question and bounded answer")
    rows, earlier = plan["sections"], set()
    if not isinstance(rows, list) or not 1 <= len(rows) <= 48:
        raise ValueError("article_plan requires 1..48 sections")
    base = {"id", "question", "contribution", "depends_on", "claim_ids"}
    for row in rows:
        if not isinstance(row, dict) or not base <= set(row) <= base | {"role", "card_ids", "entry_weights"}:
            raise ValueError("invalid article_plan section fields")
        if not _text(row["id"], 80) or row["id"] in earlier or any(not _text(row[k], 800) for k in ("question", "contribution")):
            raise ValueError("article_plan needs unique sections with a question and contribution")
        if not _refs(row["depends_on"], earlier):
            raise ValueError("article_plan prerequisites must name unique earlier sections")
        claims = row["claim_ids"]
        if not isinstance(claims, list) or len(claims) > 128 or any(not _text(x, 100) for x in claims) or len(claims) != len(set(claims)):
            raise ValueError("article_plan claim_ids must be a bounded unique list")
        cards = row.get("card_ids", [])
        if row.get("role") is not None and row["role"] not in roles:
            raise ValueError("article_plan section role is unknown")
        if not isinstance(cards, list) or len(cards) > 32 or any(not _text(x, 100) for x in cards) or len(cards) != len(set(cards)):
            raise ValueError("article_plan card_ids must be a bounded unique list of experience card IDs")
        earlier.add(row["id"])
    _entry_weights(rows)
    if plan.get("genre") == DECK_GUIDE:
        _deck_guide_roles([{**row, "card_ids": row.get("card_ids", [])} for row in rows])
    elif plan.get("genre") == BG_TIERLIST:
        _tierlist_roles(rows)


def validate_plan_evidence(plan, handoff: dict) -> list[str]:
    try:
        validate_plan(plan)
    except ValueError as error:
        return [str(error)]
    allowed = {row["claim_id"] for row in handoff["claims"]}
    required = {key for row in handoff["chapters"] for key in row["required_claim_ids"]}
    used = {key for row in plan["sections"] for key in row["claim_ids"]}
    errors = (["article_plan references unknown claims"] if used - allowed else []) + (
        ["article_plan leaves required claims uncovered"] if required - used else []
    )
    if plan.get("genre") not in GENRES:
        return errors
    by_id = {card.get("card_id"): card for card in experience_cards(handoff)}
    for row in plan["sections"]:
        named = row.get("card_ids", [])
        if set(named) - set(by_id):
            # Пустой пакет опыта: раздел мастерства писать не из чего.
            errors.append(f"article_plan section {row['id']} references unknown experience cards")
        elif row.get("role") == "mastery" and not any(by_id[key]["advice_form"] in MASTERY_FORMS for key in named):
            errors.append(f"article_plan section {row['id']}: mastery needs a threshold or order experience card")
    return errors


def validate_plan_review(plan, text: str, rows) -> list[str]:
    try:
        validate_plan(plan)
        blocks = inventory(text)["blocks"]
    except ValueError as error:
        return [str(error)]
    if not isinstance(rows, list) or len(rows) != len(plan["sections"]):
        return ["plan_checks: every planned question must be assessed"]
    positions = {b["id"]: i for i, b in enumerate(blocks)}
    seen, errors = {}, []
    for section, row in zip(plan["sections"], rows):
        if not isinstance(row, dict) or row.get("id") != section["id"]:
            errors.append("plan_checks: missing, duplicate or reordered section")
            continue
        refs = row.get("block_ids")
        if not _refs(refs, set(positions)) or not refs:
            errors.append("plan_checks: actual answer blocks required")
            continue
        first = min(positions[key] for key in refs)
        if any(dep not in seen or seen[dep] > first for dep in section["depends_on"]):
            errors.append("plan_checks: explanation occurs before its prerequisite")
        seen[section["id"]] = max(positions[key] for key in refs)
        if row.get("status") != "clear" or not _text(row.get("reason")):
            errors.append("plan_checks: unresolved or unexplained plan deviation")
    return errors
