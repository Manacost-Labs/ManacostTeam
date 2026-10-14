import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.api import APIServer, Handler, prepare_request  # noqa: E402


class ServerAPITests(unittest.TestCase):
    def test_rejection_drains_unread_request_before_socket_close(self):
        request = Mock()
        request.recv.side_effect = [b"GET /health HTTP/1.0\r\n\r\n", b""]
        self.api.shutdown_request(request)
        request.recv.assert_called()
        self.assertLessEqual(request.recv.call_count, 9)
        self.assertLessEqual(request.settimeout.call_args.args[0], 0.1)
        calls = [call[0] for call in request.mock_calls]
        self.assertLess(calls.index("recv"), calls.index("close"))

    def test_socket_drain_is_bounded_and_timeout_still_closes(self):
        for chunks, expected_reads in (
            ([b"x" * (64 * 1024)] * 9 + [AssertionError("unbounded drain")], 9),
            ([b"x" * (16 * 1024)] * 36 + [AssertionError("unbounded drain")], 36),
            ([TimeoutError("silent peer")], 1),
        ):
            with self.subTest(expected_reads=expected_reads):
                request = Mock()
                request.recv.side_effect = chunks
                with patch("server.api.time.monotonic", return_value=0):
                    self.api.shutdown_request(request)
                self.assertEqual(request.recv.call_count, expected_reads)
                request.close.assert_called_once()

    def setUp(self):
        self.calls = []
        calls = self.calls

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append((self.path, body))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {"task_context": body["task_context"], "text": body["text"]}
                    ).encode()
                )

        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        upstream_url = f"http://127.0.0.1:{self.upstream.server_port}"
        handler = type(
            "Configured",
            (Handler,),
            {
                "token": b"x" * 32,
                "default_game": "deadlock",
                "upstreams": dict.fromkeys(
                    ("editor", "analyzer", "translator"), upstream_url
                ),
            },
        )
        self.api = APIServer(("127.0.0.1", 0), handler)
        for server in (self.upstream, self.api):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(thread.join, 5)
            self.addCleanup(server.shutdown)

    def request(self, path, value=None, token=True, **headers):
        data = json.dumps(value).encode() if value is not None else None
        if token:
            headers["Authorization"] = "Bearer " + "x" * 32
        if data:
            headers.setdefault("Content-Type", "application/json")
        request = Request(
            f"http://127.0.0.1:{self.api.server_port}{path}", data=data, headers=headers
        )
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_token_is_required_before_forwarding(self):
        self.assertEqual(
            self.request("/v1/editor/edit", {"text": "Text"}, token=False)[0], 401
        )
        self.assertEqual(self.request("/v1/games", token=False)[0], 401)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.request("/health", token=False), (200, {"ok": True}))

    def test_catalog_and_default_game_use_manacost(self):
        status, catalog = self.request("/v1/games")
        self.assertEqual(status, 200)
        self.assertEqual(len(catalog["games"]), 6)
        self.assertEqual(catalog["default_game"], "deadlock")
        status, result = self.request("/v1/editor/analyze", {"text": "Урон 20%."})
        self.assertEqual(status, 200)
        self.assertEqual(result["task_context"]["game"]["id"], "deadlock")
        self.assertEqual(result["task_context"]["profile"]["id"], "manacost")

    def test_all_games_select_the_right_context_and_route(self):
        for game in (
            "hearthstone",
            "world-of-warcraft",
            "league-of-legends",
            "deadlock",
            "overwatch",
            "heroes-of-the-storm",
        ):
            status, result = self.request(
                "/v1/editor/edit", {"text": "Text", "game": game, "mode": "edit"}
            )
            self.assertEqual(status, 200)
            self.assertEqual(result["task_context"]["game"]["id"], game)
            self.assertEqual(self.calls[-1][0], "/v2/edit")

    def test_invalid_game_and_translation_scope_fail_before_any_call(self):
        for value in (
            [],
            {"text": "Text", "game": "unknown"},
            {"text": "Text", "game": None},
            {"text": "Text", "url": "https://example.com"},
        ):
            self.assertEqual(self.request("/v1/editor/analyze", value)[0], 400)
        for value in (
            {"text": "Text"},
            {"text": "Text", "game": "world-of-warcraft", "patch": "123"},
            {"text": "Text", "patch": "123", "product": "retail"},
        ):
            self.assertEqual(self.request("/v1/translate/prepare", value)[0], 400)
        self.assertEqual(self.calls, [])
        payload = prepare_request(
            "/v1/translate/prepare",
            {
                "text": "Text",
                "game": "world-of-warcraft",
                "patch": "123",
                "product": "retail",
            },
            "hearthstone",
        )
        self.assertEqual(payload["product"], "retail")

    def test_wrong_media_type_is_rejected(self):
        self.assertEqual(
            self.request(
                "/v1/editor/edit", {"text": "Text"}, **{"Content-Type": "text/plain"}
            )[0],
            415,
        )
        self.assertFalse(self.calls)

    def test_editor_handoff_is_forwarded_only_to_edit_validation(self):
        handoff = {"schema_version": 1, "status": "research_blocked"}
        payload = prepare_request(
            "/v1/editor/edit",
            {"text": "Text", "research_handoff": handoff},
            "hearthstone",
        )
        self.assertEqual(payload["research_handoff"], handoff)
        # Semantic readiness is checked by the existing Go handoff validator,
        # not inferred by the transport adapter from this status string.
        for path in ("/v1/editor/analyze", "/v1/translate/prepare"):
            with self.assertRaises(ValueError):
                prepare_request(
                    path,
                    {"text": "Text", "patch": "123", "research_handoff": handoff},
                    "hearthstone",
                )

    def test_capacity_and_body_limits_reject_before_forwarding(self):
        for _ in range(16):
            self.api.slots.acquire()
        try:
            self.assertEqual(self.request("/health", token=False)[0], 503)
            self.assertEqual(
                self.request("/v1/editor/edit", {"text": "x" * (64 * 1024)})[0], 503
            )
        finally:
            for _ in range(16):
                self.api.slots.release()
        self.assertEqual(
            self.request("/v1/editor/edit", {"text": "x" * (512 * 1024)})[0], 413
        )
        self.assertFalse(self.calls)
