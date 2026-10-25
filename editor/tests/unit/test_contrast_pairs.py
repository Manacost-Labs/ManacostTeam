"""Пары «скучно → интересно»: интересное — дословно из корпуса, скучное — помечено."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from editorteam import server

ROOT = Path(__file__).resolve().parents[2]
PAIRS = json.loads((ROOT / "config" / "contrast_pairs.json").read_text(encoding="utf-8"))["pairs"]


def _corpus_by_id() -> dict[str, str]:
    out = {}
    for path in (ROOT / "гайды").glob("*.md"):
        text = path.read_text(encoding="utf-8")
        match = re.search(r"^id:\s*(\S+)\s*$", text, re.M)
        if match:
            out[match.group(1)] = text
    return out


def test_pairs_cover_distinct_topics_and_mark_synthetic_boring_text() -> None:
    assert len(PAIRS) >= 5
    assert len({pair["topic"] for pair in PAIRS}) == len(PAIRS)
    for pair in PAIRS:
        assert pair["boring"]["synthetic"] is True and pair["boring"]["how"]
        assert pair["why"].strip()
        assert pair["boring"]["text"] != pair["interesting"]["text"]


def test_interesting_paragraphs_are_verbatim_author_text() -> None:
    corpus = _corpus_by_id()
    if not corpus:
        pytest.skip("корпус гайды/ отсутствует")
    for pair in PAIRS:
        doc = corpus[pair["interesting"]["source_id"]]
        for paragraph in pair["interesting"]["text"].split("\n\n"):
            assert paragraph in doc, (pair["id"], paragraph[:60])


def test_rules_carry_pairs_for_hearthstone_writer_only() -> None:
    pairs = server.rules_for("hearthstone", "constructed-guide")["contrast_pairs"]
    assert [p["topic"] for p in pairs] == [p["topic"] for p in PAIRS]
    assert set(pairs[0]) == {"topic", "boring", "interesting", "why"}
