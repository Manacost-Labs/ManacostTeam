"""Exact draft blocks and grounded repair context; no Markdown rewriting or verdicts."""

from __future__ import annotations

import hashlib
import re

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+\S")
_LIST = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+\S")
_ASSET = re.compile(
    r"\[(hs_card|hs_bg|card|cardlink)\b(?=[^\]]*\bid\s*=)[^\]]*\]"
    r"[^\[\]\r\n]*\[/\1\]",
    re.IGNORECASE,
)
_STRUCTURAL = {"heading", "code", "shortcode"}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _opening_fence(line: str) -> re.Match | None:
    match = _FENCE.match(line)
    # CommonMark 4.5: backtick fence info cannot itself contain a backtick.
    # Treat doubtful markup as prose; tilde info has no such restriction.
    if match and match[1].startswith("`") and "`" in line[match.end() :]:
        return None
    return match


def _kind(text: str) -> str:
    if _HEADING.match(text) and "\n" not in text:
        return "heading"
    if _ASSET.fullmatch(text):
        return "shortcode"
    if text.startswith(">"):
        return "quote"
    if _LIST.match(text):
        return "list"
    if "|" in text and re.search(r"(?m)^\s*\|?\s*:?-{3,}:?\s*\|", text):
        return "table"
    if text.startswith("<") and not re.sub(r"<[^>]*>", "", text, flags=re.DOTALL).strip():
        return "html"
    return "prose"


def block_inventory(text: str) -> dict:
    """Partition meaningful characters without normalizing or hiding any content.

    This is deliberately a conservative block scanner, not a Markdown AST.
    Offsets are Python Unicode code-point indexes into the exact input string.
    IDs are unique within a draft; article/block hashes bind them to that version.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("nonempty draft required for block inventory")
    lines = text.splitlines(keepends=True)
    offsets, position = [], 0
    for line in lines:
        offsets.append(position)
        position += len(line)
    blocks, index = [], 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        first, kind = index, None
        fence = _opening_fence(lines[index])
        index += 1
        if fence:
            closing = re.compile(
                r"^ {0,3}"
                + re.escape(fence[1][0])
                + "{"
                + str(len(fence[1]))
                + r",}[ \t]*(?:\r\n|\r|\n)?\Z"
            )
            while index < len(lines):
                if closing.match(lines[index]):
                    index += 1
                    kind = "code"
                    break
                index += 1
            # An unclosed fence may hide ordinary prose; it is not exempted.
            kind = kind or "prose"
        elif not _HEADING.match(lines[first]):
            while index < len(lines) and lines[index].strip():
                if _opening_fence(lines[index]) or _HEADING.match(lines[index]):
                    break
                index += 1
        start = offsets[first]
        end = offsets[index] if index < len(lines) else len(text)
        raw = text[start:end]
        start += len(raw) - len(raw.lstrip())
        end -= len(raw) - len(raw.rstrip())
        content = text[start:end]
        protected = [
            {
                "kind": "shortcode",
                "start": start + match.start(),
                "end": start + match.end(),
                "sha256": _hash(match[0]),
                "text": match[0],
            }
            for match in _ASSET.finditer(content)
        ]
        blocks.append(
            {
                "block_id": f"b{len(blocks) + 1:04d}",
                "kind": kind or _kind(content),
                "start": start,
                "end": end,
                "sha256": _hash(content),
                "text": content,
                "protected_spans": protected,
            }
        )
    return {
        "version": 1,
        "article_sha256": _hash(text),
        "offset_unit": "unicode_codepoint",
        "blocks": blocks,
        "limitation": "Inventory proves exact coverage, not semantic understanding; markup remains unchanged.",
    }


def validate_coverage(text: str, rows: object) -> list[str]:
    blocks = {block["block_id"]: block for block in block_inventory(text)["blocks"]}
    if not isinstance(rows, list):
        return ["composition: paragraph_functions must be a list"]
    errors, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("block_id"), str):
            errors.append("composition: block_id required")
            continue
        identity = row["block_id"]
        if identity not in blocks or identity in seen:
            errors.append(f"composition: unknown or duplicate block_id {identity}")
            continue
        seen.add(identity)
        block = blocks[identity]
        if row.get("block_sha256") != block["sha256"]:
            errors.append(f"composition: stale block hash {identity}")
        for key in ("quote", "function", "reason"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                errors.append(f"composition: {identity} requires {key}")
        if isinstance(row.get("quote"), str) and row["quote"] not in block["text"]:
            errors.append(f"composition: {identity} quote absent from its block")
        disposition = row.get("disposition")
        if disposition not in ("retain", "revise", "structural"):
            errors.append(f"composition: invalid disposition for {identity}")
        elif disposition == "structural" and block["kind"] not in _STRUCTURAL:
            errors.append(f"composition: substantive block {identity} requires semantic review")
        elif disposition == "revise":
            errors.append(f"composition: unresolved block {identity} requires repair")
    for identity in blocks.keys() - seen:
        errors.append(f"composition: missing paragraph function for {identity}")
    return sorted(errors)


def repair_brief(
    text: str,
    report: dict,
    *,
    keep_spans: list[dict] | None = None,
    expected_handoff_sha256: str | None = None,
) -> dict:
    """Only current, exact and unambiguous findings become repair targets."""
    inventory = block_inventory(text)
    result = {
        "article_sha256": inventory["article_sha256"],
        "targets": [],
        "unresolved_targets": [],
        "keep_spans": [
            row
            for row in keep_spans or []
            if isinstance(row, dict)
            and isinstance(row.get("quote"), str)
            and row["quote"].strip()
            and row["quote"] in text
        ],
        "policy": "Targets are grounded review assignments, not verified facts. Block references resolve through block_inventory; neighbors are context only; preserve markup and keep_spans. Re-run both independent reviews after revise.",
    }
    if not isinstance(report, dict) or report.get("article_sha256") != inventory["article_sha256"]:
        result["unresolved_targets"].append(
            {"reason": "review article hash mismatch; recheck report"}
        )
        return result
    if (
        expected_handoff_sha256 is not None
        and report.get("handoff_sha256") != expected_handoff_sha256
    ):
        result["unresolved_targets"].append(
            {"reason": "review handoff hash mismatch; recheck report"}
        )
        return result
    from .editorial_practices import LOGIC, PRESERVATION, catalog

    allowed_checks = {
        "practice_checks": {row["id"] for row in catalog()["practices"]},
        "logic_checks": set(LOGIC),
        "preservation_checks": set(PRESERVATION),
    }
    blocks = inventory["blocks"]

    def reference(block):
        return {key: block[key] for key in ("block_id", "sha256", "start", "end")}

    for field in ("findings", "practice_checks", "logic_checks", "preservation_checks"):
        rows = report.get(field, [])
        if not isinstance(rows, list):
            result["unresolved_targets"].append({"field": field, "reason": "malformed review rows"})
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                result["unresolved_targets"].append(
                    {"field": field, "index": index, "reason": "malformed finding"}
                )
                continue
            active = (
                row.get("severity") in ("warning", "error", "blocker")
                if field == "findings"
                else row.get("status") in ("issue", "unverified")
            )
            if not active:
                continue
            identity = {"field": field, "index": index}
            if row.get("status") == "unverified":
                result["unresolved_targets"].append(
                    {
                        **identity,
                        "reason": "unverified claim needs evidence or review before text repair",
                    }
                )
                continue
            required = ("quote", "reason", "suggestion", "benefit", "meaning_risk")
            if field == "findings":
                required += ("category",)
            else:
                if not isinstance(row.get("id"), str) or row["id"] not in allowed_checks[field]:
                    result["unresolved_targets"].append(
                        {**identity, "reason": "unknown review check; recheck report"}
                    )
                    continue
                required += ("reader_problem",)
            if any(not isinstance(row.get(key), str) or not row[key].strip() for key in required):
                result["unresolved_targets"].append(
                    {**identity, "reason": "incomplete grounded finding; recheck report"}
                )
                continue
            quote = row["quote"]
            start = text.find(quote)
            if start < 0 or text.find(quote, start + 1) >= 0:
                result["unresolved_targets"].append(
                    {
                        **identity,
                        "quote": quote,
                        "reason": "quote absent or ambiguous; reviewer must identify the exact passage",
                    }
                )
                continue
            end = start + len(quote)
            selected = [
                i for i, block in enumerate(blocks) if start < block["end"] and end > block["start"]
            ]
            context = {
                i for hit in selected for i in (hit - 1, hit + 1) if 0 <= i < len(blocks)
            } - set(selected)
            result["targets"].append(
                {
                    **identity,
                    **{key: row[key] for key in required},
                    "block_ids": [blocks[i]["block_id"] for i in selected],
                    "blocks": [reference(blocks[i]) for i in selected],
                    "neighbors": [
                        {**reference(blocks[i]), "context_only": True} for i in sorted(context)
                    ],
                }
            )
    functions = report.get("paragraph_functions", [])
    grounded = {identity for target in result["targets"] for identity in target["block_ids"]}
    if isinstance(functions, list):
        for index, row in enumerate(functions):
            if not isinstance(row, dict) or row.get("disposition") != "revise":
                continue
            identity = row.get("block_id")
            if not isinstance(identity, str) or identity not in grounded:
                result["unresolved_targets"].append(
                    {
                        "field": "paragraph_functions",
                        "index": index,
                        "block_id": identity if isinstance(identity, str) else None,
                        "reason": "revise needs an exact grounded finding with suggestion, benefit and meaning_risk; function/reason alone does not authorize a repair target",
                    }
                )
    return result
