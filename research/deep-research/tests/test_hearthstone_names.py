from __future__ import annotations

import json
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import hearthstone_names  # noqa: E402


def response(data: dict[str, object]) -> bytes:
    return json.dumps({"data": data}).encode("utf-8")


class HearthstoneNameResolverTests(unittest.TestCase):
    def test_cross_origin_redirect_strips_authorization(self) -> None:
        request = Request(
            "https://api.kolodahearthstone.com/source",
            headers={"Authorization": "Bearer dummy-token"},
            method="GET",
        )
        handler = hearthstone_names._SecretSafeRedirectHandler()

        with self.assertRaisesRegex(HTTPError, "Cross-origin redirect blocked"):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://redirect.example/target",
            )

        same_origin = handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://api.kolodahearthstone.com/target",
        )
        self.assertIsNotNone(same_origin)
        self.assertEqual(same_origin.get_header("Authorization"), "Bearer dummy-token")

    def test_resolves_constructed_russian_name(self) -> None:
        def transport(request, timeout):
            self.assertIn("/constructed-cards/by-dbf/315", request.full_url)
            self.assertEqual(timeout, 3.0)
            return 200, {}, response(
                {
                    "dbf": 315,
                    "card_id": "CS2_029",
                    "name": {"ru": "Огненный шар", "en": "Fireball"},
                    "formats": [{"slug": "wild", "name_ru": "Вольный"}],
                    "updated_at": "2026-08-31T22:31:37Z",
                }
            )

        result = hearthstone_names.KolodaNameResolver(
            timeout=3.0, transport=transport
        ).resolve(315, "constructed")
        self.assertTrue(result["resolved"])
        self.assertEqual(result["name_ru"], "Огненный шар")
        self.assertEqual(result["kind"], "constructed")
        self.assertEqual(result["resolution_status"], "resolved")
        self.assertEqual(result["api_updated_at"], "2026-08-31T22:31:37Z")
        self.assertTrue(result["resolved_at"].endswith("Z"))

    def test_names_are_trimmed_and_non_string_values_are_not_coerced(self) -> None:
        payloads = {
            1: {
                "dbf": 1,
                "name": {"ru": "  Огненный шар  ", "en": "  Fireball  "},
            },
            2: {
                "dbf": 2,
                "name": {"ru": " \t ", "en": 123},
                "name_ru": 456,
                "name_en": "  Fallback name  ",
                "updated_at": "  2026-09-01T09:10:11Z  ",
            },
        }

        def transport(request, timeout):
            del timeout
            dbf = int(request.full_url.rsplit("/", 1)[-1])
            return 200, {}, response(payloads[dbf])

        resolver = hearthstone_names.KolodaNameResolver(transport=transport)
        normalized = resolver.resolve(1, "constructed")
        self.assertEqual(normalized["name_ru"], "Огненный шар")
        self.assertEqual(normalized["name_en"], "Fireball")

        unresolved = resolver.resolve(2, "constructed")
        self.assertFalse(unresolved["resolved"])
        self.assertIsNone(unresolved["name_ru"])
        self.assertEqual(unresolved["name_en"], "Fallback name")
        self.assertEqual(unresolved["api_updated_at"], "2026-09-01T09:10:11Z")
        self.assertTrue(unresolved["resolved_at"].endswith("Z"))

    def test_resolves_battlegrounds_russian_name(self) -> None:
        def transport(request, timeout):
            del timeout
            self.assertIn("/cards/by-dbf/130298", request.full_url)
            return 200, {}, response(
                {
                    "dbf": 130298,
                    "card_id": "BG35_883",
                    "name": {
                        "ru": "Балинда Каменный Очаг",
                        "en": "Balinda Stonehearth",
                    },
                }
            )

        result = hearthstone_names.KolodaNameResolver(
            transport=transport
        ).resolve(130298, "battlegrounds-card")
        self.assertEqual(result["name_ru"], "Балинда Каменный Очаг")

    def test_auto_falls_through_only_after_not_found(self) -> None:
        paths: list[str] = []

        def transport(request, timeout):
            del timeout
            paths.append(request.full_url)
            if "/constructed-cards/" in request.full_url:
                return 404, {}, b"{}"
            return 200, {}, response(
                {
                    "dbf": 130298,
                    "card_id": "BG35_883",
                    "name": {
                        "ru": "Балинда Каменный Очаг",
                        "en": "Balinda Stonehearth",
                    },
                }
            )

        result = hearthstone_names.KolodaNameResolver(
            transport=transport
        ).resolve(130298)
        self.assertEqual(result["kind"], "battlegrounds-card")
        self.assertEqual(result["attempted_kinds"], ["constructed", "battlegrounds-card"])
        self.assertEqual(len(paths), 2)

    def test_missing_russian_name_stays_unresolved(self) -> None:
        def transport(request, timeout):
            del request, timeout
            return 200, {}, response(
                {"dbf": 99, "card_id": "TEST_99", "name": {"en": "Test Card"}}
            )

        result = hearthstone_names.KolodaNameResolver(
            transport=transport
        ).resolve(99, "constructed")
        self.assertFalse(result["resolved"])
        self.assertIsNone(result["name_ru"])
        self.assertEqual(result["localization_gap"], "missing_russian_name")
        self.assertEqual(result["resolution_status"], "unresolved")
        self.assertEqual(result["unresolved_reason"], "missing_ru_name")

    def test_not_found_stays_visible(self) -> None:
        def transport(request, timeout):
            del request, timeout
            return 404, {}, b"{}"

        result = hearthstone_names.KolodaNameResolver(
            transport=transport
        ).resolve(123456, "hero")
        self.assertFalse(result["resolved"])
        self.assertEqual(result["localization_gap"], "entity_not_found")
        self.assertEqual(result["unresolved_reason"], "not_found")
        expected_url = "https://api.kolodahearthstone.com/api/v1/heroes/by-dbf/123456"
        self.assertEqual(result["source_url"], expected_url)
        self.assertEqual(result["source_urls"], [expected_url])
        self.assertEqual(
            result["attempts"],
            [
                {
                    "kind": "hero",
                    "source_url": expected_url,
                    "outcome": "not_found",
                    "checked_at": result["attempts"][0]["checked_at"],
                }
            ],
        )
        self.assertTrue(result["attempts"][0]["checked_at"].endswith("Z"))
        self.assertTrue(result["resolved_at"].endswith("Z"))

    def test_auto_unresolved_preserves_every_checked_url_and_attempt(self) -> None:
        def transport(request, timeout):
            del request, timeout
            return 404, {}, b"{}"

        result = hearthstone_names.KolodaNameResolver(
            transport=transport
        ).resolve(987654)
        self.assertFalse(result["resolved"])
        self.assertEqual(len(result["source_urls"]), len(hearthstone_names.AUTO_KINDS))
        self.assertEqual(len(result["attempts"]), len(hearthstone_names.AUTO_KINDS))
        self.assertEqual(
            [attempt["kind"] for attempt in result["attempts"]],
            list(hearthstone_names.AUTO_KINDS),
        )
        self.assertTrue(
            all(attempt["outcome"] == "not_found" for attempt in result["attempts"])
        )
        self.assertEqual(result["source_url"], result["source_urls"][-1])

    def test_hero_resolves_nested_entities_without_guessing_missing_locale(self) -> None:
        def transport(request, timeout):
            del timeout
            dbf = int(request.full_url.rsplit("/", 1)[-1])
            if dbf == 73941:
                return 404, {}, b"{}"
            if dbf == 77778:
                return 200, {}, response(
                    {
                        "dbf": 77778,
                        "card_id": "BG21_HERO_000_Buddy",
                        "name": {
                            "ru": "Капитан Гордостанная",
                            "en": "Captain Fairmount",
                        },
                    }
                )
            return 200, {}, response(
                {
                    "dbf": 73940,
                    "card_id": "BG21_HERO_000",
                    "name": {"ru": "Кариэль Роум", "en": "Cariel Roame"},
                    "hero_power": {
                        "dbf": 73941,
                        "card": {"dbf": 73941, "name": "  Убежденность  "},
                    },
                    "buddy": {
                        "dbf": 77778,
                        "card": {
                            "dbf": 77778,
                            "card_id": "BG21_HERO_000_Buddy",
                            "name": {"ru": "Капитан Гордостанная"},
                        },
                    },
                    "updated_at": "2026-08-31 05:23:24",
                }
            )

        resolver = hearthstone_names.KolodaNameResolver(transport=transport)
        result = resolver.resolve(73940, "hero")
        self.assertTrue(result["resolved"])
        hero_power = result["embedded_entities"]["hero_power"]
        self.assertEqual(hero_power["dbf"], 73941)
        self.assertEqual(hero_power["display_name"], "Убежденность")
        self.assertIsNone(hero_power["name_ru"])
        self.assertEqual(hero_power["display_name_language"], "unspecified")
        self.assertEqual(
            hero_power["localization_provenance"], "unqualified_embedded_name"
        )
        self.assertFalse(hero_power["standalone_resolved"])
        self.assertEqual(hero_power["standalone_unresolved_reason"], "not_found")
        self.assertEqual(hero_power["source_url"], result["source_url"])

        buddy = result["embedded_entities"]["buddy"]
        self.assertEqual(buddy["dbf"], 77778)
        self.assertEqual(buddy["card_id"], "BG21_HERO_000_Buddy")
        self.assertEqual(buddy["name_ru"], "Капитан Гордостанная")
        self.assertEqual(buddy["name_en"], "Captain Fairmount")
        self.assertIsNone(buddy["display_name"])
        self.assertEqual(
            buddy["localization_provenance"], "standalone_exact_dbf"
        )
        self.assertTrue(buddy["standalone_resolved"])
        self.assertEqual(buddy["standalone_resolution_status"], "resolved")

        result["embedded_entities"]["buddy"]["name_ru"] = "Искажённое имя"
        result["formats"].append({"slug": "mutated"})
        result["attempts"][0]["outcome"] = "mutated"
        result["source_urls"].append("https://example.com/mutated")
        cached = resolver.resolve(73940, "hero")
        self.assertEqual(
            cached["embedded_entities"]["buddy"]["name_ru"],
            "Капитан Гордостанная",
        )
        self.assertEqual(cached["formats"], [])
        self.assertEqual(cached["attempts"][0]["outcome"], "resolved")
        self.assertNotIn("https://example.com/mutated", cached["source_urls"])

    def test_token_is_header_only_and_never_returned(self) -> None:
        seen_authorization: list[str | None] = []

        def transport(request, timeout):
            del timeout
            seen_authorization.append(request.get_header("Authorization"))
            return 200, {}, response(
                {
                    "dbf": 315,
                    "card_id": "CS2_029",
                    "name": {"ru": "Огненный шар", "en": "Fireball"},
                }
            )

        with patch.dict(os.environ, {hearthstone_names.TOKEN_ENV: "private-token"}):
            result = hearthstone_names.KolodaNameResolver(
                transport=transport
            ).resolve(315, "constructed")
        rendered = json.dumps(result, ensure_ascii=False)
        self.assertEqual(seen_authorization, ["Bearer private-token"])
        self.assertNotIn("private-token", rendered)
        self.assertNotIn("private-token", result["source_url"])

    def test_token_is_never_sent_to_a_custom_origin(self) -> None:
        seen_authorization: list[str | None] = []

        def transport(request, timeout):
            del timeout
            seen_authorization.append(request.get_header("Authorization"))
            self.assertTrue(request.full_url.startswith("https://attacker.example/"))
            return 200, {}, response(
                {
                    "dbf": 315,
                    "card_id": "CS2_029",
                    "name": {"ru": "Огненный шар", "en": "Fireball"},
                }
            )

        with patch.dict(os.environ, {hearthstone_names.TOKEN_ENV: "private-token"}):
            resolver = hearthstone_names.KolodaNameResolver(
                base_url="https://attacker.example",
                transport=transport,
            )
            result = resolver.resolve(315, "constructed")

        self.assertFalse(resolver.authenticated)
        self.assertEqual(seen_authorization, [None])
        self.assertTrue(result["resolved"])

    def test_invalid_token_characters_are_rejected_without_leaking_value(self) -> None:
        unsafe_token = "dummy-secret-line-one\ndummy-secret-line-two"
        output = io.StringIO()
        with (
            patch.dict(os.environ, {hearthstone_names.TOKEN_ENV: unsafe_token}),
            patch("sys.stdout", output),
        ):
            exit_code = hearthstone_names.main(
                ["--dbf", "315", "--kind", "constructed"]
            )
        self.assertEqual(exit_code, 2)
        self.assertNotIn("dummy-secret", output.getvalue())
        self.assertIn("invalid header characters", output.getvalue())

    def test_transient_response_retries_with_bound(self) -> None:
        calls = 0
        delays: list[float] = []

        def transport(request, timeout):
            nonlocal calls
            del request, timeout
            calls += 1
            if calls == 1:
                return 503, {"Retry-After": "0"}, b"{}"
            return 200, {}, response(
                {
                    "dbf": 315,
                    "card_id": "CS2_029",
                    "name": {"ru": "Огненный шар", "en": "Fireball"},
                }
            )

        result = hearthstone_names.KolodaNameResolver(
            max_attempts=2, transport=transport, sleep=delays.append
        ).resolve(315, "constructed")
        self.assertTrue(result["resolved"])
        self.assertEqual(calls, 2)
        self.assertEqual(delays, [0.0])

    def test_network_retries_are_bounded(self) -> None:
        calls = 0

        def transport(request, timeout):
            nonlocal calls
            del request, timeout
            calls += 1
            raise URLError("offline")

        resolver = hearthstone_names.KolodaNameResolver(
            max_attempts=2, transport=transport, sleep=lambda delay: None
        )
        with self.assertRaisesRegex(RuntimeError, "lookup failed"):
            resolver.resolve(315, "constructed")
        self.assertEqual(calls, 2)

    def test_rejects_invalid_dbf_and_kind(self) -> None:
        resolver = hearthstone_names.KolodaNameResolver(
            transport=lambda request, timeout: (404, {}, b"{}")
        )
        with self.assertRaisesRegex(ValueError, "positive"):
            resolver.resolve(0)
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            resolver.resolve(315, "invented")


if __name__ == "__main__":
    unittest.main()
