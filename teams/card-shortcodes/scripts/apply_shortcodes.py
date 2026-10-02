#!/usr/bin/env python3
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "python"))
from editorteam.card_shortcodes import apply_shortcodes
from editorteam.wordpress import load_catalog


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Insert only catalog-confirmed card shortcodes."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument(
        "--format",
        required=True,
        choices=["standard", "wild", "arena", "battlegrounds"],
    )
    parser.add_argument("--mentions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    temporary = None
    try:
        for original in (args.source, args.catalog, args.mentions):
            if original is not None and (
                args.output.resolve() == original.resolve()
                or (
                    args.output.exists()
                    and original.exists()
                    and args.output.samefile(original)
                )
            ):
                raise ValueError("output must differ from every input file")
        source = args.source.read_bytes().decode("utf-8")
        mentions = (
            json.loads(args.mentions.read_text(encoding="utf-8"))
            if args.mentions
            else None
        )
        if args.mentions and not isinstance(mentions, list):
            raise ValueError("mentions must be an array of reviewed spans")
        result = apply_shortcodes(
            source,
            catalog=load_catalog(args.catalog),
            game_format=args.format,
            mentions=mentions,
        )
        # Prepare the entire result before replacing an existing output.
        with tempfile.NamedTemporaryFile(
            dir=args.output.parent, delete=False
        ) as target:
            temporary = Path(target.name)
            target.write(result.text.encode("utf-8"))
        os.replace(temporary, args.output)
    except (ValueError, OSError, UnicodeError) as exc:
        parser.error(str(exc))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(
        json.dumps(
            {"inserted": result.inserted, "review": result.review}, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
