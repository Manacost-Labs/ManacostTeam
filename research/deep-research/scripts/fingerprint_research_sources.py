#!/usr/bin/env python3
"""Verify and optionally record SHA-256 fingerprints for local source snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Schema 1.1 research bundle directory")
    parser.add_argument("--apply", action="store_true", help="Write verified fingerprints")
    parser.add_argument(
        "--require-all", action="store_true", help="Fail when any mutable source lacks a snapshot"
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write(path: Path, text: str) -> None:
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"{path.name}:{line_number}: record must be an object")
        records.append(item)
    return records


def main() -> int:
    args = parse_args()
    root = Path(args.directory).expanduser().resolve()
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        sources = load_jsonl(root / "sources.jsonl")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if manifest.get("schema_version") not in {"1.1", "1.2"}:
        print("error: fingerprinting requires schema 1.1 or 1.2", file=sys.stderr)
        return 2

    verified = 0
    missing: list[str] = []
    changed = False
    for source in sources:
        if source.get("mutable") is not True:
            continue
        snapshot_value = source.get("snapshot_path")
        if not isinstance(snapshot_value, str) or not snapshot_value:
            missing.append(str(source.get("source_id", "unknown")))
            continue
        snapshot = (root / snapshot_value).resolve()
        if not snapshot.is_relative_to(root):
            print(
                f"error: snapshot escapes bundle: {source.get('source_id')}", file=sys.stderr
            )
            return 2
        if not snapshot.is_file():
            missing.append(str(source.get("source_id", "unknown")))
            continue
        payload = snapshot.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        verified += 1
        if args.apply:
            source["content_sha256"] = digest
            source["content_bytes"] = len(payload)
            source["fingerprinted_at"] = utc_now()
            source["fingerprint_status"] = "verified"
            source.pop("fingerprint_reason", None)
            changed = True

    print(
        f"Source fingerprint check: {verified} verified, {len(missing)} missing, apply={args.apply}"
    )
    if missing:
        print(f"Missing snapshots: {', '.join(missing)}")
    if args.apply and changed:
        text = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in sources)
        atomic_write(root / "sources.jsonl", text)
    if args.require_all and missing:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

