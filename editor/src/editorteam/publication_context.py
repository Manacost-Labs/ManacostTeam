"""Bounded task context. Selected style references are neither game evidence nor gold."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path

PURPOSE = "task_style_only_not_game_evidence_or_training_approval"
MAX_BYTES = 48_000


def _text(value: object, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def validate(context: dict, profile: str, *, frozen: bool = False) -> None:
    if not isinstance(context, dict) or set(context) - {
        "schema_version", "profile", "requirements", "style_examples", "style_note", "purpose", "article_plan"
    }:
        raise ValueError("invalid author context fields")
    if type(context.get("schema_version")) is not int or context["schema_version"] != 1:
        raise ValueError("author context schema_version must be 1")
    if context.get("profile") != profile or not _text(context.get("style_note"), 800):
        raise ValueError("author context profile must match; explicit style_note required")
    if frozen and context.get("purpose") != PURPOSE:
        raise ValueError("author context must be style-only, not training approval")
    if "article_plan" in context:
        from .article_structure import validate_plan

        validate_plan(context["article_plan"])
    if len(json.dumps(context, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        raise ValueError("author context exceeds size limit")
    requirements = context.get("requirements")
    if not isinstance(requirements, list) or not 1 <= len(requirements) <= 24:
        raise ValueError("author context requires 1..24 requirements")
    seen = set()
    for row in requirements:
        if not isinstance(row, dict) or set(row) - {"id", "instruction", "forbidden_literals"}:
            raise ValueError("invalid requirement fields")
        if not _text(row.get("id"), 80) or row["id"] in seen or not _text(row.get("instruction"), 800):
            raise ValueError("invalid or duplicate requirement")
        seen.add(row["id"])
        terms = row.get("forbidden_literals", [])
        if not isinstance(terms, list) or len(terms) > 24 or any(not _text(t, 100) for t in terms):
            raise ValueError("invalid forbidden_literals")
    examples = context.get("style_examples")
    if not isinstance(examples, list) or len(examples) > 4:
        raise ValueError("at most four task style examples allowed")
    seen = set()
    for row in examples:
        allowed = {"id", "profile", "source", "source_sha256", "quote", "use_for", "avoid"}
        if not frozen:
            allowed.add("source_path")
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError("invalid style example fields; no inferred approval")
        if (
            not _text(row.get("id"), 80) or row["id"] in seen
            or row.get("profile") != profile
            or not _text(row.get("source"), 1000)
            or not _text(row.get("quote"), 2000)
            or not _text(row.get("use_for"), 500)
            or not _text(row.get("avoid"), 500)
            or not re.fullmatch(r"[a-f0-9]{64}", str(row.get("source_sha256", "")))
        ):
            raise ValueError("invalid style example: id/profile/source/quote/use_for/avoid/hash")
        seen.add(row["id"])


def freeze(artifact: Path, profile: str) -> bytes:
    raw = artifact.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("author context exceeds size limit")
    context = json.loads(raw.decode("utf-8-sig"))
    validate(context, profile)
    for row in context["style_examples"]:
        if not _text(row.get("source_path"), 4000):
            raise ValueError("style example source_path required")
        source = Path(row.pop("source_path"))
        if not source.is_absolute():
            source = artifact.parent / source
        if source.stat().st_size > 2_000_000:
            raise ValueError("style source too large; select a bounded saved document")
        raw_source = source.read_bytes()
        if hashlib.sha256(raw_source).hexdigest() != row["source_sha256"]:
            raise ValueError("style source hash mismatch")
        if row["quote"] not in raw_source.decode("utf-8-sig"):
            raise ValueError("style quote is not present in source")
    context["purpose"] = PURPOSE
    validate(context, profile, frozen=True)
    return (json.dumps(context, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def packet(context: dict, stage: str) -> dict:
    result = deepcopy(context)
    if stage not in {"draft", "literary_review"}:
        result.pop("style_examples", None)
        result.pop("style_note", None)
    return result


class _VisibleText(HTMLParser):
    BLOCKS = frozenset({
        "p", "div", "section", "article", "aside", "header", "footer", "main",
        "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote",
        "pre", "table", "tr", "td", "th", "br", "hr", "figure", "figcaption",
    })

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden.append(tag)
        if tag in self.BLOCKS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.hidden and self.hidden[-1] == tag:
            self.hidden.pop()
        if tag in self.BLOCKS:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def literal_errors(context: dict, article: str) -> list[str]:
    # Check visible words, including headings and captions, without substring bans.
    # Link destinations and reference definitions are not author-facing prose.
    visible = re.sub(r"!?\[([^\]\n]*)\]\((?:[^()\n]|\([^()\n]*\))*\)", r"\1", article)
    visible = re.sub(r"(?m)^ {0,3}\[[^\]\n]+\]:[^\n]*$", "", visible)
    parser = _VisibleText()
    parser.feed(visible)
    parser.close()
    visible = "".join(parser.parts)
    visible = re.sub(r"\[/?hs_(?:bg|card)\b[^\]]*\]", "", visible)
    visible = re.sub(r"[*_`]", "", visible)
    errors = []
    for row in context["requirements"]:
        for term in row.get("forbidden_literals", []):
            if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", visible, re.IGNORECASE):
                errors.append(f"requirement {row['id']}: forbidden literal {term!r}")
    return errors


def review_errors(context: dict, digest: str, article: str, report: dict, stage: str) -> list[str]:
    errors = literal_errors(context, article)
    if not isinstance(report, dict) or report.get("author_context_sha256") != digest:
        return errors + ["review author_context_sha256 mismatch"]
    if stage != "literary_review":
        return errors
    from .article_structure import validate_plan_review

    errors += validate_plan_review(context.get("article_plan"), article, report.get("plan_checks"))
    for field, expected in (
        ("requirement_checks", {r["id"] for r in context["requirements"]}),
        ("style_checks", {r["id"] for r in context["style_examples"]}),
    ):
        rows = report.get(field)
        if not isinstance(rows, list):
            errors.append(f"{field}: complete per-id review required")
            continue
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                errors.append(f"{field}: malformed row")
                continue
            key = row["id"]
            if key not in expected or key in seen:
                errors.append(f"{field}: unknown or duplicate id {key}")
            seen.add(key)
            if row.get("status") not in {"met", "not_applicable"}:
                errors.append(f"{field}/{key}: unresolved requirement or style mismatch")
            if not _text(row.get("reason"), 3000):
                errors.append(f"{field}/{key}: specific reason required")
            quote = row.get("quote")
            if not isinstance(quote, str) or (quote and quote not in article):
                errors.append(f"{field}/{key}: invalid candidate quote")
            if row.get("status") == "met" and not _text(quote, 5000):
                errors.append(f"{field}/{key}: exact candidate quote required")
        if seen != expected:
            errors.append(f"{field}: coverage mismatch")
    return errors
