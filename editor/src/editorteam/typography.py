"""Типографика через Typograf: тире и неразрывные пробелы, слова не меняются.

Typograf (npm-пакет `typograf`, MIT) — детерминированный типограф. Набор правил
у него по умолчанию шире, чем нужно изданию, и местами меняет смысл: «1/2»
становится «½» (а это статы существа), апостроф в «Кел'Тузад» — типографским,
«ёлочки» спорят с решением `typography.yaml: quotes: straight`. Поэтому стадия
устроена узко:

1. Всё, что нельзя трогать, гасится заглушками: код, ссылки, разметка, шорткоды,
   заголовки (и короткие строки-заголовки, как их видит structure.py), цитаты `>`,
   коды колод и точные названия карт из справочника.
2. Typograf запускается только с белым списком правил — тире и неразрывные
   пробелы; набор зависит от решений в `config/typography.yaml`.
3. Результат проверяется: пробел может стать неразрывным, а дефис — длинным тире,
   но ничего не добавляется и не пропадает. Любое другое расхождение — отказ,
   исходный файл остаётся нетронутым.

Стадия идёт после редакторских проверок и до шорткодов карт: `apply_shortcodes`
ищет названия точными строками с обычным пробелом, а кавычки в атрибутах
шорткода Typograf превращает в «ёлочки».

Нужен Node.js в PATH. Сама библиотека лежит в `assets/typograf/` и не требует
`npm install`. Без Node стадия сообщает, что не запущена; молча пропускать её нельзя.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from editorteam import rules

ROOT = Path(__file__).resolve().parents[2]
_SKILL = ROOT / ".claude" / "skills" / "hs-edit"
ASSETS = (_SKILL if _SKILL.exists() else ROOT) / "assets"
RUNNER = ASSETS / "typograf" / "run.js"
CATALOG = ASSETS / "cards-ru.json"
TIMEOUT_SECONDS = 60

# Тире: основной знак издания — длинное, с неразрывным пробелом перед ним.
DASH_RULES = ("ru/dash/main",)
# Неразрывные пробелы после коротких слов и в устойчивых оборотах. Правила только
# заменяют существующий пробел неразрывным и ничего не вставляют: число слов и
# символов в тексте остаётся прежним. Остальные правила группы nbsp на корпусе
# автора не срабатывают, поэтому не включены.
NBSP_RULES = (
    "common/nbsp/afterShortWord",
    "common/nbsp/afterShortWordByList",
    "common/nbsp/beforeShortLastWord",
    "common/nbsp/beforeShortLastNumber",
    "ru/nbsp/beforeParticle",
    "ru/nbsp/dayMonth",
)
# Включаются только если издание решило ставить «ёлочки».
QUOTE_RULES = ("common/punctuation/quote",)

# Правила Typograf, которые для этого издания включать нельзя, и почему. Тест
# следит, чтобы ни одно из них не попало в рабочий набор. Цифры — сколько строк
# корпуса из 49 гайдов автора правило изменило бы.
NEVER = {
    "common/number/fraction": "«1/4 оружие» — статы существа, а не дробь (11 строк)",
    "common/punctuation/apostrophe": "апостроф в «Дрек'Тар» прямой: cards.py считает ’ ошибкой (195)",
    "ru/typo/switchingKeyboardLayout": "подменяет латинские буквы-двойники кириллическими внутри "
    "слов: это правка текста, а названия и «ОТК» пишутся посимвольно (79)",
    "common/punctuation/hellip": "многоточие — авторский голос, его не трогаем",
    "common/other/repeatWord": "удаляет повторы слов, то есть правит текст",
    "ru/dash/years": "диапазоны по СТИЛЬ.md пишутся через дефис: «2-3 маны»",
    "ru/dash/daysMonth": "диапазоны по СТИЛЬ.md пишутся через дефис (1)",
    "ru/dash/month": "диапазоны по СТИЛЬ.md пишутся через дефис (1)",
    "ru/dash/centuries": "диапазоны по СТИЛЬ.md пишутся через дефис",
    "ru/nbsp/afterNumberSign": "ставит узкий неразрывный пробел U+202F вместо обычного (8)",
    "ru/nbsp/abbr": "вставляет пробел внутрь «т.е.»: стадия только заменяет пробелы (90)",
}

# Разметка и служебные участки, которые гасятся целиком. Порядок важен: что раньше,
# то приоритетнее. Имена нужны, чтобы другие стадии (подсказки орфографии) могли
# исключить часть правил, например заголовки.
_MARKUP = (
    ("front_matter", re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*(?:\n|\Z)", re.S)),
    # блок кода; если закрывающей ограды нет, он идёт до конца текста
    (
        "fence",
        re.compile(
            r"^[ \t]*(?P<f>`{3,}|~{3,})[^\n]*\n(?:.*?^[ \t]*(?P=f)[ \t]*$|.*\Z)", re.S | re.M
        ),
    ),
    ("comment", re.compile(r"<!--.*?-->", re.S)),
    (
        "html_block",
        re.compile(r"<(script|style|pre|code|kbd|textarea)\b[^>]*>.*?</\1>", re.S | re.I),
    ),
    ("tag", re.compile(r"</?[A-Za-z][^<>]*>")),  # теги и автоссылки <https://…>
    ("inline_code", re.compile(r"`+[^`\n]*`+")),
    ("shortcode", re.compile(r"\[/?[A-Za-z_][\w\-]*(?:\s[^\]\n]*)?\]")),  # только сами теги
    ("link_target", re.compile(r"(?<=\])\((?:[^()\n]|\([^()\n]*\))*\)")),
    ("link_definition", re.compile(r"^[ \t]{0,3}\[[^\]\n]+\]:[^\n]*$", re.M)),
    ("url", re.compile(r"(?:https?://|www\.)[^\s<>\]\)]+", re.I)),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("entity", re.compile(r"&(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")),
    ("deck_code", re.compile(r"^[ \t]*AAE\S{20,}[ \t]*$", re.M)),
    ("quote", re.compile(r"^[ \t]*>.*$", re.M)),  # чужие цитаты
    ("heading", re.compile(r"^[ \t]{0,3}#{1,6}[ \t].*$", re.M)),  # инструменты сверяют точно
    (
        # короткая самостоятельная строка — заголовок и для structure.headings(): сверка
        # разделов идёт точными строками, неразрывный пробел её бы сломал
        "plain_heading",
        re.compile(
            r"^[^\S\n]*(?=[A-ZА-ЯЁ])(?=[^\n]{3,40}?[^\S\n]*$)"
            r"\S+(?:[^\S\n]+\S+){0,4}(?<![.!?,:])[^\S\n]*$",
            re.M,
        ),
    ),
    (
        "table_rule",
        re.compile(r"^[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$", re.M),
    ),
    ("rule", re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", re.M)),
    ("list_marker", re.compile(r"^[ \t]*(?:[-*+]|\d{1,9}[.)])(?=[ \t])", re.M)),
)
_WORD = re.compile(r"\w")
_DASH_RUN = re.compile(r"[-–—]+")
_HSPACE = re.compile(r"[^\S\n]")
_QUOTES = str.maketrans(dict.fromkeys("«»„“”", '"'))
_NBSP_CHARS = "\u00a0\u202f"


class TypographyError(RuntimeError):
    """Типограф не смог безопасно обработать текст: файл не изменён."""


class ToolUnavailable(TypographyError):
    """Инструмент не запущен (нет Node.js или файлов Typograf)."""


@dataclass(frozen=True)
class Masked:
    """Текст с заглушками вместо защищённых участков."""

    text: str
    saved: tuple[str, ...]
    prefix: str
    suffix: str

    def restore(self, produced: str) -> str:
        pattern = re.compile(re.escape(self.prefix) + r"(\d{6})" + re.escape(self.suffix))
        found = [int(number) for number in pattern.findall(produced)]
        if found != list(range(len(self.saved))):
            raise TypographyError("заглушки защищённых участков повреждены или переставлены")
        return pattern.sub(lambda match: self.saved[int(match.group(1))], produced)


@dataclass(frozen=True)
class TypographyResult:
    text: str
    rules: tuple[str, ...]
    engine_version: str
    protected: int
    lines_changed: int
    nbsp_added: int
    dashes_added: int

    @property
    def changed(self) -> bool:
        return self.lines_changed > 0


Runner = Callable[[str, tuple[str, ...]], tuple[str, str]]


def enabled_rules(decisions: dict | None = None) -> tuple[str, ...]:
    """Правила Typograf по решениям издания из `config/typography.yaml`."""
    decisions = rules.typography() if decisions is None else decisions
    dashes = decisions.get("dashes") or {}
    chosen: list[str] = []
    if dashes.get("primary", "—") == "—" and dashes.get("normalize_en_to_em", True):
        chosen.extend(DASH_RULES)
    chosen.extend(NBSP_RULES)
    if (decisions.get("quotes") or {}).get("decision") == "guillemets":
        chosen.extend(QUOTE_RULES)
    return tuple(chosen)


@lru_cache(maxsize=1)
def card_names() -> tuple[str, ...]:
    """Названия карт из справочника локализации — их Typograf видеть не должен."""
    if not CATALOG.exists():
        raise ToolUnavailable(
            f"нет справочника карт {CATALOG}: без него названия не защитить; "
            "обновить: python3 .claude/skills/hs-edit/scripts/update_cards.py"
        )
    return tuple(json.loads(CATALOG.read_text(encoding="utf-8")).get("карты", ()))


def _name_index(names: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """Названия по первым двум символам, длинные раньше коротких."""
    buckets: dict[str, list[str]] = {}
    for name in names:
        if len(name) >= 2:
            buckets.setdefault(name[:2], []).append(name)
    return {key: tuple(sorted(group, key=len, reverse=True)) for key, group in buckets.items()}


def protected_spans(
    text: str, names: Iterable[str] = (), *, skip: Iterable[str] = ()
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Участки, которых стадиям трогать нельзя: (разметка, названия карт).

    `skip` — имена правил разметки, которые не нужны (например, «heading»). Названия
    ищутся только вне разметки, длинные раньше коротких, по границам слов.
    """
    skipped = set(skip)
    taken = bytearray(len(text))
    markup: list[tuple[int, int]] = []
    cards: list[tuple[int, int]] = []

    def add(spans: list[tuple[int, int]], start: int, end: int) -> None:
        if end > start and not any(taken[start:end]):
            taken[start:end] = b"\x01" * (end - start)
            spans.append((start, end))

    for rule, pattern in _MARKUP:
        if rule not in skipped:
            for match in pattern.finditer(text):
                add(markup, *match.span())

    index = _name_index(tuple(names))
    if index:
        limit = len(text)
        for start in range(limit - 1):
            candidates = index.get(text[start : start + 2])
            if not candidates or taken[start]:
                continue
            if start and _WORD.match(text[start - 1]) and _WORD.match(text[start]):
                continue
            for name in candidates:
                end = start + len(name)
                if not text.startswith(name, start):
                    continue
                if end < limit and _WORD.match(text[end - 1]) and _WORD.match(text[end]):
                    continue
                add(cards, start, end)
                break
    return sorted(markup), sorted(cards)


def protect(text: str, names: Iterable[str] = ()) -> Masked:
    """Заменить защищённые участки заглушками, которые Typograf считает словами."""
    markup, cards = protected_spans(text, names)
    spans = sorted(markup + cards)
    prefix, suffix = "Qzx", "xzQ"
    while prefix in text or suffix in text:
        prefix, suffix = prefix + "x", "x" + suffix
    if len(spans) >= 10**6:
        raise TypographyError("слишком много защищённых участков")
    parts: list[str] = []
    saved: list[str] = []
    position = 0
    for start, end in spans:
        parts.append(text[position:start])
        parts.append(f"{prefix}{len(saved):06d}{suffix}")
        saved.append(text[start:end])
        position = end
    parts.append(text[position:])
    return Masked("".join(parts), tuple(saved), prefix, suffix)


def signature(text: str, *, quotes: bool = False) -> list[str]:
    """Что обязано остаться прежним: символ в символ, пробелы любого вида — один пробел.

    Пробел может стать неразрывным, а дефис или среднее тире — длинным тире, но пробелы не
    появляются и не пропадают: число слов и символов в строке сохраняется. С `quotes=True`
    «ёлочки» и лапки приравниваются к прямым кавычкам.
    """
    text = _DASH_RUN.sub("-", text)
    if quotes:
        text = text.translate(_QUOTES)
    return [_HSPACE.sub(" ", line) for line in text.split("\n")]


def verify(original: str, result: str, *, quotes: bool = False) -> list[str]:
    """Расхождения, которых типограф вносить не вправе. Пусто — всё в порядке."""
    before, after = signature(original, quotes=quotes), signature(result, quotes=quotes)
    if len(before) != len(after):
        return [f"изменилось число строк: {len(before)} → {len(after)}"]
    problems = []
    for number, (was, became) in enumerate(zip(before, after, strict=True), 1):
        if was != became:
            problems.append(f"строка {number}: изменилось что-то кроме вида пробела и тире")
            if len(problems) == 5:
                break
    return problems


def run_node(text: str, enabled: tuple[str, ...]) -> tuple[str, str]:
    """Запустить Typograf через Node.js: (текст, версия библиотеки)."""
    node = shutil.which("node")
    if node is None:
        raise ToolUnavailable("Node.js не найден в PATH: типографика не запущена")
    if not RUNNER.exists():
        raise ToolUnavailable(f"нет {RUNNER}: Typograf не найден в сборке")
    payload = json.dumps({"text": text, "locale": ["ru", "en-US"], "enable": list(enabled)})
    try:
        done = subprocess.run(
            [node, str(RUNNER)],
            input=payload.encode("utf-8"),
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TypographyError(f"Typograf не ответил за {TIMEOUT_SECONDS} с") from error
    if done.returncode != 0:
        message = done.stderr.decode("utf-8", "replace").strip()
        raise TypographyError(message or f"Typograf завершился с кодом {done.returncode}")
    answer = json.loads(done.stdout.decode("utf-8"))
    return answer["text"], answer["version"]


def _count(text: str, chars: str) -> int:
    return sum(text.count(char) for char in chars)


def typograph(
    text: str,
    *,
    decisions: dict | None = None,
    names: Iterable[str] | None = None,
    runner: Runner = run_node,
) -> TypographyResult:
    """Расставить тире и неразрывные пробелы; текст — с переводами строк `\\n`."""
    decisions = rules.typography() if decisions is None else decisions
    enabled = enabled_rules(decisions)
    masked = protect(text, card_names() if names is None else names)
    produced, version = runner(masked.text, enabled)
    result = masked.restore(produced)
    quotes = "common/punctuation/quote" in enabled
    problems = verify(text, result, quotes=quotes)
    if problems:
        raise TypographyError("проверка не пройдена, файл не изменён: " + "; ".join(problems))
    changed = sum(
        was != became for was, became in zip(text.split("\n"), result.split("\n"), strict=True)
    )
    return TypographyResult(
        text=result,
        rules=enabled,
        engine_version=version,
        protected=len(masked.saved),
        lines_changed=changed,
        nbsp_added=_count(result, _NBSP_CHARS) - _count(text, _NBSP_CHARS),
        dashes_added=max(0, result.count("—") - text.count("—")),
    )


def read_document(path: Path) -> tuple[str, str, bool]:
    """Текст с `\\n`, исходный перевод строки и признак BOM."""
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    eol = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n"), eol, bom


def write_document(path: Path, text: str, eol: str = "\n", bom: bool = False) -> None:
    """Записать через временный файл: прерванная запись не оставит половину текста."""
    payload = (text.replace("\n", eol)).encode("utf-8")
    if bom:
        payload = b"\xef\xbb\xbf" + payload
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        if path.exists():
            shutil.copymode(path, temporary)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
