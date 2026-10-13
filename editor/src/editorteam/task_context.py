"""Adapt the common metadata envelope to the existing editor game/genre API."""

from __future__ import annotations

import sys
from pathlib import Path

from editorteam import games, profiles


def adapt_editor_request(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("request must be a JSON object")
    if "task_context" not in data:
        return dict(data)
    # The portable skill supplies this module on PYTHONPATH; source/Docker use shared/.
    try:
        from manacost_context import validate_context
    except ModuleNotFoundError:
        for parent in Path(__file__).resolve().parents[2:4]:
            if (parent / "shared/manacost_context.py").is_file():
                sys.path.insert(0, str(parent / "shared"))
                break
        from manacost_context import validate_context

    context = validate_context(data["task_context"])
    if context["profile"]["id"] != "manacost":
        raise ValueError(
            "editor task_context currently supports only the manacost editorial profile"
        )
    canonical = context["game"]["id"]
    legacy_game = "wow" if canonical == "world-of-warcraft" else canonical
    if data.get("game") not in (None, "", canonical, legacy_game):
        raise ValueError("game conflicts with task_context.game")
    game = games.load(legacy_game)
    genre = data.get("profile") or game.profiles[0]
    if genre not in game.profiles:
        raise ValueError("genre profile is not supported by task_context.game")
    profiles.load(genre)
    patch = data.get("current_patch") or None
    if patch is not None and patch != context["patch"]:
        raise ValueError("current_patch conflicts with task_context.patch")
    return {
        **data,
        "game": legacy_game,
        "profile": genre,
        "current_patch": context["patch"],
        "task_context": context,
    }
