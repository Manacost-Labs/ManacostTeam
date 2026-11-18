"""Тесты доменного чекера БГ, досье карт и симулятора 1-го хода."""

from __future__ import annotations

import json
import os
import random
from functools import lru_cache
from pathlib import Path

import pytest

from editorteam import bg_dossier, bg_mechanics_gate, bg_sim
from editorteam.bg_mechanics_gate import check_bg_mechanics


def codes(text: str, **kwargs) -> list[str]:
    return [f["id"] for f in check_bg_mechanics(text, **kwargs)]


# ---------------------------------------------------------------- gate


class TestForbiddenTribeWord:
    @pytest.mark.parametrize(
        "phrase",
        [
            "Демоны — лучшее племя для старта.",
            "Без этого племени таверна пустеет.",
            "Все племена получают бафф.",
            "Пять племён в лобби.",
            "Игра племенем.",
            "Помогает разным племенам.",
            "Играть племенами сложно.",
            "О племенах поговорим ниже.",
        ],
    )
    def test_every_form_is_error(self, phrase):
        found = check_bg_mechanics(phrase)
        assert [f["id"] for f in found] == ["bg.forbidden_tribe_word"]
        assert found[0]["severity"] == "error"
        assert found[0]["suggestion"] == "тип существ"

    def test_direct_quote_is_ignored(self):
        assert codes("Игроки до сих пор пишут «племя», но мы так не говорим.") == []
        assert codes("> Это племя сильнее всех.\n\nМы не согласны.") == []

    def test_type_wording_is_clean(self):
        assert codes("Этот тип существ силён на старте.") == []


class TestLobbyTautology:
    def test_today_phrase_single_type_demon(self):
        found = check_bg_mechanics("Заклинатель гнева хорош только в лобби с демонами.")
        assert [f["id"] for f in found] == ["bg.lobby_tautology"]
        assert found[0]["meta"]["card"] == "Заклинатель гнева"

    def test_exception_phrase_under_heading(self):
        text = "### Заклинатель гнева\n\nИсключение — лобби с демонами, там его берут всегда."
        assert codes(text) == ["bg.lobby_tautology"]

    @pytest.mark.parametrize(
        "phrase",
        [
            "Иглошкура-геоманта стоит брать в лобби со свинобразами.",
            "Порхающий нетопырь силён в лобби со зверями.",
            "Пузырькового стрелка берите только в лобби с мурлоками.",
            "Бликостраж хорош в лобби с драконами.",
            "Зоатроид играет только в лобби с аберрациями.",
            "Баюбот хорош в лобби с механизмами.",
        ],
    )
    def test_builtin_tier1_minions(self, phrase):
        assert codes(phrase) == ["bg.lobby_tautology"]

    def test_dual_type_seer_is_not_error(self):
        assert codes("Зловещая пророчица хороша в лобби с нагами.") == []
        assert codes("Зловещая пророчица сильна в лобби с демонами и нагами.") == []

    def test_neutral_and_foreign_type_are_not_error(self):
        assert codes("Подозрительный надзиратель хорош в лобби с демонами.") == []
        assert codes("Заклинатель гнева сильнее в лобби без механизмов.") == []

    def test_dossier_card_is_used(self):
        dossier = {"cards": [{"name_ru": "Тестовый мурлок", "type": "MINION", "races": ["MURLOC"], "techLevel": 3}]}
        assert codes("Тестовый мурлок хорош в лобби с мурлоками.", dossier=dossier) == ["bg.lobby_tautology"]
        assert codes("Тестовый мурлок хорош в лобби с мурлоками.") == []


class TestBattlecryInHand:
    def test_today_phrase(self):
        found = check_bg_mechanics("Мурлоки собирают удачных Стрелков в руке до розыгрыша.")
        assert [f["id"] for f in found] == ["bg.battlecry_in_hand"]

    def test_already_keyworded_in_hand(self):
        assert codes("Держите в руке уже получивших свойство стрелков.") == ["bg.battlecry_in_hand"]

    def test_corrected_phrase(self):
        text = "Разыграйте Стрелка сразу: свойство он получает при розыгрыше, неудачного продайте."
        assert codes(text) == []


class TestTurn2Curve:
    def test_tier2_minion_on_turn2(self):
        assert codes("Если найдете на 2-м ходу Дирижера душ, берите его.") == ["bg.turn2_curve"]

    def test_spell_on_turn2_with_seer(self):
        text = "Разыграйте Пророчицу на 1-м ходу и купите на 2-м ходу заклинание."
        assert codes(text) == ["bg.turn2_curve"]

    def test_extra_gold_turns_2_4(self):
        assert codes("С лишним золотом на 2–4-м ходу можно чаще обновлять таверну.") == ["bg.turn2_curve"]
        assert codes("Лишний золотой на 2-м ходу решает.") == ["bg.turn2_curve"]

    def test_economy_source_in_paragraph_allows_it(self):
        text = (
            "Музыкант Южных Морей на 1-м ходу дает лишний золотой на 2-м ходу, "
            "и тогда можно найти на 2-м ходу Дирижера душ."
        )
        assert codes(text) == []
        assert codes("Монетка таверны на 1-м ходу, и на 2-м ходу купите заклинание.") == []

    def test_plain_turn2_buy_is_fine(self):
        assert codes("На 2-м ходу купите второе существо 1-го уровня.") == []


class TestTokenZone:
    def test_today_phrase(self):
        text = "Продайте Зоатроида — щупальце останется на столе и прикроет героя."
        assert codes(text) == ["bg.token_zone_mismatch"]

    def test_summon_wording(self):
        assert codes("Зоатроид при продаже призывает на стол щупальце 0/2.") == ["bg.token_zone_mismatch"]

    def test_corrected(self):
        assert codes("Продайте Зоатроида — щупальце 0/2 с Провокацией придет в руку.") == []


class TestFalseFreeGold:
    def test_today_phrase(self):
        text = "Затаившаяся лев-рыба и Порхающий нетопырь дают бесплатное золото с продажи."
        assert codes(text) == ["bg.false_free_gold"]

    def test_corrected_mentions_real_cost(self):
        text = (
            "Затаившаяся лев-рыба за 2 золотых меняет карту на наживку, "
            "а нетопырь, уничтоживший ее, получает +5/+5."
        )
        assert codes(text) == []

    def test_free_gold_without_lionfish_context(self):
        assert codes("Монетка таверны — это бесплатное золото.") == []


class TestUnlinkedPoolSpell:
    def test_warning_when_other_shortcodes_present(self):
        text = '[hs_bg id="BG28_810"]Монетка таверны[/hs_bg] и Банан в меню на 1-м ходу.'
        found = check_bg_mechanics(text)
        assert [f["id"] for f in found] == ["bg.unlinked_pool_spell"]
        assert found[0]["severity"] == "warning"
        assert found[0]["meta"]["card_id"] == "BG28_897"

    @pytest.mark.parametrize(
        "name,card_id",
        [
            ("Монетку таверны", "BG28_810"),
            ("Банан в меню", "BG28_897"),
            ("Флаг Альянса", "BG31_880"),
            ("Укрепление", "BG28_503"),
            ("Лови яблочко", "BG28_966"),
            ("Зачарованное лассо", "BG28_512"),
            ("Вербовку новобранца", "BG28_504"),
        ],
    )
    def test_all_spells_with_expect(self, name, card_id):
        found = check_bg_mechanics(f"Возьмите {name}.", expect_shortcodes=True)
        assert [(f["id"], f["meta"]["card_id"]) for f in found] == [("bg.unlinked_pool_spell", card_id)]

    def test_no_warning_without_expectation(self):
        assert codes("Банан в меню на 1-м ходу.") == []
        assert codes("Банан в меню на 1-м ходу.", expect_shortcodes=False) == []

    def test_warning_does_not_fail_cli(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("Банан в меню.", encoding="utf-8")
        assert bg_mechanics_gate.main([str(path), "--expect-shortcodes"]) == 0


def test_corrected_article_is_clean():
    text = """# Тир-1 существа Полей сражений

### Заклинатель гнева

Заклинатель гнева — демон 1-го уровня. Его берут, когда рядом есть другие демоны.

### Зловещая пророчица

Зловещая пророчица — демон и нага сразу, поэтому она чаще встречается в лобби с нагами.

### Пузырьковый стрелок

Разыграйте Стрелка сразу: свойство он получает при розыгрыше. Этот тип существ любит Провокацию.

### Зоатроид

Продайте Зоатроида — щупальце 0/2 с Провокацией придет в руку.

### Затаившаяся лев-рыба

Лев-рыба за 2 золотых меняет карту на наживку, и нетопырь получает +5/+5.

На 2-м ходу купите второе существо 1-го уровня.
"""
    assert check_bg_mechanics(text) == []


def test_cli_exit_code_on_error(tmp_path, capsys):
    path = tmp_path / "bad.md"
    path.write_text("Демоны — лучшее племя.", encoding="utf-8")
    assert bg_mechanics_gate.main([str(path)]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed[0]["id"] == "bg.forbidden_tribe_word"
    assert printed[0]["line"] == 1


def test_finding_offsets_point_to_evidence():
    text = "Первая строка.\n\nДемоны — лучшее племя."
    finding = check_bg_mechanics(text)[0]
    assert text[finding["start"]:finding["end"]] == "племя"
    assert finding["line"] == 3


# ---------------------------------------------------------------- dossier


def _minion(card_id, dbf, name, atk, hp, races, tier=1, text="", pool=True, **extra):
    card = {"id": card_id, "dbfId": dbf, "name": name, "type": "MINION", "attack": atk,
            "health": hp, "races": races, "techLevel": tier, "cost": 0, "text": text,
            "set": "BATTLEGROUNDS"}
    if pool:
        card["isBattlegroundsPoolMinion"] = True
    card.update(extra)
    return card


def _spell(card_id, dbf, name, text, tier=1):
    return {"id": card_id, "dbfId": dbf, "name": name, "type": "BATTLEGROUND_SPELL",
            "techLevel": tier, "cost": 1, "text": text, "isBattlegroundsPoolSpell": True,
            "set": "BATTLEGROUNDS"}


RU = [
    _minion("BG31_149", 1, "Пузырьковый стрелок", 2, 3, ["MURLOC"],
            text="[x]<b>Боевой клич:</b>\nполучает случайное\n <b>бонусное свойство</b>.",
            battlegroundsPremiumDbfId=2),
    _minion("BG31_149_G", 2, "Пузырьковый стрелок", 4, 6, ["MURLOC"], pool=False,
            text="<b>Боевой клич:</b> получает 2 случайных <b>бонусных свойства</b>."),
    _minion("BG36_200", 3, "Порхающий нетопырь", 1, 4, ["BEAST"], text="<b>Боевой раж:</b> призывает зверя 1/1."),
    _minion("BG36_200t", 4, "Нетопырь-добытчик", 1, 1, ["BEAST"], pool=False),
    _minion("BG36_200_G", 5, "Порхающий нетопырь", 2, 8, ["BEAST"], pool=False),
    _minion("BG36_200_Gt", 6, "Нетопырь-добытчик", 2, 2, ["BEAST"], pool=False),
    {"id": "BG36_200te", "dbfId": 7, "name": "Чары", "type": "ENCHANTMENT", "text": ""},
    _minion("BG36_201", 8, "Затаившаяся лев-рыба", 2, 3, ["BEAST"], tier=2,
            text="<b>Активация (2):</b> выберите карту в таверне, чтобы заменить ее на наживку."),
    _minion("BG36_205", 9, "Наживка", 0, 1, ["BEAST"], tier=2, pool=False,
            text="[x]<i>Не может получать характеристики</i>.\n<b>Предсмертный хрип:</b>\n"
                 "уничтожившее наживку\nсущество получает +5/+5."),
    _minion("BG36_205_G", 10, "Наживка", 0, 2, ["BEAST"], tier=2, pool=False,
            text="<b>Предсмертный хрип:</b> уничтожившее наживку существо получает +10/+10."),
    _minion("BG36_098", 11, "Зоатроид", 3, 2, ["ABERRATION"],
            text="Когда вы продаете это существо, вы получаете щупальце 0/2 с <b>«Провокацией»</b>."),
    _minion("BGFYM_002t", 12, "Чудовищное щупальце", 0, 2, ["ABERRATION"], pool=False, text="<b>Провокация</b>"),
    _minion("BG20_100", 13, "Иглошкур-геомант", 2, 1, ["QUILBOAR"],
            text="<b>Боевой клич:</b> вы получаете 2 <b>кровавых самоцвета</b>."),
    {"id": "BG20_GEM", "dbfId": 14, "name": "Кровавый самоцвет", "type": "SPELL", "text": "Существо получает +1/+1."},
    _minion("BGS_004", 15, "Заклинатель гнева", 1, 3, ["DEMON"], battlegroundsPremiumDbfId=16,
            text="Когда вы разыгрываете демона, наносит 1 ед. урона вашему герою и получает +2/+2."),
    _minion("TB_BaconUps_079", 16, "Заклинатель гнева", 2, 6, ["DEMON"], pool=False,
            text="Когда вы разыгрываете демона, дважды наносит 1 ед. урона вашему герою."),
    _minion("BG26_174", 17, "Дирижер душ", 4, 2, ["DEMON"], tier=2,
            text="После того как ваш герой\n получает урон, этот урон\n отменяется."),
    _minion("BG32_873", 18, "Пепельный осквернитель", 4, 8, ["DEMON"], tier=4,
            text="После того как ваш герой получает урон, этот урон отменяется."),
    _minion("BG99_999", 19, "Далекий демон", 9, 9, ["DEMON"], tier=6,
            text="После того как ваш герой получает урон, этот урон отменяется."),
    _minion("BG31_330", 20, "Зловещая пророчица", 2, 1, ["DEMON", "NAGA"],
            text="<b>Боевой клич:</b> следующее заклинание таверны стоит на (1) меньше."),
    _minion("BG36_345", 21, "Подозрительный надзиратель", 3, 3, []),
    _spell("BG28_810", 22, "Монетка таверны", "Вы получаете 1 золотой."),
    _spell("BG28_897", 23, "Банан в меню", "Существо получает +2/+2."),
    _spell("BG31_880", 24, "Флаг Альянса", "<b>Выберите эффект:</b>\nсущество получает +3/+1 или +1/+3."),
    _spell("BG28_503", 25, "Укрепление", "Существо получает +3 к здоровью и <b>«Провокацию»</b>."),
    _spell("BG28_518", 26, "Выбор шеф-повара", "…", tier=2),
]
EN = [
    {"id": "BG31_149", "name": "Bubble Gunner", "text": "<b>Battlecry:</b> Gain a random <b>Bonus Keyword</b>."},
    {"id": "BG36_200", "name": "Flittering Bat", "text": "<b>Rally:</b> Summon a 1/1 Beast."},
    {"id": "BG36_201", "name": "Lurking Lionfish", "text": "<b>Activate (2):</b> Replace a card with Fishbait."},
    {"id": "BG36_205", "name": "Fishbait", "text": "<b>Deathrattle:</b> The minion that destroyed this gets +5/+5."},
    {"id": "BG36_098", "name": "Zoatroid", "text": "When you sell this, get a 0/2 Tentacle with <b>Taunt</b>."},
    {"id": "BGFYM_002t", "name": "Monstrous Tentacle", "text": "<b>Taunt</b>"},
    {"id": "BGS_004", "name": "Wrath Weaver", "text": "After you play a Demon, deal 1 damage to your hero."},
    {"id": "BG28_810", "name": "Tavern Coin", "text": "Gain 1 Gold."},
]


def dossier(**kwargs):
    return bg_dossier.build_dossier(RU, EN, **kwargs)


def entry(card_id, **kwargs):
    result = dossier(ids=[card_id], **kwargs)
    assert result["missing"] == []
    return result["cards"][0]


class TestDossier:
    def test_base_fields_and_clean_text(self):
        gunner = entry("BG31_149")
        assert gunner["name_ru"] == "Пузырьковый стрелок"
        assert gunner["name_en"] == "Bubble Gunner"
        assert (gunner["attack"], gunner["health"], gunner["techLevel"]) == (2, 3, 1)
        assert gunner["types_ru"] == ["Мурлоки"]
        assert gunner["is_pool_minion"] is True and gunner["is_pool_spell"] is False
        assert gunner["text_ru"] == "Боевой клич: получает случайное бонусное свойство."
        assert "<" not in gunner["text_en"]
        assert gunner["golden"]["id"] == "BG31_149_G"

    def test_bonus_keyword_pool(self):
        pool = entry("BG31_149")["bonus_keywords_pool_ru"]
        assert pool == ["Божественный щит", "Перерождение", "Провокация",
                        "Неистовство ветра", "Токсичность", "Маскировка"]
        assert "bonus_keywords_pool_ru" not in entry("BG36_200")

    def test_prefix_tokens_skip_enchantments(self):
        tokens = {t["id"]: t for t in entry("BG36_200")["related_tokens"]}
        assert set(tokens) == {"BG36_200t", "BG36_200_Gt"}
        assert (tokens["BG36_200t"]["attack"], tokens["BG36_200t"]["health"]) == (1, 1)
        assert tokens["BG36_200t"]["name_ru"] == "Нетопырь-добытчик"

    def test_fishbait_expanded(self):
        tokens = {t["id"]: t for t in entry("BG36_201")["related_tokens"]}
        assert {"BG36_205", "BG36_205_G"} <= set(tokens)
        bait = tokens["BG36_205"]
        assert (bait["attack"], bait["health"]) == (0, 1)
        assert "+5/+5" in bait["text_ru"]
        assert "+10/+10" in tokens["BG36_205_G"]["text_ru"]

    def test_tentacle_expanded(self):
        tokens = {t["id"]: t for t in entry("BG36_098")["related_tokens"]}
        tentacle = tokens["BGFYM_002t"]
        assert (tentacle["attack"], tentacle["health"]) == (0, 2)
        assert tentacle["types_ru"] == ["Аберрации"]
        assert tentacle["text_ru"] == "Провокация"
        assert "в руку" in tentacle["note_ru"]

    def test_blood_gem_expanded(self):
        tokens = {t["id"] for t in entry("BG20_100")["related_tokens"]}
        assert "BG20_GEM" in tokens

    def test_builtin_token_when_snapshot_lacks_it(self):
        ru = [c for c in RU if not c["id"].startswith("BG36_205")]
        en = [c for c in EN if not c["id"].startswith("BG36_205")]
        card = bg_dossier.build_dossier(ru, en, ids=["BG36_201"])["cards"][0]
        bait = next(t for t in card["related_tokens"] if t["id"] == "BG36_205")
        assert bait["source"] == "builtin" and (bait["attack"], bait["health"]) == (0, 1)

    def test_golden_via_premium_dbf(self):
        assert entry("BGS_004")["golden"]["id"] == "TB_BaconUps_079"

    def test_synergy_neighbors_for_wrath_weaver(self):
        neighbors = entry("BGS_004", include_synergy_neighbors=True)["synergy_neighbors"]
        ids = [n["id"] for n in neighbors]
        assert ids == ["BG26_174", "BG32_873"]  # тир-6 за пределом соседства
        assert all(n["types_ru"] == ["Демоны"] for n in neighbors)

    def test_tier_filter_and_spells(self):
        result = dossier(tiers=[1])
        ids = {c["id"] for c in result["cards"]}
        assert {"BG31_149", "BG36_200", "BG36_098", "BG31_330", "BG36_345"} <= ids
        assert not ids & {"BG36_201", "BG36_200t", "BG28_810"}
        with_spells = {c["id"] for c in dossier(tiers=[1], include_spells=True)["cards"]}
        assert {"BG28_810", "BG28_897", "BG31_880", "BG28_503"} <= with_spells
        assert "BG28_518" not in with_spells

    def test_types_ru_dual_and_neutral(self):
        assert entry("BG31_330")["types_ru"] == ["Демоны", "Наги"]
        assert entry("BG36_345")["types_ru"] == ["Нейтральное"]

    def test_names_filter_and_missing(self):
        result = dossier(names=["Wrath Weaver", "зоатроид"], ids=["NOPE_1"])
        assert [c["id"] for c in result["cards"]] == ["BGS_004", "BG36_098"]
        assert result["missing"] == ["NOPE_1"]

    def test_never_uses_tribe_word(self):
        dumped = json.dumps(dossier(tiers=[1, 2], include_spells=True, include_synergy_neighbors=True),
                            ensure_ascii=False).lower()
        assert "племя" not in dumped and "плем" not in dumped

    def test_shortcode_catalog(self):
        catalog = bg_dossier.build_shortcode_catalog(RU, EN)
        by_id = {c["id"]: c for c in catalog}
        for spell_id in ("BG28_810", "BG28_897", "BG31_880", "BG28_503"):
            assert by_id[spell_id]["formats"] == ["battlegrounds"]
        assert by_id["BG28_810"] == {"id": "BG28_810", "name": "Монетка таверны", "formats": ["battlegrounds"]}
        assert "BG31_149" in by_id and "BG31_149_G" not in by_id and "BG36_200t" not in by_id
        names = [c["name"] for c in catalog]
        assert len(names) == len(set(names))

    def test_shortcode_catalog_is_valid_for_wordpress(self):
        from editorteam.wordpress import Card, HearthstoneFormat, _validated_catalog

        cards = [Card(c["name"], c["id"], frozenset({HearthstoneFormat.BATTLEGROUNDS}))
                 for c in bg_dossier.build_shortcode_catalog(RU)]
        assert _validated_catalog(cards)

    def test_cli(self, tmp_path, capsys):
        ru, en = tmp_path / "ru.json", tmp_path / "en.json"
        ru.write_text(json.dumps(RU, ensure_ascii=False), encoding="utf-8")
        en.write_text(json.dumps(EN, ensure_ascii=False), encoding="utf-8")
        assert bg_dossier.main(["--ru", str(ru), "--en", str(en), "--ids", "BG36_098"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["cards"][0]["related_tokens"][0]["id"] == "BGFYM_002t"
        assert bg_dossier.main(["--ru", str(ru), "--shortcode-catalog"]) == 0
        assert any(c["id"] == "BG28_810" for c in json.loads(capsys.readouterr().out))


REPO = Path(__file__).resolve().parents[2]
LOCAL_RU = Path(os.environ.get("BG_HSJSON_RU", REPO / "build/deck-guide-pilot/raza-dh-2026-11-10/cards-ruRU.json"))
LOCAL_EN = Path(os.environ.get("BG_HSJSON_EN", REPO / "build/deck-guide-pilot/raza-dh-2026-11-10/cards-enUS.json"))


@lru_cache(maxsize=1)
def _local_snapshot():
    return bg_dossier.load_cards(LOCAL_RU), bg_dossier.load_cards(LOCAL_EN)


@pytest.mark.skipif(not (LOCAL_RU.exists() and LOCAL_EN.exists()), reason="нет локального снимка hsjson")
def test_local_hsjson_snapshot():
    ru, en = _local_snapshot()
    result = bg_dossier.build_dossier(
        ru, en, ids=["BG31_149", "BG36_200", "BG36_201", "BG36_098", "BGS_004"],
        include_synergy_neighbors=True,
    )
    cards = {c["id"]: c for c in result["cards"]}
    assert len(cards["BG31_149"]["bonus_keywords_pool_ru"]) == 6
    assert "BG36_200t" in {t["id"] for t in cards["BG36_200"]["related_tokens"]}
    bait = next(t for t in cards["BG36_201"]["related_tokens"] if t["id"] == "BG36_205")
    assert "+5/+5" in bait["text_ru"]
    assert "BGFYM_002t" in {t["id"] for t in cards["BG36_098"]["related_tokens"]}
    assert {"BG26_174", "BG32_873"} <= {n["id"] for n in cards["BGS_004"]["synergy_neighbors"]}
    catalog = {c["id"] for c in bg_dossier.build_shortcode_catalog(ru, en)}
    assert {"BG28_810", "BG28_897", "BG31_880", "BG28_503"} <= catalog


# ---------------------------------------------------------------- simulator


class TestSim:
    def test_pool_has_21_minions(self):
        assert len(bg_sim.TIER1) == 21

    def test_bubble_gunner_all_six_keywords(self):
        assert "stealth" in bg_sim.BONUS_KEYWORDS
        assert set(bg_sim.BONUS_KEYWORDS) == {"taunt", "ds", "wf", "reborn", "ven", "stealth"}
        rng = random.Random(1)
        seen = {bg_sim.make_minion("Bubble Gunner", rng=rng)["bonus"] for _ in range(300)}
        assert seen == set(bg_sim.BONUS_KEYWORDS)
        stealthy = bg_sim.make_minion("Bubble Gunner", keyword="stealth")
        assert stealthy["stealth"] is True

    def test_venomous_is_spent_after_first_damage(self):
        att = bg_sim.make_minion("Bubble Gunner", keyword="ven")
        first, second = bg_sim.make_minion("Flittering Bat"), bg_sim.make_minion("Glim Guardian")
        bg_sim.resolve_attack(att, first)
        assert first["hp"] <= 0
        assert att["ven"] == 0
        bg_sim.resolve_attack(att, second)
        assert second["hp"] == 2  # обычные 2 урона, яда больше нет

    def test_venomous_not_spent_on_divine_shield(self):
        att = bg_sim.make_minion("Bubble Gunner", keyword="ven")
        shielded = bg_sim.make_minion("Aureate Laureate")
        bg_sim.resolve_attack(att, shielded)
        assert shielded["ds"] is False and shielded["hp"] == 2
        assert att["ven"] == 1

    def test_geomancer_default_is_4_3(self):
        assert bg_sim.default_opponent_pool()["Razorfen Geomancer"]["gems"] == 2
        geo = bg_sim.make_minion("Razorfen Geomancer")
        assert (geo["atk"], geo["hp"]) == (4, 3)
        assert [(bg_sim.make_minion("Иглошкур-геомант", gems=g)["atk"]) for g in (0, 1, 2)] == [2, 3, 4]

    def test_glim_loses_to_geomancer_attacking_first(self):
        glim, geo = bg_sim.make_minion("Glim Guardian"), bg_sim.make_minion("Razorfen Geomancer")
        assert bg_sim.duel([glim], [geo], first="b", rng=random.Random(0)) == "b"
        report = bg_sim.simulate_turn1("Glim Guardian", opponent_pool=["Razorfen Geomancer"],
                                       first="opponent", trials=50)
        assert report["by_opponent"]["Razorfen Geomancer"]["loss"] == 1.0

    def test_fixed_bubble_keyword_and_spell_buff(self):
        venom = bg_sim.simulate_turn1("Bubble Gunner", keyword="ven", trials=200, seed=3)
        assert venom["keyword"] == "ven" and venom["overall"]["loss"] == 0.0
        plain = bg_sim.simulate_turn1("Bubble Gunner", keyword="stealth", trials=200, seed=3)
        assert plain["overall"]["loss"] > venom["overall"]["loss"]
        seer = bg_sim.simulate_turn1("Wrath Weaver", trials=50)
        assert "buff" not in seer
        banana = bg_sim.simulate_turn1("Зловещая пророчица", buff=(2, 2), trials=200, seed=3)
        assert banana["buff"] == [2, 2] and banana["overall"]["loss"] == 0.0
        with pytest.raises(ValueError):
            bg_sim.simulate_turn1("Glim Guardian", keyword="ds", trials=1)
        with pytest.raises(ValueError):
            bg_sim.simulate_turn1("Glim Guardian", buff=(-1, 0), trials=1)

    def test_cli_keyword_and_buff(self, capsys):
        assert bg_sim.main(["--player", "Bubble Gunner", "--keyword", "reborn", "--trials", "20"]) == 0
        assert json.loads(capsys.readouterr().out)[0]["keyword"] == "reborn"
        assert bg_sim.main(["--player", "Зловещая пророчица", "--buff", "1", "3", "--trials", "20"]) == 0
        assert json.loads(capsys.readouterr().out)[0]["buff"] == [1, 3]

    def test_glim_rally_trades_when_attacking_first(self):
        glim, geo = bg_sim.make_minion("Glim Guardian"), bg_sim.make_minion("Razorfen Geomancer")
        assert bg_sim.duel([glim], [geo], first="a", rng=random.Random(0)) == "tie"
        assert glim["atk"] == 3

    def test_flittering_bat_rally_summons(self):
        bat = bg_sim.make_minion("Flittering Bat")
        board = [bat]
        bg_sim.resolve_attack(bat, bg_sim.make_minion("Glim Guardian"), board)
        assert len(board) == 2 and (board[1]["atk"], board[1]["hp"]) == (1, 1)

    def test_tusked_camper_rally_plays_gem(self):
        camper = bg_sim.make_minion("Tusked Camper")
        bg_sim.resolve_attack(camper, bg_sim.make_minion("Glim Guardian"))
        assert camper["atk"] == 3

    def test_divine_shield_windfury_cyclone(self):
        cyclone, glim = bg_sim.make_minion("Crackling Cyclone"), bg_sim.make_minion("Glim Guardian")
        assert bg_sim.duel([cyclone], [glim], first="a", rng=random.Random(0)) == "tie"
        cyclone, bat = bg_sim.make_minion("Crackling Cyclone"), bg_sim.make_minion("Flittering Bat")
        bat["atk"] = 0  # проверяем чистую двойную атаку
        bg_sim.duel([cyclone], [bat], first="a", rng=random.Random(0))
        assert bat["hp"] == 0

    def test_reborn_and_taunt_rider(self):
        # Музыкант 3/1 бьёт первым, размен; Всадник перерождается 2/1 с Провокацией.
        rider, busker = bg_sim.make_minion("Risen Rider"), bg_sim.make_minion("Southsea Busker")
        board = [rider]
        assert bg_sim.duel(board, [busker], first="b", rng=random.Random(0)) == "a"
        assert (board[0]["atk"], board[0]["hp"], board[0]["taunt"], board[0]["reborn"]) == (2, 1, True, False)

    def test_deathrattle_bonehead(self):
        bonehead, weaver = bg_sim.make_minion("Harmless Bonehead"), bg_sim.make_minion("Wrath Weaver")
        board = [bonehead]
        bg_sim.resolve_attack(weaver, bonehead)
        bg_sim._cleanup(board)
        assert [(m["atk"], m["hp"]) for m in board] == [(1, 1), (1, 1)]

    def test_stealth_cannot_be_targeted(self):
        hidden = bg_sim.make_minion("Bubble Gunner", keyword="stealth")
        visible = bg_sim.make_minion("Glim Guardian")
        assert bg_sim._targets([hidden, visible]) == [visible]
        assert bg_sim._targets([hidden]) == [hidden]

    def test_weights_select_single_opponent(self):
        report = bg_sim.simulate_turn1(
            "Glim Guardian", trials=100, seed=3,
            weights={name: (1.0 if name == "Wrath Weaver" else 0.0) for name in bg_sim.TIER1},
        )
        assert report["overall"] == report["by_opponent"]["Wrath Weaver"]

    def test_cli(self, capsys):
        assert bg_sim.main(["--player", "Razorfen Geomancer", "--gems", "0", "2", "--trials", "20"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert [r["gems"] for r in out] == [0, 2]
