"""Focused transport, credential and source-scope regression tests."""

from __future__ import annotations

import gzip
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import source_access as access


class SourceAccessTests(unittest.TestCase):
    def test_protected_sources_use_super_and_browser_options_are_preserved(self):
        body = (
            "<html><title>Stats</title><p>Published data. </p>"
            + "Evidence. " * 60
            + "</html>"
        ).encode()
        with patch.object(
            access,
            "request",
            return_value=(
                body,
                {
                    "content_type": "text/html",
                    "target_status": "200",
                    "provider_status": 200,
                },
            ),
        ) as req:
            result = access.fetch(
                "https://www.hsguru.com/decks", render=True, wait_ms=3000, country="us"
            )
        params = req.call_args.args[1]
        self.assertEqual(params["super"], "true")
        self.assertEqual(params["render"], "true")
        self.assertEqual(params["customWait"], "3000")
        self.assertEqual(params["geoCode"], "us")
        self.assertTrue(result["super_proxy"])

    def test_fetch_preserves_article_after_void_tags_in_dropped_navigation(self):
        body = (
            "<html><head><title>Article</title><link class='login' href='/style.css'></head>"
            "<body><nav><img src='logo.png'><input><br/><li>One<li>Two</nav><form><input></form>"
            "<article><p>Original Hearthstone strategy with a condition. </p>"
            + "Useful evidence. " * 40
            + "</article></body></html>"
        )
        with patch.object(
            access,
            "request",
            return_value=(
                body.encode(),
                {
                    "content_type": "text/html",
                    "target_status": "200",
                    "provider_status": 200,
                },
            ),
        ):
            result = access.fetch("https://example.com/")
        self.assertEqual(result["status"], "SUCCESS")
        self.assertIn("Original Hearthstone strategy with a condition.", result["text"])
        self.assertNotIn("style.css", result["text"])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.secret = Path(self.tmp.name) / "credentials.json"
        self.secret.write_text(
            json.dumps(
                {
                    "SCRAPE_DO_API_TOKEN": "fixture-only-scrape",
                    "TRANSCRIPTAPI_TOKEN": "fixture-only-transcript",
                    "REDDITAPIS_KEY": "fixture-only-reddit",
                    "OTHER_SECRET": "do-not-load",
                }
            ),
            encoding="utf-8",
        )
        self.env = patch.dict(
            os.environ, {"MANACOST_SOURCE_CREDENTIALS": str(self.secret)}, clear=True
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def response(self, body, headers=None, status=200):
        response = Mock()
        response.read.return_value = body
        response.headers = headers or {}
        response.status = status
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_local_credentials_allowlist_and_environment_precedence(self):
        os.environ["SCRAPE_DO_API_TOKEN"] = "environment-fixture"
        self.assertEqual(
            access.load_credentials(),
            {
                "SCRAPE_DO_API_TOKEN": True,
                "TRANSCRIPTAPI_TOKEN": True,
                "REDDITAPIS_KEY": True,
            },
        )
        self.assertEqual(os.environ["SCRAPE_DO_API_TOKEN"], "environment-fixture")
        self.assertEqual(os.environ["TRANSCRIPTAPI_TOKEN"], "fixture-only-transcript")
        self.assertNotIn("OTHER_SECRET", os.environ)

    def test_missing_or_malformed_local_file_is_not_a_network_call(self):
        self.secret.write_text("{invalid", encoding="utf-8")
        with (
            patch.object(access, "urlopen") as transport,
            self.assertRaises(access.AccessError) as raised,
        ):
            access.request("/", {})
        self.assertEqual(raised.exception.code, "SCRAPE_DO_NOT_CONFIGURED")
        transport.assert_not_called()
        self.secret.unlink()
        self.assertFalse(any(access.load_credentials().values()))

    def test_nested_output_redacts_keys_values_and_provider_urls(self):
        access.load_credentials()
        result = access.scrub(
            {
                "token": "fixture-only-scrape",
                "results": [
                    {
                        "text": "fixture-only-transcript",
                        "url": "https://example.com/?x=fixture-only-scrape",
                    }
                ],
                "Authorization": "Bearer fixture-only-transcript",
            }
        )
        encoded = json.dumps(result)
        self.assertNotIn("fixture-only", encoded)
        self.assertNotIn("Authorization", result)
        self.assertNotIn("token", result)

    def test_search_never_accepts_google_results_outside_requested_site(self):
        payload = {
            "organic_results": [
                {"link": "https://bbs.nga.cn/read.php?tid=1", "title": "In scope"},
                {"link": "https://youtube.com/watch?v=outside", "title": "Outside"},
                {"link": "https://bbs.nga.cn.attacker.example/", "title": "Lookalike"},
            ],
            "search_information": {"query_displayed": "Rewritten"},
        }
        with patch.object(
            access,
            "request",
            return_value=(json.dumps(payload).encode(), {"credits": "10"}),
        ) as req:
            result = access.search(
                "炉石", site="bbs.nga.cn", language="zh-CN", country="tw"
            )
        self.assertEqual([r["title"] for r in result["results"]], ["In scope"])
        self.assertEqual(len(result["out_of_scope_results"]), 2)
        self.assertEqual(result["results"][0]["evidence_status"], "discovery_only")
        self.assertEqual(req.call_args.args[1]["q"], "site:bbs.nga.cn 炉石")
        self.assertEqual(result["search_information"]["query_displayed"], "Rewritten")

    def test_site_filter_accepts_real_subdomains_and_records_empty_scope(self):
        for case, url, count in [
            ("real_subdomain", "https://www.reddit.com/r/hearthstone", 1),
            ("foreign_only", "https://example.com/", 0),
        ]:
            with (
                self.subTest(case=case),
                patch.object(
                    access,
                    "request",
                    return_value=(
                        json.dumps({"organic_results": [{"link": url}]}).encode(),
                        {},
                    ),
                ),
            ):
                self.assertEqual(
                    len(access.search("Hearthstone", site="reddit.com")["results"]),
                    count,
                )

    def test_invalid_query_or_site_never_contacts_provider(self):
        for case, query, site, offset in [
            ("empty", " ", None, 0),
            ("site_injection", "deck", "example.com -site:x", 0),
            ("negative_offset", "deck", None, -1),
            ("large_offset", "deck", None, 101),
        ]:
            with (
                self.subTest(case=case),
                patch.object(access, "request") as req,
                self.assertRaises(access.AccessError),
            ):
                access.search(query, site=site, start=offset)
            req.assert_not_called()

    def test_invalid_json_or_shape_remains_failure(self):
        for case, body in [
            ("invalid_json", b"not json"),
            ("missing_list", b"{}"),
            ("array", b"[]"),
        ]:
            with (
                self.subTest(case=case),
                patch.object(access, "request", return_value=(body, {})),
                self.assertRaises(access.AccessError),
            ):
                access.search("deck")

    def test_request_uses_internal_auth_and_returns_only_safe_diagnostics(self):
        response = self.response(
            b"content",
            {"Scrape.do-Request-Cost": "1", "Scrape.do-Initial-Status-Code": "200"},
        )
        with patch.object(access, "urlopen", return_value=response) as transport:
            data, meta = access.request("/", {"url": "https://example.com/"})
        self.assertIn("fixture-only-scrape", transport.call_args.args[0].full_url)
        self.assertNotIn("fixture-only-scrape", json.dumps(meta))
        self.assertEqual(data, b"content")
        self.assertEqual(meta["target_status"], "200")
        self.assertEqual(meta["credits"], "1")

    def test_network_error_hides_token_bearing_exception_without_retry(self):
        with (
            patch.object(
                access, "urlopen", side_effect=URLError("fixture-only-scrape")
            ) as req,
            self.assertRaises(access.AccessError) as raised,
        ):
            access.request("/", {})
        self.assertEqual(str(raised.exception), "PROVIDER_NETWORK_ERROR")
        self.assertNotIn("fixture-only-scrape", str(raised.exception))
        req.assert_called_once()

    def test_auth_and_rate_errors_remain_distinct_failures(self):
        for code in (401, 429):
            with (
                self.subTest(case=code),
                patch.object(
                    access,
                    "urlopen",
                    side_effect=HTTPError(
                        "https://api.scrape.do/?token=fixture-only-scrape",
                        code,
                        "error",
                        {},
                        io.BytesIO(),
                    ),
                ),
                self.assertRaises(access.AccessError) as raised,
            ):
                access.request("/plugin/google/search", {})
            self.assertEqual(raised.exception.status, code)
            self.assertNotIn("fixture-only-scrape", str(raised.exception))

    def test_transparent_target_block_is_not_provider_auth_failure(self):
        error = HTTPError(
            "https://api.scrape.do/",
            403,
            "blocked",
            {"Scrape.do-Initial-Status-Code": "403"},
            io.BytesIO(b"Forbidden"),
        )
        with patch.object(access, "urlopen", side_effect=error):
            body, meta = access.request("/", {})
        self.assertEqual(body, b"Forbidden")
        self.assertEqual(meta["target_status"], "403")

    def test_gzip_is_decoded_and_size_limit_is_enforced(self):
        response = self.response(gzip.compress(b"hello"), {"Content-Encoding": "gzip"})
        with patch.object(access, "urlopen", return_value=response):
            self.assertEqual(access.request("/", {})[0], b"hello")
        with (
            patch.object(access, "MAX_BYTES", 2),
            patch.object(access, "urlopen", return_value=self.response(b"abc")),
            self.assertRaises(access.AccessError) as raised,
        ):
            access.request("/", {})
        self.assertEqual(raised.exception.code, "RESPONSE_TOO_LARGE")

    def test_private_and_credential_bearing_targets_are_rejected(self):
        cases = [
            "http://example.com/",
            "https://localhost/",
            "https://127.0.0.1/",
            "https://10.1.2.3/",
            "https://api.scrape.do/",
            "https://user:pass@example.com/",
            "https://example.com/?token=something",
        ]
        for index, url in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(access.AccessError):
                access.public_url(url)
        self.assertEqual(
            access.public_url("https://www.hsguru.com/decks"),
            "https://www.hsguru.com/decks",
        )

    def test_public_fetch_does_not_treat_js_shell_as_article(self):
        with patch.object(
            access,
            "request",
            return_value=(
                b"<html><title>Site</title><div id='app'></div></html>",
                {
                    "content_type": "text/html",
                    "target_status": "200",
                    "provider_status": 200,
                },
            ),
        ):
            result = access.fetch("https://example.com/")
        self.assertEqual(result["status"], "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
