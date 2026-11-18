"""Тесты детерминированного гейта ладдерных гайдов."""

from __future__ import annotations

import base64
import json

import pytest

from editorteam import ladder_mechanics_gate as gate
from editorteam.ladder_mechanics_gate import check_ladder_mechanics, decode_deckstring

CARDS = [
    {"id": "EX1_298", "dbfId": 2228, "name": "Рагнарос Повелитель Огня", "collectible": True,
     "type": "MINION", "set": "EXPERT1", "rarity": "LEGENDARY", "cardClass": "NEUTRAL",
     "cost": 8, "attack": 8, "health": 8, "text": "Не может атаковать."},
    {"id": "HERO_01bb", "dbfId": 90001, "name": "Рагнарос Повелитель Огня", "collectible": True,
     "type": "HERO", "set": "HERO_SKINS", "rarity": "FREE", "cardClass": "WARRIOR", "cost": 0},
    {"id": "CULT_01", "dbfId": 101, "name": "Неофитка культа", "collectible": True,
     "type": "MINION", "set": "CORE", "rarity": "COMMON", "cardClass": "WARLOCK",
     "cost": 2, "attack": 3, "health": 2, "mechanics": ["BATTLECRY"],
     "text": "<b>Боевой клич:</b> заклинания противника дороже."},
    {"id": "LOOT_01", "dbfId": 102, "name": "Лутоплут", "collectible": True,
     "type": "MINION", "set": "CORE", "rarity": "RARE", "cardClass": "NEUTRAL",
     "cost": 3, "attack": 2, "health": 3, "mechanics": ["DEATHRATTLE"],
     "text": "<b>Предсмертный хрип:</b> возьмите карту."},
    {"id": "HUNT_01", "dbfId": 103, "name": "Меткий выстрел", "collectible": True,
     "type": "SPELL", "set": "CORE", "rarity": "COMMON", "cardClass": "HUNTER", "cost": 3},
    {"id": "WARLOCK_HERO", "dbfId": 893, "name": "Гул'дан", "collectible": True,
     "type": "HERO", "set": "HERO_SKINS", "rarity": "FREE", "cardClass": "WARLOCK", "cost": 0},
]


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def encode_deck(cards: dict[int, int], *, fmt: int = 2, hero: int = 893) -> str:
    singles = [dbf for dbf, n in cards.items() if n == 1]
    doubles = [dbf for dbf, n in cards.items() if n == 2]
    many = [(dbf, n) for dbf, n in cards.items() if n > 2]
    raw = b"\x00" + _varint(1) + _varint(fmt) + _varint(1) + _varint(hero)
    raw += _varint(len(singles)) + b"".join(_varint(d) for d in singles)
    raw += _varint(len(doubles)) + b"".join(_varint(d) for d in doubles)
    raw += _varint(len(many)) + b"".join(_varint(d) + _varint(n) for d, n in many)
    return base64.b64encode(raw).decode()


def ids(text: str, **kwargs) -> list[tuple[str, str]]:
    return [(f["id"], f["severity"]) for f in check_ladder_mechanics(text, CARDS, **kwargs)]


class TestCardClaims:
    def test_cost_in_brackets_must_match(self) -> None:
        assert ids("Ставьте Неофитку культа (1) на первый ход.") == [("ladder.cost_mismatch", "error")]
        assert ids("Ставьте Неофитку культа (2) на второй ход.") == []

    def test_cost_words_before_and_after_name(self) -> None:
        assert ids("8-мановый Рагнарос Повелитель Огня закрывает игру.") == []
        assert ids("7-мановый Рагнарос Повелитель Огня закрывает игру.") == [("ladder.cost_mismatch", "error")]
        assert ids("Рагнарос Повелитель Огня стоит 7 маны.") == [("ladder.cost_mismatch", "warning")]
        # «За N маны» — розыгрыш, обычно со скидкой: не проверяем.
        assert ids("Разыграйте Лутоплута за 2 маны.") == []

    def test_single_word_name_does_not_match_a_longer_word(self) -> None:
        cards = CARDS + [{"id": "HUNT_02", "dbfId": 104, "name": "Охота", "collectible": True,
                          "type": "SPELL", "set": "CORE", "rarity": "COMMON",
                          "cardClass": "HUNTER", "cost": 1}]
        assert check_ladder_mechanics("Охотник (5) против Охоты (3).", cards)[0]["evidence"] == "Охоты (3)"

    def test_discount_in_sentence_is_not_an_error(self) -> None:
        assert ids("После скидки Рагнарос Повелитель Огня стоит 5 маны.") == []

    def test_brackets_in_deck_list_are_only_a_warning(self) -> None:
        assert ids("- Неофитка культа (1)") == [("ladder.cost_mismatch", "warning")]

    def test_stats_must_match_unless_buffed(self) -> None:
        assert ids("Неофитка культа 4/2 бьёт первой.") == [("ladder.stats_mismatch", "error")]
        assert ids("Неофитка культа (3/2) бьёт первой.") == []
        assert ids("Неофитка культа получает +1 и становится 4/2.") == []

    def test_keyword_must_exist_on_card(self) -> None:
        assert ids("Предсмертный хрип Лутоплута добирает карту.") == []
        assert ids("Боевой клич Неофитки культа дорожает чужие заклинания.") == []
        assert ids("Предсмертный хрип Неофитки культа добирает карту.") == [("ladder.keyword_mismatch", "error")]
        # Название в начальной форме — дополнение, а не владелец свойства.
        assert ids("Он активирует боевой клич Меткий выстрел и добор.") == []

    def test_two_copies_of_a_legendary(self) -> None:
        assert ids("Берите две копии Рагнароса Повелителя Огня.") == [("ladder.legendary_copies", "warning")]
        assert ids("Рагнарос Повелитель Огня x2 в списке.") == [("ladder.legendary_copies", "error")]
        assert ids("Берите две копии Неофитки культа.") == []

    def test_shortcode_tags_are_ignored(self) -> None:
        text = "[hs_card id=CULT_01]Неофитка культа[/hs_card] (1) на первый ход."
        assert ids(text) == [("ladder.cost_mismatch", "error")]


class TestDeckCodes:
    def test_decode_roundtrip(self) -> None:
        code = encode_deck({101: 2, 102: 1, 2228: 1}, fmt=1)
        deck = decode_deckstring(code)
        assert deck == {"format": "wild", "heroes": [893], "cards": {101: 2, 102: 1, 2228: 1}}

    def test_invalid_code_is_an_error(self) -> None:
        truncated = "AAECAf0GBMODB9vgB6D2B+35Bw3QngbTngbX"  # обрезанный настоящий код
        assert ("ladder.deckcode_invalid", "error") in ids(f"Код: {truncated}")

    def test_size_unknown_cards_and_legendary_copies(self) -> None:
        code = encode_deck({101: 2, 2228: 2, 999999: 1})
        found = ids(f"Стандарт. Код колоды: {code}")
        assert ("ladder.deck_size", "warning") in found
        assert ("ladder.deck_unknown_cards", "warning") in found
        assert ("ladder.legendary_copies", "error") in found

    def test_format_mismatch_with_text(self) -> None:
        code = encode_deck({101: 2, 102: 1}, fmt=1)
        assert ("ladder.deck_format_mismatch", "warning") in ids(f"Колода для Стандарта.\n\n{code}")
        assert ("ladder.deck_format_mismatch", "warning") not in ids(f"Колода для Вольного.\n\n{code}")

    def test_mulligan_cards_must_be_in_the_deck(self) -> None:
        code = encode_deck({101: 2, 102: 2})
        text = (
            f"Код: {code}\n\n## Мулиган\n\nОставляйте Неофитку культа и Рагнароса Повелителя Огня. "
            "Против Меткого выстрела не спешите.\n\n## Поздняя игра\n\nРагнарос Повелитель Огня не нужен."
        )
        found = [f for f in check_ladder_mechanics(text, CARDS) if f["id"] == "ladder.mulligan_not_in_deck"]
        assert [f["evidence"] for f in found] == ["Рагнароса Повелителя Огня"]

    def test_deckcode_argument_is_checked(self) -> None:
        code = encode_deck({2228: 2})
        assert ("ladder.legendary_copies", "error") in ids("Гайд без кода в тексте.", deck_codes=[code])


def test_hero_skin_name_does_not_hide_legendary() -> None:
    index = gate.build_index(CARDS)
    assert [c["id"] for c in index.by_name["Рагнарос Повелитель Огня"]] == ["EX1_298"]


def test_cli_exit_code_and_json(tmp_path, capsys) -> None:
    article = tmp_path / "guide.md"
    article.write_text("Рагнарос Повелитель Огня (7) закрывает игру.", encoding="utf-8")
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(CARDS, ensure_ascii=False), encoding="utf-8")
    assert gate.main([str(article), "--cards", str(cards)]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed[0]["id"] == "ladder.cost_mismatch"
    article.write_text("Рагнарос Повелитель Огня (8) закрывает игру.", encoding="utf-8")
    assert gate.main([str(article), "--cards", str(cards)]) == 0


@pytest.mark.parametrize("bad", ["", "not json"])
def test_load_cards_rejects_non_list(tmp_path, bad) -> None:
    path = tmp_path / "cards.json"
    path.write_text(json.dumps({"cards": []}) if not bad else bad, encoding="utf-8")
    with pytest.raises(ValueError):
        gate.load_cards(path)
