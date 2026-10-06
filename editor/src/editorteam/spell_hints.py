"""Подсказки об опечатках от SAGE: только подсказки, текст не меняется.

SAGE (ai-forever/sage, MIT; модели sage-fredt5-distilled-95m, sage-fredt5-large и
sage-m2m100-1.2B тоже MIT) — нейросетевой корректор русской орфографии. Он дополняет
словарную проверку (Hunspell в Go-сервисе), но так же ничего не исправляет: находка
уходит редактору как `review`, решение за ним.

Модель обучена на искусственных ошибках в Википедии и расшифровках видео, поэтому
сленг игры, склонённые названия карт и имена она «исправляет» неверно. Против этого
стоят фильтры, а не доверие к модели. Подсказка остаётся, только если:

* слово заменено на близкое по написанию (правка опечатки, а не перефразирование);
* исходного слова нет в словаре pymorphy3, а подсказка в нём есть;
* слова нет среди игровых терминов `config/dictionaries/` и терминологии издания,
  среди слов названий карт и в авторском корпусе `гайды/` (два употребления и больше);
* это не имя с заглавной буквы в середине предложения и не точное название карты;
* различие не сводится к регистру или букве «ё» (по СТИЛЬ.md «ё» не ставится).

Подсказка, где исходное слово словарю известно (модель заменила одно слово другим),
по умолчанию не показывается: это правка смысла, а не опечатки. Разметка, код, ссылки
и шорткоды модели не передаются.

Тяжёлые зависимости (torch, transformers) не обязательны: без них команда сообщает,
что SAGE не запущен. Веса не скачиваются без `--download` (95-миллионная модель — 0,38 ГБ).
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from editorteam import games, rules, typography
from editorteam.finding import Finding, Report

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "гайды"
DEFAULT_MODEL = "ai-forever/sage-fredt5-distilled-95m"
MAX_SENTENCE_CHARS = 600
MIN_CORPUS_COUNT = 2

_WORD = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*")
_SENTENCE = re.compile(r"[^\s][^\n]*?(?:[.!?…]+(?=\s|\Z)|(?=\n)|\Z)")


class ProviderUnavailable(RuntimeError):
    """Источник подсказок не запущен: нет библиотек или модели."""


class Provider(Protocol):
    name: str

    def correct(self, sentences: list[str]) -> list[str]:
        """Те же предложения с исправленными опечатками."""


@dataclass(frozen=True)
class Candidate:
    start: int
    end: int
    original: str
    suggestion: str
    first: bool  # слово открывает предложение


class SageProvider:
    """SAGE через transformers; библиотеки и модель подгружаются при первом вызове."""

    name = "sage"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        device: str | None = None,
        batch_size: int = 8,
        allow_download: bool = False,
    ):
        self.model_id = model
        self.device = device
        self.batch_size = batch_size
        self.allow_download = allow_download
        self._loaded = None

    def _load(self):
        if self._loaded is not None:
            return self._loaded
        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ImportError as error:
            raise ProviderUnavailable(
                "SAGE не установлен: pip install -r requirements-sage.txt (torch, transformers)"
            ) from error
        local = not self.allow_download
        try:
            tokenizer = AutoTokenizer.from_pretrained(self.model_id, local_files_only=local)
            model = AutoModelForSeq2SeqLM.from_pretrained(self.model_id, local_files_only=local)
        except OSError as error:
            raise ProviderUnavailable(
                f"модель {self.model_id} не скачана; --download разрешает загрузку с Hugging Face "
                "(sage-fredt5-distilled-95m — 0,38 ГБ)"
            ) from error
        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._loaded = (torch, tokenizer, model.to(device).eval(), device)
        return self._loaded

    def correct(self, sentences: list[str]) -> list[str]:
        torch, tokenizer, model, device = self._load()
        corrected: list[str] = []
        for start in range(0, len(sentences), self.batch_size):
            batch = sentences[start : start + self.batch_size]
            inputs = tokenizer(
                batch, max_length=None, padding="longest", truncation=False, return_tensors="pt"
            ).to(device)
            with torch.no_grad():
                generated = model.generate(
                    **inputs, max_length=int(inputs["input_ids"].size(1) * 1.5)
                )
            corrected.extend(tokenizer.batch_decode(generated, skip_special_tokens=True))
        return corrected


def _fold(word: str) -> str:
    return word.lower().replace("ё", "е")


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b))
            )
        previous = current
    return previous[-1]


def _blank(text: str, spans: Iterable[tuple[int, int]]) -> str:
    """Заменить участки пробелами, сохранив длину и переводы строк: смещения не плывут."""
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


def _usable(sentence: str) -> bool:
    words = _WORD.findall(sentence)
    return sum(len(word) >= 3 for word in words) >= 2 and len(sentence) <= MAX_SENTENCE_CHARS


def find_candidates(masked: str, provider: Provider) -> tuple[list[Candidate], dict[str, int]]:
    """Слова, которые модель заменила один-к-одному, — до любых фильтров."""
    sentences = [(match.start(), match.group()) for match in _SENTENCE.finditer(masked)]
    chosen = [(start, sentence) for start, sentence in sentences if _usable(sentence)]
    stats = {"sentences": len(sentences), "checked": len(chosen)}
    # смещения берутся из исходного предложения, а слова сопоставляются по порядку,
    # поэтому модели можно отдать предложение без пробелов на месте погашенной разметки
    asked = [" ".join(sentence.split()) for _, sentence in chosen]
    corrected = provider.correct(asked) if chosen else []
    if len(corrected) != len(chosen):
        raise ProviderUnavailable("источник подсказок вернул другое число предложений")
    found: list[Candidate] = []
    for (offset, sentence), fixed in zip(chosen, corrected, strict=True):
        was = list(_WORD.finditer(sentence))
        now = [match.group() for match in _WORD.finditer(fixed)]
        matcher = difflib.SequenceMatcher(None, [m.group() for m in was], now, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "replace" or i2 - i1 != j2 - j1:
                continue
            for k in range(i2 - i1):
                token = was[i1 + k]
                found.append(
                    Candidate(
                        offset + token.start(),
                        offset + token.end(),
                        token.group(),
                        now[j1 + k],
                        first=i1 + k == 0,
                    )
                )
    return found, stats


@lru_cache(maxsize=1)
def allowlist() -> frozenset[str]:
    """Слова, которые издание оставляет как есть: игровые термины, терминология, защищённые."""
    words: set[str] = set()
    folder = rules.CONFIG_DIR / "dictionaries"
    for path in sorted(folder.glob("*.txt")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                words.update(_fold(word) for word in _WORD.findall(line))
    for rule in rules.terminology():
        for term in (rule.slang, rule.word, rule.preferred, rule.alternative, *rule.alias_names()):
            if term:
                words.update(_fold(word) for word in _WORD.findall(term))
    for term in games.load().protected:
        words.update(_fold(word) for word in _WORD.findall(term))
    return frozenset(words)


@lru_cache(maxsize=4)
def corpus_vocabulary(folder: str = str(CORPUS)) -> Counter:
    """Слова авторского корпуса: так автор пишет, опечаткой это быть не может."""
    counts: Counter = Counter()
    for path in sorted(Path(folder).glob("*.md")):
        counts.update(_fold(word) for word in _WORD.findall(path.read_text(encoding="utf-8")))
    return counts


def card_words(names: Iterable[str]) -> frozenset[str]:
    return frozenset(_fold(word) for name in names for word in _WORD.findall(name))


def _known(word: str, known_word: Callable[[str], bool]) -> bool:
    return all(known_word(part) for part in _fold(word).split("-"))


def reject_reason(
    candidate: Candidate,
    *,
    known_word: Callable[[str], bool],
    allow: frozenset[str],
    vocabulary: Counter,
    cards: frozenset[str],
    include_model_only: bool,
) -> str | None:
    """Почему подсказку не показываем; None — оставить."""
    original, suggestion = candidate.original, candidate.suggestion
    if _fold(original) == _fold(suggestion):
        return "case_or_yo_only"
    if edit_distance(_fold(original), _fold(suggestion)) > max(2, len(original) // 3):
        return "rewrite_not_typo"
    folded = _fold(original)
    if folded in allow:
        return "game_or_editorial_term"
    if folded in cards:
        return "card_name_word"
    if vocabulary[folded] >= MIN_CORPUS_COUNT:
        return "author_vocabulary"
    if original[0].isupper() and not candidate.first:
        return "proper_name"
    if _known(original, known_word):
        return None if include_model_only else "known_word"
    if not _known(suggestion, known_word):
        return "suggestion_unknown"
    return None


def line_column(text: str, offset: int) -> tuple[int, int]:
    return text.count("\n", 0, offset) + 1, offset - (text.rfind("\n", 0, offset) + 1) + 1


def analyze(
    text: str,
    provider: Provider,
    *,
    known_word: Callable[[str], bool],
    names: Iterable[str] = (),
    document: str = "<text>",
    include_model_only: bool = False,
    vocabulary: Counter | None = None,
    allow: frozenset[str] | None = None,
) -> Report:
    """Подсказки об опечатках в виде отчёта; текст не меняется."""
    names = tuple(names)
    markup, cards = typography.protected_spans(text, names, skip=("heading",))
    candidates, stats = find_candidates(_blank(text, markup), provider)
    allow = allowlist() if allow is None else allow
    vocabulary = corpus_vocabulary() if vocabulary is None else vocabulary
    words = card_words(names)
    report = Report(document=document, profile="spelling-hints")
    dropped: Counter = Counter()
    for candidate in candidates:
        if any(candidate.start < end and candidate.end > start for start, end in cards):
            dropped["card_name"] += 1
            continue
        reason = reject_reason(
            candidate,
            known_word=known_word,
            allow=allow,
            vocabulary=vocabulary,
            cards=words,
            include_model_only=include_model_only,
        )
        if reason:
            dropped[reason] += 1
            continue
        confirmed = not _known(candidate.original, known_word)
        line, column = line_column(text, candidate.start)
        report.add(
            Finding(
                id="spelling.sage",
                analyzer=provider.name,
                category="spelling",
                severity="review" if confirmed else "info",
                confidence=0.8 if confirmed else 0.35,
                message="возможная опечатка: слова нет в словаре, SAGE предлагает близкое"
                if confirmed
                else "SAGE предлагает другое слово: словарю исходное известно, это не опечатка",
                evidence=candidate.original,
                suggestion=candidate.suggestion,
                line=line,
                column=column,
                start=candidate.start,
                end=candidate.end,
                meta={"dictionary": "unknown" if confirmed else "known"},
            )
        )
    report.metrics = {
        **stats,
        "model_replacements": len(candidates),
        "hints": len(report.findings),
        "dropped": dict(sorted(dropped.items())),
    }
    report.notes.append(
        f"{provider.name}: только подсказки, текст не менялся; решает редактор. "
        "Слова из словарей игры, названия карт и авторский словарь не предлагаются."
    )
    return report


def evaluate(
    paths: Iterable[Path],
    provider: Provider,
    *,
    known_word: Callable[[str], bool],
    names: Iterable[str] = (),
    include_model_only: bool = False,
) -> dict:
    """Сколько подсказок модель выдаёт на заведомо вычитанных текстах — это ложные срабатывания."""
    names = tuple(names)
    words = hints = 0
    pairs: Counter = Counter()
    dropped: Counter = Counter()
    files = 0
    total = corpus_vocabulary()
    for path in paths:
        text = path.read_text(encoding="utf-8")
        # словарь автора без самого проверяемого файла: иначе каждое слово «подтверждает» себя
        own = Counter(_fold(word) for word in _WORD.findall(text))
        report = analyze(
            text,
            provider,
            known_word=known_word,
            names=names,
            document=str(path),
            include_model_only=include_model_only,
            vocabulary=total - own,
        )
        files += 1
        words += len(text.split())
        hints += len(report.findings)
        dropped.update(report.metrics["dropped"])
        pairs.update(f"{f.evidence} → {f.suggestion}" for f in report.findings)
    return {
        "files": files,
        "words": words,
        "hints": hints,
        "hints_per_1000_words": round(1000 * hints / words, 2) if words else 0.0,
        "dropped": dict(sorted(dropped.items())),
        "top_pairs": pairs.most_common(30),
    }
