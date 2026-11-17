"""Загрузчик редакционных правил.

Одно решение хранится в одном месте — в `config/*.yaml`. Код и документация
читают отсюда, а не повторяют таблицы у себя. Раньше правило про «винрейт»
жило одновременно в CLAUDE.md, ГОЛОС.md и в голове редактора, и они разошлись.

Виды решений:
    auto_replace — заменять автоматически, практика автора совпадает с правилом
    allowed      — оставлять как написано, слово авторское
    advisory     — корпусная подсказка; авторское слово сохраняется по контексту
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

DECISIONS = {"auto_replace", "allowed", "forbidden", "advisory"}


class ConfigError(ValueError):
    """Конфигурация не проходит валидацию."""


@dataclass
class TermRule:
    id: str
    decision: str
    authority: str = ""
    slang: str | None = None
    word: str | None = None
    preferred: str | None = None
    alternative: str | None = None
    rejected_replacement: str | None = None
    corpus: dict = field(default_factory=dict)
    note: str = ""
    # другие написания той же сущности: строка (по леммам) или {pattern, shown, case_sensitive}
    aliases: list = field(default_factory=list)
    pattern: str | None = None
    case_sensitive: bool = False

    @property
    def subject(self) -> str:
        return self.slang or self.word or self.id

    def alias_names(self) -> list[str]:
        """Как показать алиасы читателю правил: слово или подпись образца."""
        out = []
        for a in self.aliases:
            if isinstance(a, str):
                out.append(a)
            elif isinstance(a, dict) and a.get("shown"):
                out.append(str(a["shown"]))
        return out

    def replacement_for(self, text_word: str) -> str | None:
        """Чем заменять — или None, если решение «оставить»."""
        if self.decision != "auto_replace" or not self.preferred or not self.mandatory:
            return None
        return self.preferred

    @property
    def mandatory(self) -> bool:
        return self.authority in {"language_norm", "author_global"}


def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    if not path.exists():
        raise ConfigError(f"нет файла конфигурации: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{name}: ожидался словарь на верхнем уровне")
    return data


@lru_cache(maxsize=1)
def terminology() -> list[TermRule]:
    data = _load_yaml("terminology.yaml")
    rules = []
    for raw in data.get("rules", []):
        if "id" not in raw:
            raise ConfigError(f"правило без id: {raw}")
        if raw.get("decision") not in DECISIONS:
            raise ConfigError(
                f"{raw['id']}: decision должен быть одним из {sorted(DECISIONS)}, "
                f"получено {raw.get('decision')!r}"
            )
        known = set(TermRule.__dataclass_fields__)
        rules.append(TermRule(**{k: v for k, v in raw.items() if k in known}))
    return rules


@lru_cache(maxsize=1)
def typography() -> dict:
    return _load_yaml("typography.yaml")


def validate() -> list[str]:
    """Проверить конфигурацию на конфликты. Возвращает список проблем."""
    problems: list[str] = []
    rules = terminology()

    seen_ids: dict[str, int] = {}
    for r in rules:
        seen_ids[r.id] = seen_ids.get(r.id, 0) + 1
    for rid, n in seen_ids.items():
        if n > 1:
            problems.append(f"повторяющийся id: {rid} ({n} раз)")

    # одно и то же слово не может одновременно заменяться и оставаться
    by_subject: dict[str, list[TermRule]] = {}
    for r in rules:
        by_subject.setdefault(r.subject.lower(), []).append(r)
    for subject, group in by_subject.items():
        decisions = {r.decision for r in group}
        if len(decisions) > 1:
            problems.append(
                f"«{subject}»: противоречивые решения {sorted(decisions)} "
                f"в правилах {', '.join(r.id for r in group)}"
            )

    for r in rules:
        for a in r.aliases:
            ok = isinstance(a, str) or (isinstance(a, dict) and a.get("pattern"))
            if not ok:
                problems.append(f"{r.id}: alias должен быть строкой или {{pattern: …}}: {a!r}")
        if r.aliases and r.decision not in ("auto_replace", "forbidden", "advisory"):
            problems.append(f"{r.id}: aliases требуют правила замены или контекстной подсказки")

    # auto_replace обязан указывать, на что заменять
    for r in rules:
        if r.decision == "auto_replace" and not r.preferred:
            problems.append(f"{r.id}: auto_replace без preferred")
        if r.decision == "allowed" and r.preferred:
            problems.append(f"{r.id}: allowed с preferred — решение неоднозначно")

    # замена не должна противоречить частотам корпуса
    for r in rules:
        c = r.corpus or {}
        if r.decision == "auto_replace":
            slang_n, pref_n = c.get("slang"), c.get("preferred")
            if slang_n is not None and pref_n is not None and slang_n > pref_n:
                problems.append(
                    f"{r.id}: заменяем «{r.subject}» ({slang_n}) на «{r.preferred}» "
                    f"({pref_n}), хотя в корпусе чаще исходное слово"
                )

    problems.extend(_validate_typography())
    return problems


def _validate_typography() -> list[str]:
    problems = []
    t = typography()

    yo = t.get("yo", {})
    if yo.get("decision") not in {"remove", "keep", "as_written"}:
        problems.append(f"typography.yo.decision: неизвестное значение {yo.get('decision')!r}")

    q = t.get("quotes", {})
    if q.get("decision") not in {"straight", "guillemets", "as_written"}:
        problems.append(f"typography.quotes.decision: неизвестное значение {q.get('decision')!r}")

    arch = t.get("archetype_hyphen", {})
    if arch.get("decision") == "space" and arch.get("corpus", {}).get("с дефисом", 0) > 0:
        problems.append("archetype_hyphen: решение «без дефиса» при ненулевой частоте дефиса")

    nums = t.get("numbers", {})
    rng = nums.get("range", {})
    dashes = t.get("dashes", {})
    # диапазон через дефис и нормализация тире не должны спорить
    if rng.get("decision") == "hyphen" and "матч-ап" not in dashes.get("keep_hyphen_in", []):
        problems.append("dashes.keep_hyphen_in не покрывает случаи, где дефис обязателен")

    return problems


def as_markdown_table() -> str:
    """Таблица для документации — чтобы Markdown не расходился с конфигурацией."""
    lines = ["| Слово | Решение | Корпус |", "|---|---|---|"]
    for r in terminology():
        c = r.corpus or {}
        freq = ", ".join(f"{k}: {v}" for k, v in c.items())
        decision = {
            "auto_replace": f"→ {r.preferred}",
            "allowed": "оставлять",
            "forbidden": "нет в корпусе",
            "advisory": f"контекстная подсказка: {r.preferred}; не обязательная замена",
        }[r.decision]
        lines.append(f"| {r.subject} | {decision} | {freq} |")
    return "\n".join(lines)


def word_pattern(rule: TermRule) -> re.Pattern:
    """Образец для поиска слова правила во всех падежах (грубо, по основе)."""
    stem = re.escape(rule.subject[:-1] if len(rule.subject) > 4 else rule.subject)
    return re.compile(rf"\b{stem}\w*", re.IGNORECASE)


# ── форма подачи по профилю: оглавления тиров ────────────────────────────────
# Пункт-оглавление тира — одно жирное название карты без пояснения:
# «- **Подозрительный надзиратель**». Это перечень, а не акцент и не приём
# «**Ярлык:** пояснение», поэтому в профиле с form.allow_bold_index_lists
# маркеры жирного на таких строках не показываются. Пункт с двоеточием или
# тире после названия остаётся под проверкой как раньше.
BOLD_INDEX_LINE = re.compile(
    r"^\s*(?:[-*+]|\d{1,3}[.)])\s+\*\*[^*\n]{1,80}\*\*\s*[.,;]?\s*$"
)
BOLD_MARKER_IDS = frozenset({"bold-spam", "bold-label-list"})
# Карточка тира — абзац или пункт, который открывается официальным названием
# карты жирным и тире: «**Подозрительный надзиратель** — берите на 1-м ходу».
# Это навигация по тиру, а не приём «**Ярлык:** пояснение». Внутри карточки
# допустим ещё один акцент на решении; три выделения и больше — по-прежнему
# перебор жирного. Название — шорткод карты или имя из снимка карт: «**Плюс** —»
# карточкой не считается.
CARD_ENTRY_LINE = re.compile(
    r"^\s*(?:[-*+]\s+|\d{1,3}[.)]\s+)?\*\*(?P<name>[^*\n]{1,120})\*\*\s*(?:[—–]|-(?=\s))\s*\S"
)
CARD_ENTRY_MAX_BOLD = 2
_BOLD_SPAN = re.compile(r"\*\*[^*\n]{1,80}\*\*")
_CARD_SHORTCODE = re.compile(r"\[(?:hs_bg|hs_card)\b", re.I)
_ENTRY_BREAK = re.compile(r"^\s*(?:#{1,6}\s|[-*+]\s|\d{1,3}[.)]\s)")


def _profile_form(profile) -> dict:
    if profile is None:
        return {}
    if isinstance(profile, dict):
        return profile.get("form", profile) or {}
    return getattr(profile, "form", None) or {}


@lru_cache(maxsize=1)
def _card_names() -> frozenset[str]:
    """Официальные названия карт из снимка HearthstoneJSON, строчными и без «ё»."""
    from editorteam import card_paraphrase

    try:
        names = set(card_paraphrase.load_texts())
        names |= {row["n"] for row in card_paraphrase.load_bg().values()}
    except (OSError, ValueError, KeyError):
        return frozenset()  # без снимка карточкой считается только шорткод
    return frozenset(" ".join(n.split()).lower().replace("ё", "е") for n in names)


def _is_card_name(label: str) -> bool:
    if _CARD_SHORTCODE.search(label):
        return True
    return " ".join(label.split()).lower().replace("ё", "е") in _card_names()


def _card_entry_lines(lines: list[str]) -> set[int]:
    """Номера строк карточек тира, где жирного не больше CARD_ENTRY_MAX_BOLD.

    Карточка — от строки-зачина до пустой строки, заголовка, следующего пункта
    или следующего зачина.
    """
    out: set[int] = set()
    n = 0
    while n < len(lines):
        m = CARD_ENTRY_LINE.match(lines[n])
        if not (m and _is_card_name(m.group("name"))):
            n += 1
            continue
        end = n + 1
        while (
            end < len(lines)
            and lines[end].strip()
            and not _ENTRY_BREAK.match(lines[end])
            and not CARD_ENTRY_LINE.match(lines[end])
        ):
            end += 1
        if sum(len(_BOLD_SPAN.findall(line)) for line in lines[n:end]) <= CARD_ENTRY_MAX_BOLD:
            out.update(range(n + 1, end + 1))
        n = end
    return out


def filter_marker_hits(hits: list[dict], text: str, profile) -> list[dict]:
    """Снять маркеры жирного с пунктов-оглавлений и карточек тира, если профиль это разрешает.

    `hits` — выход `markers.scan` (поля id, line, para, min_hits, scope);
    `profile` — Profile, его `form` или None. Без флага
    `form.allow_bold_index_lists` список возвращается без изменений. После
    снятия кластер жирного в абзаце пересчитывается: два оставшихся акцента
    при пороге 3 уже не сигнал.
    """
    if not _profile_form(profile).get("allow_bold_index_lists"):
        return hits
    lines = text.splitlines()
    entries = _card_entry_lines(lines)

    def allowed_line(number: int) -> bool:
        # образец маркера начинается с `^\s*` и может захватить пустые строки
        # перед пунктом: смотрим первую непустую строку от места совпадения
        while 1 <= number <= len(lines) and not lines[number - 1].strip():
            number += 1
        if not 1 <= number <= len(lines):
            return False
        return number in entries or bool(BOLD_INDEX_LINE.match(lines[number - 1]))

    kept = [
        h for h in hits
        if not (h.get("id") in BOLD_MARKER_IDS and allowed_line(int(h.get("line", 0))))
    ]
    counts: dict[tuple, int] = {}
    for h in kept:
        if h.get("id") in BOLD_MARKER_IDS:
            key = (h["id"], h.get("para"))
            counts[key] = counts.get(key, 0) + 1
    return [
        h for h in kept
        if h.get("id") not in BOLD_MARKER_IDS
        or h.get("scope", "paragraph") == "document"
        or counts[(h["id"], h.get("para"))] >= int(h.get("min_hits", 1))
    ]
