#!/usr/bin/env python3
"""Fetch a public page into a research bundle with a verified snapshot.

The script opens one URL without cookies or credentials, extracts readable
text, stores it under ``snapshots/``, computes the SHA-256 fingerprint, and
appends a schema 1.1 source record to ``sources.jsonl``. With ``--query-id`` it
also links the new source to the query that found it.

It refuses URLs that carry credentials, non-HTTP schemes, and private or
loopback hosts unless ``--allow-private`` is given. It never follows a login,
paywall, or consent flow. A page that requires JavaScript, authentication, or a
binary format must be recorded manually with an honest ``access_integrity``.

Use ``--file`` to ingest a page already saved by the host tool without
network access; the URL is then recorded as requested and final.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from candidates import record_candidate
from search_support import canonical_url, lineage_hint, next_id

MAX_RESPONSE_BYTES = 5_000_000
MIN_READABLE_CHARS = 300
JS_SHELL_MARKERS = (
    "enable javascript",
    "javascript is required",
    "javascript is disabled",
    "please enable js",
    "turn on javascript",
)
DEFAULT_TIMEOUT_SECONDS = 20.0
USER_AGENT = "deep-research-fetch-source/1.0 (read-only research snapshot)"
TEXT_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/json")
SKIPPED_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "head"})
BLOCK_TAGS = frozenset(
    {
        "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
        "tr", "td", "th", "table", "section", "article", "header", "footer",
        "blockquote", "pre", "hr", "figure", "figcaption", "dd", "dt", "dl",
        "main", "nav", "aside", "form", "summary", "details",
    }
)
SOURCE_TYPES = (
    "official",
    "official_law",
    "official_social",
    "statistics",
    "dataset",
    "expert",
    "guide",
    "community",
    "forum",
    "video",
    "interview",
    "news",
    "localization",
    "tournament_report",
    "other",
)
CHARSET_RE = re.compile(r"charset=([\w.-]+)", re.IGNORECASE)
META_CHARSET_RE = re.compile(rb"<meta[^>]+charset=[\"']?([\w.-]+)", re.IGNORECASE)

Transport = Callable[[Request, float], tuple[int, str, Mapping[str, str], bytes]]


class FetchError(RuntimeError):
    """A fetch that must not silently produce a source record."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIPPED_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
            return
        if self._skip_depth:
            return
        self.parts.append(data)


def html_to_text(markup: str) -> tuple[str | None, str]:
    """Return ``(title, text)`` with scripts, styles, and markup removed."""

    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    title = " ".join("".join(parser.title_parts).split()) or None
    raw = "".join(parser.parts)
    lines = [" ".join(line.split()) for line in raw.splitlines()]
    collapsed: list[str] = []
    blank = 0
    for line in lines:
        if line:
            collapsed.append(line)
            blank = 0
        elif blank < 1:
            collapsed.append("")
            blank += 1
    return title, "\n".join(collapsed).strip() + "\n"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def check_url(url: str, *, allow_private: bool) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchError("only http and https URLs can be fetched")
    if not parts.hostname:
        raise FetchError("URL has no host")
    if parts.username or parts.password:
        raise FetchError("URL carries credentials; never fetch authenticated URLs")
    host = parts.hostname.lower()
    if allow_private:
        return
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise FetchError("private host refused; pass --allow-private for a local mirror")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise FetchError("private or reserved IP refused; pass --allow-private for a local mirror")


def _urllib_transport(request: Request, timeout: float) -> tuple[int, str, Mapping[str, str], bytes]:
    try:
        with urlopen(request, timeout=timeout) as response:
            return (
                response.status,
                response.geturl(),
                dict(response.headers.items()),
                response.read(MAX_RESPONSE_BYTES + 1),
            )
    except HTTPError as exc:
        return exc.code, exc.geturl() or request.full_url, dict(exc.headers.items()), b""
    except URLError as exc:
        raise FetchError(f"request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise FetchError("request timed out") from exc


def decode_body(body: bytes, content_type: str) -> str:
    match = CHARSET_RE.search(content_type) or META_CHARSET_RE.search(body[:4096])
    encoding = "utf-8"
    if match:
        candidate = match.group(1)
        encoding = candidate.decode("ascii", "ignore") if isinstance(candidate, bytes) else candidate
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def fetch(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """Fetch ``url`` and return status, final URL, content type, and decoded body."""

    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,application/json;q=0.8",
            "Accept-Language": "en,ru;q=0.8,zh;q=0.6",
        },
        method="GET",
    )
    status, final_url, headers, body = (transport or _urllib_transport)(request, timeout)
    content_type = ""
    for name, value in headers.items():
        if name.lower() == "content-type":
            content_type = value
            break
    if status != 200:
        raise FetchError(f"HTTP {status}; record the access failure manually if it matters")
    if len(body) > MAX_RESPONSE_BYTES:
        raise FetchError(f"response exceeds {MAX_RESPONSE_BYTES} bytes")
    lowered = content_type.lower()
    if content_type and not lowered.startswith(TEXT_CONTENT_TYPES):
        raise FetchError(f"unsupported content type {content_type!r}; save the text manually")
    return {
        "http_status": status,
        "final_url": final_url,
        "content_type": content_type.split(";")[0].strip() or "unknown",
        "body": decode_body(body, content_type),
    }


def build_snapshot(
    *,
    title: str,
    requested_url: str,
    final_url: str,
    accessed_at: str,
    content_type: str,
    text: str,
) -> str:
    return (
        f"Source: {title}\n"
        f"URL: {final_url}\n"
        f"Requested: {requested_url}\n"
        f"Canonical: {canonical_url(final_url)}\n"
        f"Accessed: {accessed_at} via fetch_source.py\n"
        f"Content-Type: {content_type}\n"
        "\n"
        f"{text}"
    )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            if isinstance(item, dict):
                records.append(item)
    return records


def atomic_write(path: Path, text: str) -> None:
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def find_duplicate(sources: list[dict[str, Any]], url: str) -> str | None:
    target = canonical_url(url)
    for record in sources:
        for field in ("canonical_url", "final_url", "requested_url", "url"):
            value = record.get(field)
            if isinstance(value, str) and value and canonical_url(value) == target:
                return str(record.get("source_id", "?"))
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Schema 1.1 or 1.2 research bundle directory")
    parser.add_argument("url", nargs="?", help="Public http(s) URL of the source")
    parser.add_argument(
        "--refresh",
        metavar="SOURCE_ID",
        help="Re-fetch an existing source's final_url and replace its snapshot and fingerprint",
    )
    parser.add_argument("--file", help="Local HTML/text file to ingest instead of fetching")
    parser.add_argument("--title", help="Override the page title")
    parser.add_argument("--source-type", default="other", choices=SOURCE_TYPES)
    parser.add_argument("--platform", help="Platform label such as forum, reddit, youtube")
    parser.add_argument("--author")
    parser.add_argument("--publisher")
    parser.add_argument("--published-at", help="Publication date, ISO-8601")
    parser.add_argument(
        "--lineage", help="Lineage ID of the upstream origin; default derives from the URL"
    )
    parser.add_argument(
        "--immutable", action="store_true", help="Mark the source as immutable (default mutable)"
    )
    parser.add_argument("--query-id", help="Link the source to this query's result_source_ids")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--allow-private", action="store_true")
    parser.add_argument(
        "--allow-duplicate", action="store_true", help="Record even if the URL already exists"
    )
    parser.add_argument("--apply", action="store_true", help="Write snapshot and source record")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, transport: Transport | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.directory).expanduser().resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        print(f"error: not a research bundle: {root}", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sources = load_jsonl(root / "sources.jsonl")
        queries = load_jsonl(root / "queries.jsonl")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if manifest.get("schema_version") not in {"1.1", "1.2"}:
        print("error: fetch_source requires a schema 1.1 or 1.2 bundle", file=sys.stderr)
        return 2

    refresh_target: dict[str, Any] | None = None
    if args.refresh:
        refresh_target = next((item for item in sources if item.get("source_id") == args.refresh), None)
        if refresh_target is None:
            print(f"error: unknown source {args.refresh}", file=sys.stderr)
            return 2
        if args.url:
            print("error: --refresh takes the URL from the existing record; omit the URL", file=sys.stderr)
            return 2
        args.url = str(refresh_target.get("final_url") or refresh_target.get("requested_url") or "")
    if not args.url:
        print("error: a URL or --refresh SOURCE_ID is required", file=sys.stderr)
        return 2
    try:
        check_url(args.url, allow_private=args.allow_private)
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    duplicate = None if refresh_target else find_duplicate(sources, args.url)
    if duplicate and not args.allow_duplicate:
        print(f"error: URL already recorded as {duplicate}; pass --allow-duplicate to add another record", file=sys.stderr)
        return 1

    query_record: dict[str, Any] | None = None
    if args.query_id:
        query_record = next((item for item in queries if item.get("query_id") == args.query_id), None)
        if query_record is None:
            print(f"error: unknown query {args.query_id}", file=sys.stderr)
            return 2

    accessed_at = utc_now()
    try:
        if args.file:
            body = Path(args.file).read_text(encoding="utf-8", errors="replace")
            fetched = {
                "http_status": None,
                "final_url": args.url,
                "content_type": "text/html" if "<" in body[:2048] else "text/plain",
                "body": body,
            }
        else:
            fetched = fetch(args.url, timeout=args.timeout, transport=transport)
    except (FetchError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if fetched["content_type"].startswith("text/html") or "<html" in fetched["body"][:2048].lower():
        page_title, text = html_to_text(fetched["body"])
    else:
        page_title, text = None, fetched["body"].strip() + "\n"
    if not text.strip():
        print("error: no readable text extracted; the page may need JavaScript", file=sys.stderr)
        return 1
    lowered_text = text.casefold()
    if len(text.strip()) < MIN_READABLE_CHARS or any(marker in lowered_text for marker in JS_SHELL_MARKERS):
        print(
            "error: too little readable text; the page is probably a JavaScript shell or a block page. "
            "Save the rendered page from the host tool and ingest it with --file, or record the "
            "access limit manually.",
            file=sys.stderr,
        )
        return 1
    fallback_title = str(refresh_target.get("title", "")) if refresh_target else ""
    if not fallback_title and not fetched["content_type"].startswith("text/html"):
        # Machine-readable documents (JSON, plain text) have no <title>; name them by URL.
        fallback_title = urlsplit(fetched["final_url"]).path.rstrip("/").rsplit("/", 1)[-1] or fetched["final_url"]
    title = (args.title or page_title or fallback_title).strip()
    if not title:
        print("error: no title found; pass --title", file=sys.stderr)
        return 1

    existing_ids = {str(item.get("source_id")) for item in sources if item.get("source_id")}
    source_id = str(refresh_target["source_id"]) if refresh_target else next_id("SRC", existing_ids)
    snapshot_relative = f"snapshots/{source_id}.txt"
    snapshot_text = build_snapshot(
        title=title,
        requested_url=args.url,
        final_url=fetched["final_url"],
        accessed_at=accessed_at,
        content_type=fetched["content_type"],
        text=text,
    )
    payload = snapshot_text.encode("utf-8")
    record: dict[str, Any] = {
        "source_id": source_id,
        "title": title,
        "requested_url": args.url,
        "final_url": fetched["final_url"],
        "canonical_url": canonical_url(fetched["final_url"]),
        "accessed_at": accessed_at,
        "access_integrity": "full",
        "source_type": args.source_type,
        "lineage_id": args.lineage or lineage_hint(fetched["final_url"]),
        "mutable": not args.immutable,
        "fingerprint_status": "verified",
        "snapshot_path": snapshot_relative,
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "content_bytes": len(payload),
        "fingerprinted_at": accessed_at,
        "retrieved_by": "fetch_source.py" + (" --file" if args.file else ""),
        "content_type": fetched["content_type"],
    }
    if fetched["http_status"] is not None:
        record["http_status"] = fetched["http_status"]
    for field in ("platform", "author", "publisher", "published_at"):
        value = getattr(args, field)
        if value:
            record[field] = value
    if query_record is not None:
        record["found_by_query_ids"] = [args.query_id]
    if refresh_target is not None:
        # Keep the researcher's descriptive fields; replace only access and fingerprint facts.
        merged = dict(refresh_target)
        for field in (
            "final_url", "canonical_url", "accessed_at", "access_integrity", "fingerprint_status",
            "snapshot_path", "content_sha256", "content_bytes", "fingerprinted_at", "retrieved_by",
            "content_type", "http_status",
        ):
            if field in record:
                merged[field] = record[field]
        merged.pop("fingerprint_reason", None)
        merged["title"] = merged.get("title") or record["title"]
        merged["previous_snapshot_refreshed_at"] = accessed_at
        record = merged

    if not args.apply:
        print(json.dumps({"preview": record, "text_excerpt": text[:600]}, ensure_ascii=False, indent=2))
        print("Preview only; use --apply to write the snapshot and source record")
        return 0

    (root / "snapshots").mkdir(exist_ok=True)
    snapshot_path = root / snapshot_relative
    if snapshot_path.exists() and refresh_target is None:
        print(f"error: snapshot already exists: {snapshot_relative}", file=sys.stderr)
        return 1
    snapshot_path.write_bytes(payload)
    if refresh_target is not None:
        replaced = [record if item.get("source_id") == source_id else item for item in sources]
        atomic_write(
            root / "sources.jsonl",
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in replaced),
        )
    else:
        with (root / "sources.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    if query_record is not None:
        linked = query_record.get("result_source_ids")
        if not isinstance(linked, list):
            linked = []
        if source_id not in linked:
            linked.append(source_id)
        query_record["result_source_ids"] = linked
        atomic_write(
            root / "queries.jsonl",
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in queries),
        )
        record_candidate(
            root,
            query_id=args.query_id,
            url=args.url,
            decision="opened",
            source_id=source_id,
            title=title,
        )
    verb = "Refreshed" if refresh_target is not None else "Recorded"
    print(
        f"{verb} {source_id}: {record['title']} ({record['content_bytes']} bytes, "
        f"sha256 {record['content_sha256'][:12]}...)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
