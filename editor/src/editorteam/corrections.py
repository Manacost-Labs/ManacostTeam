"""Контекстная память правок. Пример не становится глобальным запретом.

Одна функция applicable выбирает политику для prompt и postflight. Только
явные language_norm/author_global могут быть обязательными; локальные,
фактические и структурные примеры служат подсказками с сохранением контекста.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "corrections.yaml"
KINDS = ("term", "phrase", "structure", "fact")
SCOPES = ("language_norm", "author_global", "local", "fact", "structure")
OPERATIONS = ("replace", "insert", "delete")
MAX_WORDS = 6  # длиннее — это не замена, а переписанный абзац
WORD = re.compile(r"[А-Яа-яЁёA-Za-z'’-]+")


class CorrectionsError(ValueError):
    pass


@dataclass
class Correction:
    was: str
    became: str
    kind: str = "phrase"
    reason: str = ""
    context: str = ""
    date: str = ""
    source: str = ""
    author: str = ""
    game: str = ""
    genre: str = ""
    meaning: str = ""
    scope: str = "local"
    operation: str = "replace"
    model_proposal: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out = {"was": self.was, "became": self.became, "kind": self.kind}
        for key in (
            "reason",
            "context",
            "date",
            "source",
            "author",
            "game",
            "genre",
            "meaning",
            "scope",
            "operation",
            "model_proposal",
        ):
            value = getattr(self, key)
            if value:
                out[key] = value
        out.update(self.extra)
        return out


def path() -> Path:
    return Path(os.environ.get("EDITOR_CORRECTIONS", DEFAULT_PATH))


def load(file: Path | None = None) -> list[Correction]:
    p = file or path()
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = []
    for raw in data.get("corrections") or []:
        if not isinstance(raw, dict) or not (raw.get("was") or raw.get("became")):
            continue
        kind = raw.get("kind", "phrase")
        if kind not in KINDS:
            raise CorrectionsError(f"неизвестный kind «{kind}» у правки «{raw['was']}»")
        scope = raw.get("scope", "local")
        operation = raw.get("operation", "replace")
        if scope not in SCOPES or operation not in OPERATIONS:
            raise CorrectionsError("неизвестная область или операция правки")
        known = {
            "was",
            "became",
            "kind",
            "reason",
            "context",
            "date",
            "source",
            "author",
            "game",
            "genre",
            "meaning",
            "scope",
            "operation",
            "model_proposal",
        }
        out.append(
            Correction(
                was=str(raw.get("was", "")).strip(),
                became=str(raw.get("became", "")).strip(),
                kind=kind,
                reason=str(raw.get("reason", "") or ""),
                context=str(raw.get("context", "") or ""),
                date=str(raw.get("date", "") or ""),
                source=str(raw.get("source", "") or ""),
                author=str(raw.get("author", "") or ""),
                game=str(raw.get("game", "") or ""),
                genre=str(raw.get("genre", "") or ""),
                meaning=str(raw.get("meaning", "") or ""),
                scope=scope,
                operation=operation,
                model_proposal=str(raw.get("model_proposal", "") or ""),
                extra={k: v for k, v in raw.items() if k not in known},
            )
        )
    return out


def save(items: list[Correction], file: Path | None = None) -> Path:
    p = file or path()
    header = ""
    if p.exists():
        text = p.read_text(encoding="utf-8")
        header = text.split("corrections:")[0].rstrip("\n") + "\n"
    if not header.strip():
        header = "version: 1\n"
    body = yaml.safe_dump(
        {"corrections": [c.to_dict() for c in items]},
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
    p.write_text(header + body, encoding="utf-8")
    return p


def add(
    was: str,
    became: str,
    *,
    kind: str = "phrase",
    reason: str = "",
    context: str = "",
    source: str = "",
    author: str = "",
    game: str = "",
    genre: str = "",
    meaning: str = "",
    scope: str = "local",
    operation: str = "replace",
    model_proposal: str = "",
    file: Path | None = None,
) -> Correction:
    if kind not in KINDS:
        raise CorrectionsError(f"kind должен быть одним из {', '.join(KINDS)}")
    if scope not in SCOPES or operation not in OPERATIONS:
        raise CorrectionsError("неизвестная область или операция правки")
    if scope == "author_global" and not author.strip():
        raise CorrectionsError("author_global требует явного автора")
    was, became = was.strip(), became.strip()
    if was == became or (operation == "replace" and (not was or not became)):
        raise CorrectionsError("для замены нужны разные «было» и «стало»")
    if (operation == "insert" and (was or not became)) or (
        operation == "delete" and (not was or became)
    ):
        raise CorrectionsError("вставка требует пустое «было», удаление — пустое «стало»")
    items = load(file)
    for item in items:
        if (
            item.was.lower() == was.lower()
            and item.became.lower() == became.lower()
            and (item.author, item.game, item.genre, item.meaning, item.scope, item.context)
            == (author, game, genre, meaning, scope, context)
        ):
            return item
    item = Correction(
        was=was,
        became=became,
        kind=kind,
        reason=reason,
        context=context,
        date=date.today().isoformat(),
        source=source,
        author=author,
        game=game,
        genre=genre,
        meaning=meaning,
        scope=scope,
        operation=operation,
        model_proposal=model_proposal,
    )
    items.append(item)
    save(items, file)
    return item


def proposals(before: str, after: str) -> list[dict]:
    """Содержательные вставки, удаления и замены как локальные примеры.

    Длинные изменения сохраняются как structure, а не обобщаются в запрет.
    """
    import difflib

    wa, wb = before.split(), after.split()
    sm = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        was, became = " ".join(wa[i1:i2]), " ".join(wb[j1:j2])
        if not (WORD.search(was) or WORD.search(became)):
            continue
        clean = lambda s: s.strip(" .,;:!?«»\"'()—–-")  # noqa: E731
        was, became = clean(was), clean(became)
        if was.lower() == became.lower():
            continue
        # Punctuation-only sides disappear during cleanup. Classify the cleaned
        # example so saving a substantive insertion/deletion remains valid.
        operation = "insert" if not was else "delete" if not became else "replace"
        left = " ".join(wa[max(0, i1 - 3) : i1])
        right = " ".join(wa[i2 : i2 + 3])
        kind = "term" if len(was.split()) == 1 and len(became.split()) == 1 else "phrase"
        if operation != "replace" or max(i2 - i1, j2 - j1) > MAX_WORDS:
            kind = "structure"
        out.append(
            {
                "was": was,
                "became": became,
                "kind": kind,
                "context": f"{left} [{was}] {right}".strip(),
                "operation": operation,
                "scope": "local",
            }
        )
    seen, unique = set(), []
    for item in out:
        key = (item["was"].lower(), item["became"].lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def applicable(
    *, author: str = "", game: str = "", genre: str = "", meaning: str = "", text: str = ""
) -> list[Correction]:
    """Неизвестная квалификация не означает совпадение; legacy остаётся advisory."""
    context = {"author": author, "game": game, "genre": genre, "meaning": meaning}
    out = []
    for c in load():
        if any(
            str(getattr(c, key)).strip().casefold() != str(value).strip().casefold()
            for key, value in context.items()
            if getattr(c, key)
        ):
            continue
        if c.scope == "author_global" and not c.author:
            continue
        # Local context is retained for the model, never silently promoted to a ban.
        # Qualifiers select the article; free-text context explains the intended sense.
        out.append(c)
    return out


def _required(c: Correction) -> bool:
    return (
        c.scope in ("language_norm", "author_global")
        and c.kind in ("term", "phrase")
        and c.operation == "replace"
        and bool(c.was and c.became)
    )


def for_prompt(limit: int = 40, **context) -> list[dict]:
    """Лимит сокращает только примеры: скрывать обязательную норму от модели нельзя."""
    items = applicable(**context)
    required = [c for c in items if _required(c)]
    optional_limit = max(0, limit - len(required))
    optional = [c for c in items if not _required(c)]
    selected = required + (optional[-optional_limit:] if optional_limit else [])
    return [
        {
            **{
                key: str(getattr(c, key))
                for key in (
                    "was",
                    "became",
                    "kind",
                    "reason",
                    "context",
                    "date",
                    "source",
                    "author",
                    "game",
                    "genre",
                    "meaning",
                    "scope",
                    "operation",
                    "model_proposal",
                )
            },
            "enforcement": "required" if _required(c) else "advisory",
        }
        for c in selected
    ]


def for_gate(**context) -> list[dict]:
    """Только явно обязательные применимые замены для затвора."""
    return [
        {
            "id": f"correction:{c.was}",
            "subject": c.was,
            "preferred": c.became,
            "pattern": _pattern(c.was) if len(c.was.split()) > 1 else None,
            "case_sensitive": False,
        }
        for c in applicable(**context)
        if _required(c)
    ]


def _pattern(phrase: str) -> str:
    """Образец фразы с падежами: «яичная сборка» ловит «яичные сборки»."""
    parts = []
    for word in phrase.split():
        w = re.escape(word)
        parts.append(w[:-2] + r"\w*" if len(word) > 4 else w)
    return r"\b" + r"\s+".join(parts)
