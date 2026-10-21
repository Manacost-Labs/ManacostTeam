"""Optional browser lifecycle and discovery boundaries without a browser install."""

import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import source_access as access
import source_browser as browser


class BrowserRouteTests(unittest.TestCase):
    def setUp(self):
        self.contexts, self.pages = [], []
        self.pw, self.chrome = Mock(), Mock()
        self.pw.chromium.launch.return_value = self.chrome
        self.factory = Mock()
        self.factory.return_value.start.return_value = self.pw
        self.chrome.new_context.side_effect = self.new_context
        self.at = 0
        self.pool = browser.BrowserPool(
            factory=self.factory, validator=lambda u: u, now=lambda: self.at, wait_ms=0
        )
        self.addCleanup(self.pool.close)

    def new_context(self, **_options):
        context = Mock()
        context.new_page.side_effect = self.new_page
        self.contexts.append(context)
        return context

    def new_page(self):
        page = Mock()

        def goto(url, **_options):
            page.url = url
            return Mock(status=200)

        page.goto.side_effect = goto
        page.content.return_value = (
            "<html><title>Hearthstone</title><article>"
            + "Useful conditional advice. " * 30
            + "</article></html>"
        )
        body, links = Mock(), Mock()
        body.inner_text.return_value = "Hearthstone useful conditional advice. " * 30
        links.evaluate_all.return_value = []
        page.locator.side_effect = lambda selector: (
            body if selector == "body" else links
        )
        page.get_by_text.return_value.count.return_value = 0
        self.pages.append(page)
        return page

    def test_one_browser_reuses_context_within_domain_and_isolates_domains(self):
        for url in [
            "https://a.example/one",
            "https://b.example/two",
            "https://a.example/three",
        ]:
            self.pool.fetch(url)
        self.assertEqual(self.pw.chromium.launch.call_count, 1)
        self.assertEqual(len(self.contexts), 2)
        self.assertEqual(self.pool.metrics["contexts_reused"], 1)
        self.assertTrue(all(p.close.call_count == 1 for p in self.pages))
        self.assertEqual(self.pool.metrics["pages_closed"], 3)
        for call in self.chrome.new_context.call_args_list:
            self.assertNotIn("storage_state", call.kwargs)
            self.assertFalse(call.kwargs["accept_downloads"])

    def test_context_limit_evicts_oldest_and_page_limit_recycles(self):
        self.pool.max_contexts = 1
        self.pool.fetch("https://a.example/one")
        self.pool.fetch("https://b.example/two")
        self.contexts[0].close.assert_called_once()
        self.pool.max_pages = 1
        self.pool.fetch("https://b.example/three")
        self.contexts[1].close.assert_called_once()
        self.assertEqual(self.pool.metrics["contexts_created"], 3)

    def test_context_ttl_boundary_recycles_and_close_is_idempotent(self):
        self.pool.fetch("https://a.example/")
        self.at = 899
        self.pool.fetch("https://a.example/other")
        self.assertEqual(len(self.contexts), 1)
        self.at = 900
        self.pool.fetch("https://a.example/third")
        self.assertEqual(len(self.contexts), 2)
        self.pool.close()
        self.pool.close()
        self.chrome.close.assert_called_once()
        self.pw.stop.assert_called_once()

    def test_missing_optional_runtime_is_explicit_and_safe(self):
        pool = browser.BrowserPool(validator=lambda u: u)
        with (
            patch.object(
                browser.importlib,
                "import_module",
                side_effect=ImportError("private path"),
            ),
            self.assertRaises(access.AccessError) as error,
        ):
            pool.fetch("https://a.example/")
        self.assertEqual(error.exception.code, "BROWSER_UNAVAILABLE")
        self.assertNotIn("private path", str(error.exception))

    def test_cross_thread_browser_use_fails_before_launch(self):
        errors = []

        def run():
            try:
                self.pool.fetch("https://a.example/")
            except access.AccessError as error:
                errors.append(error.code)

        thread = threading.Thread(target=run)
        thread.start()
        thread.join()
        self.assertEqual(errors, ["BROWSER_THREAD_MISMATCH"])
        self.pw.chromium.launch.assert_not_called()

    def test_public_guest_continue_uses_real_link_once_without_cookie_injection(self):
        page = self.new_page()
        page.get_by_text.return_value.count.return_value = 1
        context = Mock()
        context.new_page.return_value = page
        self.chrome.new_context.side_effect = None
        self.chrome.new_context.return_value = context
        result = self.pool.fetch("https://bbs.nga.cn/thread.php?fid=422")
        page.get_by_text.assert_called_with("如不能自动跳转 可点此链接", exact=True)
        page.get_by_text.return_value.click.assert_called_once()
        context.add_cookies.assert_not_called()
        self.assertTrue(result["diagnostics"]["public_guest_continue"])

    def test_route_guard_blocks_private_requests_media_and_writes(self):
        for url, method, resource, allowed in [
            ("https://a.example/", "GET", "document", True),
            ("https://a.example/update", "POST", "xhr", False),
            ("https://a.example/video", "GET", "media", False),
            ("https://a.example/cdn-cgi/challenge-platform/test", "POST", "xhr", True),
        ]:
            with self.subTest(method=method, resource=resource):
                route = Mock()
                route.request.url = url
                route.request.method = method
                route.request.resource_type = resource
                self.pool._guard(route)
                self.assertEqual(route.continue_.called, allowed)
                self.assertEqual(route.abort.called, not allowed)
        self.pool.validator = Mock(
            side_effect=access.AccessError("PUBLIC_HTTPS_URL_REQUIRED")
        )
        route = Mock()
        route.request.url = "https://127.0.0.1/"
        self.pool._guard(route)
        route.abort.assert_called_once()
        route.continue_.assert_not_called()

    def test_discovery_redacts_values_and_never_promotes_session_or_signed_request(
        self,
    ):
        row = browser.candidate(
            "https://api.example/search?q=private-topic&w_rid=private-signature",
            "GET",
            200,
            "application/json",
            ["Cookie"],
        )
        self.assertEqual(row["classification"], "SESSION_OR_AUTH_NOT_REPLAYED")
        self.assertFalse(row["automatically_promoted"])
        self.assertNotIn("private-", json.dumps(row))
        self.assertNotIn("w_rid", row["query_keys"])
        public = browser.candidate(
            "https://api.example/search?q=topic", "GET", 200, "application/json", []
        )
        self.assertEqual(public["classification"], "DISCOVERY_ONLY")
        failed = browser.candidate(
            "https://api.example/search?q=topic", "GET", 503, "application/json", []
        )
        self.assertEqual(failed["classification"], "FAILED_HTTP_NOT_REPLAYED")
        for url, content_type in [
            ("https://a.example/cdn-cgi/path/token", "application/json"),
            ("https://a.example/bfs/icon.json", "application/json"),
            ("https://a.example/index", "text/html"),
            ("https://127.0.0.1/api", "application/json"),
        ]:
            self.assertIsNone(browser.candidate(url, "GET", 200, content_type, []))

    def test_content_links_prefer_descriptive_title_and_reject_credentials(self):
        anchors = [
            {"href": "https://www.bilibili.com/video/BV123/", "text": "1234 01:30"},
            {
                "href": "https://www.bilibili.com/video/BV123/",
                "text": "炉石传说新卡实战",
            },
            {"href": "https://127.0.0.1/video/BV999/", "text": "private"},
            {"href": "https://a.example/deck/1?token=secret", "text": "secret"},
        ]
        result = browser.content_links(anchors, "https://search.bilibili.com/")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "炉石传说新卡实战")
        self.assertEqual(result[0]["evidence_status"], "discovery_only")

    def test_navigation_failure_closes_page_and_hides_exception_text(self):
        page = self.new_page()
        page.goto.side_effect = RuntimeError("private browser details")
        page.close.side_effect = RuntimeError("cleanup details")
        context = Mock()
        context.new_page.return_value = page
        self.chrome.new_context.side_effect = None
        self.chrome.new_context.return_value = context
        with self.assertRaises(access.AccessError) as error:
            self.pool.fetch("https://a.example/")
        self.assertEqual(error.exception.code, "BROWSER_NAVIGATION_FAILED")
        self.assertNotIn("private", str(error.exception))
        page.close.assert_called_once()
        self.assertEqual(self.pool.metrics["cleanup_failures"], 1)

    def test_invalid_options_never_launch_browser(self):
        for options in [
            {"engine": "unknown"},
            {"max_contexts": 0},
            {"max_pages": 0},
            {"context_ttl": 0},
            {"wait_ms": 15001},
        ]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                browser.BrowserPool(**options)
