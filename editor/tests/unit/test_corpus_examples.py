"""Retrieval примеров авторского стиля через существующий индекс корпуса."""

from __future__ import annotations

from pathlib import Path

import pytest

from editorteam import server

ROOT = Path(__file__).resolve().parents[2]
GUIDES = sorted((ROOT / "гайды").glob("*.md"))

QUERY = (
    "В медленных поединках куда важнее станут источники добора, а также крупные угрозы. "
    "Чем больше тяжелых угроз будет у Воина, тем лучше, но нужно постоянно следить за пулом "
    "существ, которых воскрешают легендарки. Медленные матч-апы во многом определяются "
    "зачистками противника, исцелением и добором карт."
)


@pytest.fixture(scope="module")
def has_corpus() -> None:
    if not GUIDES:
        pytest.skip("корпус гайды/ отсутствует")


def test_examples_come_from_the_same_game_and_profile_family(has_corpus: None) -> None:
    result = server.corpus_examples(QUERY, "hearthstone", "constructed-guide")
    assert result["status"] == "ok"
    examples = result["examples"]
    assert 1 <= len(examples) <= server.RETRIEVAL_MAX
    total = 0
    for item in examples:
        assert item["game"] == "hearthstone"
        assert server.GENRE_FAMILIES.get(item["profile"]) == "guide"
        assert 0 < len(item["excerpt"]) <= server.RETRIEVAL_EXCERPT_MAX
        assert item["why_relevant"]
        assert isinstance(item["voice_features"], list)
        assert "#" in item["id"]
        total += len(item["excerpt"])
    assert total <= server.RETRIEVAL_TOTAL_MAX
    assert len({item["excerpt"] for item in examples}) == len(examples)


def test_voice_analysis_runs_only_for_final_selected_examples(monkeypatch, has_corpus):
    seen = []
    monkeypatch.setattr(server, "_voice_features", lambda text: seen.append(text) or ["voice"])
    result = server.corpus_examples("\n\n".join([QUERY, QUERY + " Поэтому нужен ресурс."]), "hearthstone", "constructed-guide")
    assert seen == [item["excerpt"] for item in result["examples"]]
    assert all(item["voice_features"] == ["voice"] for item in result["examples"])


def test_plain_manacost_rules_load_house_style_without_task_context():
    rules = server.rules_for("hearthstone", "game-guide", text="", depth="обычная")
    text = "\n".join(rules.get("style_rules", []))
    assert (ROOT / "СТИЛЬ.md").read_text(encoding="utf-8").strip() in text
    assert server.voice_signature() in text and server.voice_signature()


def test_other_game_and_news_profile_get_nothing(has_corpus: None) -> None:
    assert server.corpus_examples(QUERY, "wow", "wow-guide")["examples"] == []
    assert server.corpus_examples(QUERY, "hearthstone", "news")["examples"] == []
    assert server.corpus_examples("", "hearthstone", "constructed-guide")["examples"] == []


def test_game_guide_gets_same_game_guide_style(has_corpus: None) -> None:
    examples = server.corpus_examples(QUERY, "hearthstone", "game-guide")["examples"]
    assert examples
    assert all(item["game"] == "hearthstone" for item in examples)
    assert all(server.GENRE_FAMILIES.get(item["profile"]) == "guide" for item in examples)


def test_edited_text_is_excluded_by_hash_and_containment(has_corpus: None) -> None:
    body = server._scripts().body(GUIDES[28])
    paragraphs = server._scripts().paragraphs(body, min_words=35)
    assert paragraphs
    own = paragraphs[len(paragraphs) // 2]
    result = server.corpus_examples(own, "hearthstone", "constructed-guide")
    own_norm = server._content_norm(own)
    for item in result["examples"]:
        assert server._content_norm(item["excerpt"]) != own_norm
        assert server._content_norm(item["excerpt"]) not in own_norm
    excluded = server.corpus_examples(
        QUERY, "hearthstone", "constructed-guide", exclude_hash=server._content_hash(own)
    )
    assert all(server._content_norm(item["excerpt"]) != own_norm for item in excluded["examples"])


def test_author_filter_and_limit(has_corpus: None) -> None:
    assert (
        server.corpus_examples(QUERY, "hearthstone", "constructed-guide", author="кто-то")[
            "examples"
        ]
        == []
    )
    assert (
        len(server.corpus_examples(QUERY, "hearthstone", "constructed-guide", limit=1)["examples"])
        <= 1
    )


def test_author_is_returned_and_matched_ignoring_case(has_corpus: None) -> None:
    same = server.corpus_examples(QUERY, "hearthstone", "constructed-guide", author=" Manacost ")
    assert same["examples"]
    assert all(item["author"] == "manacost" for item in same["examples"])
    plain = server.corpus_examples(QUERY, "hearthstone", "constructed-guide")["examples"]
    assert plain and all("author" in item for item in plain)


CALM = (
    "После срабатывания эффекта запас ресурса увеличивается на величину полученного урона. "
    "Поэтому порядок действий определяет доступные варианты продолжения хода и позволяет заранее "
    "оценить остаток ресурса после обмена существами на столе. Это объяснение относится только "
    "к описанному взаимодействию и сохраняет его условия."
)


def test_calm_explanation_is_eligible_without_voice_signal_quota():
    assert server._good_example(CALM)
    assert "mechanism" in server._editorial_functions(CALM)


def test_retrieval_reaches_late_paragraph_and_preserves_function(monkeypatch):
    paragraphs = [
        ("Обычное описание ситуации и доступных вариантов. " * 7) + str(i) for i in range(9)
    ]
    paragraphs.append("Поэтому механизм срабатывает после действия. " * 8)
    seen = []

    class Archive:
        idf = {}

        def search(self, query, top):
            seen.append(query)
            if "срабатывает" not in query:
                return []
            return [
                (
                    4.0,
                    "late",
                    CALM,
                    {
                        "game": "hearthstone",
                        "genre": "constructed-guide",
                        "author": "ivan",
                        "reader_level": "beginner",
                    },
                )
            ]

    monkeypatch.setattr(server, "_archive", lambda version: Archive())
    monkeypatch.setattr(server, "_document_hashes", lambda version: {})
    result = server.corpus_examples(
        "\n\n".join(paragraphs),
        "hearthstone",
        "constructed-guide",
        author="ivan",
        reader_level="beginner",
    )
    assert len(seen) == 10
    assert len(result["examples"]) == 1
    assert "mechanism" in result["examples"][0]["editorial_functions"]
    assert result["examples"][0]["reader_level"] == "beginner"
    assert (
        server.corpus_examples(
            paragraphs[-1], "hearthstone", "constructed-guide", author="ivan", reader_level="expert"
        )["examples"]
        == []
    )


def test_function_retrieval_can_find_example_without_lexical_overlap(monkeypatch):
    class Archive:
        idf = {}
        docs = [
            (
                "calm",
                CALM,
                {},
                {"game": "hearthstone", "genre": "constructed-guide", "author": "ivan"},
            )
        ]

        def search(self, query, top):
            return []

    monkeypatch.setattr(server, "_archive", lambda version: Archive())
    monkeypatch.setattr(server, "_document_hashes", lambda version: {})
    assert server.corpus_examples(
        "Потому что иначе действие недоступно.", "hearthstone", "constructed-guide", author="ivan"
    )["examples"]


def test_legacy_exemplar_fallback_keeps_game_genre_author_and_self_exclusion(monkeypatch):
    monkeypatch.setattr(server, "_archive", lambda version: None)
    monkeypatch.setattr(
        server, "_exemplars", lambda: {"profiles": {"global": [{"name": "sample", "text": CALM}]}}
    )
    assert server.style_examples("исходник", "news")[0] == []
    assert server.style_examples("исходник", "constructed-guide", author="other")[0] == []
    assert server.style_examples(CALM, "constructed-guide")[0] == []
