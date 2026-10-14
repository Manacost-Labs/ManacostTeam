import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from editorteam.task_context import adapt_editor_request

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools"))
from resolve_context import resolve_context  # noqa: E402


def context(game="world-of-warcraft"):
    return resolve_context(REPO, game=game, profile="manacost", patch="fixture-build")


def test_legacy_request_keeps_its_existing_fields_and_defaults():
    request = {"text": "Пример", "game": "wow", "profile": "news"}
    assert adapt_editor_request(request) == request
    assert adapt_editor_request({"text": "Пример"}) == {"text": "Пример"}


def test_shared_context_selects_wow_genre_without_using_editorial_profile_as_genre():
    result = adapt_editor_request({"task_context": context()})
    assert result["game"] == "wow"
    assert result["profile"] == "wow-guide"
    assert result["current_patch"] == "fixture-build"
    assert result["task_context"]["profile"]["id"] == "manacost"


def test_shared_context_accepts_legacy_alias_and_compatible_explicit_genre():
    result = adapt_editor_request({"task_context": context(), "game": "wow", "profile": "news"})
    assert result["profile"] == "news"


@pytest.mark.parametrize(
    "game", ["league-of-legends", "deadlock", "overwatch", "heroes-of-the-storm"]
)
def test_other_games_use_common_genre_and_keep_manacost_voice(game, sidecar):
    status, rules = sidecar("/rules", {"task_context": context(game), "depth": "переплавка"})
    assert status == 200
    assert rules["profile"] == "game-guide"
    assert rules["author_profile"] == "manacost"
    assert rules["style_rules"]
    assert rules["replace"] == []
    assert "архетип" not in rules["voice_signature"].lower()
    assert "style_examples" not in rules
    assert "archetype_hyphen" not in rules["typography"]
    assert "mana" not in rules["typography"]["numbers"]


def test_other_game_cannot_use_hearthstone_genre():
    with pytest.raises(ValueError):
        adapt_editor_request(
            {"task_context": context("league-of-legends"), "profile": "constructed-guide"}
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"game": "hearthstone"},
        {"profile": "constructed-guide"},
        {"current_patch": "different"},
        {"game": []},
    ],
)
def test_conflicting_context_is_rejected_before_work(extra):
    with pytest.raises(ValueError):
        adapt_editor_request({"task_context": context(), **extra})


def test_unimplemented_editorial_profile_is_explicitly_rejected():
    neutral = resolve_context(REPO, game="hearthstone", profile="neutral")
    with pytest.raises(ValueError, match="manacost"):
        adapt_editor_request({"task_context": neutral})


def test_cli_selects_wow_context_and_preserves_numbers(tmp_path, capsys):
    from editorteam.cli import main

    source = tmp_path / "before.md"
    result = tmp_path / "after.md"
    metadata = tmp_path / "context.json"
    source.write_text("Способность усиливает урон на 20%.", encoding="utf-8")
    result.write_text("Способность усиливает урон на 30%.", encoding="utf-8")
    metadata.write_text(json.dumps(context()), encoding="utf-8")
    assert (
        main(
            [
                "validate-edit",
                str(source),
                str(result),
                "--task-context",
                str(metadata),
                "--format",
                "json",
            ]
        )
        != 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["task_context"]["game"]["id"] == "world-of-warcraft"
    assert output["accepted"] is False


@pytest.fixture
def sidecar():
    from editorteam.server import Handler

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(path, payload):
        request = Request(
            f"http://127.0.0.1:{server.server_port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    yield post
    server.shutdown()
    thread.join(timeout=10)
    server.server_close()


def test_http_context_routes_apply_game_and_preserve_legacy_rules(sidecar):
    status, wow = sidecar("/rules", {"task_context": context()})
    assert status == 200
    assert wow["game"] == "wow"
    assert wow["profile"] == "wow-guide"
    assert wow["replace"] == []
    assert wow["task_context"]["game"]["id"] == "world-of-warcraft"
    status, legacy = sidecar("/rules", {"game": "hearthstone"})
    status, shared = sidecar("/rules", {"task_context": context("hearthstone")})
    assert status == 200
    shared.pop("task_context")
    shared.pop("author_profile")
    shared.pop("style_rules")
    assert shared == legacy


def test_wow_protects_own_terms_without_hearthstone_terms():
    from editorteam.server import _scripts

    report = _scripts().sibling("report")
    lost = report.protected_lost("возвещение ГКД 20", "20", game="wow", protected=["ГКД"])
    assert "возвещение" not in lost
    assert "ГКД" in lost


def test_rewrite_for_other_game_skips_hearthstone_terms_and_lexicon():
    from editorteam.server import _scripts

    gate = _scripts().sibling("rewrite_gate")
    text = "# Что делать\n\nВ этом режиме дека не нужна. Подарки племени повышают урон на 20%."
    _, _, metrics = gate.analyze(text, profile="game-guide", game="deadlock")
    assert metrics["terminology_hits"] == 0
    assert "lexicon" not in metrics


def test_http_rejects_context_conflict_and_invalid_shape(sidecar):
    for payload in ({"task_context": None}, {"task_context": context(), "game": "hearthstone"}, []):
        status, result = sidecar("/context/resolve", payload)
        assert status == 400
        assert "task_context" not in result


def test_cli_context_audit_uses_wow_checks_and_rejects_unsupported_flags(tmp_path, capsys):
    from editorteam.cli import main

    source, metadata = tmp_path / "article.md", tmp_path / "context.json"
    source.write_text("Способность повышает урон на 20%.", encoding="utf-8")
    metadata.write_text(json.dumps(context()), encoding="utf-8")
    arguments = ["audit", str(source), "--task-context", str(metadata), "--format", "json"]
    main(arguments)
    result = json.loads(capsys.readouterr().out)
    assert result["game"] == "wow"
    assert result["profile"] == "wow-guide"
    assert "cards" in result["analyzers_skipped"]
    with pytest.raises(SystemExit) as error:
        main([*arguments, "--deep"])
    assert error.value.code == 2
