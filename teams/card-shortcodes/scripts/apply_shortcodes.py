#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "python"))
from editorteam.card_shortcodes import apply_shortcodes
from editorteam.wordpress import load_catalog

parser = argparse.ArgumentParser(description="Insert only catalog-confirmed card shortcodes.")
parser.add_argument("source", type=Path)
parser.add_argument("--catalog", type=Path, required=True)
parser.add_argument("--format", required=True, choices=["standard", "wild", "arena", "battlegrounds"])
parser.add_argument("--mentions", type=Path)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
if args.output.resolve() == args.source.resolve():
    parser.error("output must differ from source; preserve the original")
source = args.source.read_bytes().decode("utf-8")
mentions = json.loads(args.mentions.read_text(encoding="utf-8")) if args.mentions else None
result = apply_shortcodes(source, catalog=load_catalog(args.catalog), game_format=args.format, mentions=mentions)
args.output.write_bytes(result.text.encode("utf-8"))
print(json.dumps({"inserted": result.inserted, "review": result.review}, ensure_ascii=False))
