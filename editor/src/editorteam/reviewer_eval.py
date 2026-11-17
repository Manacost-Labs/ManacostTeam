"""Оценка рецензента-модели (рубрика owner_checks) на отклонениях владельца.

`owner-eval` меряет детерминированный audit. Большая часть претензий владельца
(вода, слабые советы, нелогичные сравнения, жанр) уходит рецензенту-модели;
этот модуль меряет его на том же наборе (формат — editor/docs/OWNER_EVAL.md).

Для каждого уникального текста набора (версии до исправления, принятая версия,
gold/*) рецензент получает то же назначение, что в publication run
(`owner_review.assignment`), и возвращает строки owner_checks. Имя файла и
разметка модели не передаются: оценка слепая.

- soft: строка нужной категории (`owner_eval.REVIEW_CATEGORY`) получила
  issue или unverified;
- strict: вдобавок цитата строки задевает размеченный фрагмент (как в owner-eval);
- false alarm: issue на принятой версии или эталоне. unverified там
  считается отдельно: это сомнение, а не претензия;
- стабильность: доля прогонов, в которых отклонение поймано.

Модель вызывается через переданную функцию `call(system, prompt) -> str`;
модуль сам сеть и CLI не трогает. Ответы кэшируются по sha256 текста, номеру
прогона, модели и версии промпта, поэтому прерванный прогон продолжается.
"""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from editorteam import owner_eval as OwnerEval
from editorteam import owner_review as OwnerReview

PROMPT_VERSION = "1"
CAUGHT = ("issue", "unverified")

SYSTEM = (
    "Ты независимый литературный рецензент игрового сайта Манакост. "
    "Тебе дают статью и назначение owner_review_assignment. Оцени статью так, как её "
    "оценил бы требовательный владелец сайта: практическая польза для игрока, без воды, "
    "очевидностей, пересказа карт, слабых советов, нелогичных сравнений, атрибуции "
    "источников в тексте и шаблонной интонации. "
    "По каждой категории из assignment.categories верни ровно одну строку "
    "{id, status: clear|issue|unverified, quote, reason}. quote — непустая дословная "
    "цитата из статьи (самый показательный фрагмент; для clear — фрагмент, который ты "
    "проверил). Не ставь clear ради допуска; сомнение — unverified. "
    "Программа проверяет охват и цитаты, смысл и качество оцениваешь ты. "
    'Ответь только JSON-объектом {"owner_checks": [...]} без пояснений вокруг.'
)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_prompt(text: str, context: dict | None = None) -> str:
    payload = {"owner_review_assignment": OwnerReview.assignment(text, context)}
    if context:
        payload["author_context"] = {
            k: context[k] for k in ("requirements", "style_examples") if k in context
        }
    return json.dumps(payload, ensure_ascii=False, indent=1) + "\n\n=== СТАТЬЯ ===\n" + text


_JSON = re.compile(r"\{.*\}", re.S)


def parse_reply(reply: str) -> list[dict] | None:
    """owner_checks из ответа модели; None, если JSON не найден."""
    match = _JSON.search(reply or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    rows = data.get("owner_checks") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else None


def _row(rows: list[dict] | None, category: str) -> dict | None:
    for row in rows or []:
        if isinstance(row, dict) and row.get("id") == category:
            return row
    return None


def _quote_touches(text: str, quote: str, fragments: list[str]) -> bool:
    if not quote or not fragments:
        return False
    quote_lines = OwnerEval._lines_with(text, quote)
    for fragment in fragments:
        lines = OwnerEval._lines_with(text, fragment)
        finding = {"line": quote_lines[0] if quote_lines else None, "evidence": quote}
        if OwnerEval._hits(finding, fragment, lines):
            return True
        # цитата рецензента короче фрагмента и лежит внутри него
        if OwnerEval.norm(quote) in OwnerEval.norm(fragment):
            return True
    return False


def judge(rejection: dict, text: str, rows: list[dict] | None) -> dict:
    category = OwnerEval.REVIEW_CATEGORY.get(rejection["category"], rejection["category"])
    row = _row(rows, category)
    status = row.get("status") if row else None
    soft = status in CAUGHT
    fragments = rejection.get("fragments") or []
    if not fragments:
        strict = soft  # претензия ко всей статье (жанр, длина): цитировать нечего
    else:
        strict = soft and _quote_touches(text, str(row.get("quote") or ""), fragments)
    return {
        "category": category,
        "status": status or "missing",
        "soft": soft,
        "strict": strict,
        "quote": (row or {}).get("quote", ""),
        "reason": (row or {}).get("reason", ""),
    }


def evaluate(
    folder: Path,
    call: Callable[[str, str], str],
    *,
    runs: int = 1,
    model: str = "",
    context: dict | None = None,
    cache: Path | None = None,
    parallel: int = 1,
    retries: int = 1,
) -> dict:
    """Прогнать рецензента по набору. `call(system, prompt)` возвращает ответ модели."""
    folder = Path(folder)
    labels = json.loads((folder / "labels.json").read_text(encoding="utf-8"))
    versions = folder / "versions"
    accepted = labels.get("accepted") or sorted(
        p.name for p in versions.glob("*.md") if "accepted" in p.name
    )
    texts: dict[str, str] = {}
    for rejection in labels["rejections"]:
        texts[f"versions/{rejection['version']}"] = (versions / rejection["version"]).read_text(
            encoding="utf-8"
        )
    clean_names = [f"versions/{n}" for n in accepted]
    clean_names += [
        f"gold/{p.name}"
        for p in sorted((folder / "gold").glob("*"))
        if p.is_file() and p.suffix in OwnerEval.TEXT_SUFFIXES
    ]
    for name in clean_names:
        texts[name] = (folder / name).read_text(encoding="utf-8")

    deck = OwnerReview.is_deck_guide(context)
    context_sha = sha(json.dumps(context, ensure_ascii=False, sort_keys=True)) if context else "-"

    def key(name: str, run: int) -> str:
        raw = f"{PROMPT_VERSION}|{model}|{context_sha}|{sha(texts[name])}|{run}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    def review(job: tuple[str, int]) -> tuple[str, int, dict]:
        name, run = job
        path = cache / f"{key(name, run)}.json" if cache else None
        if path and path.exists():
            return name, run, json.loads(path.read_text(encoding="utf-8"))
        text = texts[name]
        prompt = build_prompt(text, context)
        record: dict = {"attempts": 0}
        for _ in range(retries + 1):
            record["attempts"] += 1
            try:
                reply = call(SYSTEM, prompt)
            except Exception as error:  # noqa: BLE001 - сбой модели записывается в отчёт
                record.update(reply="", error=str(error))
                continue
            rows = parse_reply(reply)
            record.update(reply=reply, error="" if rows is not None else "no owner_checks JSON")
            if rows is not None:
                break
        rows = parse_reply(record.get("reply", ""))
        record["rows"] = rows
        record["validation"] = (
            OwnerReview.validate_rubric(text, rows, allow_unresolved=True, deck_guide=deck)
            if rows is not None
            else ["no owner_checks JSON"]
        )
        if path and rows is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        return name, run, record

    jobs = [(name, run) for run in range(runs) for name in texts]
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        done = list(pool.map(review, jobs))
    reviews: dict[str, list[dict]] = {name: [{} for _ in range(runs)] for name in texts}
    for name, run, record in done:
        reviews[name][run] = record

    rejections = []
    for rejection in labels["rejections"]:
        name = f"versions/{rejection['version']}"
        per_run = [judge(rejection, texts[name], r.get("rows")) for r in reviews[name]]
        rejections.append(
            {
                "id": rejection["id"],
                "version": rejection["version"],
                "owner_category": rejection["category"],
                "category": per_run[0]["category"],
                "deterministic": rejection["category"] in OwnerEval.DETERMINISTIC,
                "soft_rate": sum(r["soft"] for r in per_run) / runs,
                "strict_rate": sum(r["strict"] for r in per_run) / runs,
                "runs": per_run,
            }
        )

    clean = {}
    for name in clean_names:
        per_run = []
        for record in reviews[name]:
            rows = record.get("rows") or []
            per_run.append(
                {
                    "issue": sorted(r.get("id") for r in rows if r.get("status") == "issue"),
                    "unverified": sorted(
                        r.get("id") for r in rows if r.get("status") == "unverified"
                    ),
                }
            )
        clean[name] = per_run

    validity = {name: [not r.get("validation") for r in recs] for name, recs in reviews.items()}
    # Различение: сколько категорий в среднем помечено issue на отклонённых
    # версиях и на хороших текстах. Рецензент, который ставит issue везде,
    # «ловит» все отклонения, но не отличает плохой текст от хорошего.
    issue_counts = {
        name: [sum(1 for r in rec.get("rows") or [] if r.get("status") == "issue") for rec in recs]
        for name, recs in reviews.items()
    }
    rejected_names = {f"versions/{r['version']}" for r in labels["rejections"]}

    def mean(names) -> float:
        values = [n for name in names for n in issue_counts[name]]
        return round(sum(values) / len(values), 2) if values else 0.0

    discrimination = {
        "categories": len(OwnerReview.categories_for(deck)),
        "rejected_mean_issues": mean(sorted(rejected_names)),
        "clean_mean_issues": mean(clean_names),
    }
    return {
        "mode": "reviewer",
        "dataset": str(folder),
        "article": labels.get("article", ""),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "runs": runs,
        "author_context": bool(context),
        "rejections": rejections,
        "clean": clean,
        "validation": {
            name: [r.get("validation", []) for r in recs] for name, recs in reviews.items()
        },
        "issue_counts": issue_counts,
        "totals": {**totals(rejections, clean, validity, runs), **discrimination},
    }


def totals(rejections: list[dict], clean: dict, validity: dict, runs: int) -> dict:
    reviewer = [r for r in rejections if not r["deterministic"]]
    false_alarms: dict[str, int] = {}
    unverified: dict[str, int] = {}
    for per_run in clean.values():
        for run in per_run:
            for cid in run["issue"]:
                false_alarms[cid] = false_alarms.get(cid, 0) + 1
            for cid in run["unverified"]:
                unverified[cid] = unverified.get(cid, 0) + 1
    checks = [ok for oks in validity.values() for ok in oks]
    return {
        "rejections": len(rejections),
        "reviewer_only": len(reviewer),
        "soft": round(sum(r["soft_rate"] for r in rejections), 2),
        "strict": round(sum(r["strict_rate"] for r in rejections), 2),
        "reviewer_only_soft": round(sum(r["soft_rate"] for r in reviewer), 2),
        "reviewer_only_strict": round(sum(r["strict_rate"] for r in reviewer), 2),
        "unstable": sum(1 for r in rejections if 0 < r["soft_rate"] < 1),
        "clean_texts": len(clean),
        "clean_reviews": len(clean) * runs,
        "false_alarms": sum(false_alarms.values()),
        "false_alarms_by_category": dict(sorted(false_alarms.items())),
        "clean_unverified": sum(unverified.values()),
        "valid_reviews": sum(checks),
        "reviews": len(checks),
    }


def calls_needed(folder: Path, runs: int) -> int:
    labels = json.loads((Path(folder) / "labels.json").read_text(encoding="utf-8"))
    versions = {r["version"] for r in labels["rejections"]}
    accepted = labels.get("accepted") or [
        p.name for p in (Path(folder) / "versions").glob("*.md") if "accepted" in p.name
    ]
    versions |= set(accepted)
    gold = [
        p
        for p in (Path(folder) / "gold").glob("*")
        if p.is_file() and p.suffix in OwnerEval.TEXT_SUFFIXES
    ]
    return (len(versions) + len(gold)) * runs


def compare(result: dict, baseline: dict) -> dict:
    """Дельта итогов с прежним прогоном того же набора (reviewer-eval JSON)."""
    keys = (
        "soft",
        "strict",
        "reviewer_only_soft",
        "reviewer_only_strict",
        "false_alarms",
        "clean_unverified",
        "unstable",
        "rejected_mean_issues",
        "clean_mean_issues",
    )
    now, then = result["totals"], baseline.get("totals", {})
    return {k: round(now.get(k, 0) - then.get(k, 0), 2) for k in keys if k in then}


def _rate(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".") if x not in (0, 1) else str(int(x))


def render(result: dict, delta: dict | None = None) -> str:
    out = [
        f"reviewer-eval: {result['article']} ({result['dataset']})",
        f"модель: {result['model'] or 'по умолчанию CLI'}, прогонов: {result['runs']}, "
        f"author-context: {'да' if result['author_context'] else 'нет'}",
        "",
        f"{'ID':<4} {'категория владельца':<36} {'рубрика':<28} {'soft':>5} {'strict':>6}  статус (прогон 1)",
    ]
    for r in result["rejections"]:
        mark = " (audit)" if r["deterministic"] else ""
        first = r["runs"][0]["status"]
        out.append(
            f"{r['id']:<4} {(r['owner_category'] + mark):<36} {r['category']:<28} "
            f"{_rate(r['soft_rate']):>5} {_rate(r['strict_rate']):>6}  {first}"
        )
    t = result["totals"]
    out += [
        "",
        f"поймано (soft): {t['soft']} из {t['rejections']}; с цитатой во фрагменте (strict): {t['strict']}",
        f"только для рецензента: soft {t['reviewer_only_soft']} / strict {t['reviewer_only_strict']} "
        f"из {t['reviewer_only']}",
        f"нестабильных между прогонами: {t['unstable']}",
        f"ложные тревоги (issue) на эталонах и принятой версии: {t['false_alarms']} "
        f"на {t['clean_reviews']} отзывов; unverified там: {t['clean_unverified']}",
    ]
    if t["false_alarms_by_category"]:
        out.append("    " + ", ".join(f"{k} {v}" for k, v in t["false_alarms_by_category"].items()))
    out.append(
        f"различение: issue в среднем на отклонённой версии {t['rejected_mean_issues']}, "
        f"на хорошем тексте {t['clean_mean_issues']} (из {t['categories']} категорий)"
    )
    out.append(f"валидных отзывов (validate_rubric): {t['valid_reviews']} из {t['reviews']}")
    if delta:
        out.append("\nдельта к baseline: " + ", ".join(f"{k} {v:+g}" for k, v in delta.items()))
    out.append(
        "\nsoft — нужная категория получила issue/unverified; strict — и цитата задевает "
        "размеченный фрагмент. Охват рубрики не доказывает качество суждений."
    )
    return "\n".join(out)
