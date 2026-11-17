"""Детерминированные контрасты статистики из api.kolodahearthstone.com.

Шаг 0 исследования: до черновика автор видит не «пересказ таблицы», а места,
где цифры спорят друг с другом. Модуль только считает и метит контрасты;
причину («почему карта ловушка») он не придумывает — её ищут в стримах,
на Reddit и в патчноутах.

Источник — первичный API владельца (только публичные GET) или уже сохранённые
JSON: каталог `stats-bundle` из
`research/deep-research/scripts/community_sources.py` либо сохранённый вывод
`community_sources.py stats-api`. Имена файлов совпадают с именами срезов:

* `battlegrounds-minions.json` — `GET /v1/battlegrounds/minions?limit=500`;
* `hsreplay_battlegrounds_trinkets_{all,top_1_percent}_current_battlegrounds_patch.json`
  — `GET /datasets/<source_id>`;
* `hsguru_meta_<standard|wild>_<diamond_4to1|legend|top_legend>.json`
  — `GET /datasets/<source_id>`.

    python -m editorteam.stats_insights --mode battlegrounds --tavern-tier 1 \
        --output RUN/stats-insights.json
    python -m editorteam.stats_insights --mode standard --output RUN/stats-insights.json
    python -m editorteam.stats_insights --mode battlegrounds --from RUN/stats-bundle \
        --output RUN/stats-insights.json

Формат `stats-insights.json` (ключи стабильны, порядок записей детерминирован):

    {
      "schema_version": "1.0",
      "mode": "battlegrounds" | "standard" | "wild",
      "tavern_tier": 1 | null,
      "fetched_at": "<самый старый fetched_at среди использованных срезов>",
      "source_urls": ["https://api.kolodahearthstone.com/..."],
      "sources": [{"name", "source_url", "source_id", "fetched_at", "stale"}],
      "warnings": ["Срез ... устарел ..."],
      "thresholds": {...именованные пороги ниже...},
      "pool": {...объём пула и записи без статистики...},
      "insights": {
        "crowd_traps": [запись существа],
        "pure_early_tempo": [запись существа],
        "scaling_engines": [запись существа + "survivorship_note"],
        "rank_skill_gaps": [запись архетипа или аксессуара]
      }
    }

Запись существа: `card_id`, `dbf_id`, `name` (русское имя, если есть),
`name_en`, `tavern_tier`, `popularity`, `popularity_rank`, `combat_winrate`,
`impact`, `avg_placement_with`, `avg_placement_without`, `games_with_minion`,
`label`. Запись `rank_skill_gaps`: `kind` (`ladder_archetype` | `bg_trinket`),
`name`, срезы `low_rank`/`high_rank`, значения в обоих срезах, разницы,
`contrasts` (машинные метки) и `label`. В режимах Ладдера списки детекторов
БГ остаются пустыми, но ключи присутствуют всегда.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCHEMA_VERSION = "1.0"
API_BASE_URL = (
    os.environ.get("HEARTHSTONE_STATS_API_URL", "https://api.kolodahearthstone.com/v1")
    .strip()
    .rstrip("/")
)
DATASET_BASE_URL = API_BASE_URL.removesuffix("/v1")
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 30.0
ENDPOINT_PAGE_LIMIT = 500  # максимум `limit`, который принимает API
BUNDLE_MANIFEST = "stats-bundle-manifest.json"

# Пороги детекторов. Меняйте здесь, а не в коде детекторов.
CROWD_TRAP_MAX_IMPACT = -0.04  # популярность >= p75 тира И impact <= -0.04
EARLY_TEMPO_MIN_COMBAT_WINRATE = 56.0  # combat winrate >= 56% И impact <= 0
EARLY_TEMPO_MAX_IMPACT = 0.0
SCALING_MIN_IMPACT = 0.10  # impact >= +0.10, всегда с survivorship_note
MIN_GAMES_WITH_MINION = 1000  # меньше — шум, существо не идёт в детекторы
MIN_POOL_FOR_QUANTILE = 4  # p75 по меньшему пулу не считаем
STALE_AFTER_HOURS = 30.0  # совпадает со stale_after_hours самого API
LADDER_RANK_PAIRS = (("diamond_4to1", "legend"), ("diamond_4to1", "top_legend"))
LADDER_MIN_GAMES = 300
LADDER_RELATIVE_WINRATE_GAP_PP = 2.0
LADDER_POPULARITY_GAP_PP = 2.0
TRINKET_RANK_PAIRS = (("all", "top_1_percent"),)
TRINKET_MIN_GAMES = 100
TRINKET_PICK_RATE_GAP_PP = 8.0
TRINKET_RELATIVE_PLACEMENT_GAP = 0.30
MAX_SKILL_GAPS_PER_PAIR = 12

MINIONS_SLICE = "battlegrounds-minions"
ENDPOINT_SLICES = {MINIONS_SLICE: ("/battlegrounds/minions", {"limit": ENDPOINT_PAGE_LIMIT})}
MODES = ("battlegrounds", "standard", "wild")
INSIGHT_KEYS = ("crowd_traps", "pure_early_tempo", "scaling_engines", "rank_skill_gaps")

RANK_RU = {
    "all": "все игроки",
    "top_1_percent": "топ-1%",
    "diamond_4to1": "Алмаз 4–1",
    "legend": "Легенда",
    "top_legend": "Топ-Легенда",
    "top_5k": "Топ-5000",
}

SURVIVORSHIP_NOTE = (
    "Положительный impact — корреляция, а не причина: в партии «с существом» чаще "
    "попадают столы, которые дожили до момента, когда его держат, поэтому плюс может "
    "отражать выживание стола, а не силу самой карты. Проверяйте вывод ходом покупки "
    "и разборами сильных игроков."
)
LABEL_CROWD_TRAP = (
    "популярность не ниже p75 тира, но среднее место с существом хуже, чем без него"
)
LABEL_EARLY_TEMPO = (
    f"выигрывает бои (combat winrate ≥ {EARLY_TEMPO_MIN_COMBAT_WINRATE:g}%), "
    f"но impact ≤ {EARLY_TEMPO_MAX_IMPACT:g}"
)
LABEL_SCALING = (
    f"среднее место с существом лучше, чем без него, на {SCALING_MIN_IMPACT:.2f} и больше"
)


class StatsInsightsError(RuntimeError):
    """Обязательный срез недоступен или не похож на ответ API."""


def trinket_slice(rank: str) -> str:
    return f"hsreplay_battlegrounds_trinkets_{rank}_current_battlegrounds_patch"


def ladder_slice(fmt: str, rank: str) -> str:
    return f"hsguru_meta_{fmt}_{rank}"


def slice_url(name: str) -> str:
    """Канонический публичный URL среза; произвольные адреса не принимаются."""

    if name in ENDPOINT_SLICES:
        path, query = ENDPOINT_SLICES[name]
        return f"{API_BASE_URL}{path}?{urlencode(query)}"
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", name):
        raise StatsInsightsError(f"недопустимое имя среза: {name!r}")
    return f"{DATASET_BASE_URL}/datasets/{name}"


def required_slices(mode: str) -> tuple[list[str], list[str]]:
    """(обязательные, необязательные) срезы режима."""

    if mode == "battlegrounds":
        ranks = sorted({rank for pair in TRINKET_RANK_PAIRS for rank in pair})
        return [MINIONS_SLICE], [trinket_slice(rank) for rank in ranks]
    ranks = []
    for low, high in LADDER_RANK_PAIRS:
        for rank in (low, high):
            if rank not in ranks:
                ranks.append(rank)
    return [ladder_slice(mode, ranks[0])], [ladder_slice(mode, rank) for rank in ranks[1:]]


# ---------------------------------------------------------------- загрузка


def _http_get_json(url: str) -> dict:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "editorteam-stats-insights/1.0"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise StatsInsightsError(f"API вернул HTTP {exc.code}: {url}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise StatsInsightsError(f"API недоступен: {url}") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise StatsInsightsError(f"ответ API больше {MAX_RESPONSE_BYTES} байт: {url}")
    return _parse_payload(raw, url)


def _parse_payload(raw: bytes, origin: str) -> dict:
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StatsInsightsError(f"не JSON: {origin}") from exc
    if not isinstance(payload, dict):
        raise StatsInsightsError(f"неожиданная форма ответа: {origin}")
    return _unwrap_adapter_envelope(payload)


def _unwrap_adapter_envelope(payload: dict) -> dict:
    """Принять и сохранённый вывод `community_sources.py stats-api`."""

    envelope = payload.get("data") if payload.get("ok") is True else payload
    if not isinstance(envelope, dict) or envelope.get("provider") != "koloda_stats_api":
        return payload
    results = envelope.get("results")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return payload
    first = results[0]
    unwrapped = {"data": first.get("data"), "meta": first.get("api_meta") or {}}
    if isinstance(first.get("source_url"), str):
        unwrapped["_source_url"] = first["source_url"]
    return unwrapped


def _manifest_urls(directory: Path) -> dict[str, str]:
    path = directory / BUNDLE_MANIFEST
    if not path.is_file():
        return {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    urls = {}
    for row in manifest.get("files", []) if isinstance(manifest, dict) else []:
        if isinstance(row, dict) and isinstance(row.get("name"), str) and isinstance(row.get("url"), str):
            urls[row["name"]] = row["url"]
    return urls


def load_slice_from_dir(directory: Path, name: str) -> dict:
    path = directory / f"{name}.json"
    if not path.is_file():
        raise StatsInsightsError(f"нет файла среза: {path}")
    payload = _parse_payload(path.read_bytes(), str(path))
    url = payload.pop("_source_url", None) or _manifest_urls(directory).get(name) or slice_url(name)
    return {"url": url, "payload": payload}


def collect(
    mode: str,
    *,
    source_dir: Path | None = None,
    fetch: Callable[[str], dict] = _http_get_json,
) -> tuple[dict, list[str]]:
    """Собрать срезы режима. Обязательный срез без ответа — ошибка, остальные — warning."""

    required, optional = required_slices(mode)
    slices: dict[str, dict] = {}
    warnings: list[str] = []
    for name in [*required, *optional]:
        try:
            if source_dir is not None:
                slices[name] = load_slice_from_dir(source_dir, name)
            else:
                slices[name] = {"url": slice_url(name), "payload": fetch(slice_url(name))}
        except StatsInsightsError as exc:
            if name in required:
                raise
            warnings.append(f"Нет среза {name} ({exc}); контрасты по нему не построены.")
    return slices, warnings


# ---------------------------------------------------------------- разбор


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:[.,]\d+)?", value)
        if match:
            return float(match.group(0).replace(",", "."))
    return None


def _round(value: float | None, digits: int = 2) -> float | None:
    # `+ 0.0` убирает -0.0, чтобы вывод не дрожал между «-0.0» и «0.0».
    return None if value is None else round(value, digits) + 0.0


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def slice_meta(payload: dict) -> dict:
    """fetched_at/stale/source_id из ответа эндпоинта (`meta`) или датасета."""

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    publication = payload.get("publication") if isinstance(payload.get("publication"), dict) else {}
    source_id = meta.get("source_id") or payload.get("source_id") or data.get("source_id")
    source_id = source_id or publication.get("source_id")
    stale = meta.get("stale") if isinstance(meta.get("stale"), bool) else None
    return {
        "source_id": source_id if isinstance(source_id, str) else None,
        "fetched_at": meta.get("fetched_at") or payload.get("fetched_at"),
        "stale": stale,
    }


def _structured(payload: dict) -> dict:
    data = payload.get("data")
    if isinstance(data, dict):
        structured = data.get("structured")
        if isinstance(structured, dict):
            return structured
        return data
    return {}


def minion_rows(payload: dict) -> list[dict]:
    data = payload.get("data")
    rows = data if isinstance(data, list) else _structured(payload).get("minions")
    if not isinstance(rows, list):
        raise StatsInsightsError("в срезе существ нет списка data")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        card_id = row.get("card_id") or row.get("id")
        if not isinstance(card_id, str):
            continue
        name_en = row.get("name") if isinstance(row.get("name"), str) else None
        result.append(
            {
                "card_id": card_id,
                "dbf_id": row.get("dbf_id", row.get("dbfId")),
                "name": row.get("name_ru") or name_en,
                "name_en": name_en,
                "tavern_tier": row.get("tavern_tier"),
                "popularity": _num(row.get("popularity_value", row.get("popularity"))),
                "combat_winrate": _num(row.get("combat_winrate_value", row.get("combat_winrate"))),
                "impact": _num(row.get("impact")),
                "avg_placement_with": _num(row.get("avg_placement_with")),
                "avg_placement_without": _num(row.get("avg_placement_without")),
                "games_with_minion": row.get("games_with_minion"),
            }
        )
    return result


def ladder_rows(payload: dict) -> dict[str, dict]:
    structured = _structured(payload)
    rows = structured.get("strategies") or structured.get("items")
    if not isinstance(rows, list):
        raise StatsInsightsError("в срезе HSGuru нет таблицы архетипов")
    result: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("Archetype") or row.get("archetype")
        winrate_key = next((key for key in row if str(key).lower().startswith("winrate")), None)
        popularity = row.get("Popularity", row.get("popularity"))
        games = row.get("games")
        if isinstance(popularity, str):
            match = re.search(r"\((\d+)\)", popularity)
            games = int(match.group(1)) if match else games
        winrate = _num(row.get(winrate_key)) if winrate_key else None
        if not isinstance(name, str) or winrate is None or not isinstance(games, int):
            continue
        result[name] = {"winrate": winrate, "popularity": _num(popularity), "games": games}
    return result


def trinket_rows(payload: dict) -> dict[str, dict]:
    rows = _structured(payload).get("trinkets")
    if not isinstance(rows, list):
        raise StatsInsightsError("в срезе аксессуаров нет списка trinkets")
    result: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        card_id = row.get("trinket_id") or row.get("id")
        pick_rate = _num(row.get("pick_rate"))
        placement = _num(row.get("avg_placement"))
        games = row.get("games")
        if not isinstance(card_id, str) or pick_rate is None or placement is None:
            continue
        if not isinstance(games, int):
            continue
        result[card_id] = {
            "card_id": card_id,
            "dbf_id": row.get("dbfId"),
            "name": row.get("localized_name") or row.get("name"),
            "name_en": row.get("name"),
            "trinket_type": row.get("trinket_tier") or row.get("type"),
            "pick_rate": pick_rate,
            "avg_placement": placement,
            "games": games,
        }
    return result


# ---------------------------------------------------------------- детекторы


def _minion_record(row: dict, label: str, popularity_rank: int) -> dict:
    return {
        "card_id": row["card_id"],
        "dbf_id": row["dbf_id"],
        "name": row["name"],
        "name_en": row["name_en"],
        "tavern_tier": row["tavern_tier"],
        "popularity": row["popularity"],
        "popularity_rank": popularity_rank,
        "combat_winrate": row["combat_winrate"],
        "impact": row["impact"],
        "avg_placement_with": row["avg_placement_with"],
        "avg_placement_without": row["avg_placement_without"],
        "games_with_minion": row["games_with_minion"],
        "label": label,
    }


def _has_stats(row: dict) -> bool:
    games = row["games_with_minion"]
    return (
        all(row[key] is not None for key in ("popularity", "combat_winrate", "impact"))
        and isinstance(games, int)
        and games >= MIN_GAMES_WITH_MINION
    )


def battlegrounds_insights(rows: list[dict], tavern_tier: int | None) -> tuple[dict, dict, list[str]]:
    insights = {key: [] for key in INSIGHT_KEYS}
    warnings: list[str] = []
    tiers = sorted({row["tavern_tier"] for row in rows if isinstance(row["tavern_tier"], int)})
    if tavern_tier is not None:
        tiers = [tier for tier in tiers if tier == tavern_tier]
        if not tiers:
            raise StatsInsightsError(f"в срезе нет существ таверны {tavern_tier}-го уровня")
    pool: dict = {"tiers": [], "no_stats": []}
    for tier in tiers:
        tier_rows = sorted(
            (row for row in rows if row["tavern_tier"] == tier), key=lambda row: row["card_id"]
        )
        ranked = sorted(
            (row for row in tier_rows if _has_stats(row)),
            key=lambda row: (-row["popularity"], row["card_id"]),
        )
        rank_of = {row["card_id"]: index for index, row in enumerate(ranked, start=1)}
        pool["no_stats"].extend(
            {"card_id": row["card_id"], "name": row["name"], "tavern_tier": tier}
            for row in tier_rows
            if not _has_stats(row)
        )
        p75 = None
        if len(ranked) >= MIN_POOL_FOR_QUANTILE:
            popularities = [row["popularity"] for row in ranked]
            p75 = statistics.quantiles(popularities, n=4, method="inclusive")[2]
        else:
            warnings.append(
                f"В тире {tier} меньше {MIN_POOL_FOR_QUANTILE} существ со статистикой: "
                "crowd_traps для него не считаются."
            )
        pool["tiers"].append(
            {
                "tavern_tier": tier,
                "rows": len(tier_rows),
                "with_stats": len(ranked),
                "popularity_p75": _round(p75),
            }
        )
        for row in ranked:
            rank = rank_of[row["card_id"]]
            if p75 is not None and row["popularity"] >= p75 and row["impact"] <= CROWD_TRAP_MAX_IMPACT:
                insights["crowd_traps"].append(_minion_record(row, LABEL_CROWD_TRAP, rank))
            if (
                row["combat_winrate"] >= EARLY_TEMPO_MIN_COMBAT_WINRATE
                and row["impact"] <= EARLY_TEMPO_MAX_IMPACT
            ):
                insights["pure_early_tempo"].append(_minion_record(row, LABEL_EARLY_TEMPO, rank))
            if row["impact"] >= SCALING_MIN_IMPACT:
                record = _minion_record(row, LABEL_SCALING, rank)
                record["survivorship_note"] = SURVIVORSHIP_NOTE
                insights["scaling_engines"].append(record)
    insights["crowd_traps"].sort(key=lambda r: (-r["popularity"], r["tavern_tier"], r["card_id"]))
    insights["pure_early_tempo"].sort(
        key=lambda r: (-r["combat_winrate"], r["tavern_tier"], r["card_id"])
    )
    insights["scaling_engines"].sort(key=lambda r: (-r["impact"], r["tavern_tier"], r["card_id"]))
    return insights, pool, warnings


def _weighted_mean(rows: list[dict], value: str, weight: str) -> float | None:
    total = sum(row[weight] for row in rows)
    if total <= 0:
        return None
    return sum(row[value] * row[weight] for row in rows) / total


def _gap_score(*parts: tuple[float | None, float]) -> float:
    return max(abs(value) / threshold for value, threshold in parts if value is not None)


def _signed(value: float, digits: int = 1) -> str:
    return f"{value:+.{digits}f}"


def ladder_skill_gaps(fmt: str, by_rank: dict[str, dict]) -> tuple[list[dict], dict]:
    """Пары рангов HSGuru: относительный винрейт и популярность архетипа."""

    pool = {
        rank: {
            "rows": len(rows),
            "winrate_mean": _round(_weighted_mean(list(rows.values()), "winrate", "games")),
        }
        for rank, rows in sorted(by_rank.items())
    }
    gaps: list[dict] = []
    for low, high in LADDER_RANK_PAIRS:
        if low not in by_rank or high not in by_rank:
            continue
        mean_low, mean_high = pool[low]["winrate_mean"], pool[high]["winrate_mean"]
        if mean_low is None or mean_high is None:
            continue
        pair: list[dict] = []
        for name in sorted(set(by_rank[low]) & set(by_rank[high])):
            a, b = by_rank[low][name], by_rank[high][name]
            if min(a["games"], b["games"]) < LADDER_MIN_GAMES:
                continue
            # Пороги сравниваем с округлёнными числами, которые попадут в запись.
            relative = _round((b["winrate"] - mean_high) - (a["winrate"] - mean_low), 1)
            popularity = (
                _round(b["popularity"] - a["popularity"], 1)
                if a["popularity"] is not None and b["popularity"] is not None
                else None
            )
            contrasts, labels = [], []
            if abs(relative) >= LADDER_RELATIVE_WINRATE_GAP_PP:
                higher = relative > 0
                contrasts.append(f"winrate_{'higher' if higher else 'lower'}_at_high_rank")
                labels.append(
                    f"на ранге «{RANK_RU[high]}» винрейт относительно среднего по рангу "
                    f"{'выше' if higher else 'ниже'} ({_signed(relative)} п.п.)"
                )
            if popularity is not None and abs(popularity) >= LADDER_POPULARITY_GAP_PP:
                more = popularity > 0
                contrasts.append(f"{'more' if more else 'less'}_popular_at_high_rank")
                labels.append(
                    f"на ранге «{RANK_RU[high]}» играют {'чаще' if more else 'реже'} "
                    f"({a['popularity']:.1f}% → {b['popularity']:.1f}%)"
                )
            if not contrasts:
                continue
            pair.append(
                {
                    "kind": "ladder_archetype",
                    "name": name,
                    "format": fmt,
                    "low_rank": low,
                    "high_rank": high,
                    "winrate_low": a["winrate"],
                    "winrate_high": b["winrate"],
                    "winrate_delta_pp": _round(b["winrate"] - a["winrate"], 1),
                    "winrate_mean_low": mean_low,
                    "winrate_mean_high": mean_high,
                    "relative_winrate_delta_pp": relative,
                    "popularity_low": a["popularity"],
                    "popularity_high": b["popularity"],
                    "popularity_delta_pp": popularity,
                    "games_low": a["games"],
                    "games_high": b["games"],
                    "contrasts": contrasts,
                    "label": "; ".join(labels),
                    "_score": _gap_score(
                        (relative, LADDER_RELATIVE_WINRATE_GAP_PP),
                        (popularity, LADDER_POPULARITY_GAP_PP),
                    ),
                }
            )
        pair.sort(key=lambda r: (-r["_score"], r["name"]))
        gaps.extend(pair[:MAX_SKILL_GAPS_PER_PAIR])
    for record in gaps:
        record.pop("_score")
    return gaps, pool


def trinket_skill_gaps(by_rank: dict[str, dict]) -> tuple[list[dict], dict]:
    """Аксессуары БГ: все игроки против топ-1% (частота выбора и место)."""

    pool: dict = {}
    means: dict[tuple[str, str], float | None] = {}
    for rank, rows in sorted(by_rank.items()):
        pool[rank] = {"rows": len(rows), "avg_placement_mean": {}}
        for kind in sorted({str(row["trinket_type"]) for row in rows.values()}):
            kind_rows = [row for row in rows.values() if str(row["trinket_type"]) == kind]
            means[(rank, kind)] = _weighted_mean(kind_rows, "avg_placement", "games")
            pool[rank]["avg_placement_mean"][kind] = _round(means[(rank, kind)])
    gaps: list[dict] = []
    for low, high in TRINKET_RANK_PAIRS:
        if low not in by_rank or high not in by_rank:
            continue
        pair: list[dict] = []
        for card_id in sorted(set(by_rank[low]) & set(by_rank[high])):
            a, b = by_rank[low][card_id], by_rank[high][card_id]
            kind = str(a["trinket_type"])
            if min(a["games"], b["games"]) < TRINKET_MIN_GAMES:
                continue
            mean_low, mean_high = means.get((low, kind)), means.get((high, str(b["trinket_type"])))
            if mean_low is None or mean_high is None:
                continue
            # Пороги сравниваем с округлёнными числами, которые попадут в запись.
            pick = _round(b["pick_rate"] - a["pick_rate"], 1)
            relative = _round((b["avg_placement"] - mean_high) - (a["avg_placement"] - mean_low))
            contrasts, labels = [], []
            if abs(pick) >= TRINKET_PICK_RATE_GAP_PP:
                more = pick > 0
                contrasts.append(f"picked_{'more' if more else 'less'}_at_high_rank")
                labels.append(
                    f"{RANK_RU[high]} берёт {'чаще' if more else 'реже'} "
                    f"({a['pick_rate']:.1f}% → {b['pick_rate']:.1f}%)"
                )
            if abs(relative) >= TRINKET_RELATIVE_PLACEMENT_GAP:
                better = relative < 0
                contrasts.append(f"placement_{'better' if better else 'worse'}_at_high_rank")
                labels.append(
                    f"у «{RANK_RU[high]}» место относительно среднего по срезу "
                    f"{'лучше' if better else 'хуже'} ({_signed(relative, 2)})"
                )
            if not contrasts:
                continue
            pair.append(
                {
                    "kind": "bg_trinket",
                    "card_id": card_id,
                    "dbf_id": a["dbf_id"],
                    "name": a["name"],
                    "name_en": a["name_en"],
                    "trinket_type": a["trinket_type"],
                    "low_rank": low,
                    "high_rank": high,
                    "pick_rate_low": a["pick_rate"],
                    "pick_rate_high": b["pick_rate"],
                    "pick_rate_delta_pp": pick,
                    "avg_placement_low": a["avg_placement"],
                    "avg_placement_high": b["avg_placement"],
                    "avg_placement_mean_low": _round(mean_low),
                    "avg_placement_mean_high": _round(mean_high),
                    "relative_placement_delta": relative,
                    "games_low": a["games"],
                    "games_high": b["games"],
                    "contrasts": contrasts,
                    "label": "; ".join(labels),
                    "_score": _gap_score(
                        (pick, TRINKET_PICK_RATE_GAP_PP),
                        (relative, TRINKET_RELATIVE_PLACEMENT_GAP),
                    ),
                }
            )
        pair.sort(key=lambda r: (-r["_score"], r["card_id"]))
        gaps.extend(pair[:MAX_SKILL_GAPS_PER_PAIR])
    for record in gaps:
        record.pop("_score")
    return gaps, pool


# ---------------------------------------------------------------- сборка


def freshness_warnings(slices: dict, now: datetime) -> tuple[list[dict], list[str]]:
    sources, warnings = [], []
    for name, item in slices.items():
        meta = slice_meta(item["payload"])
        sources.append(
            {
                "name": name,
                "source_url": item["url"],
                "source_id": meta["source_id"],
                "fetched_at": meta["fetched_at"],
                "stale": meta["stale"],
            }
        )
        problems = []
        if meta["stale"] is True:
            problems.append("API помечает его stale: true")
        fetched = _parse_time(meta["fetched_at"])
        if fetched is None:
            problems.append("в ответе нет читаемого fetched_at")
        else:
            age_hours = (now - fetched).total_seconds() / 3600
            if age_hours > STALE_AFTER_HOURS:
                problems.append(f"возраст {age_hours:.0f} ч при пороге {STALE_AFTER_HOURS:.0f} ч")
        if problems:
            warnings.append(
                f"Срез {name} (fetched_at {meta['fetched_at']}) устарел: "
                + "; ".join(problems)
                + ". Не выдавайте эти цифры за данные текущего дня или хотфикса."
            )
    return sources, warnings


def _thresholds(mode: str) -> dict:
    if mode == "battlegrounds":
        return {
            "crowd_trap_popularity_quantile": "p75 тира",
            "crowd_trap_max_impact": CROWD_TRAP_MAX_IMPACT,
            "early_tempo_min_combat_winrate": EARLY_TEMPO_MIN_COMBAT_WINRATE,
            "early_tempo_max_impact": EARLY_TEMPO_MAX_IMPACT,
            "scaling_min_impact": SCALING_MIN_IMPACT,
            "min_games_with_minion": MIN_GAMES_WITH_MINION,
            "trinket_rank_pairs": [list(pair) for pair in TRINKET_RANK_PAIRS],
            "trinket_min_games": TRINKET_MIN_GAMES,
            "trinket_pick_rate_gap_pp": TRINKET_PICK_RATE_GAP_PP,
            "trinket_relative_placement_gap": TRINKET_RELATIVE_PLACEMENT_GAP,
            "max_skill_gaps_per_pair": MAX_SKILL_GAPS_PER_PAIR,
            "stale_after_hours": STALE_AFTER_HOURS,
        }
    return {
        "ladder_rank_pairs": [list(pair) for pair in LADDER_RANK_PAIRS],
        "ladder_min_games": LADDER_MIN_GAMES,
        "ladder_relative_winrate_gap_pp": LADDER_RELATIVE_WINRATE_GAP_PP,
        "ladder_popularity_gap_pp": LADDER_POPULARITY_GAP_PP,
        "max_skill_gaps_per_pair": MAX_SKILL_GAPS_PER_PAIR,
        "stale_after_hours": STALE_AFTER_HOURS,
    }


def build_insights(
    mode: str,
    slices: dict,
    *,
    tavern_tier: int | None = None,
    now: datetime | None = None,
    extra_warnings: list[str] | None = None,
) -> dict:
    """Срезы → stats-insights.json без сети; при заданном `now` результат детерминирован."""

    if mode not in MODES:
        raise StatsInsightsError(f"неизвестный режим: {mode}")
    now = now or datetime.now(timezone.utc)
    sources, warnings = freshness_warnings(slices, now)
    warnings = [*(extra_warnings or []), *warnings]
    if mode == "battlegrounds":
        insights, minion_pool, detector_warnings = battlegrounds_insights(
            minion_rows(slices[MINIONS_SLICE]["payload"]), tavern_tier
        )
        trinkets = {
            rank: trinket_rows(slices[trinket_slice(rank)]["payload"])
            for rank in sorted({rank for pair in TRINKET_RANK_PAIRS for rank in pair})
            if trinket_slice(rank) in slices
        }
        gaps, trinket_pool = trinket_skill_gaps(trinkets)
        insights["rank_skill_gaps"] = gaps
        pool = {"minions": minion_pool, "trinkets": trinket_pool}
        warnings.extend(detector_warnings)
    else:
        by_rank = {
            name.removeprefix(f"hsguru_meta_{mode}_"): ladder_rows(item["payload"])
            for name, item in slices.items()
        }
        gaps, ladder_pool = ladder_skill_gaps(mode, by_rank)
        insights = {key: [] for key in INSIGHT_KEYS}
        insights["rank_skill_gaps"] = gaps
        pool = {"ladder": ladder_pool}
    fetched = [row["fetched_at"] for row in sources if _parse_time(row["fetched_at"]) is not None]
    oldest = min(fetched, key=lambda value: _parse_time(value)) if fetched else None
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "tavern_tier": tavern_tier if mode == "battlegrounds" else None,
        "fetched_at": oldest,
        "source_urls": [row["source_url"] for row in sources],
        "sources": sources,
        "warnings": warnings,
        "thresholds": _thresholds(mode),
        "pool": pool,
        "insights": insights,
    }


def render(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m editorteam.stats_insights",
        description=(
            "Контрасты статистики api.kolodahearthstone.com для автора: ловушки толпы, "
            "ранний темп, точки выхода и разрывы между рангами. Только числа и метки, "
            "без выдуманных причин."
        ),
    )
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--tavern-tier", type=int, help="только существа этого уровня таверны (1–7)")
    parser.add_argument(
        "--from", dest="source_dir", help="каталог stats-bundle с сохранёнными JSON (без сети)"
    )
    parser.add_argument("-o", "--output", help="файл для JSON (по умолчанию stdout)")
    parser.add_argument(
        "--now", help="момент проверки свежести в ISO 8601 (по умолчанию текущее UTC-время)"
    )
    args = parser.parse_args(argv)
    if args.tavern_tier is not None and args.mode != "battlegrounds":
        parser.error("--tavern-tier применим только к --mode battlegrounds")
    if args.tavern_tier is not None and not 1 <= args.tavern_tier <= 7:
        parser.error("--tavern-tier должен быть от 1 до 7")
    now = _parse_time(args.now) if args.now else None
    if args.now and now is None:
        parser.error("--now должен быть датой ISO 8601")
    try:
        slices, warnings = collect(
            args.mode, source_dir=Path(args.source_dir) if args.source_dir else None
        )
        result = build_insights(
            args.mode, slices, tavern_tier=args.tavern_tier, now=now, extra_warnings=warnings
        )
    except StatsInsightsError as exc:
        sys.stderr.write(f"stats_insights: {exc}\n")
        return 2
    payload = render(result)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
