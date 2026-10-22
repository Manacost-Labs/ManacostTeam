"""Sync/check the single source of contextual editorial practice data."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "editor/src/editorteam/editorial_practices.json"
TARGET = ROOT / "editor/go/internal/editorialreview/practices.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = SOURCE.read_bytes()
    if args.check:
        if not TARGET.exists() or TARGET.read_bytes() != data:
            parser.exit(1, "editorial practices drift: run tools/sync_editorial_practices.py\n")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_bytes(data)
    print("editorial practices: Python/Go catalog match")


if __name__ == "__main__":
    main()
