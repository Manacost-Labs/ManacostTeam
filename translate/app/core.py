"""Pure helpers for Codex-oriented game translation preparation and QA."""

from __future__ import annotations

import csv
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


STYLE_PRESETS = {
    "literal": "Точный перевод без стилистической адаптации; сохраняй терминологию и структуру.",
    "manacost": "Публикационный стиль Manacost: естественный русский, ясные игровые формулировки, без добавления фактов.",
    "technical": "Технический гайд: приоритет точности механик, чисел, приоритетов и терминов.",
    "summary": "Краткое изложение: сократи только явно второстепенные детали, не меняя фактов и чисел.",
}


@dataclass(frozen=True)
class Segment:
    id: str
    text: str


def _safe_aliases(source: str, comment: str) -> set[str]:
    stripped = source.strip("\"“”«»")
    candidates = {source, stripped}
    if "manual=true" in comment:
        return {candidate for candidate in candidates if candidate}
    return {
        candidate
        for candidate in candidates
        if len(re.findall(r"[A-Za-z0-9]+", candidate)) >= 2
    }


def load_glossary(paths: Iterable[Path]) -> dict[str, str]:
    """Use only unambiguous EN→RU pairs; avoid generic one-word dump entries."""
    variants: dict[str, set[str]] = defaultdict(set)
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            parts = line.split("\t", 2)
            if len(parts) < 2:
                continue
            source, target = parts[0].strip(), parts[1].strip()
            comment = parts[2].strip() if len(parts) == 3 else ""
            if not source or not target or source == "source_en":
                continue
            for alias in _safe_aliases(source, comment):
                variants[alias].add(target)
    return {
        source: next(iter(targets))
        for source, targets in variants.items()
        if len(targets) == 1
    }


def protect_terms(text: str, glossary: dict[str, str]) -> tuple[str, dict[str, str]]:
    if not glossary:
        return text, {}
    pattern = re.compile("|".join(re.escape(term) for term in sorted(glossary, key=len, reverse=True)))
    replacements: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        marker = f"[[[TERM_{len(replacements) + 1}]]]"
        replacements[marker] = glossary[match.group(0)]
        return marker

    return pattern.sub(replace, text), replacements


def segment_markdown(text: str, limit: int = 4200) -> list[Segment]:
    """Make stable paragraph-first segments for memory reuse and update diffs."""
    segments: list[Segment] = []
    for block in re.split(r"\n{2,}", text.strip()):
        current = block.strip()
        while current and len(current) > limit:
            cut = current.rfind("\n", 0, limit)
            if cut < limit // 2:
                cut = current.rfind(". ", 0, limit)
            if cut < limit // 2:
                cut = limit
            segments.append(_segment(current[:cut].strip()))
            current = current[cut:].lstrip()
        if current:
            segments.append(_segment(current))
    return segments


def _segment(text: str) -> Segment:
    normalized = re.sub(r"\s+", " ", text).strip()
    return Segment(hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16], text)


def changed_segment_ids(previous: str | None, current: str) -> list[str]:
    old = {segment.id for segment in segment_markdown(previous or "")}
    return [segment.id for segment in segment_markdown(current) if segment.id not in old]


def load_translation_memory(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        if not {"source_en", "target_ru", "status"}.issubset(reader.fieldnames or []):
            return {}
        return {
            row["source_en"]: row["target_ru"]
            for row in reader
            if row.get("status") == "approved" and row.get("source_en") and row.get("target_ru")
        }


def append_translation_memory(path: Path, source_en: str, target_ru: str, context: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=("source_en", "target_ru", "status", "context"),
            delimiter="\t",
            lineterminator="\n",
        )
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "source_en": source_en.replace("\n", " ").strip(),
                "target_ru": target_ru.replace("\n", " ").strip(),
                "status": "approved",
                "context": context.replace("\n", " ").strip(),
            }
        )


def find_review_candidates(text: str, glossary: dict[str, str]) -> list[str]:
    """Surface likely proper names, but never turn a heuristic into a glossary entry."""
    pattern = re.compile(r"\b[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+)+\b")
    found = {match.group(0) for match in pattern.finditer(text)}
    return sorted(term for term in found if term not in glossary)[:40]


def qa_translation(protected_source: str, translated: str, replacements: dict[str, str]) -> dict[str, object]:
    """Mechanical fidelity checks; linguistic judgment remains with Codex editor."""
    source_without_markers = re.sub(r"\[\[\[TERM_\d+\]\]\]", "", protected_source)
    source_numbers = sorted(re.findall(r"\d+(?:[.,]\d+)?%?", source_without_markers))
    target_numbers = sorted(re.findall(r"\d+(?:[.,]\d+)?%?", translated))
    source_links = sorted(re.findall(r"https?://[^\s)>]+", protected_source))
    target_links = sorted(re.findall(r"https?://[^\s)>]+", translated))
    source_codes = len(re.findall(r"`[^`]+`", protected_source))
    target_codes = len(re.findall(r"`[^`]+`", translated))
    expected_terms = sorted(set(replacements.values()))
    missing_terms = [term for term in expected_terms if term not in translated]
    leaked_markers = re.findall(r"\[\[\[TERM_\d+\]\]\]", translated)
    return {
        "numbers_match": source_numbers == target_numbers,
        "missing_numbers": sorted(set(source_numbers) - set(target_numbers)),
        "links_match": source_links == target_links,
        "missing_links": sorted(set(source_links) - set(target_links)),
        "code_spans_match": source_codes == target_codes,
        "missing_terms": missing_terms,
        "leaked_markers": leaked_markers,
        "table_row_delta": _table_rows(translated) - _table_rows(protected_source),
        "ready_for_editor": not (
            source_numbers != target_numbers
            or source_links != target_links
            or source_codes != target_codes
            or missing_terms
            or leaked_markers
        ),
    }


def _table_rows(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.count("|") >= 2)
