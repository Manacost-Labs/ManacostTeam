#!/usr/bin/env python3
"""Small authenticated HTTP facade for the read-only community source adapters."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from community_sources import ProviderError, build_parser, doctor, execute


HOST = os.environ.get("SOURCE_GATEWAY_HOST", "0.0.0.0")
PORT = int(os.environ.get("SOURCE_GATEWAY_PORT", "8777"))
SOURCE_GATEWAY_TOKEN = os.environ.get("SOURCE_GATEWAY_TOKEN", "").strip()
MAX_BODY_BYTES = 64 * 1024


def option_value(options: dict[str, Any], name: str, default: Any = None) -> Any:
    value = options.get(name, default)
    if value is None:
        return default
    if not isinstance(value, (str, int, bool)):
        raise ValueError(f"option {name} has an invalid type")
    return value


def command_argv(body: dict[str, Any]) -> list[str]:
    command = body.get("command")
    options = body.get("options", {})
    if not isinstance(command, str) or not isinstance(options, dict):
        raise ValueError("command and options are required")

    if command == "doctor":
        return ["doctor"]
    if command == "reddit-posts":
        argv = ["reddit-posts", "--subreddit", str(option_value(options, "subreddit", ""))]
        if not options.get("subreddit"):
            raise ValueError("subreddit is required")
        return argv + optional_args(
            options,
            {"sort": "top", "timeframe": "week", "limit": 25, "after": None},
        )
    if command == "reddit-search":
        query = option_value(options, "query", "")
        if not query:
            raise ValueError("query is required")
        argv = ["reddit-search", "--query", str(query)]
        if options.get("subreddit"):
            argv.extend(["--subreddit", str(options["subreddit"])])
        return argv + optional_args(
            options,
            {"sort": "relevance", "timeframe": "week", "limit": 25, "after": None},
        )
    if command == "reddit-comments":
        post_id = option_value(options, "post_id", "")
        if not post_id:
            raise ValueError("post_id is required")
        return ["reddit-comments", "--post-id", str(post_id)]
    if command == "x-search":
        query = option_value(options, "query", "")
        if not query:
            raise ValueError("query is required")
        argv = ["x-search", "--query", str(query)]
        if options.get("product"):
            argv.extend(["--product", str(options["product"])])
        if options.get("cursor"):
            argv.extend(["--cursor", str(options["cursor"])])
        return argv
    if command == "youtube-search":
        query = option_value(options, "query", "")
        if not query:
            raise ValueError("query is required")
        limit = int(option_value(options, "limit", 20))
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        return ["youtube-search", "--query", str(query), "--limit", str(limit)]
    if command == "youtube-transcript":
        video = option_value(options, "video", "")
        if not video:
            raise ValueError("video is required")
        argv = ["youtube-transcript", "--video", str(video)]
        if options.get("language"):
            argv.extend(["--language", str(options["language"])])
        return argv
    if command == "tinyfish-search":
        query = option_value(options, "query", "")
        if not query:
            raise ValueError("query is required")
        argv = ["tinyfish-search", "--query", str(query)]
        for name in ("location", "language", "include_domains", "exclude_domains"):
            if options.get(name):
                argv.extend([f"--{name.replace('_', '-')}", str(options[name])])
        page = int(option_value(options, "page", 0))
        if not 0 <= page <= 10:
            raise ValueError("page must be between 0 and 10")
        argv.extend(["--page", str(page)])
        return argv
    if command == "tinyfish-fetch":
        urls = options.get("urls")
        if not isinstance(urls, list) or not 1 <= len(urls) <= 10 or not all(
            isinstance(url, str) and url.startswith(("http://", "https://")) for url in urls
        ):
            raise ValueError("urls must contain 1-10 http(s) URLs")
        argv = ["tinyfish-fetch"]
        for url in urls:
            argv.extend(["--url", url])
        return argv
    if command == "stats-api":
        operation = option_value(options, "operation", "")
        if not operation:
            raise ValueError("operation is required")
        argv = ["stats-api", "--operation", str(operation)]
        if operation == "dataset":
            source_id = option_value(options, "source_id", "")
            allowed_characters = "abcdefghijklmnopqrstuvwxyz0123456789_-"
            if (
                not isinstance(source_id, str)
                or not source_id
                or len(source_id) > 128
                or any(character not in allowed_characters for character in source_id)
                or source_id[0] not in "abcdefghijklmnopqrstuvwxyz0123456789"
            ):
                raise ValueError("dataset source_id is invalid")
        for name in (
            "q",
            "class_name",
            "format_name",
            "source_id",
            "min_win_rate",
            "rank_range",
            "period",
            "min_games",
            "game_type",
            "mode",
            "tavern_tier",
        ):
            if options.get(name) is not None:
                argv.extend([f"--{name.replace('_', '-')}", str(options[name])])
        for name, default in (("limit", 50), ("offset", 0)):
            value = int(option_value(options, name, default))
            argv.extend([f"--{name}", str(value)])
        return argv
    raise ValueError("unsupported source command")


def optional_args(options: dict[str, Any], defaults: dict[str, Any]) -> list[str]:
    argv: list[str] = []
    for name, default in defaults.items():
        value = option_value(options, name, default)
        if value is None or value == default and name == "after":
            continue
        argv.extend([f"--{name}", str(value)])
    return argv


class SourceGatewayHandler(BaseHTTPRequestHandler):
    server_version = "ResearchSourceGateway/1.0"

    def log_message(self, _format: str, *_args: Any) -> None:
        # Queries and source URLs are user research data; keep them out of service logs.
        return

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def authorized(self) -> bool:
        presented = self.headers.get("X-Source-Gateway-Token", "").strip()
        return bool(SOURCE_GATEWAY_TOKEN) and secrets.compare_digest(
            presented, SOURCE_GATEWAY_TOKEN
        )

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        status = doctor()
        self.send_json(HTTPStatus.OK, {"ok": True, "providers": status})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/source":
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        if not self.authorized():
            self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid body size"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("body must be an object")
            args = build_parser().parse_args(command_argv(body))
            result = execute(args)
        except SystemExit:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid source options"})
            return
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        except ProviderError as exc:
            self.send_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": exc.as_dict()})
            return
        except Exception:
            self.send_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": "source request failed"})
            return
        self.send_json(HTTPStatus.OK, {"ok": True, "data": result})


def main() -> int:
    if not SOURCE_GATEWAY_TOKEN:
        print("SOURCE_GATEWAY_TOKEN is required", file=sys.stderr)
        return 2
    server = ThreadingHTTPServer((HOST, PORT), SourceGatewayHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
