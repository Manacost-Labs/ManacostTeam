"""Тела запросов Studio совпадают с `server/api.py:prepare_request`."""

from __future__ import annotations

import importlib.util

import pytest

from app.context import ANALYZE, EDIT, TRANSLATE, RequestError, prepare_request
from conftest import REPO

spec = importlib.util.spec_from_file_location("manacost_server_api", REPO / "server" / "api.py")
server_api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_api)

CASES = [
    (ANALYZE, {"text": "т"}),
    (ANALYZE, {"text": "т", "game": "hearthstone", "genre": "battlegrounds-guide", "patch": "32.4"}),
    (ANALYZE, {"text": "т", "game": "overwatch"}),
    (EDIT, {"text": "т"}),
    (EDIT, {"text": "т", "game": "world-of-warcraft", "genre": "wow-guide", "mode": "rewrite"}),
    (EDIT, {"text": "т", "game": "deadlock", "genre": "news", "mode": "edit", "patch": "1"}),
    (TRANSLATE, {"text": "t", "game": "hearthstone", "patch": "32.4.0.1"}),
    (TRANSLATE, {"text": "t", "game": "world-of-warcraft", "patch": "11.2", "product": "retail"}),
]


@pytest.mark.parametrize(("path", "value"), CASES)
def test_bodies_match_server_api(path, value):
    assert prepare_request(path, dict(value)) == server_api.prepare_request(path, dict(value), "hearthstone")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (ANALYZE, {"text": " "}),
        (ANALYZE, {"text": "т", "game": "dota"}),
        (ANALYZE, {"text": "т", "mode": "edit"}),
        (EDIT, {"text": "т", "mode": "polish"}),
        (EDIT, {"text": "т", "game": "overwatch", "genre": "meta-report"}),
        (TRANSLATE, {"text": "t"}),
        (TRANSLATE, {"text": "t", "game": "world-of-warcraft", "patch": "1"}),
    ],
)
def test_invalid_inputs_rejected_by_both(path, value):
    with pytest.raises(RequestError):
        prepare_request(path, dict(value))
    with pytest.raises(ValueError):
        server_api.prepare_request(path, dict(value), "hearthstone")
