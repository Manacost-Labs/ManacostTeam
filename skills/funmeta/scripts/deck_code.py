"""Strict, dependency-free deckstring reader. This does not validate game legality.

Format reference: https://hearthsim.info/docs/deckstrings/
Sideboard reference: HearthSim/python-hearthstone, hearthstone/deckstrings.py.
"""

import base64
import binascii


def normalize_deck(value):
    """Normalize an independently transcribed DBF list for exact comparison."""
    if not isinstance(value, dict) or type(value.get("format")) is not int:
        raise ValueError("deck_list: format must be an integer")
    if value["format"] not in (1, 2):
        raise ValueError("deck_list: only Wild (1) and Standard (2) are supported")
    heroes = value.get("heroes")
    if (not isinstance(heroes, list) or len(heroes) != 1
            or type(heroes[0]) is not int or heroes[0] <= 0):
        raise ValueError("deck_list: exactly one positive hero DBF ID required")
    normalized = {"format": value["format"], "heroes": heroes.copy()}
    for key, width in (("cards", 2), ("sideboards", 3)):
        rows = value.get(key)
        if not isinstance(rows, list) or (key == "cards" and not rows):
            raise ValueError(f"deck_list: {key} array required")
        identities = set()
        for row in rows:
            if (not isinstance(row, list) or len(row) != width
                    or any(type(item) is not int or item <= 0 for item in row)):
                raise ValueError(f"deck_list: invalid {key} entry")
            identity = (row[0], row[2]) if width == 3 else row[0]
            if identity in identities:
                raise ValueError(f"deck_list: duplicate {key} entry")
            identities.add(identity)
        normalized[key] = sorted(rows)
    owners = {row[0] for row in normalized["cards"]}
    if any(row[2] not in owners for row in normalized["sideboards"]):
        raise ValueError("deck_list: sideboard owner missing from main deck")
    return normalized


def decode(code):
    if not isinstance(code, str) or not code or len(code) > 20000:
        raise ValueError("deck code: expected one nonempty base64 string")
    try:
        raw = base64.b64decode(code, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("deck code: invalid base64") from exc
    if not raw or raw[0] != 0:
        raise ValueError("deck code: invalid reserved byte")
    cursor = 1

    def number():
        nonlocal cursor
        value = 0
        for shift in range(0, 35, 7):
            if cursor >= len(raw):
                raise ValueError("deck code: truncated integer")
            byte = raw[cursor]
            cursor += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError("deck code: oversized integer")

    def count():
        value = number()
        if value > 1000:
            raise ValueError("deck code: oversized array")
        return value

    if number() != 1:
        raise ValueError("deck code: unsupported header/version")
    game_format = number()
    heroes = [number() for _ in range(count())]

    def cards(sideboard=False):
        result = []
        for fixed in (1, 2, None):
            for _ in range(count()):
                card = number()
                amount = fixed if fixed is not None else number()
                row = [card, amount]
                if sideboard:
                    row.append(number())
                result.append(row)
        return result

    main = cards()
    sideboards = []
    if cursor < len(raw):
        marker = raw[cursor]
        cursor += 1
        if marker == 1:
            sideboards = cards(sideboard=True)
        elif marker != 0:
            raise ValueError("deck code: unsupported sideboard marker")
    if cursor != len(raw):
        raise ValueError("deck code: unsupported trailing data")
    return normalize_deck({"format": game_format, "heroes": heroes,
                           "cards": main, "sideboards": sideboards})
