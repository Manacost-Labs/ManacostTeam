"""Правила с scope=document срабатывают по плотности, а не по факту встречи.

Одно «, а не» в тексте — нормальный русский. Серия таких фраз — след шаблона.
Порог взят из корпуса автора (90-й процентиль), поэтому короткий текст с одной
фразой чистый, а тот же текст с пятью — нет.
"""

import markers

FILLER = "Колода добивает соперника к пятому ходу и хорошо держит темп. " * 30


def _ids(text):
    return {f["id"] for f in markers.scan(text, markers.load_patterns())}


def test_single_contrast_is_not_flagged():
    text = FILLER + "Колода выигрывает темпом, а не размером. " + FILLER
    assert "a-ne" not in _ids(text)


def test_series_of_contrasts_is_flagged():
    text = (
        FILLER
        + "Выигрывает темпом, а не размером. Играйте картой, а не планом. Ищите ход, а не хайп. "
        + FILLER
    )
    assert "a-ne" in _ids(text)


def test_hedge_verbs_flagged_only_when_dense():
    quiet = FILLER * 4 + "Это не доказывает силу колоды. " + FILLER * 4
    dense = (
        FILLER
        + "Это не доказывает силу. Пул не гарантирует карты. Аксессуар не заменяет план. "
        + FILLER
    )
    assert "ne-oznachaet" not in _ids(quiet)
    assert "ne-oznachaet" in _ids(dense)


def test_label_pattern_flagged_when_dense():
    dense = (
        FILLER
        + "Главная ошибка — играть рано. Главный риск — не найти Пирата. Основная слабость — темп. "
        + FILLER
    )
    assert "glavnaya-metka" in _ids(dense)
