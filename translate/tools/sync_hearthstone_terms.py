"""Fetch EN/RU Hearthstone entity names for one explicit HearthstoneJSON build."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen


BASE_URL = "https://api.hearthstonejson.com/v1/{build}/{locale}/cards.json"


def fetch(build: str, locale: str) -> list[dict]:
    request = Request(
        BASE_URL.format(build=build, locale=locale),
        headers={"User-Agent": "TranslateTeam/1.0"},
    )
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def clean(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", required=True, help="Numeric HearthstoneJSON build; do not use latest for a published article.")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "hearthstone-names.en-ru.tsv")
    args = parser.parse_args()
    try:
        english = {card["id"]: card for card in fetch(args.build, "enUS") if card.get("id")}
        russian = {card["id"]: card for card in fetch(args.build, "ruRU") if card.get("id")}
    except Exception as error:
        print(f"Could not download HearthstoneJSON: {error}", file=sys.stderr)
        return 1

    rows = []
    for card_id in sorted(english.keys() & russian.keys()):
        source = str(english[card_id].get("name") or "").strip()
        target = str(russian[card_id].get("name") or "").strip()
        if source and target:
            card = english[card_id]
            comment = (
                f"id={card_id}; type={card.get('type', '')}; class={card.get('cardClass', '')}; "
                f"set={card.get('set', '')}; build={args.build}"
            )
            rows.append((source, target, comment))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as output:
        for row in sorted(rows, key=lambda item: (item[0].casefold(), item[2])):
            output.write("\t".join(clean(value) for value in row) + "\n")
    print(f"Wrote {len(rows)} pairs to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
