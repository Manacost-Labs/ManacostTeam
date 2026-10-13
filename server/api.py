"""Authenticated transport adapter for the existing editor/translation services."""

from __future__ import annotations

import hmac
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
from manacost_context import ROOT, load_catalog, resolve_context  # noqa: E402

MAX_BODY = 512 * 1024
ROUTES = {
    "/v1/editor/analyze": ("analyzer", "/analyze"),
    "/v1/editor/edit": ("editor", "/v2/edit"),
    "/v1/translate/prepare": ("translator", "/prepare"),
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class APIServer(ThreadingHTTPServer):
    """Bound concurrent requests and time spent waiting for HTTP headers/bodies."""

    def __init__(self, *args, **kwargs):
        self.slots = BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(15)
        return request, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            body = b'{"error":"too many concurrent requests"}'
            try:
                request.sendall(
                    b"HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\n\r\n"
                    + body
                )
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def forward(url: str, payload: dict) -> tuple[int, dict]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        response = build_opener(NoRedirect).open(request, timeout=150)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("upstream response is too large")
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("upstream response must be an object")
        return response.status, body


def prepare_request(path: str, value: dict, default_game: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError("request must be a JSON object")
    allowed = {"game", "patch", "text", "genre", "product", "mode"}
    if set(value) - allowed:
        raise ValueError(
            "unknown fields; use game, patch, text, genre, product and mode"
        )
    text = value.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("nonempty text is required")
    if not isinstance(value.get("game", default_game), str):
        raise ValueError("game must be a canonical game ID")
    if value.get("genre") is not None and not isinstance(value["genre"], str):
        raise ValueError("genre must be a string")
    context = resolve_context(
        ROOT,
        game=value.get("game", default_game),
        execution="server",
        patch=value.get("patch"),
    )
    result = {"text": text, "task_context": context}
    if path == "/v1/translate/prepare":
        if value.get("genre") is not None or value.get("mode") is not None:
            raise ValueError("genre/mode do not apply to translation preparation")
        if context["patch"] is None:
            raise ValueError("translation requires an exact patch/build")
        product = value.get("product")
        if context["game"]["id"] == "world-of-warcraft":
            if not isinstance(product, str) or not product.strip() or len(product) > 80:
                raise ValueError("WoW translation requires product")
            result["product"] = product
        elif product is not None:
            raise ValueError("product is only supported for WoW")
    else:
        if value.get("product") is not None:
            raise ValueError("product applies only to WoW translation preparation")
        genre = value.get("genre")
        canonical = context["game"]["id"]
        if canonical not in ("hearthstone", "world-of-warcraft"):
            genre = genre or "game-guide"
            if genre not in ("game-guide", "game-article", "news"):
                raise ValueError(
                    "choose game-guide, game-article or news for this game"
                )
        if genre:
            result["profile"] = genre
        if path.endswith("/edit"):
            mode = value.get("mode", "proofread")
            if mode not in ("proofread", "edit", "rewrite"):
                raise ValueError("mode must be proofread, edit or rewrite")
            result["mode"] = mode
        elif value.get("mode") is not None:
            raise ValueError("mode applies only to editor/edit")
    return result


class Handler(BaseHTTPRequestHandler):
    token = b""
    default_game = "hearthstone"
    upstreams = {}

    def log_message(self, fmt, *args):
        # Neither credentials nor submitted text are logged.
        sys.stderr.write(f"{self.command} {self.path.split('?')[0]}\n")

    def send(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "").encode()
        if not self.token or not hmac.compare_digest(supplied, b"Bearer " + self.token):
            self.send(401, {"error": "API token required"})
            return False
        return True

    def do_GET(self):
        if self.path == "/health":
            self.send(200, {"ok": True})
        elif self.authorized():
            if self.path == "/v1/games":
                games, _ = load_catalog(ROOT, "games")
                self.send(
                    200,
                    {
                        "games": list(games.values()),
                        "default_game": self.default_game,
                        "profile": "manacost",
                    },
                )
            else:
                self.send(404, {"error": "unknown endpoint"})

    def do_POST(self):
        if not self.authorized():
            return
        if self.path not in ROUTES:
            self.send(404, {"error": "unknown endpoint"})
            return
        try:
            self.connection.settimeout(15)
            if self.headers.get("Transfer-Encoding") or self.headers.get(
                "Content-Encoding"
            ):
                raise ValueError("encoded/chunked bodies are not supported")
            if (
                self.headers.get("Content-Type", "").split(";")[0].strip()
                != "application/json"
            ):
                self.send(415, {"error": "application/json required"})
                return
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BODY:
                self.send(413, {"error": "body must be between 1 and 524288 bytes"})
                return
            value = json.loads(self.rfile.read(size))
            payload = prepare_request(self.path, value, self.default_game)
        except (ValueError, OSError) as error:
            self.send(400, {"error": str(error)})
            return
        service, route = ROUTES[self.path]
        try:
            status, body = forward(self.upstreams[service] + route, payload)
            self.send(status, body)
        except (ValueError, OSError, URLError):
            self.send(502, {"error": "service unavailable or invalid service response"})


def main():
    Handler.token = Path(os.environ["MANACOST_TOKEN_FILE"]).read_bytes().strip()
    if not re.fullmatch(rb"[A-Za-z0-9_-]{32,}", Handler.token):
        raise ValueError("API token must contain at least 32 URL-safe ASCII characters")
    Handler.default_game = os.getenv("MANACOST_GAME", "hearthstone")
    resolve_context(ROOT, game=Handler.default_game)
    Handler.upstreams = {
        name: os.getenv(f"MANACOST_{name.upper()}_URL", default).rstrip("/")
        for name, default in (
            ("analyzer", "http://127.0.0.1:8731"),
            ("editor", "http://127.0.0.1:8740"),
            ("translator", "http://127.0.0.1:8787"),
        )
    }
    with APIServer(
        (
            os.getenv("MANACOST_HOST", "127.0.0.1"),
            int(os.getenv("MANACOST_PORT", "8800")),
        ),
        Handler,
    ) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
