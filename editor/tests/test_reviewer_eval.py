"""reviewer-eval на синтетическом наборе с фейковой моделью: сеть и CLI не вызываются."""

import json

from editorteam import owner_eval as OwnerEval
from editorteam import reviewer_eval as RE
from editorteam.owner_review import CATEGORIES

V1 = "Вступление статьи.\nЕсли стол слабый, просто сдавайтесь, это очевидно.\nКонец."
V2 = "Вступление статьи.\nСравните Героя А на ходу 3 и Героя Б на ходу 3.\nКонец."
GOOD = "Хорошая статья.\nСовет с условием и причиной.\nКонец."


def make_set(tmp_path):
    (tmp_path / "versions").mkdir()
    (tmp_path / "gold").mkdir()
    (tmp_path / "versions" / "v1.md").write_text(V1, encoding="utf-8")
    (tmp_path / "versions" / "v2.md").write_text(V2, encoding="utf-8")
    (tmp_path / "versions" / "final-accepted.md").write_text(GOOD, encoding="utf-8")
    (tmp_path / "gold" / "ref.txt").write_text(GOOD, encoding="utf-8")
    labels = {
        "schema_version": 1,
        "article": "Синтетика",
        "rejections": [
            {
                "id": "R1",
                "version": "v1.md",
                "category": "water_hedging",
                "fragments": ["просто сдавайтесь, это очевидно"],
            },
            {
                "id": "R2",
                "version": "v2.md",
                "category": "illogical_comparison",
                "fragments": ["Сравните Героя А на ходу 3 и Героя Б на ходу 3"],
            },
            {
                "id": "R3",
                "version": "v1.md",
                "category": "genre_mismatch_too_long_literary",
                "fragments": [],
            },
        ],
    }
    (tmp_path / "labels.json").write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def fake_model(plan):
    """plan: {маркер текста: {категория: (status, quote)}}; прочие категории clear."""
    calls = []

    def call(system, prompt):
        calls.append(prompt)
        assert "owner_review_assignment" in prompt and "СТАТЬЯ" in prompt
        assert "R1" not in prompt and "labels" not in prompt  # слепая оценка
        article = prompt.split("=== СТАТЬЯ ===\n", 1)[1]
        rows = []
        verdicts = next((v for marker, v in plan.items() if marker in article), {})
        for cid in CATEGORIES:
            status, quote = verdicts.get(cid, ("clear", article.split("\n")[0]))
            rows.append({"id": cid, "status": status, "quote": quote, "reason": "проверено"})
        return "```json\n" + json.dumps({"owner_checks": rows}, ensure_ascii=False) + "\n```"

    return call, calls


def test_soft_strict_and_false_alarms(tmp_path):
    folder = make_set(tmp_path)
    call, calls = fake_model(
        {
            "сдавайтесь": {
                "obvious_or_water": ("issue", "просто сдавайтесь"),  # цитата внутри фрагмента
                "genre_fit": ("unverified", "Вступление статьи."),
            },
            "Героя А": {"illogical_comparison": ("issue", "Вступление статьи.")},  # мимо фрагмента
            "Хорошая": {"ai_tells": ("issue", "Хорошая статья.")},
        }
    )
    result = RE.evaluate(folder, call)
    by_id = {r["id"]: r for r in result["rejections"]}
    assert by_id["R1"]["soft_rate"] == 1 and by_id["R1"]["strict_rate"] == 1
    assert by_id["R2"]["soft_rate"] == 1 and by_id["R2"]["strict_rate"] == 0
    assert by_id["R3"]["category"] == "genre_fit" and by_id["R3"]["strict_rate"] == 1
    t = result["totals"]
    assert t["false_alarms"] == 2 and t["false_alarms_by_category"] == {"ai_tells": 2}
    assert t["valid_reviews"] == t["reviews"] == 4
    # v1 и v2 — по одной issue; на хороших текстах тоже по одной: различения нет
    assert t["rejected_mean_issues"] == 1 and t["clean_mean_issues"] == 1
    # v1 общий для R1 и R3: один вызов на уникальный текст
    assert len(calls) == 4 == RE.calls_needed(folder, 1)
    assert "поймано (soft)" in RE.render(result)


def test_cache_resumes_and_runs_measure_stability(tmp_path):
    folder = make_set(tmp_path)
    flip = {"n": 0}

    def call(system, prompt):
        article = prompt.split("=== СТАТЬЯ ===\n", 1)[1]
        status = "clear"
        if "сдавайтесь" in article:
            flip["n"] += 1
            status = "issue" if flip["n"] % 2 else "clear"
        rows = [
            {
                "id": c,
                "status": status if c == "obvious_or_water" else "clear",
                "quote": article.split("\n")[0],
                "reason": "r",
            }
            for c in CATEGORIES
        ]
        return json.dumps({"owner_checks": rows}, ensure_ascii=False)

    cache = tmp_path / "cache"
    first = RE.evaluate(folder, call, runs=2, cache=cache)
    r1 = next(r for r in first["rejections"] if r["id"] == "R1")
    assert r1["soft_rate"] == 0.5 and first["totals"]["unstable"] == 1

    def must_not_call(system, prompt):
        raise AssertionError("cache miss")

    again = RE.evaluate(folder, must_not_call, runs=2, cache=cache)
    assert again["totals"] == first["totals"]


def test_bad_reply_is_retried_and_reported(tmp_path):
    folder = make_set(tmp_path)

    def call(system, prompt):
        return "не JSON"

    result = RE.evaluate(folder, call, retries=1)
    assert result["totals"]["valid_reviews"] == 0
    assert all(r["runs"][0]["status"] == "missing" for r in result["rejections"])
    assert result["totals"]["soft"] == 0


def test_compare_reports_delta():
    base = {"totals": {"soft": 5, "strict": 3, "false_alarms": 2}}
    now = {"totals": {"soft": 7, "strict": 3, "false_alarms": 4}}
    assert RE.compare(now, base) == {"soft": 2, "strict": 0, "false_alarms": 2}


def test_owner_eval_baseline_flags_regression():
    base = {
        "totals": {"detected": 1, "partial": 2, "missed": 0, "needs_reviewer": 12},
        "clean_totals": {"error": 0, "review": 2},
    }
    same = OwnerEval.compare(base, base)
    assert not OwnerEval.is_regression(same) and "не хуже" in OwnerEval.render_delta(same)
    worse = {
        "totals": {**base["totals"], "detected": 0, "missed": 1},
        "clean_totals": {"error": 0, "review": 3},
    }
    delta = OwnerEval.compare(worse, base)
    assert delta["detected"] == -1 and delta["clean_review"] == 1
    assert OwnerEval.is_regression(delta)


def test_pairwise_swap_debiasing_and_positional_bias_detection(tmp_path):
    folder = make_set(tmp_path)
    calls = []

    def smart_judge(system, prompt):
        calls.append(prompt)
        assert "R1" not in prompt and "labels" not in prompt
        assert "ЭТАЛОН ВЛАДЕЛЬЦА (REFERENCE)" in prompt
        # Determine which slot contains the GOOD text
        text_a = prompt.split("=== ТЕКСТ A ===\n", 1)[1].split("=== ТЕКСТ B ===\n", 1)[0]
        text_b = prompt.split("=== ТЕКСТ B ===\n", 1)[1]
        winner = "A" if "Совет с условием и причиной" in text_a else ("B" if "Совет с условием и причиной" in text_b else "tie")
        return json.dumps({"winner": winner, "confidence": "high", "reason": "ближе к эталону", "loser_flaws": ["вода"]})

    cache = tmp_path / "cache"
    result = RE.evaluate_pairwise(folder, smart_judge, cache=cache)
    t = result["totals"]
    assert t["pairs"] == 3
    # v1 shared by R1 and R3 -> only 2 unique pairs * 2 orders = 4 calls!
    assert t["unique_calls"] == 4 == RE.pairwise_calls_needed(folder)
    assert len(calls) == 4
    assert t["correct_wins"] == 3 and t["discrimination_accuracy"] == 1.0
    assert t["swap_consistent"] == 3 and t["swap_consistency"] == 1.0
    assert t["positional_bias_cases"] == 0
    assert "дискриминация" in RE.render_pairwise(result)

    # Cached rerun makes zero model calls
    def must_not_call(system, prompt):
        raise AssertionError("cache miss")

    cached = RE.evaluate_pairwise(folder, must_not_call, cache=cache)
    assert cached["totals"] == result["totals"]

    # Positional bias judge: always picks slot A regardless of swap
    def biased_judge(system, prompt):
        return json.dumps({"winner": "A", "confidence": "high", "reason": "первый лучше", "loser_flaws": []})

    biased = RE.evaluate_pairwise(folder, biased_judge)
    bt = biased["totals"]
    assert bt["correct_wins"] == 0
    assert bt["swap_consistency"] == 0.0
    assert bt["positional_bias_cases"] == 3


def test_pairwise_supports_evals_pairs_directory(tmp_path):
    p = tmp_path / "pair-1"
    p.mkdir()
    (p / "draft.md").write_text("Водяной черновик без сути.", encoding="utf-8")
    (p / "reference.md").write_text("Плотный совет с точным ходом.", encoding="utf-8")
    (p / "meta.json").write_text(json.dumps({"id": "pair-1", "type": "GUIDE"}), encoding="utf-8")

    def judge(system, prompt):
        text_a = prompt.split("=== ТЕКСТ A ===\n", 1)[1].split("=== ТЕКСТ B ===\n", 1)[0]
        winner = "A" if "Плотный совет" in text_a else "B"
        return json.dumps({"winner": winner, "confidence": "high", "reason": "плотность", "loser_flaws": []})

    res = RE.evaluate_pairwise(tmp_path, judge)
    assert res["totals"]["correct_wins"] == 1
    assert res["totals"]["discrimination_accuracy"] == 1.0
