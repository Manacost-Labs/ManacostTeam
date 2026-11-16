"""Шорткоды карт в процессе: `editorteam.card_shortcodes.apply_shortcodes`.

Только точные имена каталога выбранного режима; контекстные mentions
(падежи, сокращения) Studio не угадывает — это работа навыка card-shortcodes.
"""

from __future__ import annotations

import threading
from pathlib import Path

from editorteam.card_shortcodes import apply_shortcodes
from editorteam.wordpress import Card, ExportError, load_catalog, parse_format

FORMAT_TITLES = {
    "standard": "Стандарт",
    "wild": "Вольный",
    "arena": "Арена",
    "battlegrounds": "Поля сражений",
}


class CatalogUnavailable(Exception):
    pass


class CatalogStore:
    """Каталог читается с диска и перечитывается, когда файл меняется."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._cached: tuple[float, int, tuple[Card, ...]] | None = None

    def load(self) -> tuple[Card, ...]:
        if not self.path:
            raise CatalogUnavailable(
                "Каталог карт не подключён: задайте CARD_CATALOG_FILE — JSON вида "
                '{"cards": [{"name": "…", "id": "…", "formats": ["standard"]}]} '
                "с подтверждёнными card ID."
            )
        file = Path(self.path)
        try:
            stat = file.stat()
        except OSError as exc:
            raise CatalogUnavailable("Файл каталога карт из CARD_CATALOG_FILE не найден.") from exc
        with self._lock:
            if self._cached and self._cached[:2] == (stat.st_mtime, stat.st_size):
                return self._cached[2]
            try:
                cards = load_catalog(file)
            except ExportError as exc:
                raise CatalogUnavailable(f"Каталог карт некорректен: {exc}") from exc
            if not cards:
                raise CatalogUnavailable("Каталог карт пуст.")
            self._cached = (stat.st_mtime, stat.st_size, cards)
            return cards

    def available(self) -> bool:
        try:
            self.load()
        except CatalogUnavailable:
            return False
        return True


def run(store: CatalogStore, text: str, game_format: str) -> dict:
    selected = parse_format(game_format)  # ExportError → 400 у вызывающего
    result = apply_shortcodes(text, catalog=store.load(), game_format=selected)
    return {
        "text": result.text,
        "inserted": result.inserted,
        "review": list(result.review),
        "format": selected.value,
        "format_title": FORMAT_TITLES[selected.value],
    }
