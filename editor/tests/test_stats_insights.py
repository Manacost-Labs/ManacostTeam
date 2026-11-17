"""Тесты экстрактора контрастов статистики api.kolodahearthstone.com.

Фикстуры — обрезанные реальные ответы API от 2026-11-16/17 (тир 1 БГ,
аксессуары «все» и «топ-1%», мета HSGuru Стандарта на трёх рангах).
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from editorteam import stats_insights as si

FIXTURES = Path(__file__).parent / "fixtures" / "stats_insights"
NOW = datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _bg(tavern_tier: int | None = 1, now: datetime = NOW) -> dict:
    slices, warnings = si.collect("battlegrounds", source_dir=FIXTURES)
    return si.build_insights(
        "battlegrounds", slices, tavern_tier=tavern_tier, now=now, extra_warnings=warnings
    )


def _ids(records: list[dict]) -> list[str]:
    return [record["card_id"] for record in records]


def _minion(card_id: str, popularity: float, combat: float, impact: float, tier: int = 1) -> dict:
    return {
        "card_id": card_id,
        "name_ru": card_id,
        "name": card_id,
        "tavern_tier": tier,
        "popularity": popularity,
        "combat_winrate": combat,
        "impact": impact,
        "avg_placement_with": 4.0,
        "avg_placement_without": 4.0 + impact,
        "games_with_minion": 50_000,
    }


def _synthetic(rows: list[dict], *, stale: bool = False, fetched_at: str = "2026-11-17T20:00:00Z"):
    payload = {"data": rows, "meta": {"source_id": "x", "fetched_at": fetched_at, "stale": stale}}
    return {si.MINIONS_SLICE: {"url": si.slice_url(si.MINIONS_SLICE), "payload": payload}}


# ---------------------------------------------------------------- детекторы БГ


class TestCrowdTraps:
    def test_suspicious_prisonguard_signature_is_a_crowd_trap(self):
        result = _bg()
        traps = result["insights"]["crowd_traps"]
        assert _ids(traps) == ["BG36_345"]
        trap = traps[0]
        assert trap["name"] == "Подозрительный надзиратель"
        assert trap["name_en"] == "Suspicious Prisonguard"
        assert (trap["popularity"], trap["combat_winrate"], trap["impact"]) == (8.07, 57.31, -0.06)
        assert (trap["avg_placement_with"], trap["avg_placement_without"]) == (4.38, 4.32)
        assert trap["popularity_rank"] == 1
        assert trap["label"] == si.LABEL_CROWD_TRAP
        assert result["pool"]["minions"]["tiers"][0]["popularity_p75"] <= 8.07

    def test_popular_card_with_mild_minus_is_not_a_trap(self):
        # Бликостраж: популярность у p75, но impact -0.03 мягче порога -0.04.
        result = _bg()
        assert "BG29_888" not in _ids(result["insights"]["crowd_traps"])

    def test_unpopular_card_with_big_minus_is_not_a_trap(self):
        rows = [
            _minion("POP_A", 9.0, 50.0, -0.05),
            _minion("POP_B", 6.0, 50.0, 0.02),
            _minion("POP_C", 5.0, 50.0, 0.01),
            _minion("LOW", 1.0, 50.0, -0.30),
            _minion("LOW_2", 1.5, 50.0, 0.0),
        ]
        result = si.build_insights("battlegrounds", _synthetic(rows), tavern_tier=1, now=NOW)
        assert _ids(result["insights"]["crowd_traps"]) == ["POP_A"]

    def test_small_pool_skips_quantile_with_warning(self):
        rows = [_minion("A", 9.0, 50.0, -0.5), _minion("B", 1.0, 50.0, 0.0)]
        result = si.build_insights("battlegrounds", _synthetic(rows), tavern_tier=1, now=NOW)
        assert result["insights"]["crowd_traps"] == []
        assert any("crowd_traps для него не считаются" in w for w in result["warnings"])


class TestPureEarlyTempo:
    def test_high_combat_winrate_without_placement_gain(self):
        tempo = _ids(_bg()["insights"]["pure_early_tempo"])
        assert tempo == ["BG29_888", "BG29_611", "BGS_119", "BG36_345", "BG33_886", "BG28_300"]

    def test_positive_impact_excludes_tempo_label(self):
        # Выживший красный дракон: 61.82% боёв, но impact +0.05 — не «чистый темп».
        tempo = _ids(_bg()["insights"]["pure_early_tempo"])
        assert "BG35_814" not in tempo
        assert "BG36_200" not in tempo  # Порхающий нетопырь: 57.39%, impact +0.3


class TestScalingEngines:
    def test_impact_threshold_and_survivorship_note(self):
        engines = _bg()["insights"]["scaling_engines"]
        assert _ids(engines) == ["BG31_803", "BG36_200", "BG33_890t", "BG20_100"]
        assert all(record["impact"] >= si.SCALING_MIN_IMPACT for record in engines)
        assert all(record["survivorship_note"] == si.SURVIVORSHIP_NOTE for record in engines)
        assert "не причина" in si.SURVIVORSHIP_NOTE or "а не причина" in si.SURVIVORSHIP_NOTE


class TestPoolAndFilters:
    def test_tier_filter_excludes_other_tiers(self):
        result = _bg()
        everything = [r for records in result["insights"].values() for r in records]
        assert all(r.get("tavern_tier") in (1, None) for r in everything)
        assert "BG36_201" not in json.dumps(result)  # Лев-рыба 2-го тира отсечена

    def test_minions_without_stats_are_listed_not_detected(self):
        no_stats = {row["card_id"] for row in _bg()["pool"]["minions"]["no_stats"]}
        assert {"BG32_236", "BG_ICC_026t", "BG36_200t"} <= no_stats

    def test_all_tiers_without_filter(self):
        result = _bg(tavern_tier=None)
        tiers = [row["tavern_tier"] for row in result["pool"]["minions"]["tiers"]]
        assert tiers == [1, 2, 4]  # в фикстуре ещё Лев-рыба (2) и BG26_137 (4)
        assert result["tavern_tier"] is None

    def test_missing_tier_is_an_error(self):
        with pytest.raises(si.StatsInsightsError):
            _bg(tavern_tier=7)

    def test_low_sample_minion_is_ignored(self):
        rows = [_minion(f"M{i}", 2.0 + i, 60.0, -0.1) for i in range(5)]
        rows[0]["games_with_minion"] = si.MIN_GAMES_WITH_MINION - 1
        result = si.build_insights("battlegrounds", _synthetic(rows), tavern_tier=1, now=NOW)
        assert "M0" not in _ids(result["insights"]["pure_early_tempo"])
        assert "M0" in {row["card_id"] for row in result["pool"]["minions"]["no_stats"]}


# ---------------------------------------------------------------- разрыв рангов


class TestRankSkillGaps:
    def test_trinkets_all_vs_top_1_percent(self):
        gaps = _bg()["insights"]["rank_skill_gaps"]
        assert gaps and all(g["kind"] == "bg_trinket" for g in gaps)
        assert {(g["low_rank"], g["high_rank"]) for g in gaps} == {("all", "top_1_percent")}
        first = gaps[0]
        assert first["card_id"] == "BG35_MagicItem_820"
        assert (first["pick_rate_low"], first["pick_rate_high"]) == (38.0, 78.6)
        assert first["pick_rate_delta_pp"] == 40.6
        assert first["contrasts"] == ["picked_more_at_high_rank"]
        assert all(min(g["games_low"], g["games_high"]) >= si.TRINKET_MIN_GAMES for g in gaps)

    def test_trinket_placement_is_compared_relative_to_bracket(self):
        gaps = {g["card_id"]: g for g in _bg()["insights"]["rank_skill_gaps"]}
        portrait = gaps["BG32_MagicItem_205"]
        assert "placement_better_at_high_rank" in portrait["contrasts"]
        expected = (portrait["avg_placement_high"] - portrait["avg_placement_mean_high"]) - (
            portrait["avg_placement_low"] - portrait["avg_placement_mean_low"]
        )
        assert portrait["relative_placement_delta"] == pytest.approx(expected, abs=0.011)

    def test_contrast_tags_match_rounded_numbers(self):
        rows = {
            "all": {"T": {"card_id": "T", "dbf_id": 1, "name": "Т", "name_en": "T",
                          "trinket_type": "Greater", "pick_rate": 40.0, "avg_placement": 4.0,
                          "games": 5000}},
            "top_1_percent": {"T": {"card_id": "T", "dbf_id": 1, "name": "Т", "name_en": "T",
                                    "trinket_type": "Greater", "pick_rate": 31.95,
                                    "avg_placement": 3.0, "games": 500}},
        }
        # Второй аксессуар задаёт средние места срезов так, что сырой сдвиг T = 0.2999.
        rows["all"]["U"] = {**rows["all"]["T"], "card_id": "U", "avg_placement": 4.0}
        rows["top_1_percent"]["U"] = {**rows["top_1_percent"]["T"], "card_id": "U",
                                      "avg_placement": 2.4002}
        gaps, _ = si.trinket_skill_gaps(rows)
        t = next(g for g in gaps if g["card_id"] == "T")
        assert t["relative_placement_delta"] == 0.3
        assert "placement_worse_at_high_rank" in t["contrasts"]
        for gap in [*gaps, *_bg()["insights"]["rank_skill_gaps"]]:
            has_pick = any(tag.startswith("picked_") for tag in gap["contrasts"])
            has_place = any(tag.startswith("placement_") for tag in gap["contrasts"])
            assert has_pick == (abs(gap["pick_rate_delta_pp"]) >= si.TRINKET_PICK_RATE_GAP_PP)
            assert has_place == (
                abs(gap["relative_placement_delta"]) >= si.TRINKET_RELATIVE_PLACEMENT_GAP
            )

    def test_ladder_pairs_diamond_vs_legend_and_top_legend(self):
        slices, warnings = si.collect("standard", source_dir=FIXTURES)
        result = si.build_insights("standard", slices, now=NOW, extra_warnings=warnings)
        assert result["warnings"] == []
        insights = result["insights"]
        assert insights["crowd_traps"] == insights["pure_early_tempo"] == []
        assert insights["scaling_engines"] == []
        gaps = insights["rank_skill_gaps"]
        assert {(g["low_rank"], g["high_rank"]) for g in gaps} == {
            ("diamond_4to1", "legend"),
            ("diamond_4to1", "top_legend"),
        }
        holy = next(g for g in gaps if g["name"] == "Holy Paladin")
        assert (holy["winrate_low"], holy["winrate_high"]) == (54.7, 45.2)
        assert holy["winrate_delta_pp"] == -9.5
        assert "winrate_lower_at_high_rank" in holy["contrasts"]
        mug = next(g for g in gaps if g["name"] == "Mug Shaman" and g["high_rank"] == "top_legend")
        assert mug["contrasts"] == ["more_popular_at_high_rank"]
        assert "4.0% → 14.2%" in mug["label"]


# ---------------------------------------------------------------- свежесть


class TestFreshnessWarnings:
    def test_stale_flag_and_old_fetched_at_are_reported(self):
        warnings = _bg()["warnings"]
        stale = [w for w in warnings if "battlegrounds-minions" in w]
        assert len(stale) == 1
        assert "stale: true" in stale[0] and "2026-11-16T02:45:09" in stale[0]
        assert "возраст 42 ч" in stale[0]

    def test_fresh_slice_has_no_warning(self):
        rows = [_minion(f"M{i}", 2.0 + i, 50.0, 0.0) for i in range(5)]
        result = si.build_insights("battlegrounds", _synthetic(rows), tavern_tier=1, now=NOW)
        assert result["warnings"] == []

    def test_stale_flag_alone_is_enough(self):
        rows = [_minion(f"M{i}", 2.0 + i, 50.0, 0.0) for i in range(5)]
        result = si.build_insights(
            "battlegrounds", _synthetic(rows, stale=True), tavern_tier=1, now=NOW
        )
        assert len(result["warnings"]) == 1 and "stale: true" in result["warnings"][0]

    def test_top_level_fetched_at_is_the_oldest_slice(self):
        assert _bg()["fetched_at"] == "2026-11-16T02:45:09.801920+00:00"


# ---------------------------------------------------------------- офлайн, CLI, стабильность


class TestOfflineAndCli:
    def test_cli_from_dir_writes_stable_output(self, tmp_path):
        first, second = tmp_path / "a.json", tmp_path / "b.json"
        argv = ["--mode", "battlegrounds", "--tavern-tier", "1", "--from", str(FIXTURES),
                "--now", "2026-11-17T21:00:00Z"]
        assert si.main([*argv, "--output", str(first)]) == 0
        assert si.main([*argv, "--output", str(second)]) == 0
        assert first.read_bytes() == second.read_bytes()
        result = json.loads(first.read_text(encoding="utf-8"))
        assert list(result)[:2] == ["schema_version", "mode"]
        for key in ("mode", "fetched_at", "source_urls", "warnings", "insights"):
            assert key in result
        assert list(result["insights"]) == list(si.INSIGHT_KEYS)
        assert result["source_urls"][0] == (
            "https://api.kolodahearthstone.com/v1/battlegrounds/minions?limit=500"
        )

    def test_missing_required_slice_fails(self, tmp_path, capsys):
        code = si.main(["--mode", "battlegrounds", "--from", str(tmp_path)])
        assert code == 2
        assert "battlegrounds-minions" in capsys.readouterr().err

    def test_missing_optional_slice_is_a_warning(self, tmp_path):
        shutil.copy(FIXTURES / "battlegrounds-minions.json", tmp_path)
        slices, warnings = si.collect("battlegrounds", source_dir=tmp_path)
        result = si.build_insights(
            "battlegrounds", slices, tavern_tier=1, now=NOW, extra_warnings=warnings
        )
        assert result["insights"]["rank_skill_gaps"] == []
        assert sum("Нет среза hsreplay_battlegrounds_trinkets" in w for w in warnings) == 2

    def test_manifest_url_and_adapter_envelope_are_accepted(self, tmp_path):
        payload = _load("battlegrounds-minions")
        envelope = {
            "ok": True,
            "data": {
                "provider": "koloda_stats_api",
                "results": [
                    {
                        "data": payload["data"],
                        "api_meta": payload["meta"],
                        "source_url": "https://api.kolodahearthstone.com/v1/battlegrounds/minions?limit=500&offset=0",
                    }
                ],
            },
        }
        (tmp_path / "battlegrounds-minions.json").write_text(json.dumps(envelope), encoding="utf-8")
        slices, _ = si.collect("battlegrounds", source_dir=tmp_path)
        assert slices[si.MINIONS_SLICE]["url"].endswith("limit=500&offset=0")
        result = si.build_insights("battlegrounds", slices, tavern_tier=1, now=NOW)
        assert _ids(result["insights"]["crowd_traps"]) == ["BG36_345"]

    def test_tavern_tier_rejected_for_ladder(self):
        with pytest.raises(SystemExit):
            si.main(["--mode", "standard", "--tavern-tier", "1"])


class TestOnlineFetch:
    def test_online_mode_reads_only_allowlisted_get_urls(self):
        requested: list[str] = []
        files = {
            si.slice_url(si.MINIONS_SLICE): "battlegrounds-minions",
            si.slice_url(si.trinket_slice("all")): si.trinket_slice("all"),
            si.slice_url(si.trinket_slice("top_1_percent")): si.trinket_slice("top_1_percent"),
        }

        def fake_fetch(url: str) -> dict:
            requested.append(url)
            return _load(files[url])

        slices, warnings = si.collect("battlegrounds", fetch=fake_fetch)
        assert warnings == []
        assert [urlsplit(url).path for url in requested] == [
            "/v1/battlegrounds/minions",
            "/datasets/hsreplay_battlegrounds_trinkets_all_current_battlegrounds_patch",
            "/datasets/hsreplay_battlegrounds_trinkets_top_1_percent_current_battlegrounds_patch",
        ]
        online = si.render(si.build_insights("battlegrounds", slices, tavern_tier=1, now=NOW))
        assert online == si.render(_bg())

    def test_slice_name_is_validated(self):
        with pytest.raises(si.StatsInsightsError):
            si.slice_url("../admin")
