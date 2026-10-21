#!/usr/bin/env python3
"""Secret-safe Scrape.do search and public-page access for research."""

from __future__ import annotations

import argparse
import gzip
import ipaddress
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

KEY_NAMES = ("SCRAPE_DO_API_TOKEN", "TRANSCRIPTAPI_TOKEN", "REDDITAPIS_KEY")
MAX_BYTES = 8_000_000


def credential_path() -> Path:
    override = os.environ.get("MANACOST_SOURCE_CREDENTIALS")
    if override:
        return Path(override).expanduser()
    return (
        Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        / "Manacost/secrets/source-providers.json"
    )


def load_credentials() -> dict[str, bool]:
    """Environment wins; local machine-only file is optional and never echoed."""
    try:
        payload = json.loads(credential_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    if isinstance(payload, dict):
        for name in KEY_NAMES:
            if (
                not os.environ.get(name)
                and isinstance(payload.get(name), str)
                and payload[name].strip()
            ):
                os.environ[name] = payload[name].strip()
    return {name: bool(os.environ.get(name)) for name in KEY_NAMES}


class AccessError(RuntimeError):
    def __init__(self, code: str, status: int | None = None):
        self.code, self.status = code, status
        super().__init__(code)


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: scrub(v)
            for k, v in value.items()
            if not any(
                s in k.casefold()
                for s in ("token", "authorization", "api_key", "cookie")
            )
        }
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        for name in KEY_NAMES:
            secret = os.environ.get(name)
            if secret:
                value = value.replace(secret, "[REDACTED]")
    return value


def public_url(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        raise AccessError("PUBLIC_HTTPS_URL_REQUIRED")
    if host in {"localhost", "api.scrape.do"} or host.endswith(
        (".local", ".localhost")
    ):
        raise AccessError("PUBLIC_HTTPS_URL_REQUIRED")
    try:
        if not ipaddress.ip_address(host).is_global:
            raise AccessError("PUBLIC_HTTPS_URL_REQUIRED")
    except ValueError:
        pass
    if re.search(r"(?:token|api_key|password|signature)=", parts.query, re.IGNORECASE):
        raise AccessError("CREDENTIAL_FREE_TARGET_REQUIRED")
    return url


def request(
    path: str, params: dict[str, Any], *, timeout: float = 60.0
) -> tuple[bytes, dict[str, Any]]:
    load_credentials()
    token = os.environ.get("SCRAPE_DO_API_TOKEN", "")
    if not token:
        raise AccessError("SCRAPE_DO_NOT_CONFIGURED")
    if path not in {"/", "/plugin/google/search"}:
        raise AccessError("UNSUPPORTED_OPERATION")
    query = {"token": token, **params}
    # The only token-bearing URL exists inside this transport boundary.
    req = Request(
        "https://api.scrape.do" + path + "?" + urlencode(query),
        headers={"User-Agent": "ManacostResearch/1.0", "Accept-Encoding": "gzip"},
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            data = response.read(MAX_BYTES + 1)
            headers = response.headers
            status = response.status
    except HTTPError as exc:
        # transparentResponse forwards target failures; keep target and provider distinct.
        if path == "/" and exc.headers.get("Scrape.do-Initial-Status-Code"):
            data = exc.read(MAX_BYTES + 1)
            headers, status = exc.headers, exc.code
        else:
            raise AccessError("PROVIDER_HTTP_ERROR", exc.code) from None
    except (URLError, OSError, TimeoutError):
        raise AccessError("PROVIDER_NETWORK_ERROR") from None
    if len(data) > MAX_BYTES:
        raise AccessError("RESPONSE_TOO_LARGE")
    if headers.get("Content-Encoding", "").lower() == "gzip":
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError):
            raise AccessError("INVALID_GZIP") from None
        if len(data) > MAX_BYTES:
            raise AccessError("RESPONSE_TOO_LARGE")
    meta = {
        "provider_status": status,
        "target_status": headers.get("Scrape.do-Initial-Status-Code"),
        "credits": headers.get("Scrape.do-Request-Cost"),
        "remaining_credits": headers.get("Scrape.do-Remaining-Credits"),
        "content_type": headers.get("Content-Type", ""),
        "collected_at": datetime.now(UTC).isoformat(),
    }
    return data, meta


def search(
    query: str,
    *,
    site: str | None = None,
    language: str = "en",
    country: str = "us",
    start: int = 0,
) -> dict[str, Any]:
    if not query.strip() or not 0 <= start <= 100:
        raise AccessError("INVALID_QUERY_OR_OFFSET")
    if site and not re.fullmatch(r"[A-Za-z0-9.-]+", site):
        raise AccessError("INVALID_SITE_FILTER")
    effective = f"site:{site} {query}" if site else query
    data, meta = request(
        "/plugin/google/search",
        {
            "q": effective,
            "hl": language,
            "gl": country,
            "start": start,
            "cache": "true",
            "resolveGoto": "true",
        },
    )
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise AccessError("INVALID_SEARCH_JSON") from None
    if not isinstance(payload, dict) or not isinstance(
        payload.get("organic_results"), list
    ):
        raise AccessError("INVALID_SEARCH_SHAPE")
    results = [
        {
            "url": row.get("link"),
            "title": row.get("title"),
            "snippet": row.get("snippet"),
            "position": row.get("position"),
            "evidence_status": "discovery_only",
        }
        for row in payload["organic_results"]
        if isinstance(row, dict)
    ]
    outside = []
    if site:
        scope = site.lower().removeprefix("www.")
        outside = [
            row
            for row in results
            if not (
                (urlsplit(row.get("url") or "").hostname or "")
                .lower()
                .removeprefix("www.")
                == scope
                or (urlsplit(row.get("url") or "").hostname or "")
                .lower()
                .endswith("." + scope)
            )
        ]
        results = [row for row in results if row not in outside]
    return scrub(
        {
            "provider": "scrape.do",
            "operation": "google-search",
            "query": effective,
            "language": language,
            "country": country,
            "start": start,
            "results": results,
            "out_of_scope_results": outside,
            "search_information": payload.get("search_information", {}),
            "diagnostics": meta,
        }
    )


def fetch(
    url: str,
    *,
    render: bool = False,
    super_proxy: bool | None = None,
    wait_ms: int = 0,
    country: str | None = None,
) -> dict[str, Any]:
    from chinese_hearthstone import SourceProfile, validate_content

    target = public_url(url)
    host = (urlsplit(target).hostname or "").removeprefix("www.")
    if super_proxy is None:
        protected = (
            "reddit.com",
            "hsguru.com",
            "nga.cn",
            "ngabbs.com",
            "nga.178.com",
            "ptt.cc",
            "gamer.com.tw",
            "iyingdi.com",
            "bilibili.com",
            "note.com",
            "hearthpwn.com",
        )
        super_proxy = any(
            host == domain or host.endswith("." + domain) for domain in protected
        )
    if not 0 <= wait_ms <= 10000 or country and not re.fullmatch(r"[a-z]{2}", country):
        raise AccessError("INVALID_BROWSER_WAIT_OR_COUNTRY")
    params = {"url": target, "disableRetry": "true", "transparentResponse": "true"}
    if render:
        params["render"] = "true"
    if super_proxy:
        params["super"] = "true"
    if render and wait_ms:
        params["customWait"] = str(wait_ms)
    if country:
        params["geoCode"] = country
    data, meta = request("/", params)
    charset = re.search(r"charset=([\w-]+)", meta["content_type"], re.IGNORECASE)
    try:
        text = data.decode(charset[1] if charset else "utf-8", errors="replace")
    except LookupError:
        text = data.decode("utf-8", errors="replace")
    status = int(meta["target_status"] or meta["provider_status"])
    profile = SourceProfile(
        "public-research", "Public research", (urlsplit(url).hostname,), "article", 180
    )
    validation = validate_content(
        text, profile, status_code=status, content_type=meta["content_type"]
    )
    return scrub(
        {
            "provider": "scrape.do",
            "operation": "public-fetch",
            "url": target,
            "status": validation.status.value,
            "reasons": validation.reasons,
            "title": validation.title,
            "text": validation.clean_text,
            "diagnostics": meta,
            "render": render,
            "super_proxy": super_proxy,
        }
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    s = sub.add_parser("search")
    s.add_argument("--query", required=True)
    s.add_argument("--site")
    s.add_argument("--language", default="en")
    s.add_argument("--country", default="us")
    s.add_argument("--start", type=int, default=0)
    s.add_argument("--output", type=Path)
    f = sub.add_parser("fetch")
    f.add_argument("--url", required=True)
    f.add_argument("--render", action="store_true")
    f.add_argument("--super-proxy", action=argparse.BooleanOptionalAction, default=None)
    f.add_argument("--wait-ms", type=int, default=0)
    f.add_argument("--country")
    f.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    try:
        if args.command == "doctor":
            result = load_credentials()
        elif args.command == "search":
            result = search(
                args.query,
                site=args.site,
                language=args.language,
                country=args.country,
                start=args.start,
            )
        else:
            result = fetch(
                args.url,
                render=args.render,
                super_proxy=args.super_proxy,
                wait_ms=args.wait_ms,
                country=args.country,
            )
        if getattr(args, "output", None):
            from source_library import write_json

            write_json(args.output, result)
            print(json.dumps({"saved": str(args.output), "provider": "scrape.do"}))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") not in (None, "SUCCESS") else 0
    except AccessError as exc:
        print(json.dumps({"error": exc.code, "status": exc.status}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
