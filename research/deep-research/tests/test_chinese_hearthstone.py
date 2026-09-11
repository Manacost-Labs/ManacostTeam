#!/usr/bin/env python3
"""Offline regression tests for Chinese Hearthstone ingestion."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/chinese"
MODULE_PATH = ROOT / "scripts/chinese_hearthstone.py"
SPEC = importlib.util.spec_from_file_location("chinese_hearthstone", MODULE_PATH)
assert SPEC and SPEC.loader
chinese_hearthstone = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = chinese_hearthstone
SPEC.loader.exec_module(chinese_hearthstone)


def varint(value: int) -> bytes:
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        result.append(byte | 0x80 if value else byte)
        if not value:
            return bytes(result)


def encode_deck(cards: dict[int, int], hero: int = 7) -> str:
    data = bytearray(b"\0") + varint(1) + varint(2)
    data += varint(1) + varint(hero)
    singles = sorted(key for key, count in cards.items() if count == 1)
    doubles = sorted(key for key, count in cards.items() if count == 2)
    others = sorted((key, count) for key, count in cards.items() if count not in {1, 2})
    data += varint(len(singles))
    for key in singles:
        data += varint(key)
    data += varint(len(doubles))
    for key in doubles:
        data += varint(key)
    data += varint(len(others))
    for key, count in others:
        data += varint(key) + varint(count)
    data += b"\0"
    return base64.b64encode(data).decode("ascii")


class ChineseHearthstoneTest(unittest.TestCase):
    def test_valid_invalid_and_multiple_deckstrings(self) -> None:
        valid = encode_deck({key: 2 for key in range(1000, 1015)})
        text = f"第一套 {valid} 重复 {valid} 无效 AAE-not-a-real-deck-code-123456789"
        decks = chinese_hearthstone.extract_deckstrings(text)
        self.assertEqual(len(decks), 2)
        self.assertTrue(decks[0].valid)
        self.assertEqual(decks[0].cards_total, 30)
        self.assertFalse(decks[1].valid)

    def test_iyingdi_fixture_extracts_cn_statistics_and_meta_classification(
        self,
    ) -> None:
        raw = (FIXTURES / "iyingdi_cn_meta.html").read_text(encoding="utf-8")
        result = chinese_hearthstone.inspect_document(
            raw,
            source_url="https://www.iyingdi.com/tz/post/123?utm_source=test",
            profile=chinese_hearthstone.SOURCE_PROFILES["iyingdi"],
        )
        self.assertTrue(result["validation"]["valid"])
        self.assertEqual(result["statistics"]["region"], "CN")
        self.assertEqual(result["statistics"]["games"], 1280)
        self.assertEqual(result["statistics"]["win_rate"], 55.0)
        self.assertEqual(result["classification"]["label"], "CN_META")
        self.assertEqual(len(result["decks"]), 1)
        self.assertTrue(result["decks"][0]["valid"])
        self.assertNotIn("utm_source", result["source_url"])

    def test_multi_deck_page_binds_statistics_to_each_deck(self) -> None:
        first = encode_deck({key: 2 for key in range(1000, 1015)})
        second = encode_deck({key: 2 for key in range(2000, 2015)})
        raw = f"""
        <html><head><title>国服前200标准卡组</title></head><body><article>
        <h1>炉石传说国服卡组数据报</h1>
        <p>{first}</p><p>服务器：国服</p><p>口德</p>
        <p>总场数：80；赢47/输33；胜率：58.75%；排名区间：legend-5 ~ legend-200；最后更新时间：2026-08-27 19:01:00</p>
        <p>{second}</p><p>服务器：国服</p><p>兆示贼</p>
        <p>总场数：79；赢43/输36；胜率：54.43%；排名区间：legend-4 ~ legend-200；最后更新时间：2026-08-27 19:01:00</p>
        </article></body></html>
        """
        result = chinese_hearthstone.inspect_document(
            raw,
            source_url="https://www.iyingdi.com/tz/post/records",
            profile=chinese_hearthstone.SOURCE_PROFILES["iyingdi"],
        )
        records = result["deck_records"]
        self.assertEqual(result["schema_version"], "1.1")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["archetype_zh"], "口德")
        self.assertEqual(records[0]["statistics"]["games"], 80)
        self.assertEqual(records[0]["statistics"]["win_rate"], 58.75)
        self.assertEqual(records[1]["archetype_zh"], "兆示贼")
        self.assertEqual(records[1]["statistics"]["games"], 79)
        self.assertEqual(records[1]["statistics"]["win_rate"], 54.43)
        self.assertEqual(records[1]["classification"]["label"], "CN_META")
        self.assertNotEqual(records[0]["record_id"], records[1]["record_id"])

    def test_iyingdi_byline_and_title_date_do_not_use_data_timestamp(self) -> None:
        deck = encode_deck({key: 2 for key in range(1000, 1015)})
        raw = f"""
        <html><head><title>【炉石数据报】20260822 国服卡组</title>
        <meta name="Author" content="旅法师营地"></head><body><article>
        <h1>【炉石数据报】20260822 国服卡组</h1><p>许仙许宣 Lv.52</p>
        <p>{deck}</p><p>服务器：国服</p><p>口德</p>
        <p>总场数：80；胜率：58.75%；最后更新时间：2026-08-27 19:01:00</p>
        <p>8月22日 发布于广西，炉石传说卡组数据仅代表公开样本。</p>
        </article></body></html>
        """
        result = chinese_hearthstone.inspect_document(
            raw,
            source_url="https://www.iyingdi.com/tz/post/metadata",
            profile=chinese_hearthstone.SOURCE_PROFILES["iyingdi"],
        )
        self.assertEqual(result["author"], "许仙许宣")
        self.assertEqual(result["publisher"], "旅法师营地")
        self.assertEqual(result["published_at"], "2026-08-22")
        self.assertEqual(result["page_metadata"]["field_sources"]["author"], "visible-byline:lv")
        self.assertEqual(
            result["deck_records"][0]["statistics"]["updated_at_raw"],
            "2026-08-27 19:01:00",
        )

    def test_json_ld_metadata_preserves_author_publisher_and_timezone(self) -> None:
        deck = encode_deck({key: 2 for key in range(3000, 3015)})
        raw = f"""
        <html><head><title>炉石传说口德攻略</title>
        <script type="application/ld+json">{{
          "@type":"NewsArticle",
          "headline":"炉石传说口德攻略",
          "datePublished":"2026-08-22T18:36:53+08:00",
          "dateModified":"2026-08-23T09:00:00+08:00",
          "author":{{"@type":"Person","name":"十局上半战队"}},
          "publisher":{{"@type":"Organization","name":"17173"}}
        }}</script></head><body><article>
        <h1>17173 炉石传说口德卡组攻略</h1><p>{deck}</p>
        <p>起手留牌与对局运营说明，内容长度用于稳定验证页面主体。</p>
        </article></body></html>
        """
        result = chinese_hearthstone.inspect_document(
            raw,
            source_url="https://news.17173.com/content/metadata.shtml",
            profile=chinese_hearthstone.SOURCE_PROFILES["17173"],
        )
        self.assertEqual(result["author"], "十局上半战队")
        self.assertEqual(result["publisher"], "17173")
        self.assertEqual(result["published_at"], "2026-08-22T18:36:53+08:00")
        self.assertEqual(result["modified_at"], "2026-08-23T09:00:00+08:00")
        self.assertEqual(
            result["page_metadata"]["field_sources"]["published_at"],
            "json-ld:datePublished",
        )

    def test_metadata_ignores_meta_tags_without_identity(self) -> None:
        metadata = chinese_hearthstone.extract_page_metadata(
            '<html><head><meta charset="utf-8"><meta content="width=device-width"></head></html>',
            "",
            None,
        )
        self.assertIsNone(metadata.author)
        self.assertIsNone(metadata.published_at)

    def test_special_deck_size_is_a_warning_not_structural_failure(self) -> None:
        rafaam = (
            "AAECAf0GDsODB4ilB4mlB4qlB5GlB5OlB5SlB5WlB5alB5elB5qlB63ZB9LgB9vgBw2P"
            "nwTnoASpiAeEmQfenQfhnQeTvgfYvgfgvgex2Qe32QeN3AeO3AcAAA=="
        )
        deck = chinese_hearthstone.decode_deckstring(rafaam)
        self.assertTrue(deck.valid)
        self.assertEqual(deck.cards_total, 40)
        self.assertEqual(deck.deck_size_status, "SPECIAL_OR_UNVERIFIED")
        self.assertEqual(deck.validation_errors, [])
        self.assertIn("unexpected_card_total:40", deck.validation_warnings)

    def test_repeated_deck_code_keeps_distinct_source_records(self) -> None:
        deck = encode_deck({key: 2 for key in range(1000, 1015)})
        text = (
            f"{deck}\n服务器：国服\n口德\n总场数：80\n胜率：58.75%\n"
            f"{deck}\n服务器：欧服\n口德\n总场数：40\n胜率：55.0%"
        )
        records = chinese_hearthstone.extract_deck_records(text)
        self.assertEqual(len(chinese_hearthstone.extract_deckstrings(text)), 1)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["statistics"]["region"], "CN")
        self.assertEqual(records[1]["statistics"]["region"], "EU")
        self.assertNotEqual(records[0]["context_hash"], records[1]["context_hash"])

    def test_koloda_marks_noncollectible_special_encoding(self) -> None:
        deck = chinese_hearthstone.decode_deckstring(
            encode_deck({**{key: 2 for key in range(1000, 1015)}, 2000: 1})
        )

        def transport(request, timeout):
            dbf = int(request.full_url.rsplit("/", 1)[-1])
            payload = {
                "data": {
                    "dbf": dbf,
                    "card_id": f"TEST_{dbf}",
                    "name": {"ru": str(dbf), "en": str(dbf)},
                    "class": "NEUTRAL",
                    "card_type": {"slug": "MINION"},
                    "card_set": "TEST",
                    "collectible": dbf != 2000,
                    "formats": [{"slug": "standard"}],
                    "updated_at": "2026-08-30 00:00:00",
                }
            }
            return 200, {"Content-Type": "application/json"}, json.dumps(payload).encode()

        resolved = chinese_hearthstone.KolodaCardDatabase(
            transport=transport, sleep=lambda _: None
        ).resolve_deck(deck)
        self.assertEqual(resolved["deck_size_assessment"], "SPECIAL_ENCODING_DETECTED")
        self.assertEqual(resolved["noncollectible_entries_total"], 1)
        self.assertEqual(resolved["noncollectible_dbf_ids"], [2000])

    def test_gamersky_repost_preserves_lineage_and_is_not_independent(self) -> None:
        raw = (FIXTURES / "gamersky_repost.html").read_text(encoding="utf-8")
        result = chinese_hearthstone.inspect_document(
            raw,
            source_url="https://ol.gamersky.com/gl/123",
            profile=chinese_hearthstone.SOURCE_PROFILES["gamersky"],
        )
        self.assertEqual(result["classification"]["label"], "WESTERN_REPOST")
        self.assertIn("hsreplay.net", result["deduplication"]["lineage_hint"])

    def test_provenance_stops_at_brackets_and_recovers_declared_team(self) -> None:
        provenance = chinese_hearthstone.extract_provenance(
            "【来源：公众号】\n本期由十局上半战队\n给大家带来\n标准模式卡组"
        )
        self.assertEqual(provenance.original_source, "公众号")
        self.assertEqual(provenance.original_author, "十局上半战队")
        self.assertEqual(provenance.attribution_quality, "PARTIAL")

    def test_17173_fixture_keeps_all_twenty_deck_relationships(self) -> None:
        raw = (FIXTURES / "17173_multi_deck.html").read_text(encoding="utf-8")
        result = chinese_hearthstone.inspect_document(
            raw,
            source_url="https://hs.17173.com/news/123",
            profile=chinese_hearthstone.SOURCE_PROFILES["17173"],
        )
        self.assertEqual(len(result["decks"]), 20)
        self.assertTrue(all(deck["valid"] for deck in result["decks"]))
        self.assertEqual(len({deck["fingerprint"] for deck in result["decks"]}), 20)

    def test_deck_similarity_boundaries(self) -> None:
        base = {key: 1 for key in range(1, 31)}
        exact = chinese_hearthstone.compare_decks(base, base)
        near = chinese_hearthstone.compare_decks(
            base, {**{key: 1 for key in range(1, 30)}, 31: 1}
        )
        variant = chinese_hearthstone.compare_decks(
            base, {**{key: 1 for key in range(1, 29)}, 31: 1, 32: 1}
        )
        archetype = chinese_hearthstone.compare_decks(
            base, {**{key: 1 for key in range(1, 27)}, 31: 1, 32: 1, 33: 1, 34: 1}
        )
        self.assertEqual(exact.relation, "EXACT")
        self.assertEqual(near.relation, "NEAR_DUPLICATE")
        self.assertEqual(variant.relation, "VARIANT")
        self.assertEqual(archetype.relation, "ARCHETYPE_VARIANT")
        self.assertEqual(sum(variant.removed.values()), 2)
        self.assertEqual(sum(variant.added.values()), 2)

    def test_cn_original_requires_checked_absence_of_western_match(self) -> None:
        stats = chinese_hearthstone.extract_cn_stats("国服传说排名 88")
        provenance = chinese_hearthstone.extract_provenance("本人构筑，国服传说排名 88")
        unchecked = chinese_hearthstone.classify_cn_deck(
            "本人构筑，国服传说排名 88", stats, provenance
        )
        checked = chinese_hearthstone.classify_cn_deck(
            "本人构筑，国服传说排名 88",
            stats,
            provenance,
            western_match_checked=True,
        )
        self.assertEqual(unchecked.label.value, "CN_META")
        self.assertEqual(checked.label.value, "CN_ORIGINAL")

    def test_cn_variant_records_added_and_removed_cards(self) -> None:
        western = {key: 1 for key in range(1, 31)}
        chinese = {**{key: 1 for key in range(1, 29)}, 31: 1, 32: 1}
        comparison = chinese_hearthstone.compare_decks(western, chinese)
        result = chinese_hearthstone.classify_cn_deck(
            "国服传说构筑",
            chinese_hearthstone.CNStats(region="CN"),
            chinese_hearthstone.Provenance(),
            comparison=comparison,
        )
        self.assertEqual(result.label.value, "CN_VARIANT")
        self.assertEqual(result.comparison["relation"], "VARIANT")

    def test_content_validation_rejects_captcha_spa_403_and_429(self) -> None:
        profile = chinese_hearthstone.SOURCE_PROFILES["iyingdi"]
        captcha = chinese_hearthstone.validate_content(
            "<html>CAPTCHA 安全验证</html>", profile
        )
        spa = chinese_hearthstone.validate_content(
            '<html><body><div id="root"></div></body></html>', profile
        )
        forbidden = chinese_hearthstone.validate_content(
            "forbidden", profile, status_code=403
        )
        limited = chinese_hearthstone.validate_content("busy", profile, status_code=429)
        self.assertEqual(captcha.status.value, "BLOCKED")
        self.assertEqual(spa.status.value, "INCOMPLETE")
        self.assertEqual(forbidden.status.value, "BLOCKED")
        self.assertEqual(limited.status.value, "RATE_LIMITED")

    def test_scrape_do_escalates_only_after_content_failure(self) -> None:
        requests: list[dict[str, list[str]]] = []
        good = (FIXTURES / "iyingdi_cn_meta.html").read_bytes()

        def transport(request, timeout):
            query = parse_qs(urlsplit(request.full_url).query)
            requests.append(query)
            if len(requests) == 1:
                return 200, {"Content-Type": "text/html"}, b'<div id="root"></div>'
            return (
                200,
                {
                    "Content-Type": "text/html; charset=utf-8",
                    "Scrape.do-Resolved-Url": "https://iyingdi.com/post/1",
                    "Scrape.do-Request-Cost": "5",
                    "Scrape.do-Remaining-Credits": "995",
                },
                good,
            )

        client = chinese_hearthstone.ScrapeDoClient(
            "fixture-token", transport=transport, sleep=lambda _: None
        )
        result = client.fetch(
            "https://iyingdi.com/post/1", chinese_hearthstone.SOURCE_PROFILES["iyingdi"]
        )
        public = json.dumps(result.public_dict(), ensure_ascii=False)
        self.assertEqual(result.status.value, "SUCCESS")
        self.assertEqual(
            [attempt.level for attempt in result.attempts], ["normal", "render"]
        )
        self.assertNotIn("render", requests[0])
        self.assertEqual(requests[1]["render"], ["true"])
        self.assertNotIn("fixture-token", public)
        self.assertEqual(
            result.public_dict()["diagnostics"]["remaining_credits"], "995"
        )
        self.assertEqual(
            result.public_dict()["diagnostics"]["reported_credits_used"], 5.0
        )

    def test_scrape_do_cache_hit_avoids_network_and_never_stores_token(self) -> None:
        good = (FIXTURES / "iyingdi_cn_meta.html").read_bytes()
        calls = 0

        def transport(request, timeout):
            nonlocal calls
            calls += 1
            return 200, {"Content-Type": "text/html; charset=utf-8"}, good

        with tempfile.TemporaryDirectory() as temp:
            cache = chinese_hearthstone.FetchCache(Path(temp))
            first = chinese_hearthstone.ScrapeDoClient(
                "fixture-token", transport=transport, cache=cache
            ).fetch(
                "https://iyingdi.com/post/cache",
                chinese_hearthstone.SOURCE_PROFILES["iyingdi"],
            )
            second = chinese_hearthstone.ScrapeDoClient(
                "fixture-token",
                transport=lambda request, timeout: self.fail(
                    "cache hit must not use the network"
                ),
                cache=cache,
            ).fetch(
                "https://iyingdi.com/post/cache",
                chinese_hearthstone.SOURCE_PROFILES["iyingdi"],
            )
            cached_text = "".join(
                path.read_text(encoding="utf-8")
                for path in Path(temp).glob("*.json")
            )

        self.assertEqual(first.cache_status, "MISS")
        self.assertEqual(second.cache_status, "HIT")
        self.assertEqual(second.attempts, [])
        self.assertEqual(calls, 1)
        self.assertNotIn("fixture-token", cached_text)
        self.assertEqual(second.public_dict()["diagnostics"]["network_requests"], 0)

    def test_scrape_do_stale_cache_is_refetched(self) -> None:
        good = (FIXTURES / "iyingdi_cn_meta.html").read_bytes()
        calls = 0

        def transport(request, timeout):
            nonlocal calls
            calls += 1
            return 200, {"Content-Type": "text/html; charset=utf-8"}, good

        with tempfile.TemporaryDirectory() as temp:
            cache = chinese_hearthstone.FetchCache(Path(temp))
            client = chinese_hearthstone.ScrapeDoClient(
                "fixture-token",
                transport=transport,
                cache=cache,
                cache_ttl_seconds=0,
            )
            client.fetch(
                "https://iyingdi.com/post/stale",
                chinese_hearthstone.SOURCE_PROFILES["iyingdi"],
            )
            cache_path = next(Path(temp).glob("*.json"))
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            payload["created_at"] = 1
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
            result = client.fetch(
                "https://iyingdi.com/post/stale",
                chinese_hearthstone.SOURCE_PROFILES["iyingdi"],
            )

        self.assertEqual(result.cache_status, "STALE")
        self.assertEqual(calls, 2)

    def test_local_scrape_do_rate_limit_fails_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            limiter = chinese_hearthstone.SlidingWindowRateLimiter(
                1, state_dir=Path(temp), clock=lambda: 1000.0
            )
            self.assertEqual(limiter.reserve(), 0.0)
            called = False

            def transport(request, timeout):
                nonlocal called
                called = True
                return 500, {}, b""

            result = chinese_hearthstone.ScrapeDoClient(
                "fixture-token",
                transport=transport,
                rate_limiter=limiter,
                max_rate_wait=0,
            ).fetch(
                "https://nga.cn/read.php?tid=1",
                chinese_hearthstone.SOURCE_PROFILES["nga"],
            )

        self.assertFalse(called)
        self.assertEqual(result.status.value, "RATE_LIMITED")
        self.assertEqual(result.attempts[0].level, "local_rate_limit")
        self.assertEqual(
            result.public_dict()["diagnostics"]["codes"], ["local_rate_limit"]
        )

    def test_scrape_do_marks_browser_fallback_after_all_levels(self) -> None:
        def transport(request, timeout):
            return 200, {"Content-Type": "text/html"}, b'<div id="root"></div>'

        result = chinese_hearthstone.ScrapeDoClient(
            "fixture-token", transport=transport, sleep=lambda _: None
        ).fetch(
            "https://taptap.cn/topic/1", chinese_hearthstone.SOURCE_PROFILES["taptap"]
        )
        self.assertTrue(result.browser_fallback_required)
        self.assertEqual(len(result.attempts), 4)
        self.assertEqual(result.status.value, "INCOMPLETE")

    def test_koloda_adapter_normalizes_card_and_uses_bearer_header(self) -> None:
        captured = {}

        def transport(request, timeout):
            captured.update(dict(request.header_items()))
            payload = {
                "data": {
                    "dbf": 315,
                    "card_id": "CS2_029",
                    "name": {"ru": "Огненный шар", "en": "Fireball"},
                    "class": "MAGE",
                    "card_type": {"slug": "SPELL"},
                    "card_set": "LEGACY",
                    "collectible": True,
                    "formats": [{"slug": "wild"}],
                    "updated_at": "2026-08-30 21:07:27",
                }
            }
            return (
                200,
                {"Content-Type": "application/json"},
                json.dumps(payload).encode(),
            )

        database = chinese_hearthstone.KolodaCardDatabase(
            "fixture-khs-token", transport=transport, sleep=lambda _: None
        )
        card = database.get_card(315)
        self.assertEqual(card["name"]["ru"], "Огненный шар")
        self.assertEqual(captured["Authorization"], "Bearer fixture-khs-token")
        self.assertNotIn("fixture-khs-token", json.dumps(card, ensure_ascii=False))

    def test_koloda_adapter_handles_missing_card(self) -> None:
        database = chinese_hearthstone.KolodaCardDatabase(
            transport=lambda request, timeout: (404, {}, b"{}"), sleep=lambda _: None
        )
        self.assertIsNone(database.get_card(99999999))

    def test_scrape_do_does_not_escalate_a_dead_url(self) -> None:
        result = chinese_hearthstone.ScrapeDoClient(
            "fixture-token",
            transport=lambda request, timeout: (
                404,
                {
                    "Scrape.do-Initial-Status-Code": "404",
                    "Scrape.do-Request-Cost": "1",
                },
                b"not found",
            ),
            sleep=lambda _: None,
        ).fetch("https://nga.cn/not-found", chinese_hearthstone.SOURCE_PROFILES["nga"])
        self.assertEqual(result.status.value, "UNSUPPORTED")
        self.assertEqual(len(result.attempts), 1)
        self.assertFalse(result.browser_fallback_required)

    def test_bilibili_payload_preserves_timestamped_guide_evidence(self) -> None:
        payload = json.loads(
            (FIXTURES / "bilibili_video.json").read_text(encoding="utf-8")
        )
        result = chinese_hearthstone.parse_bilibili_payload(
            payload, "https://www.bilibili.com/video/BV1ResearchTeam"
        )
        self.assertEqual(len(result["transcript_segments"]), 3)
        self.assertEqual(len(result["guide_evidence"]), 2)
        self.assertEqual(result["guide_evidence"][0]["timestamp_start"], 12.5)
        self.assertEqual(result["guide_evidence"][1]["category"], "matchup")
        self.assertEqual(len(result["deckstrings"]), 1)

    def test_guide_hunter_builds_localized_queries_for_each_source(self) -> None:
        queries = chinese_hearthstone.build_guide_queries(None, "控制战")
        self.assertEqual(len(queries), 24)
        self.assertTrue(
            any("site:nga.cn" in query and "留牌" in query for query in queries)
        )
        self.assertTrue(
            any("site:bilibili.com" in query and "构筑" in query for query in queries)
        )

    def test_evidence_clustering_counts_lineages_not_reposts(self) -> None:
        first = chinese_hearthstone.make_guide_evidence(
            source_id="one",
            source_url="https://example.cn/1",
            source_type="article",
            text_zh="起手留牌优先保留低费随从",
            lineage_id="original:one",
        )
        repost = chinese_hearthstone.make_guide_evidence(
            source_id="two",
            source_url="https://example.cn/2",
            source_type="article",
            text_zh="起手留牌优先保留低费随从",
            lineage_id="original:one",
        )
        independent = chinese_hearthstone.make_guide_evidence(
            source_id="three",
            source_url="https://example.cn/3",
            source_type="video",
            text_zh="起手留牌优先保留低费随从",
            lineage_id="original:three",
        )
        cluster = chinese_hearthstone.cluster_evidence([first, repost, independent])[0]
        self.assertEqual(cluster["state"], "corroborated")
        self.assertEqual(cluster["independent_lineages"], 2)

    def test_cn_deck_score_uses_configurable_weights(self) -> None:
        score = chinese_hearthstone.cn_deck_score(
            {
                "originality": 1.0,
                "performance": 0.8,
                "evidence": 0.5,
                "freshness": 1.0,
                "guide": 0.5,
            }
        )
        self.assertEqual(score, 80.0)

    def test_dictionary_and_structured_guide_contract_are_available(self) -> None:
        self.assertEqual(chinese_hearthstone.CN_HEARTHSTONE_TERMS["留牌"], "mulligan")
        schema = chinese_hearthstone.empty_guide_schema()
        self.assertIn("always_keep", schema["mulligan"])
        self.assertEqual(schema["matchups"], [])

    def test_doctor_never_emits_credentials(self) -> None:
        with patch.dict(
            os.environ,
            {
                chinese_hearthstone.SCRAPE_DO_TOKEN_ENV: "fixture-scrape-secret",
                chinese_hearthstone.KHS_TOKEN_ENV: "fixture-khs-secret",
            },
            clear=False,
        ):
            result = chinese_hearthstone.doctor()
        rendered = json.dumps(result)
        self.assertTrue(result["scrape_do"]["configured"])
        self.assertTrue(result["koloda_card_database"]["token_configured"])
        self.assertNotIn("fixture-scrape-secret", rendered)
        self.assertNotIn("fixture-khs-secret", rendered)


if __name__ == "__main__":
    unittest.main()
