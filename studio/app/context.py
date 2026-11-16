"""Тела запросов к редактору и переводчику — так же, как `server/api.py:prepare_request`.

Логика повторена здесь, а не импортирована, чтобы образ Studio не тянул
транспортный сервер; эквивалентность закреплена тестом
`tests/test_context_parity.py` против оригинала.
"""

from __future__ import annotations

from manacost_context import ROOT, resolve_context

EDITOR_GENRES = ("game-guide", "game-article", "news")
EDIT_MODES = ("proofread", "edit", "rewrite")
ANALYZE = "/v1/editor/analyze"
EDIT = "/v1/editor/edit"
TRANSLATE = "/v1/translate/prepare"


class RequestError(ValueError):
    """Ошибка входных данных, понятная пользователю."""


def prepare_request(path: str, value: dict, default_game: str = "hearthstone") -> dict:
    if not isinstance(value, dict):
        raise RequestError("тело запроса должно быть JSON-объектом")
    allowed = {"game", "patch", "text", "genre", "product", "mode"}
    unknown = set(value) - allowed
    if unknown:
        raise RequestError("неизвестные поля: " + ", ".join(sorted(unknown)))
    text = value.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RequestError("текст пустой")
    game = value.get("game", default_game)
    if not isinstance(game, str):
        raise RequestError("игра должна быть строкой")
    if value.get("genre") is not None and not isinstance(value["genre"], str):
        raise RequestError("жанр должен быть строкой")
    patch = value.get("patch")
    try:
        context = resolve_context(ROOT, game=game, execution="server", patch=patch)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("unknown game"):
            raise RequestError(f"неизвестная игра: {game}") from exc
        if message.startswith("patch"):
            raise RequestError("патч должен быть непустой строкой") from exc
        raise RequestError(message) from exc
    result: dict = {"text": text, "task_context": context}
    if path == TRANSLATE:
        if value.get("genre") is not None or value.get("mode") is not None:
            raise RequestError("жанр и режим не применяются к переводу")
        if context["patch"] is None:
            raise RequestError("для перевода с контекстом нужен точный патч/билд")
        product = value.get("product")
        if context["game"]["id"] == "world-of-warcraft":
            if not isinstance(product, str) or not product.strip() or len(product) > 80:
                raise RequestError("для перевода WoW укажите продукт (до 80 символов)")
            result["product"] = product
        elif product is not None:
            raise RequestError("продукт указывается только для WoW")
        return result
    if value.get("product") is not None:
        raise RequestError("продукт указывается только для перевода WoW")
    genre = value.get("genre")
    if context["game"]["id"] not in ("hearthstone", "world-of-warcraft"):
        genre = genre or "game-guide"
        if genre not in EDITOR_GENRES:
            raise RequestError("для этой игры выберите game-guide, game-article или news")
    if genre:
        result["profile"] = genre
    if path == EDIT:
        mode = value.get("mode", "proofread")
        if mode not in EDIT_MODES:
            raise RequestError("режим правки: proofread, edit или rewrite")
        result["mode"] = mode
    elif value.get("mode") is not None:
        raise RequestError("режим применяется только к правке")
    return result
