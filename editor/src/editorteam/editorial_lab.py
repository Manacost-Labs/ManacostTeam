"""Private MCP candidate corpus and human-calibrated blind editorial comparisons."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None:
        raise ValueError("public source URL required")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            parsed.query,
            "",
        )
    )


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def assemble_mcp_chunks(pages: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for page in pages:
        request, response = page["request"], page["response"]
        data = response["data"]
        if data.get("id") != request.get("id"):
            raise ValueError("MCP response/request ID mismatch")
        groups[data["id"]].append(page)
    articles = {}
    for content_id, chunks in groups.items():
        chunks.sort(key=lambda p: p["request"]["textOffset"])
        first = chunks[0]["response"]["data"]
        url = canonical_url(first["url"])
        access = first.get("metadata", {}).get("access")
        if access not in {"full", "public"}:
            raise ValueError(f"{content_id}: excerpt or unknown completeness")
        expected, pieces = 0, []
        total = first.get("textLength")
        if type(total) is not int or total <= 0:
            raise ValueError(f"{content_id}: full text length required")
        for index, chunk in enumerate(chunks):
            data = chunk["response"]["data"]
            offset = chunk["request"].get("textOffset")
            text = data.get("text")
            if (
                type(offset) is not int
                or offset != expected
                or not isinstance(text, str)
                or not text
            ):
                raise ValueError(f"{content_id}: missing, repeated or malformed chunk")
            if (
                data.get("textLength") != total
                or canonical_url(data["url"]) != url
                or data.get("metadata", {}).get("access") != access
                or data.get("fetchedAt") != first.get("fetchedAt")
            ):
                raise ValueError(f"{content_id}: source snapshot changed during pagination")
            pieces.append(text)
            expected += utf16_length(text)
            next_offset = data.get("nextOffset")
            if index < len(chunks) - 1 and (
                type(next_offset) is not int or next_offset != expected
            ):
                raise ValueError(f"{content_id}: inconsistent pagination")
            if index == len(chunks) - 1 and (next_offset is not None or expected != total):
                raise ValueError(f"{content_id}: incomplete text")
        text = "".join(pieces)
        article = {
            "id": content_id,
            "source": first.get("source"),
            "url": first["url"],
            "title": first.get("title"),
            "text": text,
            "published_at": first.get("publishedAt"),
            "updated_at": first.get("updatedAt"),
            "fetched_at": first.get("fetchedAt"),
            "retrieved_at": chunks[0]["response"].get("retrievedAt"),
            "access": access,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "review_status": "candidate",
            "factual_use": "requires_current_patch_verification",
            "split": "unassigned",
        }
        previous = articles.get(url)
        if previous is None or (access == "full" and previous["access"] != "full"):
            articles[url] = article
    return list(articles.values())


def blind_cases(rows: list[dict], seed: int) -> tuple[list[dict], list[dict]]:
    cases = defaultdict(list)
    seen = set()
    for row in rows:
        identity = (row["case_id"], row["variant"])
        if identity in seen or not row.get("text", "").strip():
            raise ValueError("duplicate variant or empty text")
        seen.add(identity)
        cases[row["case_id"]].append(row)
    rng, packet, key = random.Random(seed), [], []
    for case_id in sorted(cases):
        variants = cases[case_id]
        if (
            len(variants) < 2
            or "baseline" not in {r["variant"] for r in variants}
            or any(not isinstance(r.get("patch"), str) or not r["patch"].strip() for r in variants)
            or len({r.get("patch") for r in variants}) != 1
        ):
            raise ValueError("each case needs baseline, candidate and matching patch")
        rng.shuffle(variants)
        for index, row in enumerate(variants):
            blind_id = f"{case_id}:{index + 1}"
            packet.append(
                {
                    "blind_id": blind_id,
                    "case_id": case_id,
                    "text": row["text"],
                    "patch": row.get("patch"),
                    "review_status": "pending",
                    "editor_minutes": None,
                    "critical_errors": None,
                    "required_conditions_preserved": None,
                    "preference": None,
                    "comments": "",
                }
            )
            key.append({"blind_id": blind_id, "case_id": case_id, "variant": row["variant"]})
    return packet, key


def review_summary(rows: list[dict]) -> dict:
    reviewed = [r for r in rows if r.get("review_status") == "reviewed"]
    seen = set()
    for row in reviewed:
        identity = (row.get("case_id"), row.get("variant"))
        if identity in seen:
            raise ValueError("duplicate human review")
        seen.add(identity)
        minutes, errors = row.get("editor_minutes"), row.get("critical_errors")
        if (
            type(minutes) not in {int, float}
            or not math.isfinite(minutes)
            or minutes < 0
            or type(errors) is not int
            or errors < 0
        ):
            raise ValueError("reviewed samples require measured minutes and error counts")
    return {
        "samples": len(rows),
        "reviewed": len(reviewed),
        "pending": len(rows) - len(reviewed),
        "editor_minutes": sum(r["editor_minutes"] for r in reviewed) if reviewed else None,
        "critical_errors": sum(r["critical_errors"] for r in reviewed) if reviewed else None,
        "publication_approved": False,
    }


def write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("import-mcp", "blind", "summarize"):
        command = sub.add_parser(name)
        command.add_argument("input", type=Path)
        command.add_argument("--output", type=Path, required=True)
        if name == "blind":
            command.add_argument("--key", type=Path, required=True)
            command.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    try:
        rows = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("input must be a JSON array")
        if args.command == "import-mcp":
            write_new(args.output, assemble_mcp_chunks(rows))
        elif args.command == "blind":
            packet, key = blind_cases(rows, args.seed)
            if (
                args.output.resolve() == args.key.resolve()
                or args.output.exists()
                or args.key.exists()
            ):
                raise ValueError("blind packet and key need separate new files")
            write_new(args.output, packet)
            write_new(args.key, key)
        else:
            write_new(args.output, review_summary(rows))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
