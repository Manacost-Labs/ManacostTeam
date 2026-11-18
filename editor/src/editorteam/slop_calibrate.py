"""Калибровка словаря AI-слопа (слова и n-граммы) с контролем шума по человеческому корпусу.

Сравнивает AI-черновики против заведомо человеческих гайдов (до 2023 + 2024–2025
Alexey/Zulutan), предварительно отсеивая кандидатов, которые нестабильны даже между
двумя случайными половинами человеческого корпуса (human-vs-human split control).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

from editorteam.owner_checks import _Lemmas, _strip

SLOP_POS = frozenset({"NOUN", "ADJF", "ADJS", "VERB", "INFN", "PRTF", "PRTS", "GRND", "ADVB"})
UNIGRAM_STOP = frozenset(
    "быть это весь свой который мочь такой этот тот ваш наш один так уже ещё еще "
    "очень можно нужно надо стать сам самый другой каждый первый просто также тоже "
    "лишь только даже потом теперь здесь там себя более менее когда если "
    "потому поэтому однако чтобы иметь давать делать знать видеть играть карта "
    "колода ход игра стол рука существо противник соперник мана урон здоровье "
    "январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь "
    "год месяц неделя день сезон патч обновление релиз выпуск материал статья гайд "
    "обзор подборка список код состав таблица рейтинг текст ссылка видео скриншот "
    "охотник демон друид жрец воин маг шаман разбойник чернокнижник паладин рыцарь смерть "
    "стандарт вольный арена потасовка поле сражение дуэт винрейт статистика выборка".split()
)
NGRAM_STOP_EDGE = frozenset(
    "и в на с к по о об от за из до у для без под при не ни но а или же "
    "он она оно они его её их я мы ты вы мой твой свой ваш наш этот тот весь".split()
)
NGRAM_STOP_ANY = frozenset(
    "январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь "
    "год сезон патч релиз выпуск обзор подборка код таблица рейтинг ссылка видео "
    "охотник демон друид жрец воин маг шаман разбойник чернокнижник паладин рыцарь смерть "
    "стандарт вольный арена потасовка дуэт он она оно они его её их я мы ты вы "
    "хрипнуть хрип клич".split()
)
SENT_SPLIT = re.compile(r"[.!?…\n]+|[—–:;()«»\"\[\]]")
RU_TOKEN = re.compile(r"[а-яё]+(?:-[а-яё]+)*", re.I)
NON_ARTICLE_AI_NAMES = frozenset(
    {
        "readme.md",
        "notes.md",
        "changelog.md",
        "skill.md",
        "handoff.md",
        "report.md",
        "status.md",
        "source.md",
        "comparison.md",
        "conclusion.md",
        "useful-data.md",
        "chat-before-after.md",
        "smoke_report.md",
        "core-tech-codes.md",
    }
)
_NON_ARTICLE_STEMS = (
    "release-",
    "report",
    "audit",
    "review",
    "notes",
    "handoff",
    "analysis",
    "checklist",
    "comparison",
    "conclusion",
    "status",
    "reference",
    "sources-",
    "statistics-",
    "editorial-changes",
    "purchase-",
)


def _strip_front_matter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return text


def _prose_text(text: str) -> str:
    body = _strip_front_matter(text)
    out = []
    in_fence = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence or not s or s.startswith(("#", ">", "|")):
            continue
        out.append(_strip(line))
    return "\n".join(out)


def extract_features(
    text: str,
    lemma: _Lemmas,
    game_lemmas: set[str],
) -> tuple[int, Counter[str], Counter[str]]:
    """Вернуть (число_токенов, unigrams, ngrams_2_3) из чистой прозы."""
    clean = _prose_text(text)
    total_tokens = 0
    unigrams: Counter[str] = Counter()
    ngrams: Counter[str] = Counter()

    for chunk in SENT_SPLIT.split(clean):
        raw_tokens = [t.lower() for t in RU_TOKEN.findall(chunk) if len(t) >= 2]
        if not raw_tokens:
            continue
        total_tokens += len(raw_tokens)
        parsed = [lemma(tok) for tok in raw_tokens]
        for lw, pos in parsed:
            if (
                pos in SLOP_POS
                and len(lw) >= 3
                and lw not in UNIGRAM_STOP
                and lw not in game_lemmas
            ):
                unigrams[lw] += 1

        lemmas = [lw for lw, _ in parsed]
        for n in (2, 3):
            for i in range(len(lemmas) - n + 1):
                gram_parts = lemmas[i : i + n]
                pos_parts = [parsed[j][1] for j in range(i, i + n)]
                if gram_parts[0] in NGRAM_STOP_EDGE and gram_parts[-1] in NGRAM_STOP_EDGE:
                    continue
                if pos_parts[0] == "NPRO" or pos_parts[-1] == "NPRO":
                    continue
                if any(lw in NGRAM_STOP_ANY for lw in gram_parts):
                    continue
                content_count = sum(
                    1
                    for lw, pos in zip(gram_parts, pos_parts)
                    if pos in SLOP_POS and len(lw) >= 3 and lw not in UNIGRAM_STOP
                )
                if content_count == 0:
                    continue
                if all(lw in game_lemmas for lw in gram_parts):
                    continue
                phrase = " ".join(gram_parts)
                ngrams[phrase] += 1

    return total_tokens, unigrams, ngrams


def _split_bit(doc_id: str) -> int:
    return int(hashlib.sha256(doc_id.encode("utf-8")).hexdigest()[:8], 16) % 2


def _rate(count: int, total_tokens: int) -> float:
    return (count + 0.5) / (max(total_tokens, 1) + 500) * 1000.0


def _collect_group(
    docs: Iterable[tuple[str, str, str]],
    lemma: _Lemmas,
    game_lemmas: set[str],
) -> tuple[int, Counter[str], Counter[str], dict[str, set[str]], dict[str, set[str]]]:
    total = 0
    uni_counts: Counter[str] = Counter()
    ng_counts: Counter[str] = Counter()
    uni_fams: dict[str, set[str]] = {}
    ng_fams: dict[str, set[str]] = {}
    for doc_id, family_id, text in docs:
        n_tok, u, ng = extract_features(text, lemma, game_lemmas)
        total += n_tok
        uni_counts.update(u)
        ng_counts.update(ng)
        for key in u:
            uni_fams.setdefault(key, set()).add(family_id)
        for key in ng:
            ng_fams.setdefault(key, set()).add(family_id)
    return total, uni_counts, ng_counts, uni_fams, ng_fams


def calibrate_slop(
    human_docs: list[tuple[str, str]],
    ai_docs: list[tuple[str, str, str]],
    game_texts: Iterable[str],
    morph,
    *,
    source: str = "corpus-archive(<2023) + corpus-bg(<2023 + 2024-2025 Alexey/Zulutan)",
    max_human_split_ratio: float = 2.8,
    min_ai_families: int = 3,
    min_uni_count: int = 12,
    min_uni_ratio: float = 3.2,
    min_ngram_count: int = 6,
    min_ngram_ratio: float = 3.5,
    max_unigrams: int = 150,
    max_ngrams: int = 200,
    topic_ids: Iterable[str] = (),
) -> dict:
    """Построить калиброванный словарь AI-слопа с human-vs-human контролем шума."""
    lemma = _Lemmas(morph)
    game_lemmas: set[str] = set()
    for text in game_texts:
        for tok in RU_TOKEN.findall(str(text)):
            lw, _ = lemma(tok)
            if len(lw) >= 3:
                game_lemmas.add(lw)

    human_a = [(doc_id, doc_id, txt) for doc_id, txt in human_docs if _split_bit(doc_id) == 0]
    human_b = [(doc_id, doc_id, txt) for doc_id, txt in human_docs if _split_bit(doc_id) == 1]

    ha_tok, ha_u, ha_ng, _, _ = _collect_group(human_a, lemma, game_lemmas)
    hb_tok, hb_u, hb_ng, _, _ = _collect_group(human_b, lemma, game_lemmas)
    ai_tok, ai_u, ai_ng, ai_ufam, ai_ngfam = _collect_group(ai_docs, lemma, game_lemmas)
    # Контроль темы: ИИ-черновики в основном про Поля сражений, а человеческий
    # корпус в основном про колоды. Без него в словарь попадает лексика БГ
    # («золото на»), поэтому термин должен быть редким и у людей той же темы.
    topic = set(topic_ids)
    topic_docs = [(doc_id, doc_id, txt) for doc_id, txt in human_docs if doc_id in topic]
    tp_tok, tp_u, tp_ng, _, _ = _collect_group(topic_docs, lemma, game_lemmas)

    h_tok = ha_tok + hb_tok
    h_u = ha_u + hb_u
    h_ng = ha_ng + hb_ng

    def rank(
        ai_counts: Counter[str],
        h_counts: Counter[str],
        ha_counts: Counter[str],
        hb_counts: Counter[str],
        ai_fams: dict[str, set[str]],
        tp_counts: Counter[str],
        min_count: int,
        min_ratio: float,
        limit: int,
    ) -> tuple[dict[str, dict], int, int]:
        candidates: list[tuple[float, str, dict]] = []
        dropped_noise = 0
        dropped_topic = 0
        eff_min_fam = min(min_ai_families, max(1, len({fam for _, fam, _ in ai_docs})))
        for key, ai_c in ai_counts.items():
            fams = len(ai_fams.get(key, ()))
            if ai_c < min_count or fams < eff_min_fam:
                continue
            ai_r = _rate(ai_c, ai_tok)
            h_c = h_counts.get(key, 0)
            h_r = _rate(h_c, h_tok)
            ratio = ai_r / h_r
            if ratio < min_ratio:
                continue
            ha_c = ha_counts.get(key, 0)
            hb_c = hb_counts.get(key, 0)
            if ha_c == 0 and hb_c == 0:
                split_ratio = 1.0
            else:
                ra = _rate(ha_c, ha_tok)
                rb = _rate(hb_c, hb_tok)
                split_ratio = max(ra, rb) / min(ra, rb)
            if split_ratio > max_human_split_ratio:
                dropped_noise += 1
                continue
            topic_ratio = ai_r / _rate(tp_counts.get(key, 0), tp_tok) if tp_tok else None
            if topic_ratio is not None and topic_ratio < min_ratio:
                dropped_topic += 1
                continue
            score = math.log2(ratio) * math.log1p(fams)
            candidates.append(
                (
                    score,
                    key,
                    {
                        "ai_count": ai_c,
                        "human_count": h_c,
                        "ai_per_1k": round(ai_c / max(ai_tok, 1) * 1000, 3),
                        "human_per_1k": round(h_c / max(h_tok, 1) * 1000, 3),
                        "ratio": round(ratio, 2),
                        "human_split_ratio": round(split_ratio, 2),
                        "topic_ratio": round(topic_ratio, 2) if topic_ratio is not None else None,
                        "ai_families": fams,
                        "score": round(score, 3),
                    },
                )
            )
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return {key: meta for _, key, meta in candidates[:limit]}, dropped_noise, dropped_topic

    uni_dict, uni_noise, uni_topic = rank(
        ai_u, h_u, ha_u, hb_u, ai_ufam, tp_u, min_uni_count, min_uni_ratio, max_unigrams
    )
    ng_dict, ng_noise, ng_topic = rank(
        ai_ng, h_ng, ha_ng, hb_ng, ai_ngfam, tp_ng, min_ngram_count, min_ngram_ratio, max_ngrams
    )

    return {
        "schema_version": 1,
        "_source": source,
        "human_docs": len(human_docs),
        "human_words": h_tok,
        "ai_docs": len(ai_docs),
        "ai_families": len({fam for _, fam, _ in ai_docs}),
        "ai_words": ai_tok,
        "max_human_split_ratio": max_human_split_ratio,
        "dropped_by_human_split": {"unigrams": uni_noise, "ngrams": ng_noise},
        "topic_docs": len(topic_docs),
        "topic_words": tp_tok,
        "dropped_by_topic": {"unigrams": uni_topic, "ngrams": ng_topic},
        "unigrams": uni_dict,
        "ngrams": ng_dict,
    }


def collect_human_docs(repo_root: Path) -> list[tuple[str, str]]:
    """Собрать чистые человеческие гайды: corpus-archive (<2023) и corpus-bg (<2023 + 24-25 Alexey/Zulutan)."""
    docs: list[tuple[str, str]] = []
    editor = repo_root / "editor"

    arc_manifest = editor / "corpus-archive" / "manifest.json"
    if arc_manifest.is_file():
        data = json.loads(arc_manifest.read_text(encoding="utf-8"))
        for row in data.get("guides", []):
            if str(row.get("published_at", "")) < "2023-01-01":
                path = editor / row["path"]
                if path.is_file():
                    docs.append((row["id"], path.read_text(encoding="utf-8")))

    bg_manifest = editor / "corpus-bg" / "manifest.json"
    if bg_manifest.is_file():
        data = json.loads(bg_manifest.read_text(encoding="utf-8"))
        for row in data.get("guides", []):
            pub = str(row.get("published_at", ""))
            is_pre = pub < "2023-01-01"
            is_verified_author = pub[:4] in {"2024", "2025"} and row.get("author") in {"Alexey", "Zulutan"}
            if is_pre or is_verified_author:
                path = editor / row["path"]
                if path.is_file():
                    docs.append((row["id"], path.read_text(encoding="utf-8")))
    return docs


def _family_of(name: str) -> str:
    low = name.lower()
    if low.startswith(("live-manacost-writing", "publication-precision-smoke")):
        return "topic:rewards-track-news"
    if low.startswith("live-manacost-"):
        return "topic:patch-36-6-3-live"
    if low.startswith(("live-long-strategic", "long-strategic", "long-guide")):
        return "topic:long-strategic-guide"
    if low.startswith("bg-meta"):
        return "topic:bg-meta"
    if low.startswith("budget-standard"):
        return "topic:budget-standard"
    m = re.match(r"^([a-z0-9]+-[a-z0-9]+)", low)
    return f"topic:{m.group(1)}" if m else f"topic:{low}"


_DEV_OR_AUDIT_PREFIXES = (
    "autonomous-tests",
    "editor-",
    "editorial-",
    "fidelity-",
    "gold-references",
    "long-guide-",
    "long-strategic-",
    "meta-report-dev",
    "project-recheck",
    "publication-runs",
    "quality-",
    "source-",
    "structure-smoke",
    "team-standard-",
    "archive-voice-",
    "clean-tree-",
    "context-smoke",
    "local-",
    "owner-rejections",
    "team-skills",
    "bin",
    "toolchains",
    "style-benchmark",
    "final-",
    "meta-report-forward-check",
    "smoke-",
)

_NON_ARTICLE_MARKERS = (
    "manacostteam: инструкции для агентов",
    "независимый фактологический аудит",
    "причина отклонения",
    "handoff_sha256",
    "живое сравнение редактора manacost",
    "что изменить в мета-отчёте",
    "baseline: clean",
    "сохраняйте ресурс при слабой позиции",
    "синтетический источник",
    "синтетические тесты",
)


def _is_article_draft(text: str) -> bool:
    head = text[:500].lower()
    if len(text.split()) < 150:
        return False
    return not any(marker in head for marker in _NON_ARTICLE_MARKERS)


def _is_non_article_name(filename: str) -> bool:
    low = filename.lower()
    if low in NON_ARTICLE_AI_NAMES:
        return True
    stem = low[:-3] if low.endswith(".md") else low
    return any(tok in stem for tok in _NON_ARTICLE_STEMS)


def collect_ai_docs(repo_root: Path, *, max_per_family: int = 3) -> list[tuple[str, str, str]]:
    """Собрать локальные AI-черновики статей с ограничением числа версий на одну тему."""
    docs: list[tuple[str, str, str]] = []
    family_counts: Counter[str] = Counter()
    build = repo_root / "build"
    if not build.is_dir():
        return docs

    def add_doc(doc_id: str, family: str, text: str) -> None:
        if family_counts[family] >= max_per_family or not _is_article_draft(text):
            return
        family_counts[family] += 1
        docs.append((doc_id, family, text))

    rej_root = build / "owner-rejections"
    if rej_root.is_dir():
        for dataset in sorted(rej_root.iterdir()):
            versions = dataset / "versions"
            if not versions.is_dir():
                continue
            for md in sorted(versions.glob("*.md")):
                if "accepted" in md.name.lower():
                    continue
                add_doc(
                    f"{dataset.name}/{md.name}",
                    f"rej:{dataset.name}",
                    md.read_text(encoding="utf-8", errors="ignore"),
                )

    for sub in sorted(build.iterdir()):
        if not sub.is_dir() or sub.name.lower().startswith(_DEV_OR_AUDIT_PREFIXES):
            continue
        family = _family_of(sub.name)
        for md in sorted(sub.glob("*.md")):
            if _is_non_article_name(md.name):
                continue
            add_doc(f"{sub.name}/{md.name}", family, md.read_text(encoding="utf-8", errors="ignore"))
        for sub_md in sorted(sub.glob("*/*.md")):
            parent_low = sub_md.parent.name.lower()
            if (
                _is_non_article_name(sub_md.name)
                or "smoke" in parent_low
                or "installed-" in parent_low
                or parent_low.startswith("dev-")
            ):
                continue
            if sub_md.parent.name == "artifacts" and "draft" in sub_md.name.lower():
                add_doc(
                    f"{sub.name}/artifacts/{sub_md.name}",
                    family,
                    sub_md.read_text(encoding="utf-8", errors="ignore"),
                )
            elif sub_md.name.lower() in {"draft.md", "article.md"} or sub.name in {
                "funmeta",
                "bg-meta-reports",
                "meta-reports",
                "battlegrounds-hero-guides",
            }:
                add_doc(
                    f"{sub.name}/{sub_md.parent.name}/{sub_md.name}",
                    f"{family}:{sub_md.parent.name}"[:32],
                    sub_md.read_text(encoding="utf-8", errors="ignore"),
                )
    return docs
