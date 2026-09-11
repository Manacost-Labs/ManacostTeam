#!/usr/bin/env python3
"""Декодер кода колоды Hearthstone (deckstring) — dbfId и количества.

    from deckstring import decode
    d = decode("AAECAQcE69YHstgH...")
    # {"format": 2, "heroes": [7], "cards": [(dbf, count), ...]}

Имена/стоимости карт по dbfId отдаёт API:
GET /api/v1/constructed-cards/by-dbf/{dbf}
"""
import base64


def _varints(data: bytes):
    result, shift, value = [], 0, 0
    for b in data:
        value |= (b & 0x7F) << shift
        if b & 0x80:
            shift += 7
        else:
            result.append(value)
            value, shift = 0, 0
    return result

def decode(code: str) -> dict:
    v = _varints(base64.b64decode(code))
    it = iter(v)
    if next(it) != 0:
        raise ValueError("не deckstring")
    if next(it) != 1:
        raise ValueError("неизвестная версия deckstring")
    fmt = next(it)
    heroes = [next(it) for _ in range(next(it))]
    cards = []
    for count in (1, 2):
        for _ in range(next(it)):
            cards.append((next(it), count))
    for _ in range(next(it)):
        dbf = next(it)
        cards.append((dbf, next(it)))
    return {"format": fmt, "heroes": heroes, "cards": cards}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(decode(sys.argv[1])))
