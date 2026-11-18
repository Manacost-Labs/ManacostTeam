"""Симулятор боёв 1-го хода Полей сражений: одно существо тир-1 против другого.

Нужен, чтобы утверждения вида «Бликостраж переигрывает любой 1-й ход»
проверялись числом, а не впечатлением. Модель покрывает весь текущий тир-1 пул
(21 существо) и механики, которые реально встречаются в бою на 1-м ходу:
Божественный щит, Неистовство ветра, Перерождение, Провокация, Маскировка,
Токсичность (одноразовая), Предсмертный хрип и Боевой раж (Rally).

Принятые допущения 1-го хода:
- Иглошкур-геомант у соперника — 4/3: оба кровавых самоцвета сыграны;
- Баюбот — 2/3: «в конце хода +1 к здоровью» уже сработало;
- Пузырьковый стрелок получает одно из 6 бонусных свойств равновероятно;
- при равном числе существ первым атакует случайная сторона.

    python -m editorteam.bg_sim --player "Glim Guardian" --trials 5000
    python -m editorteam.bg_sim --player "Razorfen Geomancer" --gems 0 1 2
    python -m editorteam.bg_sim --all
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
from typing import Iterable

BONUS_KEYWORDS = ("taunt", "ds", "wf", "reborn", "ven", "stealth")
MAX_BOARD = 7
MAX_ATTACKS = 200
_UID = itertools.count(1)

# Ключ — английское имя; kw — свойства, dr — Предсмертный хрип, rally — Боевой раж.
TIER1: dict[str, dict] = {
    "Razorfen Geomancer": {"id": "BG20_100", "ru": "Иглошкур-геомант", "atk": 2, "hp": 1, "gems": 2},
    "Tusked Camper": {"id": "BG33_886", "ru": "Клыкастый походник", "atk": 2, "hp": 3, "rally": "gem"},
    "Flittering Bat": {"id": "BG36_200", "ru": "Порхающий нетопырь", "atk": 1, "hp": 4, "rally": "bat"},
    "Buzzing Vermin": {"id": "BG31_803", "ru": "Жужжащий вредитель", "atk": 1, "hp": 1,
                       "kw": ("taunt",), "dr": "beetle"},
    "Dune Dweller": {"id": "BG31_815", "ru": "Дюнный силач", "atk": 3, "hp": 3},
    "Crackling Cyclone": {"id": "BGS_119", "ru": "Трескучий циклон", "atk": 2, "hp": 1, "kw": ("ds", "wf")},
    "Bubble Gunner": {"id": "BG31_149", "ru": "Пузырьковый стрелок", "atk": 2, "hp": 3, "bonus": True},
    "Flighty Scout": {"id": "BG32_330", "ru": "Вертлявый разведчик", "atk": 3, "hp": 3},
    "Wrath Weaver": {"id": "BGS_004", "ru": "Заклинатель гнева", "atk": 1, "hp": 3},
    "Lullabot": {"id": "BG26_146", "ru": "Баюбот", "atk": 2, "hp": 3},
    "Cord Puller": {"id": "BG29_611", "ru": "Протягиватель кабелей", "atk": 1, "hp": 1,
                    "kw": ("ds",), "dr": "microbot"},
    "Glim Guardian": {"id": "BG29_888", "ru": "Бликостраж", "atk": 1, "hp": 4, "rally": "glim"},
    "Scarlet Survivor": {"id": "BG35_814", "ru": "Выживший красный дракон", "atk": 3, "hp": 3},
    "Aureate Laureate": {"id": "BG32_236", "ru": "Золотой призер", "atk": 2, "hp": 2, "kw": ("ds",)},
    "Southsea Busker": {"id": "BG26_135", "ru": "Музыкант Южных Морей", "atk": 3, "hp": 1},
    "Harmless Bonehead": {"id": "BG28_300", "ru": "Безобидная черепушка", "atk": 1, "hp": 1, "dr": "skeletons"},
    "Risen Rider": {"id": "BG25_001", "ru": "Восставший всадник", "atk": 2, "hp": 1, "kw": ("taunt", "reborn")},
    "Joyous": {"id": "BG36_110", "ru": "Счастье", "atk": 2, "hp": 3},
    "Zoatroid": {"id": "BG36_098", "ru": "Зоатроид", "atk": 3, "hp": 2},
    "Ominous Seer": {"id": "BG31_330", "ru": "Зловещая пророчица", "atk": 2, "hp": 1},
    "Suspicious Prisonguard": {"id": "BG36_345", "ru": "Подозрительный надзиратель", "atk": 3, "hp": 3},
}
TOKENS = {
    "beetle": ("Beetle", 2, 2, 1),
    "microbot": ("Microbot", 1, 1, 1),
    "skeletons": ("Skeleton", 1, 1, 2),
    "bat": ("Bat Scavenger", 1, 1, 1),  # BG36_200t Нетопырь-добытчик
}
_RU_INDEX = {spec["ru"].casefold(): name for name, spec in TIER1.items()}


def resolve_name(name: str) -> str:
    """Английское или русское имя -> ключ TIER1."""
    if name in TIER1:
        return name
    for key in TIER1:
        if key.casefold() == name.casefold():
            return key
    key = _RU_INDEX.get(name.casefold())
    if key:
        return key
    raise KeyError(f"неизвестное существо тир-1: {name}")


def make_minion(name: str, *, gems: int | None = None, keyword: str | None = None,
                rng: random.Random | None = None) -> dict:
    """Создать существо в бою. gems — сыгранные самоцветы Геоманта (по умолчанию 2)."""
    key = resolve_name(name)
    spec = TIER1[key]
    minion = {
        "name": key, "atk": spec["atk"], "hp": spec["hp"],
        "taunt": False, "ds": False, "wf": False, "reborn": False, "ven": 0, "stealth": False,
        "dr": spec.get("dr"), "rally": spec.get("rally"), "base": (spec["atk"], spec["hp"]),
        "base_kw": tuple(spec.get("kw", ())), "token": False, "uid": next(_UID),
    }
    for kw in spec.get("kw", ()):
        _set_keyword(minion, kw)
    if "gems" in spec:
        played = spec["gems"] if gems is None else gems
        if not 0 <= played <= spec["gems"]:
            raise ValueError("Геомант даёт не больше 2 самоцветов")
        minion["atk"] += played
        minion["hp"] += played
    if spec.get("bonus"):
        chosen = keyword or (rng or random).choice(BONUS_KEYWORDS)
        if chosen not in BONUS_KEYWORDS:
            raise ValueError(f"бонусное свойство должно быть из {BONUS_KEYWORDS}")
        _set_keyword(minion, chosen)
        minion["bonus"] = chosen
    return minion


def _set_keyword(minion: dict, kw: str) -> None:
    minion[kw] = 1 if kw == "ven" else True


def _token(kind: str) -> dict:
    name, atk, hp, _ = TOKENS[kind]
    return {"name": name, "atk": atk, "hp": hp, "taunt": False, "ds": False, "wf": False,
            "reborn": False, "ven": 0, "stealth": False, "dr": None, "rally": None,
            "base": (atk, hp), "base_kw": (), "token": True, "uid": next(_UID)}


def _targets(board: list[dict]) -> list[dict]:
    alive = [m for m in board if m["hp"] > 0]
    visible = [m for m in alive if not m["stealth"]] or alive
    taunts = [m for m in visible if m["taunt"]]
    return taunts or visible


def _hit(source: dict, target: dict) -> None:
    """Урон source -> target с учётом щита и одноразовой Токсичности."""
    if source["atk"] <= 0:
        return
    if target["ds"]:
        target["ds"] = False
        return
    target["hp"] -= source["atk"]
    if source["ven"]:
        target["hp"] = min(target["hp"], 0)
        source["ven"] = 0


def _rally(attacker: dict, board: list[dict]) -> None:
    kind = attacker.get("rally")
    if kind == "glim":
        attacker["atk"] += 2
    elif kind == "gem":
        attacker["atk"] += 1
        attacker["hp"] += 1
    elif kind == "bat" and len([m for m in board if m["hp"] > 0]) < MAX_BOARD:
        board.insert(board.index(attacker) + 1, _token("bat"))


def resolve_attack(attacker: dict, defender: dict, attacker_board: list[dict] | None = None) -> None:
    """Одна атака: Боевой раж, снятие Маскировки, одновременный обмен уроном."""
    _rally(attacker, attacker_board if attacker_board is not None else [attacker])
    attacker["stealth"] = False
    _hit(attacker, defender)
    _hit(defender, attacker)


def _cleanup(board: list[dict]) -> None:
    index = 0
    while index < len(board):
        minion = board[index]
        if minion["hp"] > 0:
            index += 1
            continue
        board.pop(index)
        spawned: list[dict] = []
        if minion["dr"]:
            count = TOKENS[minion["dr"]][3]
            spawned += [_token(minion["dr"]) for _ in range(count)]
        if minion["reborn"]:
            atk, _ = minion["base"]
            reborn = {**_token("bat"), "name": minion["name"], "atk": atk, "hp": 1,
                      "dr": minion["dr"], "rally": minion["rally"], "base": minion["base"],
                      "base_kw": minion["base_kw"], "token": False}
            for kw in minion["base_kw"]:
                if kw != "reborn":
                    _set_keyword(reborn, kw)
            spawned.append(reborn)
        room = MAX_BOARD - len(board)
        for offset, unit in enumerate(spawned[:room]):
            board.insert(index + offset, unit)
        index += min(len(spawned), room)


def duel(board_a: list[dict], board_b: list[dict], *, first: str = "random",
         rng: random.Random | None = None) -> str:
    """Бой двух досок. first: 'a', 'b' или 'random'. Возвращает 'a', 'b' или 'tie'."""
    rng = rng or random.Random()
    boards = {"a": board_a, "b": board_b}
    if first == "random":
        if len(board_a) != len(board_b):
            first = "a" if len(board_a) > len(board_b) else "b"
        else:
            first = rng.choice("ab")
    attacked: dict[str, set[int]] = {"a": set(), "b": set()}
    side = first
    for _ in range(MAX_ATTACKS):
        own, enemy = boards[side], boards["b" if side == "a" else "a"]
        if not own or not enemy:
            break
        ready = [m for m in own if m["atk"] > 0]
        if not ready:
            if not [m for m in enemy if m["atk"] > 0]:
                break
            side = "b" if side == "a" else "a"
            continue
        pending = [m for m in ready if m["uid"] not in attacked[side]]
        if not pending:
            attacked[side].clear()
            pending = ready
        attacker = pending[0]
        attacked[side].add(attacker["uid"])
        swings = 2 if attacker["wf"] else 1
        for _swing in range(swings):
            targets = _targets(enemy)
            if not targets or attacker["hp"] <= 0:
                break
            resolve_attack(attacker, rng.choice(targets), own)
            _cleanup(own)
            _cleanup(enemy)
        side = "b" if side == "a" else "a"
    if board_a and not board_b:
        return "a"
    if board_b and not board_a:
        return "b"
    return "tie"


def default_opponent_pool() -> dict[str, dict]:
    """Соперники 1-го хода: Геомант — реальные 4/3 с двумя самоцветами."""
    return {name: {"name": name, "gems": 2 if "gems" in spec else None} for name, spec in TIER1.items()}


def simulate_turn1(
    player: str,
    *,
    gems: int | None = None,
    opponent_pool: Iterable[str] | dict[str, dict] | None = None,
    weights: dict[str, float] | None = None,
    trials: int = 2000,
    seed: int | None = 0,
    first: str = "random",
    keyword: str | None = None,
    buff: tuple[int, int] = (0, 0),
) -> dict:
    """Доли побед/ничьих/поражений player против каждого соперника и в среднем.

    weights — частота пиков соперников (по умолчанию равная).
    first — 'player', 'opponent' или 'random'.
    keyword — фиксированное бонусное свойство Пузырькового стрелка игрока.
    buff — (+атака, +здоровье) от заклинания таверны, сыгранного на существо до боя;
    Перерождение возвращает базовые характеристики карты без этой прибавки.
    """
    rng = random.Random(seed)
    player = resolve_name(player)
    if keyword is not None and not TIER1[player].get("bonus"):
        raise ValueError("keyword задаётся только существу с бонусным свойством")
    add_atk, add_hp = buff
    if add_atk < 0 or add_hp < 0:
        raise ValueError("buff не может уменьшать характеристики")
    if opponent_pool is None:
        pool = default_opponent_pool()
    elif isinstance(opponent_pool, dict):
        pool = {resolve_name(k): {"name": resolve_name(k), **v} for k, v in opponent_pool.items()}
    else:
        pool = {resolve_name(n): {"name": resolve_name(n), "gems": None} for n in opponent_pool}
    side = {"player": "a", "opponent": "b", "random": "random"}[first]
    by_opponent: dict[str, dict] = {}
    for name, opts in pool.items():
        counts = {"a": 0, "b": 0, "tie": 0}
        for _ in range(trials):
            mine = make_minion(player, gems=gems, keyword=keyword, rng=rng)
            mine["atk"] += add_atk
            mine["hp"] += add_hp
            theirs = make_minion(name, gems=opts.get("gems"), keyword=opts.get("keyword"), rng=rng)
            counts[duel([mine], [theirs], first=side, rng=rng)] += 1
        by_opponent[name] = {
            "win": counts["a"] / trials, "tie": counts["tie"] / trials, "loss": counts["b"] / trials,
        }
    weights = weights or {}
    total = sum(weights.get(n, 1.0) for n in by_opponent) or 1.0
    overall = {
        key: sum(r[key] * weights.get(n, 1.0) for n, r in by_opponent.items()) / total
        for key in ("win", "tie", "loss")
    }
    report = {"player": player, "gems": gems, "trials": trials, "first": first,
              "overall": overall, "by_opponent": by_opponent}
    if keyword is not None:
        report["keyword"] = keyword
    if buff != (0, 0):
        report["buff"] = [add_atk, add_hp]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m editorteam.bg_sim",
        description="Симулятор боёв 1-го хода Полей сражений (тир-1 против тир-1).",
    )
    parser.add_argument("--player", help="существо игрока (англ. или рус. имя)")
    parser.add_argument("--all", action="store_true", help="сводка по всем 21 существу")
    parser.add_argument("--gems", type=int, nargs="*", help="варианты самоцветов Геоманта игрока (0 1 2)")
    parser.add_argument("--trials", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--first", choices=("random", "player", "opponent"), default="random")
    parser.add_argument("--weights", help="JSON-файл {имя: вес} частоты соперников")
    parser.add_argument("--keyword", choices=BONUS_KEYWORDS,
                        help="фиксированное бонусное свойство Пузырькового стрелка игрока")
    parser.add_argument("--buff", type=int, nargs=2, metavar=("ATK", "HP"), default=(0, 0),
                        help="прибавка от заклинания таверны на существо игрока до боя")
    args = parser.parse_args(argv)
    weights = None
    if args.weights:
        with open(args.weights, encoding="utf-8") as handle:
            weights = {resolve_name(k): float(v) for k, v in json.load(handle).items()}
    players = list(TIER1) if args.all else [args.player] if args.player else []
    if not players:
        parser.error("нужен --player или --all")
    report = []
    for name in players:
        variants = args.gems if (args.gems and "gems" in TIER1[resolve_name(name)]) else [None]
        for gems in variants:
            result = simulate_turn1(name, gems=gems, weights=weights, trials=args.trials,
                                    seed=args.seed, first=args.first, keyword=args.keyword,
                                    buff=tuple(args.buff))
            if args.all:
                result.pop("by_opponent")
            report.append(result)
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
