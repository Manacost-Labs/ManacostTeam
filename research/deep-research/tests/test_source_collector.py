"""Public behavior tests for durable, source-aware acquisition."""

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import source_access as access
import source_collector as collector
from community_sources import ProviderError

URL = "https://www.ptt.cc/bbs/Hearthstone/M.1792418125.A.B7C.html"
CONTRACT = collector.Contract(canaries=("Hearthstone",), min_chars=100)


def html(status=200, text=None):
    return {
        "status": status,
        "body": text
        or "<h1>Hearthstone strategy</h1><article>"
        + "Useful conditional advice. " * 30
        + "</article>",
        "final_url": URL,
    }


class SourceCollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = collector.Store(Path(self.tmp.name) / "state.sqlite3")
        self.at = 1000.0
        self.client = collector.Collector(self.store, now=lambda: self.at)
        env = patch.dict(
            os.environ,
            {"MANACOST_SOURCE_CREDENTIALS": str(Path(self.tmp.name) / "absent.json")},
            clear=True,
        )
        env.start()
        self.addCleanup(env.stop)

    def test_response_statuses_remain_distinct_and_do_not_validate_content(self):
        for status, verdict in [
            (401, "AUTH_REQUIRED"),
            (402, "AUTH_REQUIRED"),
            (403, "BLOCKED"),
            (404, "DEAD_URL"),
            (410, "DEAD_URL"),
            (429, "RATE_LIMITED"),
            (500, "ORIGIN_DOWN"),
            (503, "ORIGIN_DOWN"),
            (302, "PARSE_FAIL"),
        ]:
            with self.subTest(status=status):
                self.assertEqual(
                    collector.validate(html(status), CONTRACT)["verdict"], verdict
                )

    def test_challenge_200_is_not_success_and_security_script_is_not_a_block(self):
        raw = html(text="<title>Just a moment</title><p>Verify you are human</p>")
        self.assertEqual(collector.validate(raw, CONTRACT)["verdict"], "SOFT_BLOCK")
        raw = html(
            text=html()["body"]
            + "<script>captcha cf-chl- window.__test = 'verify you are human';</script>"
        )
        self.assertEqual(collector.validate(raw, CONTRACT)["verdict"], "OK")

    def test_canary_only_in_script_or_menu_does_not_prove_an_article(self):
        for prefix in ["<script>Hearthstone</script>", "<nav>Hearthstone</nav>"]:
            with self.subTest(prefix=prefix):
                raw = html(
                    text=prefix
                    + "<article>"
                    + "Unrelated content. " * 40
                    + "</article>"
                )
                self.assertEqual(
                    collector.validate(raw, CONTRACT)["verdict"], "PARSE_FAIL"
                )

    def test_js_shell_and_thin_content_have_different_outcomes(self):
        self.assertEqual(
            collector.validate(
                html(text="<div id='app'></div><script src='bundle.js'></script>"),
                CONTRACT,
            )["verdict"],
            "CSR_REQUIRED",
        )
        self.assertEqual(
            collector.validate(html(text="<p>Hearthstone</p>"), CONTRACT)["verdict"],
            "THIN_CONTENT",
        )

    def test_html_contract_rejects_json_or_plain_text_with_matching_words(self):
        for body in [json.dumps({"text": "Hearthstone " * 50}), "Hearthstone " * 50]:
            with self.subTest(body=body):
                self.assertEqual(
                    collector.validate({"status": 200, "body": body}, CONTRACT)[
                        "verdict"
                    ],
                    "PARSE_FAIL",
                )

    def test_json_requires_nonempty_data_and_preserves_zero_values(self):
        contract = collector.Contract("json", json_paths=("data.0.games",), min_chars=0)
        for body, expected in [
            ("{}", "PARSE_FAIL"),
            ('{"data":[]}', "PARSE_FAIL"),
            ('{"data":[{"games":null}]}', "PARSE_FAIL"),
            ('{"data":[{"games":0}]}', "OK"),
            ('{"data":[{"games":10}]}', "OK"),
            ("not json", "PARSE_FAIL"),
        ]:
            with self.subTest(body=body):
                self.assertEqual(
                    collector.validate({"status": 200, "body": body}, contract)[
                        "verdict"
                    ],
                    expected,
                )

    def test_patch_and_stale_flags_override_a_newly_fetched_valid_shape(self):
        contract = collector.Contract(
            "json", json_paths=("data.0.name",), min_chars=0, expected_patch="patch_37"
        )
        for meta, expected in [
            ({}, "PATCH_MISMATCH"),
            ({"current_patch_period": "patch_36"}, "PATCH_MISMATCH"),
            ({"current_patch_period": "patch_37", "stale": True}, "STALE_SOURCE"),
            (
                {"current_patch_period": "patch_37", "cached_after_failure": True},
                "STALE_SOURCE",
            ),
            (
                {"current_patch_period": "patch_37", "serving_cached_dataset": True},
                "STALE_SOURCE",
            ),
            ({"current_patch_period": "patch_37", "stale": False}, "OK"),
        ]:
            with self.subTest(meta=meta):
                raw = {
                    "status": 200,
                    "body": json.dumps({"data": [{"name": "Deck"}], "meta": meta}),
                }
                result = collector.validate(raw, contract)
                self.assertEqual(result["verdict"], expected)
                self.assertEqual(result["source_freshness"], meta)

    def test_rss_and_atom_require_actual_titled_entries(self):
        contract = collector.Contract("rss", min_chars=0)
        for body, expected in [
            ("<rss><channel/></rss>", "PARSE_FAIL"),
            ("<rss><channel><item><title>Episode</title></item></channel></rss>", "OK"),
            (
                '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Episode</title></entry></feed>',
                "OK",
            ),
            ("<broken", "PARSE_FAIL"),
        ]:
            with self.subTest(body=body):
                self.assertEqual(
                    collector.validate({"status": 200, "body": body}, contract)[
                        "verdict"
                    ],
                    expected,
                )

    def test_explicit_contract_is_required_before_spending_on_unknown_source(self):
        with (
            patch.object(collector, "scrape") as network,
            self.assertRaisesRegex(ValueError, "EXPLICIT_RESPONSE_CONTRACT"),
        ):
            self.client.collect("https://example.com/article")
        network.assert_not_called()
        for kwargs in [
            {},
            {"kind": "json"},
            {"canaries": ("",)},
            {"canaries": ("Article",), "expected_patch": "patch_37"},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                collector.Contract(**kwargs)

    def test_primary_preference_and_cache_hit_make_no_second_network_call(self):
        with (
            patch.object(collector, "scrape", return_value=html()) as primary,
            patch.object(collector, "direct") as fallback,
        ):
            first = self.client.collect(URL, CONTRACT)
            self.at += 10
            second = self.client.collect(URL, CONTRACT)
        primary.assert_called_once_with(URL)
        fallback.assert_not_called()
        self.assertEqual((first["cache"], second["cache"]), ("MISS", "HIT"))
        self.assertEqual(second["age_seconds"], 10)
        self.assertEqual(second["observed_at"], 1000)
        self.assertFalse(second["evidence_validated"])

    def test_cache_expiry_boundary_and_contract_identity_trigger_revalidation(self):
        with patch.object(collector, "scrape", return_value=html()) as network:
            self.client.collect(URL, CONTRACT, ttl=10)
            self.at += 9
            self.assertEqual(self.client.collect(URL, CONTRACT, ttl=10)["cache"], "HIT")
            self.at += 1
            self.assertEqual(
                self.client.collect(URL, CONTRACT, ttl=10)["cache"], "MISS"
            )
            other = collector.Contract(canaries=("Useful",), min_chars=100)
            self.client.collect(URL, other, ttl=10)
        self.assertEqual(network.call_count, 3)

    def test_native_success_is_reused_while_failed_provider_is_in_cooldown(self):
        with (
            patch.object(
                collector,
                "scrape",
                side_effect=access.AccessError("PROVIDER_HTTP_ERROR", 502),
            ) as paid,
            patch.object(collector, "direct", return_value=html()) as native,
        ):
            one = self.client.collect(URL, CONTRACT)
            two = self.client.collect(URL, CONTRACT, refresh=True)
        self.assertEqual(one["provider"], "direct")
        self.assertEqual(two["attempts"][0]["verdict"], "COOLDOWN")
        self.assertEqual(paid.call_count, 1)
        self.assertEqual(native.call_count, 2)

    def test_terminal_target_failures_never_buy_another_route(self):
        for status in [401, 403, 404, 410, 429, 503]:
            with (
                self.subTest(status=status),
                patch.object(
                    collector,
                    "scrape",
                    return_value=html(status, "<h1>Access denied</h1>")
                    if status == 403
                    else html(status),
                ) as paid,
                patch.object(collector, "direct") as native,
            ):
                # Each scenario has isolated route health.
                isolated = collector.Collector(
                    collector.Store(Path(self.tmp.name) / f"{status}.db"),
                    now=lambda: self.at,
                )
                result = isolated.collect(URL, CONTRACT)
                self.assertNotEqual(result["verdict"], "OK")
                paid.assert_called_once()
                native.assert_not_called()

    def test_actual_block_can_render_once_after_native_block(self):
        block = html(403, "<h1>Verify you are human</h1>")
        with (
            patch.object(collector, "scrape", side_effect=[block, html()]) as paid,
            patch.object(collector, "direct", return_value=block),
        ):
            result = self.client.collect(URL, CONTRACT)
        self.assertEqual(result["provider"], "scrape-super-render")
        self.assertEqual(paid.call_count, 2)
        self.assertEqual(paid.call_args.kwargs, {"render": True})

    def test_csr_without_block_does_not_trigger_paid_render(self):
        shell = html(text="<div id='app'></div>")
        with (
            patch.object(collector, "scrape", return_value=shell) as paid,
            patch.object(collector, "direct", return_value=shell),
        ):
            self.assertEqual(
                self.client.collect(URL, CONTRACT)["verdict"], "CSR_REQUIRED"
            )
        paid.assert_called_once()

    def test_native_origin_down_does_not_trigger_paid_render_after_block(self):
        block = html(403, "<p>Verify you are human</p>")
        with (
            patch.object(collector, "scrape", return_value=block) as paid,
            patch.object(
                collector,
                "direct",
                side_effect=access.AccessError("DIRECT_NETWORK_ERROR"),
            ),
        ):
            self.assertEqual(
                self.client.collect(URL, CONTRACT)["verdict"], "ORIGIN_DOWN"
            )
        paid.assert_called_once()

    def test_retry_after_pauses_provider_across_domains_and_does_not_sleep(self):
        with (
            patch.object(
                collector,
                "scrape",
                side_effect=access.AccessError("PROVIDER_HTTP_ERROR", 429, "600"),
            ) as paid,
            patch.object(collector, "direct", return_value=html()),
        ):
            result = self.client.collect(URL, CONTRACT)
            self.assertEqual(result["attempts"][0]["provider_http_status"], 429)
            self.assertEqual(result["attempts"][0]["error_code"], "PROVIDER_HTTP_ERROR")
            self.assertIsNone(result["attempts"][0]["http_status"])
            self.at += 599
            self.client.collect("https://another.example/article", CONTRACT)
            self.assertEqual(paid.call_count, 1)
            self.at += 1
            self.client.collect("https://third.example/article", CONTRACT)
            self.assertEqual(paid.call_count, 2)

    def test_retry_after_accepts_http_date_and_rejects_nonfinite_delays(self):
        self.assertEqual(
            collector.retry_delay("Thu, 01 Jan 1970 00:20:00 GMT", 1000), 200
        )
        self.assertEqual(collector.retry_delay("-1", 1000), 0)
        self.assertEqual(collector.retry_delay("nan", 1000), 300)
        self.assertEqual(collector.retry_delay("invalid", 1000), 300)

    def test_failed_refresh_never_replaces_last_good_and_stale_is_explicit(self):
        with patch.object(collector, "scrape", return_value=html()):
            good = self.client.collect(URL, CONTRACT)
        self.at += 30000
        with patch.object(collector, "scrape", return_value=html(404)):
            failure = self.client.collect(URL, CONTRACT)
            fallback = self.client.collect(URL, CONTRACT, allow_stale=True)
        self.assertEqual(failure["verdict"], "DEAD_URL")
        self.assertNotIn("text", failure)
        self.assertEqual(fallback["verdict"], "STALE_LKG")
        self.assertEqual(fallback["refresh_verdict"], "DEAD_URL")
        self.assertEqual(fallback["text"], good["text"])
        self.assertEqual(fallback["observed_at"], 1000)
        self.assertEqual(fallback["age_seconds"], 30000)
        self.assertTrue(fallback["stale"])

    def test_stale_limit_is_inclusive_and_expired_snapshot_is_not_returned(self):
        with patch.object(collector, "scrape", return_value=html()):
            self.client.collect(URL, CONTRACT)
        with patch.object(collector, "scrape", return_value=html(404)):
            self.at += 7 * 86400
            self.assertEqual(
                self.client.collect(URL, CONTRACT, allow_stale=True)["verdict"],
                "STALE_LKG",
            )
            self.at += 1
            result = self.client.collect(URL, CONTRACT, allow_stale=True)
            self.assertEqual(result["verdict"], "COOLDOWN")
            self.assertEqual(result["refresh_verdict"], "DEAD_URL")
            self.assertNotIn("text", result)

    def test_checksum_corruption_stops_without_network_or_overwriting_data(self):
        with patch.object(collector, "scrape", return_value=html()):
            self.client.collect(URL, CONTRACT)
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute("UPDATE snapshots SET payload='{}'")
        with (
            patch.object(collector, "scrape") as paid,
            self.assertRaisesRegex(ValueError, "SNAPSHOT_CHECKSUM_MISMATCH"),
        ):
            self.client.collect(URL, CONTRACT)
        paid.assert_not_called()

    def test_promotion_rejects_unvalidated_candidate_and_keeps_previous_snapshot(self):
        self.store.promote("sample", {"verdict": "OK", "text": "original"}, 1000)
        with self.assertRaises(ValueError):
            self.store.promote("sample", {"verdict": "PARSE_FAIL", "text": "bad"}, 1001)
        self.assertEqual(self.store.snapshot("sample")[1]["text"], "original")

    def test_batch_accounts_for_duplicates_and_invalid_inputs_without_leaking_url(self):
        unsafe = "https://user:secret@example.com/"
        with patch.object(collector, "scrape", return_value=html()) as network:
            result = self.client.batch([URL, unsafe, URL], contract=CONTRACT)
        self.assertEqual(
            result["accounting"], {"input": 3, "accounted": 3, "unaccounted": 0}
        )
        self.assertEqual(result["results"][1]["verdict"], "INPUT_OR_STATE_ERROR")
        self.assertEqual(result["results"][2]["cache"], "HIT")
        self.assertNotIn("secret", json.dumps(result))
        network.assert_called_once()
        for urls in [[], [URL] * 51]:
            with self.assertRaises(ValueError):
                self.client.batch(urls, contract=CONTRACT)

    def test_reddit_uses_redditapi_before_any_other_provider(self):
        url = "https://www.reddit.com/r/CompetitiveHS/comments/1x8cxex/topic/"
        raw = {
            "status": 200,
            "body": json.dumps(
                {
                    "results": [{"text": "A conditional recommendation"}],
                    "pagination": {"listing_status": "unknown"},
                }
            ),
        }
        with (
            patch.object(collector, "reddit", return_value=raw) as primary,
            patch.object(collector, "scrape") as paid,
            patch.object(collector, "direct") as native,
        ):
            result = self.client.collect(url)
        self.assertEqual(result["provider"], "redditapi")
        self.assertEqual(result["data"]["pagination"]["listing_status"], "unknown")
        primary.assert_called_once()
        paid.assert_not_called()
        native.assert_not_called()

    def test_redditapi_failure_uses_explicit_reserve_provenance(self):
        url = "https://www.reddit.com/comments/1x8cxex/"
        raw = {"status": 200, "body": json.dumps({"results": [{"text": "Comment"}]})}
        with (
            patch.object(
                collector,
                "reddit",
                side_effect=ProviderError("redditapi", "unavailable", status=502),
            ),
            patch.object(collector, "reddit_reserve", return_value=raw),
        ):
            result = self.client.collect(url)
        self.assertEqual(result["provider"], "scrape-super")
        self.assertEqual(
            [x["route"] for x in result["attempts"]], ["redditapi", "scrape-super"]
        )

    def test_known_rss_and_first_party_api_use_native_structured_transport(self):
        for url, contract, raw in [
            (
                "https://hearthstonecommute.libsyn.com/rss",
                None,
                {
                    "status": 200,
                    "body": "<rss><channel><item><title>Episode</title></item></channel></rss>",
                },
            ),
            (
                "https://api.kolodahearthstone.com/v1/hsguru/meta",
                collector.Contract("json", json_paths=("data.0",), min_chars=0),
                {"status": 200, "body": '{"data":[{"name":"Deck"}]}'},
            ),
        ]:
            with (
                self.subTest(url=url),
                patch.object(collector, "direct", return_value=raw),
                patch.object(collector, "scrape") as paid,
            ):
                result = self.client.collect(url, contract)
                self.assertEqual(result["provider"], "native")
                paid.assert_not_called()

    def test_redirect_rejects_private_resolution_before_following(self):
        handler = collector.PublicRedirect()
        with (
            patch.object(
                collector.socket,
                "getaddrinfo",
                return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
            ),
            self.assertRaises(access.AccessError),
        ):
            handler.redirect_request(
                Mock(), None, 302, "redirect", {}, "https://public-looking.example/path"
            )

    def test_direct_transport_preserves_target_error_and_enforces_size(self):
        error = HTTPError(
            URL, 429, "rate", {"Retry-After": "120"}, io.BytesIO(b"slow down")
        )
        with (
            patch.object(collector, "public_address", side_effect=lambda u: u),
            patch.object(collector, "build_opener") as opener,
        ):
            opener.return_value.open.side_effect = error
            raw = collector.direct(URL)
        self.assertEqual((raw["status"], raw["retry_after"]), (429, "120"))
        response = Mock(code=200, headers={})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = URL
        response.read.return_value = b"oversize"
        with (
            patch.object(collector, "public_address", side_effect=lambda u: u),
            patch.object(collector, "build_opener") as opener,
            patch.object(access, "MAX_BYTES", 2),
            self.assertRaises(access.AccessError),
        ):
            opener.return_value.open.return_value = response
            collector.direct(URL)

    def test_cli_collect_dispatches_through_existing_source_access(self):
        with patch.object(collector, "main", return_value=0) as cli:
            self.assertEqual(access.main(["collect", "--health"]), 0)
        cli.assert_called_once_with(["--health"])

    def test_public_guest_bootstrap_is_csr_but_permission_denial_stays_terminal(self):
        raw = {
            "status": 403,
            "body": "<title>访客不能直接访问</title><script>guestJs; 如不能自动跳转</script>",
            "final_url": "https://bbs.nga.cn/thread.php?fid=422",
        }
        self.assertEqual(collector.validate(raw, CONTRACT)["verdict"], "CSR_REQUIRED")
        raw["final_url"] = "https://unrelated.example/"
        raw["body"] = "<h1>Permission denied</h1>"
        self.assertEqual(collector.validate(raw, CONTRACT)["verdict"], "ACCESS_DENIED")

    def test_browser_resolves_csr_after_http_routes_and_keeps_one_paid_call(self):
        pool = Mock(engine="playwright")
        pool.fetch.return_value = {
            **html(),
            "rendered_text": "Hearthstone useful advice",
        }
        client = collector.Collector(self.store, now=lambda: self.at, browser=pool)
        shell = html(text="<div id='app'></div>")
        with (
            patch.object(collector, "scrape", return_value=shell) as paid,
            patch.object(collector, "direct", return_value=shell),
        ):
            result = client.collect(URL, CONTRACT)
        self.assertEqual(result["provider"], "browser")
        pool.fetch.assert_called_once_with(URL)
        paid.assert_called_once()

    def test_browser_does_not_follow_genuine_access_denial(self):
        pool = Mock(engine="playwright")
        client = collector.Collector(self.store, now=lambda: self.at, browser=pool)
        with patch.object(
            collector, "scrape", return_value=html(403, "<h1>Access denied</h1>")
        ):
            self.assertEqual(client.collect(URL, CONTRACT)["verdict"], "ACCESS_DENIED")
        pool.fetch.assert_not_called()

    def test_explicit_browser_probe_uses_separate_identity_and_no_paid_route(self):
        pool = Mock(engine="playwright")
        pool.fetch.return_value = html()
        client = collector.Collector(self.store, now=lambda: self.at, browser=pool)
        with patch.object(
            collector, "scrape", return_value=html(403, "<h1>Access denied</h1>")
        ) as paid:
            client.collect(URL, CONTRACT)
            result = client.collect(URL, CONTRACT, browser_only=True)
        self.assertEqual(result["provider"], "browser")
        paid.assert_called_once()
        with self.assertRaisesRegex(ValueError, "BROWSER_ROUTE_REQUIRED"):
            self.client.collect(URL, CONTRACT, browser_only=True)

    def test_missing_browser_runtime_is_visible_without_extra_paid_csr_retry(self):
        pool = Mock(engine="playwright")
        pool.fetch.side_effect = access.AccessError("BROWSER_UNAVAILABLE")
        client = collector.Collector(self.store, now=lambda: self.at, browser=pool)
        shell = html(text="<div id='app'></div>")
        with (
            patch.object(collector, "scrape", return_value=shell) as paid,
            patch.object(collector, "direct", return_value=shell),
        ):
            self.assertEqual(
                client.collect(URL, CONTRACT)["verdict"], "BROWSER_UNAVAILABLE"
            )
        paid.assert_called_once()

    def test_browser_contract_requires_canary_in_visible_rendered_text(self):
        raw = {**html(), "rendered_text": "Different visible topic"}
        self.assertEqual(collector.validate(raw, CONTRACT)["verdict"], "PARSE_FAIL")

    def test_channel_route_returns_metadata_without_opening_or_transcribing_video(self):
        url = "https://www.youtube.com/@HearthTech7354/videos"
        payload = {
            "title": "Hearth Tech",
            "videos": [{"id": "video123", "title": "Guide"}],
        }
        with (
            patch.object(
                collector,
                "youtube_channel",
                return_value={"status": 200, "body": json.dumps(payload)},
            ) as channel,
            patch.object(collector, "scrape") as paid,
        ):
            result = self.client.collect(url)
        self.assertEqual(result["provider"], "transcriptapi-channel")
        self.assertFalse(result["evidence_validated"])
        channel.assert_called_once()
        paid.assert_not_called()
        self.assertIsNone(
            collector.youtube_channel_id(
                "https://youtube.com.attacker.example/@HearthTech7354"
            )
        )

    def test_browser_pause_preserves_paid_render_reserve_after_proven_block(self):
        pool = Mock(engine="playwright", channel="chrome")
        client = collector.Collector(self.store, now=lambda: self.at, browser=pool)
        self.store.record(
            "www.ptt.cc:browser:playwright:chrome",
            URL,
            "browser",
            "BLOCKED",
            self.at,
            300,
        )
        block = html(403, "<h1>Verify you are human</h1>")
        with (
            patch.object(collector, "scrape", side_effect=[block, html()]) as paid,
            patch.object(collector, "direct", return_value=block),
        ):
            result = client.collect(URL, CONTRACT)
        self.assertEqual(result["provider"], "scrape-super-render")
        self.assertEqual(paid.call_count, 2)
        pool.fetch.assert_not_called()

    def test_browser_cooldown_is_scoped_to_engine_and_channel(self):
        first = Mock(engine="playwright", channel="chrome")
        first.fetch.side_effect = access.AccessError("BROWSER_UNAVAILABLE")
        second = Mock(engine="patchright", channel="chrome")
        second.fetch.return_value = html()
        self.store.record(
            "www.ptt.cc:browser:playwright:chrome",
            URL,
            "browser",
            "BLOCKED",
            self.at,
            300,
        )
        client = collector.Collector(self.store, now=lambda: self.at, browser=second)
        self.assertEqual(
            client.collect(URL, CONTRACT, browser_only=True)["provider"], "browser"
        )
        second.fetch.assert_called_once()

    def test_new_collector_process_reuses_durable_snapshot_and_health(self):
        with patch.object(collector, "scrape", return_value=html()):
            self.client.collect(URL, CONTRACT)
        reopened = collector.Collector(
            collector.Store(self.store.path), now=lambda: self.at + 20
        )
        with patch.object(collector, "scrape") as paid:
            self.assertEqual(reopened.collect(URL, CONTRACT)["cache"], "HIT")
        paid.assert_not_called()
        health = reopened.store.health()
        self.assertEqual(health[0]["successes"], 1)
        self.assertEqual(health[0]["last_verdict"], "OK")

    def test_dead_url_negative_cache_is_scoped_to_url_and_contract(self):
        with patch.object(collector, "scrape", return_value=html(404)) as paid:
            self.assertEqual(self.client.collect(URL, CONTRACT)["verdict"], "DEAD_URL")
            result = self.client.collect(URL, CONTRACT, refresh=True)
            self.assertEqual(result["cache"], "NEGATIVE")
            paid.assert_called_once()
        with patch.object(collector, "scrape", return_value=html()) as paid:
            self.assertEqual(
                self.client.collect(URL + "?other=1", CONTRACT)["verdict"], "OK"
            )
            paid.assert_called_once()

    def test_target_rate_limit_stops_all_routes_on_same_origin(self):
        raw = {**html(429), "retry_after": "120"}
        with (
            patch.object(collector, "scrape", return_value=raw) as paid,
            patch.object(collector, "direct") as native,
        ):
            self.client.collect(URL, CONTRACT)
            result = self.client.collect(URL + "?other=1", CONTRACT)
        paid.assert_called_once()
        native.assert_not_called()
        self.assertTrue(all(x["verdict"] == "COOLDOWN" for x in result["attempts"]))

    def test_reddit_reserve_normalizes_public_json_and_never_claims_completeness(self):
        comments = [{"kind": "t1", "data": {"id": "abc", "body": "Useful reply"}}]
        raw = {
            "status": 200,
            "body": json.dumps([{"data": {}}, {"data": {"children": comments}}]),
        }
        with patch.object(collector, "scrape", return_value=raw) as paid:
            result = collector.reddit_reserve(
                "https://www.reddit.com/comments/1x8cxex/"
            )
        payload = json.loads(result["body"])
        self.assertEqual(payload["results"][0]["text"], "Useful reply")
        self.assertEqual(payload["pagination"]["listing_status"], "unknown")
        self.assertIn(".json?raw_json=1", paid.call_args.args[0])

    def test_scrape_transport_requests_super_and_render_only_when_requested(self):
        meta = {
            "content_type": "text/html",
            "target_status": "200",
            "provider_status": 200,
            "retry_after": "120",
        }
        with patch.object(
            access, "request", return_value=(b"content", meta)
        ) as transport:
            raw = collector.scrape(URL)
            self.assertEqual(transport.call_args.args[1]["super"], "true")
            self.assertNotIn("render", transport.call_args.args[1])
            self.assertEqual(raw["retry_after"], "120")
            collector.scrape(URL, render=True)
            self.assertEqual(transport.call_args.args[1]["render"], "true")
            self.assertEqual(transport.call_args.args[1]["customWait"], "5000")

    def test_incomplete_native_response_is_origin_failure_without_render_spend(self):
        block = html(403, "<p>Verify you are human</p>")
        with (
            patch.object(collector, "scrape", return_value=block) as paid,
            patch.object(
                collector, "direct", side_effect=IncompleteRead(b"private fragment")
            ),
        ):
            result = self.client.collect(URL, CONTRACT)
        self.assertEqual(result["verdict"], "ORIGIN_DOWN")
        paid.assert_called_once()
        self.assertNotIn("private fragment", json.dumps(result))

    def test_unexpected_adapter_failure_is_accounted_and_next_url_still_runs(self):
        with patch.object(
            self.client,
            "collect",
            side_effect=[RuntimeError("secret diagnostics"), {"verdict": "OK"}],
        ):
            result = self.client.batch([URL, URL + "?other=1"])
        self.assertEqual(result["accounting"]["unaccounted"], 0)
        self.assertEqual(result["results"][0]["verdict"], "UNEXPECTED_SOURCE_ERROR")
        self.assertEqual(result["results"][0]["error_type"], "RuntimeError")
        self.assertEqual(result["results"][1]["verdict"], "OK")
        self.assertNotIn("secret diagnostics", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
