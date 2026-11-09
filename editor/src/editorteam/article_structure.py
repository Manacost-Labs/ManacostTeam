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


def validate_plan(plan) -> None:
    if not isinstance(plan, dict) or set(plan) != {"reader_question", "main_answer", "sections"}:
        raise ValueError("article_plan requires reader_question, main_answer and sections")
    if any(not _text(plan.get(k), 800) for k in ("reader_question", "main_answer")):
        raise ValueError("article_plan needs a concrete reader question and bounded answer")
    rows, earlier = plan["sections"], set()
    if not isinstance(rows, list) or not 1 <= len(rows) <= 48:
        raise ValueError("article_plan requires 1..48 sections")
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "question", "contribution", "depends_on", "claim_ids"}:
            raise ValueError("invalid article_plan section fields")
        if not _text(row["id"], 80) or row["id"] in earlier or any(not _text(row[k], 800) for k in ("question", "contribution")):
            raise ValueError("article_plan needs unique sections with a question and contribution")
        if not _refs(row["depends_on"], earlier):
            raise ValueError("article_plan prerequisites must name unique earlier sections")
        claims = row["claim_ids"]
        if not isinstance(claims, list) or len(claims) > 128 or any(not _text(x, 100) for x in claims) or len(claims) != len(set(claims)):
            raise ValueError("article_plan claim_ids must be a bounded unique list")
        earlier.add(row["id"])


def validate_plan_evidence(plan, handoff: dict) -> list[str]:
    try:
        validate_plan(plan)
    except ValueError as error:
        return [str(error)]
    allowed = {row["claim_id"] for row in handoff["claims"]}
    required = {key for row in handoff["chapters"] for key in row["required_claim_ids"]}
    used = {key for row in plan["sections"] for key in row["claim_ids"]}
    return (["article_plan references unknown claims"] if used - allowed else []) + (
        ["article_plan leaves required claims uncovered"] if required - used else []
    )


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
