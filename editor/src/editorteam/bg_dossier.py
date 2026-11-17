"""Проверенное досье карт Полей сражений из локальных снимков HearthstoneJSON.

Тексты о БГ ломаются не на стиле, а на игровой физике: токен «остаётся на
столе», хотя кладётся в руку; наживка «даёт золото», хотя даёт +5/+5. Досье
собирает всё, что автору и рецензенту нужно сверить, в одном словаре и без
сети: характеристики, типы существ по-русски, очищенные тексты, золотую версию,
связанные токены и (по желанию) профильных соседей по пулу.

Вход — два снимка `cards.json` (ruRU и enUS) с api.hearthstonejson.com.

    python -m editorteam.bg_dossier --ru ru.json --en en.json --tier 1
    python -m editorteam.bg_dossier --ru ru.json --en en.json --ids BGS_004 \
        --include-synergy-neighbors
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

# Канонические русские названия типов существ. Слово «племя» не используется
# нигде: в текстах БГ пишем «тип существ».
RACE_RU = {
    "QUILBOAR": "Свинобразы",
    "DRAGON": "Драконы",
    "PIRATE": "Пираты",
    "MURLOC": "Мурлоки",
    "BEAST": "Звери",
    "ELEMENTAL": "Элементали",
    "UNDEAD": "Нежить",
    "MECHANICAL": "Механизмы",
    "DEMON": "Демоны",
    "NAGA": "Наги",
    "ABERRATION": "Аберрации",
    "ALL": "Все типы существ",
}
NEUTRAL_RU = "Нейтральное"

BONUS_KEYWORDS_RU = (
    "Божественный щит",
    "Перерождение",
    "Провокация",
    "Неистовство ветра",
    "Токсичность",
    "Маскировка",
)

# Токены, которые карта называет в тексте, но которых нет в её id-префиксе.
# Если в снимке карты нет, берём минимальную проверенную запись отсюда.
TEXT_TOKEN_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"наживк|fishbait", re.I), ("BG36_205", "BG36_205_G")),
    (re.compile(r"щупальц\w*\s+0/2|0/2\s+tentacle", re.I), ("BGFYM_002t",)),
    (re.compile(r"кровав\w*\s+самоцвет|blood\s+gem", re.I), ("BG20_GEM",)),
)
BUILTIN_TOKENS = {
    "BG36_205": {
        "name_ru": "Наживка", "name_en": "Fishbait", "type": "MINION", "techLevel": 2,
        "attack": 0, "health": 1, "races": ["BEAST"],
        "text_ru": "Не может получать характеристики. Предсмертный хрип: "
        "уничтожившее наживку существо получает +5/+5.",
    },
    "BG36_205_G": {
        "name_ru": "Наживка", "name_en": "Fishbait", "type": "MINION", "techLevel": 2,
        "attack": 0, "health": 2, "races": ["BEAST"],
        "text_ru": "Не может получать характеристики. Предсмертный хрип: "
        "уничтожившее наживку существо получает +10/+10.",
    },
    "BGFYM_002t": {
        "name_ru": "Чудовищное щупальце", "name_en": "Monstrous Tentacle", "type": "MINION",
        "techLevel": 1, "attack": 0, "health": 2, "races": ["ABERRATION"],
        "text_ru": "Провокация", "zone_ru": "рука (при продаже Зоатроида)",
    },
    "BG20_GEM": {
        "name_ru": "Кровавый самоцвет", "name_en": "Blood Gem", "type": "SPELL",
        "text_ru": "Существо получает +1/+1.",
    },
}
TOKEN_NOTES = {
    "BGFYM_002t": "кладётся в руку при продаже Зоатроида, а не призывается на стол",
    "BG36_205": "уничтожившее наживку существо получает +5/+5; золота не даёт",
    "BG36_205_G": "золотая наживка: +10/+10 уничтожившему её существу",
}
BONUS_KEYWORD_TEXT = re.compile(r"бонусн\w*\s+свойств|bonus\s+keyword", re.I)

# Профили синергии: если текст исходной карты подходит под source, ищем в пуле
# существ с текстом под target (и, когда задано, с общим типом существ).
SYNERGY_PROFILES: tuple[dict, ...] = (
    {
        "name": "урон своему герою",
        "source": re.compile(r"урон\w*\s+вашему\s+герою|damage to your hero", re.I),
        "target": re.compile(r"ваш\s+герой\s+получает\s+урон|your hero (?:takes|is dealt) damage", re.I),
        "same_race": True,
    },
    {
        "name": "кровавые самоцветы",
        "source": re.compile(r"кровав\w*\s+самоцвет|blood gem", re.I),
        "target": re.compile(r"кровав\w*\s+самоцвет|blood gem", re.I),
        "same_race": True,
    },
    {
        "name": "наживка",
        "source": re.compile(r"наживк|fishbait|боевой раж:\s*призывает зверя", re.I),
        "target": re.compile(r"наживк|fishbait", re.I),
        "same_race": False,
    },
    {
        "name": "заклинания таверны",
        "source": re.compile(r"заклинани\w*\s+таверны|tavern spell", re.I),
        "target": re.compile(r"заклинани|spell", re.I),
        "same_race": True,
    },
    {
        "name": "божество",
        "source": re.compile(r"божеств|deity", re.I),
        "target": re.compile(r"божеств|deity", re.I),
        "same_race": False,
    },
)
SYNERGY_MAX_TIER_DISTANCE = 3

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def clean_text(text: str | None) -> str:
    """Снять HTML, служебное [x], $/# у чисел и лишние пробелы (включая NBSP)."""
    if not text:
        return ""
    value = _TAG.sub("", text).replace("[x]", "").replace(" ", " ")
    value = re.sub(r"[$#](\d)", r"\1", value)
    return _SPACE.sub(" ", value).strip()


def types_ru(races: Iterable[str] | None) -> list[str]:
    races = [race for race in (races or []) if race]
    if not races:
        return [NEUTRAL_RU]
    return [RACE_RU.get(race, race) for race in races]


def load_cards(path: str | Path) -> list[dict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("cards", [])
    if not isinstance(raw, list):
        raise ValueError(f"снимок {path} должен быть массивом карт")
    return [card for card in raw if isinstance(card, dict) and card.get("id")]


class Snapshot:
    """Индексы по снимкам ru/en."""

    def __init__(self, ru_cards: Iterable[dict], en_cards: Iterable[dict] | None = None):
        self.ru = {card["id"]: card for card in ru_cards if card.get("id")}
        self.en = {card["id"]: card for card in (en_cards or []) if card.get("id")}
        self.by_dbf = {card["dbfId"]: card for card in self.ru.values() if card.get("dbfId")}
        self._ids = sorted(self.ru)

    def get(self, card_id: str) -> dict | None:
        return self.ru.get(card_id) or self.en.get(card_id)

    def ids_with_prefix(self, prefix: str) -> list[str]:
        return [card_id for card_id in self._ids if card_id.startswith(prefix)]

    def pool_minions(self) -> list[dict]:
        return [card for card in self.ru.values() if card.get("isBattlegroundsPoolMinion")]

    def pool_spells(self) -> list[dict]:
        return [card for card in self.ru.values() if card.get("isBattlegroundsPoolSpell")]

    def golden_of(self, card_id: str) -> dict | None:
        card = self.ru.get(card_id) or {}
        golden = self.ru.get(f"{card_id}_G")
        if golden is None and card.get("battlegroundsPremiumDbfId"):
            golden = self.by_dbf.get(card["battlegroundsPremiumDbfId"])
        return golden


def _base_entry(snapshot: Snapshot, card_id: str) -> dict | None:
    ru = snapshot.ru.get(card_id)
    en = snapshot.en.get(card_id) or {}
    if ru is None and not en:
        builtin = BUILTIN_TOKENS.get(card_id)
        if builtin is None:
            return None
        entry = {"id": card_id, "dbfId": None, "cost": None, "attack": None, "health": None,
                 "techLevel": None, "races": [], "text_en": "", "source": "builtin"}
        entry.update(builtin)
        entry["types_ru"] = types_ru(entry.get("races"))
        entry["is_pool_minion"] = False
        entry["is_pool_spell"] = False
        return entry
    card = ru or en
    races = card.get("races") or ([card["race"]] if card.get("race") else [])
    return {
        "id": card_id,
        "dbfId": card.get("dbfId"),
        "name_ru": (ru or {}).get("name", ""),
        "name_en": en.get("name", ""),
        "type": card.get("type"),
        "techLevel": card.get("techLevel"),
        "cost": card.get("cost"),
        "attack": card.get("attack"),
        "health": card.get("health"),
        "races": list(races),
        "types_ru": types_ru(races) if card.get("type") == "MINION" else [],
        "is_pool_minion": bool(card.get("isBattlegroundsPoolMinion")),
        "is_pool_spell": bool(card.get("isBattlegroundsPoolSpell")),
        "text_ru": clean_text((ru or {}).get("text")),
        "text_en": clean_text(en.get("text")),
        "source": "hsjson",
    }


def _token_entry(snapshot: Snapshot, card_id: str, via: str) -> dict | None:
    entry = _base_entry(snapshot, card_id)
    if entry is None:
        return None
    entry["via"] = via
    if card_id in TOKEN_NOTES:
        entry["note_ru"] = TOKEN_NOTES[card_id]
    return entry


def _related_tokens(snapshot: Snapshot, card_id: str, texts: Iterable[str]) -> list[dict]:
    seen: set[str] = {card_id}
    tokens: list[dict] = []

    def add(token_id: str, via: str) -> None:
        if token_id in seen:
            return
        token = snapshot.get(token_id)
        if token is not None and token.get("type") == "ENCHANTMENT":
            return
        entry = _token_entry(snapshot, token_id, via)
        if entry is not None:
            seen.add(token_id)
            tokens.append(entry)

    for prefix in (f"{card_id}t", f"{card_id}_Gt"):
        for token_id in snapshot.ids_with_prefix(prefix):
            add(token_id, "id-prefix")
    related_dbf = (snapshot.ru.get(card_id) or {}).get("battlegroundsRelatedCard")
    if related_dbf and related_dbf in snapshot.by_dbf:
        add(snapshot.by_dbf[related_dbf]["id"], "battlegroundsRelatedCard")
    joined = " ".join(texts)
    for pattern, token_ids in TEXT_TOKEN_RULES:
        if pattern.search(joined):
            for token_id in token_ids:
                add(token_id, "text")
    return tokens


def card_entry(snapshot: Snapshot, card_id: str) -> dict | None:
    """Полная запись одной карты: база + золото + токены + бонусные свойства."""
    entry = _base_entry(snapshot, card_id)
    if entry is None:
        return None
    golden = snapshot.golden_of(card_id)
    if golden is not None:
        golden_en = snapshot.en.get(golden["id"], {})
        entry["golden"] = {
            "id": golden["id"],
            "dbfId": golden.get("dbfId"),
            "attack": golden.get("attack"),
            "health": golden.get("health"),
            "text_ru": clean_text(golden.get("text")),
            "text_en": clean_text(golden_en.get("text")),
        }
    else:
        entry["golden"] = None
    texts = [entry.get("text_ru", ""), entry.get("text_en", "")]
    if entry["golden"]:
        texts += [entry["golden"]["text_ru"], entry["golden"]["text_en"]]
    entry["related_tokens"] = _related_tokens(snapshot, card_id, texts)
    if BONUS_KEYWORD_TEXT.search(" ".join(texts)):
        entry["bonus_keywords_pool_ru"] = list(BONUS_KEYWORDS_RU)
    return entry


def synergy_neighbors(snapshot: Snapshot, entry: dict) -> list[dict]:
    """Профильные карты пула соседних тиров (± SYNERGY_MAX_TIER_DISTANCE)."""
    source_text = " ".join([entry.get("text_ru", ""), entry.get("text_en", "")])
    tier = entry.get("techLevel") or 0
    races = set(entry.get("races") or [])
    result: list[dict] = []
    seen = {entry["id"]}
    for profile in SYNERGY_PROFILES:
        if not profile["source"].search(source_text):
            continue
        for card in sorted(snapshot.pool_minions(), key=lambda c: (c.get("techLevel") or 0, c["id"])):
            if card["id"] in seen:
                continue
            if tier and abs((card.get("techLevel") or 0) - tier) > SYNERGY_MAX_TIER_DISTANCE:
                continue
            card_races = set(card.get("races") or [])
            if profile["same_race"] and races and not (races & card_races or "ALL" in card_races):
                continue
            en_text = (snapshot.en.get(card["id"]) or {}).get("text")
            target_text = f"{clean_text(card.get('text'))} {clean_text(en_text)}"
            if not profile["target"].search(target_text):
                continue
            neighbor = _base_entry(snapshot, card["id"])
            neighbor["synergy_profile"] = profile["name"]
            result.append(neighbor)
            seen.add(card["id"])
    return result


def select_ids(
    snapshot: Snapshot,
    *,
    ids: Iterable[str] | None = None,
    names: Iterable[str] | None = None,
    tiers: Iterable[int] | None = None,
    include_spells: bool = False,
) -> list[str]:
    selected: list[str] = []

    def push(card_id: str) -> None:
        if card_id not in selected:
            selected.append(card_id)

    for card_id in ids or []:
        push(card_id)
    if names:
        bg = sorted((c for c in snapshot.ru.values() if c.get("isBattlegroundsPoolMinion")
                     or c.get("isBattlegroundsPoolSpell")), key=lambda c: c["id"])
        other = sorted((c for c in snapshot.ru.values() if c.get("set") == "BATTLEGROUNDS"),
                       key=lambda c: c["id"])
        for name in names:
            wanted = name.casefold().replace("ё", "е")
            for card in bg + other:
                en_name = (snapshot.en.get(card["id"]) or {}).get("name", "")
                if wanted in (card.get("name", "").casefold().replace("ё", "е"), en_name.casefold()):
                    push(card["id"])
                    break
    tier_set = set(tiers or [])
    if tier_set:
        for card in sorted(snapshot.pool_minions(), key=lambda c: (c.get("techLevel") or 0, c["id"])):
            if card.get("techLevel") in tier_set:
                push(card["id"])
        if include_spells:
            for card in sorted(snapshot.pool_spells(), key=lambda c: (c.get("techLevel") or 0, c["id"])):
                if card.get("techLevel") in tier_set:
                    push(card["id"])
    return selected


def build_dossier(
    ru_cards: Iterable[dict],
    en_cards: Iterable[dict] | None = None,
    *,
    ids: Iterable[str] | None = None,
    names: Iterable[str] | None = None,
    tiers: Iterable[int] | None = None,
    include_spells: bool = False,
    include_synergy_neighbors: bool = False,
) -> dict:
    """Собрать досье; неизвестные ID попадают в `missing`, а не молча теряются."""
    snapshot = Snapshot(ru_cards, en_cards)
    selected = select_ids(snapshot, ids=ids, names=names, tiers=tiers, include_spells=include_spells)
    cards: list[dict] = []
    missing: list[str] = []
    for card_id in selected:
        entry = card_entry(snapshot, card_id)
        if entry is None:
            missing.append(card_id)
            continue
        if include_synergy_neighbors:
            entry["synergy_neighbors"] = synergy_neighbors(snapshot, entry)
        cards.append(entry)
    return {"cards": cards, "missing": missing, "count": len(cards)}


def build_shortcode_catalog(ru_cards: Iterable[dict], en_cards: Iterable[dict] | None = None) -> list[dict]:
    """Каталог для card-shortcodes: существа пула и заклинания таверны БГ.

    Имена в одном формате должны быть уникальны (`wordpress._validated_catalog`),
    поэтому при совпадении имени остаётся карта с меньшим тиром и ID.
    """
    del en_cards  # имена в каталоге русские; параметр для симметрии API
    pool = [
        card for card in ru_cards
        if card.get("id") and card.get("name")
        and (card.get("isBattlegroundsPoolMinion") or card.get("isBattlegroundsPoolSpell"))
    ]
    pool.sort(key=lambda c: (0 if c.get("isBattlegroundsPoolMinion") else 1, c.get("techLevel") or 0, c["id"]))
    catalog: list[dict] = []
    names: set[str] = set()
    for card in pool:
        name = card["name"].strip()
        if name in names:
            continue
        names.add(name)
        catalog.append({"id": card["id"], "name": name, "formats": ["battlegrounds"]})
    return catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m editorteam.bg_dossier",
        description="Досье карт Полей сражений из локальных снимков HearthstoneJSON (ru/en).",
    )
    parser.add_argument("--ru", required=True, help="cards.json ruRU")
    parser.add_argument("--en", help="cards.json enUS")
    parser.add_argument("--ids", nargs="*", default=[], help="ID карт, например BGS_004 BG31_149")
    parser.add_argument("--names", nargs="*", default=[], help="русские или английские имена")
    parser.add_argument("--tier", type=int, nargs="*", default=[], help="все существа пула этих тиров")
    parser.add_argument("--include-spells", action="store_true", help="добавить заклинания таверны тех же тиров")
    parser.add_argument("--include-synergy-neighbors", action="store_true",
                        help="подтянуть профильных существ соседних тиров")
    parser.add_argument("--shortcode-catalog", action="store_true",
                        help="вместо досье вывести каталог для card-shortcodes")
    parser.add_argument("-o", "--output", help="файл для JSON (по умолчанию stdout)")
    args = parser.parse_args(argv)

    ru_cards = load_cards(args.ru)
    en_cards = load_cards(args.en) if args.en else []
    if args.shortcode_catalog:
        result: object = build_shortcode_catalog(ru_cards, en_cards)
    else:
        if not (args.ids or args.names or args.tier):
            parser.error("нужен хотя бы один фильтр: --ids, --names или --tier")
        result = build_dossier(
            ru_cards, en_cards, ids=args.ids, names=args.names, tiers=args.tier,
            include_spells=args.include_spells,
            include_synergy_neighbors=args.include_synergy_neighbors,
        )
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        sys.stdout.write(payload + "\n")
    missing = result.get("missing") if isinstance(result, dict) else None
    return 2 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
