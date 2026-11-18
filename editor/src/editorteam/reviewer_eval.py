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

    genre = OwnerReview.plan_genre(context)
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
            OwnerReview.validate_rubric(text, rows, allow_unresolved=True, genre=genre)
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
        "categories": len(OwnerReview.categories_for(genre)),
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


# ── Попарное сравнение с перестановкой позиций (pairwise) ───────────────

PAIRWISE_PROMPT_VERSION = "1"
PAIRWISE_SYSTEM = (
    "Ты независимый литературный редактор игрового сайта Манакост. "
    "Тебе дают два анонимных варианта статьи (Текст A и Текст B) и эталонный текст владельца (Reference) "
    "как ориентир тона, плотности игровых решений, отсутствия воды, пересказа карт и AI-штампов. "
    "Сравни Текст A и Текст B и реши, какой из них ближе к стандарту Reference. "
    "Не суди по длине или вежливости; цени конкретные условия решений, естественный русский язык и отсутствие лишнего. "
    "Если оба варианта одинаково близки или одинаково слабы, верни tie. "
    'Ответь только JSON-объектом {"winner":"A|B|tie","confidence":"high|medium|low","reason":"...","loser_flaws":["..."]} без пояснений вокруг.'
)


def parse_pairwise_reply(reply: str) -> dict | None:
    """Разобрать JSON-вердикт парного сравнения."""
    match = _JSON.search(reply or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    winner = str(data.get("winner", "")).strip()
    if winner not in {"A", "B", "tie"}:
        return None
    return {
        "winner": winner,
        "confidence": str(data.get("confidence", "medium")).strip().lower() or "medium",
        "reason": str(data.get("reason", "")).strip(),
        "loser_flaws": [str(x) for x in (data.get("loser_flaws") or []) if isinstance(x, str)],
    }


def build_pairwise_prompt(text_a: str, text_b: str, reference: str | None = None) -> str:
    parts = []
    if reference:
        parts.append("=== ЭТАЛОН ВЛАДЕЛЬЦА (REFERENCE) ===\n" + reference)
    parts.append("=== ТЕКСТ A ===\n" + text_a)
    parts.append("=== ТЕКСТ B ===\n" + text_b)
    return "\n\n".join(parts)


def build_pairs(folder: Path, *, max_pairs: int | None = None) -> list[dict]:
    """Сформировать пары (rejected vs accepted + gold reference) из labels.json или evals/pairs."""
    folder = Path(folder)
    pairs: list[dict] = []
    labels_path = folder / "labels.json"
    if labels_path.is_file():
        labels = json.loads(labels_path.read_text(encoding="utf-8"))
        versions = folder / "versions"
        accepted = labels.get("accepted") or sorted(
            p.name for p in versions.glob("*.md") if "accepted" in p.name
        )
        if not accepted:
            raise ValueError(f"pairwise mode: no accepted version in {versions}")
        accepted_name = accepted[0]
        accepted_text = (versions / accepted_name).read_text(encoding="utf-8")
        gold_files = [
            p
            for p in sorted((folder / "gold").glob("*"))
            if p.is_file() and p.suffix in OwnerEval.TEXT_SUFFIXES
        ]
        for idx, rej in enumerate(labels.get("rejections", [])):
            rej_path = versions / rej["version"]
            if not rej_path.is_file():
                continue
            ref_path = gold_files[idx % len(gold_files)] if gold_files else None
            pairs.append(
                {
                    "id": rej["id"],
                    "category": OwnerEval.REVIEW_CATEGORY.get(rej["category"], rej["category"]),
                    "owner_category": rej["category"],
                    "rejected_name": rej["version"],
                    "accepted_name": accepted_name,
                    "reference_name": f"gold/{ref_path.name}" if ref_path else None,
                    "rejected_text": rej_path.read_text(encoding="utf-8"),
                    "accepted_text": accepted_text,
                    "reference_text": ref_path.read_text(encoding="utf-8") if ref_path else None,
                }
            )
    else:
        for sub in sorted(folder.iterdir()):
            if not sub.is_dir():
                continue
            ref_p = sub / "reference.md"
            rej_p = sub / "ai_rejected.md"
            if not rej_p.is_file():
                rej_p = sub / "draft.md"
            if not (ref_p.is_file() and rej_p.is_file()):
                continue
            meta_p = sub / "meta.json"
            meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.is_file() else {}
            pairs.append(
                {
                    "id": meta.get("id", sub.name),
                    "category": meta.get("type", "PAIR"),
                    "owner_category": meta.get("type", "PAIR"),
                    "rejected_name": f"{sub.name}/{rej_p.name}",
                    "accepted_name": f"{sub.name}/reference.md",
                    "reference_name": None,
                    "rejected_text": rej_p.read_text(encoding="utf-8"),
                    "accepted_text": ref_p.read_text(encoding="utf-8"),
                    "reference_text": None,
                }
            )
    if max_pairs is not None:
        pairs = pairs[: max(0, max_pairs)]
    return pairs


def pairwise_calls_needed(folder: Path, *, max_pairs: int | None = None) -> int:
    pairs = build_pairs(folder, max_pairs=max_pairs)
    unique = {
        (sha(p["rejected_text"]), sha(p["accepted_text"]), sha(p["reference_text"] or ""))
        for p in pairs
    }
    return len(unique) * 2


def evaluate_pairwise(
    folder: Path,
    call: Callable[[str, str], str],
    *,
    model: str = "",
    cache: Path | None = None,
    parallel: int = 1,
    retries: int = 1,
    max_pairs: int | None = None,
) -> dict:
    """Слепое парное сравнение с двусторонней перестановкой (A,B) и (B,A)."""
    folder = Path(folder)
    pairs = build_pairs(folder, max_pairs=max_pairs)
    if not pairs:
        raise ValueError(f"pairwise mode: no pairs found in {folder}")

    jobs_map: dict[tuple[str, str, str], tuple[str, str, str | None]] = {}
    for p in pairs:
        sig_fwd = (sha(p["rejected_text"]), sha(p["accepted_text"]), sha(p["reference_text"] or ""))
        sig_rev = (sha(p["accepted_text"]), sha(p["rejected_text"]), sha(p["reference_text"] or ""))
        jobs_map.setdefault(sig_fwd, (p["rejected_text"], p["accepted_text"], p["reference_text"]))
        jobs_map.setdefault(sig_rev, (p["accepted_text"], p["rejected_text"], p["reference_text"]))

    cache_dir = (cache / "pairwise") if cache else None

    def run_one(item: tuple[tuple[str, str, str], tuple[str, str, str | None]]) -> tuple[tuple[str, str, str], dict]:
        sig, (text_a, text_b, ref_text) = item
        raw_key = f"{PAIRWISE_PROMPT_VERSION}|{model}|{'|'.join(sig)}"
        key = hashlib.sha256(raw_key.encode()).hexdigest()[:24]
        path = cache_dir / f"{key}.json" if cache_dir else None
        if path and path.exists():
            return sig, json.loads(path.read_text(encoding="utf-8"))
        prompt = build_pairwise_prompt(text_a, text_b, ref_text)
        record: dict = {"attempts": 0}
        parsed = None
        for _ in range(retries + 1):
            record["attempts"] += 1
            try:
                reply = call(PAIRWISE_SYSTEM, prompt)
            except Exception as error:  # noqa: BLE001 - записывается в отчёт
                record.update(reply="", error=str(error))
                continue
            parsed = parse_pairwise_reply(reply)
            record.update(reply=reply, error="" if parsed is not None else "no pairwise JSON")
            if parsed is not None:
                break
        record["parsed"] = parsed
        if path and parsed is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        return sig, record

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        results_by_sig = dict(pool.map(run_one, list(jobs_map.items())))

    def map_outcome(parsed: dict | None, accepted_slot: str) -> str:
        if not parsed:
            return "missing"
        w = parsed["winner"]
        if w == "tie":
            return "tie"
        return "accepted" if w == accepted_slot else "rejected"

    pair_rows = []
    by_cat: dict[str, dict] = {}
    for p in pairs:
        sig_fwd = (sha(p["rejected_text"]), sha(p["accepted_text"]), sha(p["reference_text"] or ""))
        sig_rev = (sha(p["accepted_text"]), sha(p["rejected_text"]), sha(p["reference_text"] or ""))
        rec_fwd = results_by_sig[sig_fwd]
        rec_rev = results_by_sig[sig_rev]
        p_fwd = rec_fwd.get("parsed")
        p_rev = rec_rev.get("parsed")
        out_fwd = map_outcome(p_fwd, "B")  # A=rejected, B=accepted
        out_rev = map_outcome(p_rev, "A")  # A=accepted, B=rejected
        both_valid = p_fwd is not None and p_rev is not None
        consistent = both_valid and (out_fwd == out_rev)
        correct = consistent and (out_fwd == "accepted")
        pos_bias = both_valid and (p_fwd["winner"] == p_rev["winner"]) and (p_fwd["winner"] in {"A", "B"})
        pair_rows.append(
            {
                "id": p["id"],
                "owner_category": p["owner_category"],
                "category": p["category"],
                "rejected_name": p["rejected_name"],
                "accepted_name": p["accepted_name"],
                "reference_name": p["reference_name"],
                "forward": {"winner": p_fwd["winner"] if p_fwd else "missing", "outcome": out_fwd, "reason": (p_fwd or {}).get("reason", "")},
                "reverse": {"winner": p_rev["winner"] if p_rev else "missing", "outcome": out_rev, "reason": (p_rev or {}).get("reason", "")},
                "consistent": consistent,
                "correct": correct,
                "positional_bias": pos_bias,
            }
        )
        cat = by_cat.setdefault(p["owner_category"], {"pairs": 0, "correct_wins": 0, "consistent": 0})
        cat["pairs"] += 1
        if correct:
            cat["correct_wins"] += 1
        if consistent:
            cat["consistent"] += 1

    for cat in by_cat.values():
        cat["discrimination_accuracy"] = round(cat["correct_wins"] / cat["pairs"], 3) if cat["pairs"] else 0.0

    n = len(pair_rows)
    valid_calls = sum(1 for rec in results_by_sig.values() if rec.get("parsed") is not None)
    correct_wins = sum(1 for r in pair_rows if r["correct"])
    consistent_count = sum(1 for r in pair_rows if r["consistent"])
    pos_bias_count = sum(1 for r in pair_rows if r["positional_bias"])
    ties = sum(1 for r in pair_rows if r["consistent"] and r["forward"]["outcome"] == "tie")

    article = ""
    labels_path = folder / "labels.json"
    if labels_path.is_file():
        article = json.loads(labels_path.read_text(encoding="utf-8")).get("article", "")

    return {
        "mode": "pairwise",
        "dataset": str(folder),
        "article": article,
        "model": model,
        "prompt_version": PAIRWISE_PROMPT_VERSION,
        "pairs": pair_rows,
        "totals": {
            "pairs": n,
            "unique_calls": len(results_by_sig),
            "valid_calls": valid_calls,
            "correct_wins": correct_wins,
            "discrimination_accuracy": round(correct_wins / n, 3) if n else 0.0,
            "swap_consistent": consistent_count,
            "swap_consistency": round(consistent_count / n, 3) if n else 0.0,
            "positional_bias_cases": pos_bias_count,
            "ties": ties,
        },
        "by_category": dict(sorted(by_cat.items())),
    }


def compare_pairwise(result: dict, baseline: dict) -> dict:
    keys = ("correct_wins", "discrimination_accuracy", "swap_consistent", "swap_consistency", "positional_bias_cases", "ties")
    now, then = result.get("totals", {}), baseline.get("totals", {})
    return {k: round(now.get(k, 0) - then.get(k, 0), 3) for k in keys if k in then}


def render_pairwise(result: dict, delta: dict | None = None) -> str:
    t = result["totals"]
    out = [
        f"reviewer-eval (pairwise): {result['article'] or result['dataset']}",
        f"модель: {result['model'] or 'по умолчанию CLI'}, пар: {t['pairs']}, уникальных вызовов: {t['unique_calls']}",
        "",
        f"{'ID':<6} {'категория':<34} {'прям.':<9} {'обр.':<9} {'согл.':<6} итог",
    ]
    for r in result["pairs"]:
        mark = "OK" if r["correct"] else ("BIAS" if r["positional_bias"] else "MISS")
        out.append(
            f"{r['id']:<6} {r['owner_category']:<34} {r['forward']['outcome']:<9} "
            f"{r['reverse']['outcome']:<9} {('да' if r['consistent'] else 'нет'):<6} {mark}"
        )
    out += [
        "",
        f"дискриминация (accepted победил в обоих порядках): {t['correct_wins']} / {t['pairs']} ({t['discrimination_accuracy']:.1%})",
        f"согласованность перестановки (swap consistency): {t['swap_consistent']} / {t['pairs']} ({t['swap_consistency']:.1%})",
        f"позиционный сдвиг (всегда один слот): {t['positional_bias_cases']}, ничьих: {t['ties']}",
        f"валидных вызовов: {t['valid_calls']} / {t['unique_calls']}",
    ]
    if delta:
        out.append("\nдельта к baseline: " + ", ".join(f"{k} {v:+g}" for k, v in delta.items()))
    return "\n".join(out)
