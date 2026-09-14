"""Join EN and RU World of Warcraft client exports by immutable entity ID."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def read_tsv(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines:
        raise ValueError(f"{path} is empty")
    headers = lines[0].split("\t")
    if not {"id", "name"}.issubset(headers):
        raise ValueError(f"{path} must start with id and name columns")
    id_index, name_index = headers.index("id"), headers.index("name")
    values = {}
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) > max(id_index, name_index) and fields[id_index].strip() and fields[name_index].strip():
            values[fields[id_index].strip()] = fields[name_index].strip()
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--en", required=True, type=Path, help="enUS UTF-8 TSV with id and name columns")
    parser.add_argument("--ru", required=True, type=Path, help="ruRU UTF-8 TSV with id and name columns")
    parser.add_argument("--product", required=True, help="retail, classic-era, or another explicit client product")
    parser.add_argument("--build", required=True, help="Exact client build")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "world-of-warcraft-names.en-ru.tsv")
    args = parser.parse_args()
    try:
        english, russian = read_tsv(args.en), read_tsv(args.ru)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2

    shared = sorted(set(english) & set(russian), key=str)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as output:
        for entity_id in shared:
            output.write(
                f"{english[entity_id].replace(chr(9), ' ')}\t{russian[entity_id].replace(chr(9), ' ')}"
                f"\tid={entity_id}; product={args.product}; build={args.build}\n"
            )
    print(f"Wrote {len(shared)} EN/RU WoW pairs to {args.out}")
    print(f"Unmatched: enUS={len(set(english) - set(russian))}; ruRU={len(set(russian) - set(english))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
