"""Owner rejection coverage and a deletion-only receipt; never semantic verdicts."""

from __future__ import annotations

import hashlib
import re

CATEGORIES = (
    "card_text_retelling",
    "obvious_or_water",
    "weak_or_obvious_tips",
    "duplicated_advice",
    "source_attribution_in_body",
    "unsupported_or_false_claim",
    "illogical_comparison",
    "unclear_edge_case",
    "genre_fit",
    "ai_tells",
)

CRITERIA = dict(
    zip(
        CATEGORIES,
        (
            "Есть ли польза сверх текста карты или силы героя, видимого в подсказке?",
            "Какое решение потеряет выбранный читатель при удалении фразы? Нужна ли страховочная оговорка?",
            "Есть ли подтверждённые неочевидные решения сильных игроков? Слабый блок советов убери целиком.",
            "Добавляет ли повтор новое условие или полезную навигацию? Сопоставь разные разделы.",
            "Не просочились ли в тело GUIDE площадки, «по данным…» и отчёт о поиске? Имя игрока нужно лишь полезному мнению.",
            "Не подано ли observation как правило с придуманной причиной? Сверь claim_kind и evidence, не только confidence.",
            "Может ли игрок на практике получить оба сравниваемых варианта в названной ситуации?",
            "Ясен ли путь в частный случай и какое решение он меняет? Сохрани действительно нужные исключения.",
            "Соответствуют ли объём, манера и содержательность выбранным образцам? Обоснуй отклонение от их бюджета.",
            "Нет ли искусственных рамок, натужной живости и шаблонной интонации? Не определяй авторство по признакам.",
        ),
    )
)

# Гайд по колоде: план с genre=deck_guide включает ещё три обязательные строки.
# Они не входят в CATEGORIES: прежние запуски, мета-отчёты и Полей сражений
# проверяются прежней рубрикой из десяти категорий.
DECK_GUIDE = "deck_guide"
DECK_GUIDE_CATEGORIES = (
    "advice_has_condition_and_reason",
    "mastery_has_threshold_or_order",
    "term_before_definition",
)
DECK_GUIDE_CRITERIA = dict(
    zip(
        DECK_GUIDE_CATEGORIES,
        (
            "У каждого совета есть условие (когда) и причина (почему), а при сильном совете ещё цена ошибки? "
            "Совет без условия или без причины — ремонт: добавь подтверждённое или убери.",
            "В каждом разделе мастерства есть хотя бы один порог (число, граница) или порядок действий (через «>»)? "
            "Числа и последовательность совпадают с карточкой опыта игрока без изменений? "
            "Первое лицо допустимо только там, где карточка с first_person=true.",
            "Каждый термин («вылет», «обмен», «раскрутка») объяснён при первом упоминании или в разделе "
            "«как работает колода», который стоит раньше? Цитируй первое употребление до объяснения.",
        ),
    )
)


def is_deck_guide(context: dict | None) -> bool:
    plan = context.get("article_plan") if isinstance(context, dict) else None
    return isinstance(plan, dict) and plan.get("genre") == DECK_GUIDE


def categories_for(deck_guide: bool = False) -> tuple[str, ...]:
    return CATEGORIES + DECK_GUIDE_CATEGORIES if deck_guide else CATEGORIES


DECK_GUIDE_GUIDANCE = (
    "Гайд по колоде. Порядок: вступление-сцена → как работает колода → карты по ролям → сборки с условием "
    "выбора → муллиган → план на ранние ходы → разделы мастерства → как играть против → заключение. "
    "Объяснение «как работает колода» стоит сразу после вступления: термины («вылет», «обмен», «раскрутка») "
    "не используются раньше, чем объяснены. Карту описывай ролью в колоде (зачем её берут, когда играют, "
    "чем заменяют), а не пересказом её текста; несколько абзацев подряд «Карта — …» без роли не пиши. "
    "У каждого совета есть условие и причина; при цене ошибки назови и её. "
    "Порядок действий пиши через «>» («таракан > сила героя > Эредар > сила героя»); порог — числом с границей. "
    "Формы советов: порог, порядок действий, запрет, запасной план, ловушка, совет по уровню игрока "
    "(что пропустить, если только учишься). "
    "Раздел мастерства пиши только из карточек опыта игрока (decision_cards с advice_form), по одному разделу "
    "на сильную мысль; порог и порядок из карточки переноси без изменения чисел и последовательности. "
    "Если карточек нет или пакет опыта пуст, раздел мастерства не пиши («писать не из чего»), "
    "пробел оставь пробелом, слабыми общими советами его не заполняй. "
    "Первое лицо («я», «по моему опыту») — только для содержания карточек с first_person=true; "
    "свой опыт, сыгранные партии и впечатления не выдумывай. "
    "Источник называй один раз в конце, в теле его не пересказывай."
)

CLAIM_GUIDANCE = (
    "Правилом с «потому что» подавай только claim_kind=mechanic с проверенным основанием. "
    "observation — наблюдение в указанной выборке, не правило и не причина. "
    "opinion — мнение с именем игрока, только если оно нужно читателю. "
    "Отсутствующий claim_kind у старого handoff не угадывай: проверь основание отдельно. "
    "Если handoff говорит «блок советов писать не из чего», блок не пишется; "
    "не заменяй его слабыми общими пунктами."
)

DELETION_GUIDANCE = (
    "После черновика и до литературного отзыва выполни отдельный проход на вычёркивание. "
    "Только удаляй и сокращай; новых фактов, слов, связок и перестановок не добавляй. "
    "Для каждого предложения спроси: «какое решение потеряет игрок, если это убрать?» "
    "Нет ответа — вычеркни. Удали пересказ текста карты/силы героя, уже видимого в подсказке "
    "шорткода, очевидное, страховочные оговорки без пользы, повтор совета из другого раздела, "
    "атрибуцию источника в теле («по данным…», «игроки на Reddit…»), статистическое наблюдение "
    "в форме правила без проверяемой причины, сравнение без доступного игроку выбора. "
    "Слабый блок советов убери целиком. Находки card_paraphrase.retelling, owner.overused_word, "
    "owner.section_repeat, owner.forbidden_literal — вход для решения, а не приказ удалить полезное. "
    "«Убрать воду» не означает сократить полезные объяснения: сохрани необходимые предпосылки, "
    "развилки, числа, условия, исключения и границы уверенности. Если удаление искажает совет, "
    "оставь фрагмент для содержательного ремонта, не добавляй объяснение в этом проходе. "
    "Список вычеркнутого с причиной хранится в рабочих материалах запуска, не в статье."
)


def word_count(text: str) -> int:
    text = re.sub(r"\[/?hs_(?:bg|card)\b[^\]]*\]|\[IMG\b[^\]]*\]|https?://\S+|<[^>]*>", "", text)
    return len(re.findall(r"\b[\w]+(?:[-’'][\w]+)*\b", text, re.UNICODE))


def genre_assignment(text: str, context: dict | None = None) -> dict:
    examples = [
        {
            "id": row["id"],
            "source_sha256": row["source_sha256"],
            "source_words": row.get("source_word_count"),
        }
        for row in (context or {}).get("style_examples", [])
    ]
    counts = [row["source_words"] for row in examples if row["source_words"] is not None]
    budget = (
        {"min": min(counts), "max": max(counts)}
        if counts and len(counts) == len(examples)
        else None
    )
    return {
        "article_words": word_count(text),
        "examples": examples,
        "word_budget": budget,
        "limitation": "Бюджет выведен из полных выбранных образцов, не из коротких цитат. "
        "При отсутствии замеров он неизвестен: обнови context или объясни ограничение. "
        "Отклонение от диапазона оценивает reviewer по содержанию, не автоматический порог.",
    }


def assignment(text: str, context: dict | None = None) -> dict:
    deck = is_deck_guide(context)
    return {
        "categories": list(categories_for(deck)),
        "criteria": {**CRITERIA, **(DECK_GUIDE_CRITERIA if deck else {})},
        **({"deck_guide": DECK_GUIDE_GUIDANCE} if deck else {}),
        "genre": genre_assignment(text, context),
        "schema": "owner_checks: ровно одна строка на категорию {id,status:clear|issue|unverified,quote,reason}. "
        "Для КАЖДОЙ строки нужна непустая дословная цитата текущей статьи, включая проверку отсутствия дефекта. "
        "issue/unverified требуют repair с этим фрагментом, а не подмены verdict на pass. "
        "genre_fit: сравни объём, манеру и полезное содержание с выбранными образцами; "
        "запиши genre_review из назначения и concrete reason. "
        "ai_tells — интонация и шаблонность, не определение авторства. "
        "Проверка охвата и цитат не проверяет качество суждения.",
        "claim_guidance": CLAIM_GUIDANCE,
    }


def validate_rubric(
    text: str, rows, *, allow_unresolved: bool = False, deck_guide: bool = False
) -> list[str]:
    """Весь набор категорий с цитатами; для гайда по колоде — ещё три строки.

    Сохранённый отзыв из десяти строк не разрешает новый экспорт гайда по
    колоде (missing category), но сам читается как прежде.
    """
    categories = categories_for(deck_guide)
    if not isinstance(rows, list) or len(rows) > 32:
        return ["owner_checks: complete quoted rubric required"]
    errors, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            errors.append("owner_checks: malformed row")
            continue
        key = row["id"]
        if key not in categories or key in seen:
            errors.append(f"owner_checks: unknown or duplicate category {key}")
        seen.add(key)
        if row.get("status") not in ("clear", "issue", "unverified"):
            errors.append(f"owner_checks/{key}: invalid status")
        if (
            not isinstance(row.get("quote"), str)
            or not row["quote"].strip()
            or row["quote"] not in text
        ):
            errors.append(f"owner_checks/{key}: exact nonempty candidate quote required")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            errors.append(f"owner_checks/{key}: concrete reason required")
        if row.get("status") in ("issue", "unverified") and not allow_unresolved:
            errors.append(f"owner_checks/{key}: repair required: {row.get('quote', '')}")
    for key in categories:
        if key not in seen:
            errors.append(f"owner_checks: missing category {key}")
    return errors


def validate_genre(text: str, context: dict, report: dict) -> list[str]:
    expected = genre_assignment(text, context)
    review = report.get("genre_review")
    if not isinstance(review, dict) or any(
        review.get(k) != expected[k] for k in ("article_words", "examples", "word_budget")
    ):
        return ["genre_review: use measured article and selected example word budget"]
    if not isinstance(review.get("reason"), str) or not review["reason"].strip():
        return ["genre_review: explain length and manner relative to the selected samples"]
    return []


def validate_deletion(text: str, report) -> tuple[str, list[str]]:
    """Replay exact spans. No replacement field exists, so no new prose can enter."""
    if not isinstance(report, dict) or set(report) - {
        "article_sha256",
        "deletions",
        "unchanged_reason",
    }:
        return text, ["deletion_pass: invalid fields; only removals allowed"]
    if report.get("article_sha256") != hashlib.sha256(text.encode("utf-8")).hexdigest():
        return text, ["deletion_pass: article hash mismatch"]
    rows = report.get("deletions")
    if not isinstance(rows, list) or len(rows) > 1024:
        return text, ["deletion_pass: bounded deletions array required"]
    if not rows:
        reason = report.get("unchanged_reason")
        return text, [] if isinstance(reason, str) and reason.strip() else [
            "deletion_pass: explain unchanged result"
        ]
    cursor, parts = 0, []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"start", "quote", "reason"}:
            return text, ["deletion_pass: each removal needs start/quote/reason"]
        start, quote, reason = row["start"], row["quote"], row["reason"]
        if (
            type(start) is not int
            or start < cursor
            or not isinstance(quote, str)
            or not quote
            or text[start : start + len(quote)] != quote
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            return text, ["deletion_pass: ordered nonoverlapping exact quotes and reasons required"]
        parts.append(text[cursor:start])
        cursor = start + len(quote)
    result = "".join(parts) + text[cursor:]
    return result, [] if result.strip() else ["deletion_pass: cannot erase the article"]
