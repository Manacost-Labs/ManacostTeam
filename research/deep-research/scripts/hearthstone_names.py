#!/usr/bin/env python3
"""Resolve official Russian Hearthstone entity names through Koloda API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


BASE_URL = "https://api.kolodahearthstone.com"
TOKEN_ENV = "KHS_API_TOKEN"

KIND_PATHS = {
    "constructed": "/api/v1/constructed-cards/by-dbf/{dbf}",
    "battlegrounds-card": "/api/v1/cards/by-dbf/{dbf}",
    "hero": "/api/v1/heroes/by-dbf/{dbf}",
    "timewarped": "/api/v1/timewarped-cards/by-dbf/{dbf}",
    "anomaly": "/api/v1/libraries/anomaly/by-dbf/{dbf}",
    "dark-gift": "/api/v1/libraries/dark_gift/by-dbf/{dbf}",
    "quest": "/api/v1/libraries/quest/by-dbf/{dbf}",
    "darkmoon-prize": "/api/v1/libraries/darkmoon_prize/by-dbf/{dbf}",
    "reward": "/api/v1/libraries/reward/by-dbf/{dbf}",
    "trinket": "/api/v1/libraries/trinket/by-dbf/{dbf}",
}
AUTO_KINDS = tuple(KIND_PATHS)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Transport(Protocol):
    def __call__(
        self, request: Request, timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]: ...


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is None:
        port = 443 if scheme == "https" else 80 if scheme == "http" else None
    return scheme, host, port


class _SecretSafeRedirectHandler(HTTPRedirectHandler):
    """Permit redirects only inside the official API origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and _origin(req.full_url) != _origin(newurl):
            raise HTTPError(
                req.full_url,
                code,
                "Cross-origin redirect blocked for Koloda name lookup.",
                headers,
                fp,
            )
        return redirected


def _urllib_transport(
    request: Request, timeout: float
) -> tuple[int, Mapping[str, str], bytes]:
    try:
        opener = build_opener(_SecretSafeRedirectHandler())
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def _header(headers: Mapping[str, str], name: str) -> str | None:
    return next(
        (str(value) for key, value in headers.items() if key.lower() == name.lower()),
        None,
    )


def _normalized_text(value: object) -> str | None:
    """Return a trimmed, non-empty string without coercing other JSON types."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _first_text(*values: object) -> str | None:
    for value in values:
        normalized = _normalized_text(value)
        if normalized is not None:
            return normalized
    return None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _embedded_hero_entities(
    data: Mapping[str, Any], source_url: str
) -> dict[str, dict[str, Any]]:
    """Preserve nested identity data without claiming standalone resolution.

    The hero endpoint currently returns an unqualified ``card.name`` for hero
    powers and buddies.  It looks localized in live responses, but the API
    contract does not label its language, so it must not be promoted to
    ``name_ru``.  Explicit future language fields remain safe to preserve.
    """

    embedded: dict[str, dict[str, Any]] = {}
    for payload_key, entity_kind in (
        ("hero_power", "hero-power"),
        ("buddy", "buddy"),
    ):
        relation = data.get(payload_key)
        if not isinstance(relation, Mapping):
            continue
        card = relation.get("card")
        card_data: Mapping[str, Any] = card if isinstance(card, Mapping) else {}
        nested_names = (
            card_data.get("name")
            if isinstance(card_data.get("name"), Mapping)
            else {}
        )
        name_ru = _first_text(
            nested_names.get("ru"),
            card_data.get("name_ru"),
        )
        name_en = _first_text(
            nested_names.get("en"),
            card_data.get("name_en"),
        )
        display_name = _normalized_text(card_data.get("name"))
        dbf = _positive_int(relation.get("dbf")) or _positive_int(
            card_data.get("dbf")
        )
        card_id = _normalized_text(card_data.get("card_id"))
        if not any((dbf, card_id, name_ru, name_en, display_name)):
            continue

        if name_ru or name_en:
            localization_provenance = "explicit_language_fields"
        elif display_name:
            localization_provenance = "unqualified_embedded_name"
        else:
            localization_provenance = "none"

        embedded[payload_key] = {
            "kind": entity_kind,
            "dbf": dbf,
            "card_id": card_id,
            "name_ru": name_ru,
            "name_en": name_en,
            "display_name": display_name,
            "display_name_language": "unspecified" if display_name else None,
            "standalone_resolved": False,
            "localization_provenance": localization_provenance,
            "payload_path": f"data.{payload_key}",
            "source_url": source_url,
        }
    return embedded


class KolodaNameResolver:
    """Resolve DBF IDs without inventing a Russian localization."""

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = BASE_URL,
        timeout: float = 8.0,
        max_attempts: int = 2,
        transport: Transport = _urllib_transport,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        raw_token = token if token is not None else os.environ.get(TOKEN_ENV, "")
        if any(ord(character) < 33 or ord(character) > 126 for character in raw_token):
            raise ValueError(f"{TOKEN_ENV} contains invalid header characters.")
        self._token = raw_token.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_attempts = max(1, min(max_attempts, 3))
        self.transport = transport
        self.sleep = sleep
        self._cache: dict[tuple[int, str], dict[str, Any]] = {}

    @property
    def authenticated(self) -> bool:
        return bool(self._token) and _origin(self.base_url) == _origin(BASE_URL)

    def resolve(self, dbf: int, kind: str = "auto") -> dict[str, Any]:
        if dbf <= 0:
            raise ValueError("DBF ID must be positive.")
        if kind != "auto" and kind not in KIND_PATHS:
            raise ValueError(f"Unsupported entity kind: {kind}.")

        cache_key = (dbf, kind)
        if cache_key in self._cache:
            return deepcopy(self._cache[cache_key])

        attempts: list[dict[str, Any]] = []
        for candidate in AUTO_KINDS if kind == "auto" else (kind,):
            source_url = self._source_url(dbf, candidate)
            result = self._fetch(dbf, candidate)
            if result is None:
                attempts.append(
                    {
                        "kind": candidate,
                        "source_url": source_url,
                        "outcome": "not_found",
                        "checked_at": _now_utc(),
                    }
                )
                continue
            if candidate == "hero" and result.get("embedded_entities"):
                self._resolve_embedded_hero_entities(result)
            attempts.append(
                {
                    "kind": candidate,
                    "source_url": source_url,
                    "outcome": (
                        "resolved"
                        if result["resolved"]
                        else result["localization_gap"]
                    ),
                    "checked_at": result["resolved_at"],
                }
            )
            result["attempted_kinds"] = [attempt["kind"] for attempt in attempts]
            result["source_urls"] = [attempt["source_url"] for attempt in attempts]
            result["attempts"] = attempts
            self._cache[cache_key] = deepcopy(result)
            return deepcopy(self._cache[cache_key])

        source_urls = [attempt["source_url"] for attempt in attempts]
        unresolved = {
            "dbf": dbf,
            "card_id": None,
            "kind": kind,
            "name_ru": None,
            "name_en": None,
            "resolved": False,
            "localization_gap": "entity_not_found",
            "resolution_status": "unresolved",
            "unresolved_reason": "not_found",
            "api_updated_at": None,
            "resolved_at": _now_utc(),
            "formats": [],
            "source_url": source_urls[-1] if source_urls else None,
            "source_urls": source_urls,
            "attempted_kinds": [attempt["kind"] for attempt in attempts],
            "attempts": attempts,
        }
        self._cache[cache_key] = deepcopy(unresolved)
        return deepcopy(self._cache[cache_key])

    def _resolve_embedded_hero_entities(self, result: dict[str, Any]) -> None:
        """Resolve nested hero-power/buddy DBFs through the exact card route."""

        embedded = result.get("embedded_entities")
        if not isinstance(embedded, dict):
            return
        for entity in embedded.values():
            if not isinstance(entity, dict):
                continue
            nested_dbf = entity.get("dbf")
            if not isinstance(nested_dbf, int) or nested_dbf <= 0:
                continue
            standalone = self.resolve(nested_dbf, "battlegrounds-card")
            entity["standalone_resolved"] = standalone["resolved"]
            entity["standalone_resolution_status"] = standalone[
                "resolution_status"
            ]
            entity["standalone_unresolved_reason"] = standalone[
                "unresolved_reason"
            ]
            entity["standalone_source_url"] = standalone["source_url"]
            entity["standalone_resolved_at"] = standalone["resolved_at"]
            if standalone["resolved"]:
                entity["name_ru"] = standalone["name_ru"]
                entity["name_en"] = standalone["name_en"]
                entity["card_id"] = standalone["card_id"] or entity.get("card_id")
                entity["localization_provenance"] = "standalone_exact_dbf"

    def _source_url(self, dbf: int, kind: str) -> str:
        path = KIND_PATHS[kind].format(dbf=dbf)
        return f"{self.base_url}{path}"

    def _fetch(self, dbf: int, kind: str) -> dict[str, Any] | None:
        source_url = self._source_url(dbf, kind)
        headers = {"Accept": "application/json", "User-Agent": "ResearchTeam/1.0"}
        if self.authenticated:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            request = Request(source_url, headers=headers, method="GET")
        except ValueError:
            raise RuntimeError("Koloda name lookup could not build a safe request.") from None

        for attempt in range(self.max_attempts):
            try:
                status, response_headers, body = self.transport(request, self.timeout)
            except ValueError:
                raise RuntimeError("Koloda name lookup rejected an unsafe request.") from None
            except (URLError, TimeoutError, OSError) as exc:
                if attempt + 1 < self.max_attempts:
                    self.sleep(min(float(2**attempt), 4.0))
                    continue
                raise RuntimeError("Koloda name lookup failed.") from exc

            if status == 404:
                return None
            if status in {429, 502, 503, 504} and attempt + 1 < self.max_attempts:
                retry_after = _header(response_headers, "Retry-After")
                try:
                    delay = min(float(retry_after or 2**attempt), 10.0)
                except ValueError:
                    delay = min(float(2**attempt), 10.0)
                self.sleep(delay)
                continue
            if status in {401, 403}:
                raise RuntimeError("Koloda name lookup authorization failed.")
            if status != 200:
                raise RuntimeError(f"Koloda name lookup returned HTTP {status}.")

            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError("Koloda name lookup returned invalid JSON.") from exc

            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict) or data.get("dbf") != dbf:
                raise RuntimeError("Koloda name lookup returned an unexpected shape.")

            names = data.get("name") if isinstance(data.get("name"), dict) else {}
            name_ru = _first_text(names.get("ru"), data.get("name_ru"))
            name_en = _first_text(names.get("en"), data.get("name_en"))
            formats = data.get("formats") if isinstance(data.get("formats"), list) else []
            result = {
                "dbf": dbf,
                "card_id": data.get("card_id"),
                "kind": kind,
                "name_ru": name_ru,
                "name_en": name_en,
                "resolved": bool(name_ru),
                "localization_gap": None if name_ru else "missing_russian_name",
                "resolution_status": "resolved" if name_ru else "unresolved",
                "unresolved_reason": None if name_ru else "missing_ru_name",
                "api_updated_at": _first_text(
                    data.get("updated_at"),
                    data.get("fetched_at"),
                    data.get("changed_at"),
                ),
                "resolved_at": _now_utc(),
                "formats": formats,
                "source_url": source_url,
            }
            if kind == "hero":
                embedded_entities = _embedded_hero_entities(data, source_url)
                if embedded_entities:
                    result["embedded_entities"] = embedded_entities
            return result

        raise RuntimeError("Koloda name lookup failed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve an official Russian Hearthstone name by DBF ID."
    )
    parser.add_argument("--dbf", type=int, required=True)
    parser.add_argument("--kind", choices=("auto", *KIND_PATHS), default="auto")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = KolodaNameResolver().resolve(args.dbf, args.kind)
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["resolved"] else 1


if __name__ == "__main__":
    sys.exit(main())
