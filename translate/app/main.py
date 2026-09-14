"""HTTP service that prepares game materials and validates Codex translations."""

from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .core import (
    STYLE_PRESETS,
    append_translation_memory,
    changed_segment_ids,
    find_review_candidates,
    load_glossary,
    load_translation_memory,
    protect_terms,
    qa_translation,
    segment_markdown,
)


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
MAX_SOURCE_CHARS = int(os.getenv("MAX_SOURCE_CHARS", "120000"))
ALLOWED_DOMAINS = {
    domain.strip().lower()
    for domain in os.getenv("ALLOWED_DOMAINS", "").split(",")
    if domain.strip()
}


class PrepareRequest(BaseModel):
    text: str | None = Field(default=None, max_length=MAX_SOURCE_CHARS)
    url: str | None = Field(default=None, max_length=2048)
    title: str | None = Field(default=None, max_length=500)
    game: str = Field(default="wow", pattern="^(wow|hearthstone)$")
    patch: str | None = Field(default=None, max_length=80)
    class_name: str | None = Field(default=None, max_length=100)
    spec: str | None = Field(default=None, max_length=100)
    style: str = Field(default="manacost")
    previous_source: str | None = Field(default=None, max_length=MAX_SOURCE_CHARS)


class QaRequest(BaseModel):
    protected_source: str = Field(max_length=MAX_SOURCE_CHARS)
    translated_markdown: str = Field(max_length=MAX_SOURCE_CHARS)
    terms: dict[str, str] = Field(default_factory=dict)


class MemoryRequest(BaseModel):
    source_en: str = Field(min_length=1, max_length=10000)
    target_ru: str = Field(min_length=1, max_length=10000)
    context: str = Field(default="", max_length=500)


app = FastAPI(title="TranslateTeam Codex Preparer", version="1.0.0")


def glossary() -> dict[str, str]:
    return load_glossary(DATA_DIR.glob("*-names.en-ru.tsv"))


def memory_path() -> Path:
    return DATA_DIR / "approved-segments.tsv"


def public_http_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(422, "Нужна абсолютная ссылка http:// или https://.")
    hostname = parsed.hostname.lower()
    if ALLOWED_DOMAINS and hostname not in ALLOWED_DOMAINS:
        raise HTTPException(422, "Этот домен не входит в ALLOWED_DOMAINS.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None)}
    except OSError as error:
        raise HTTPException(422, f"Не удалось разрешить домен: {error}") from error
    if any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise HTTPException(422, "Ссылки на локальные и приватные адреса запрещены.")
    return value


async def fetch_html(url: str) -> tuple[str, str]:
    current_url = public_http_url(url)
    headers = {
        "User-Agent": "TranslateTeam/1.0 (+local Codex editorial preparation)",
        "Accept": "text/html,application/xhtml+xml",
    }
    async with httpx.AsyncClient(timeout=30, follow_redirects=False, headers=headers) as client:
        for _ in range(5):
            response = await client.get(current_url)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise HTTPException(502, "Сайт вернул перенаправление без адреса.")
                current_url = public_http_url(urljoin(current_url, location))
                continue
            response.raise_for_status()
            if "html" not in response.headers.get("content-type", "").lower():
                raise HTTPException(422, "По ссылке должен быть HTML-материал.")
            if len(response.content) > 5_000_000:
                raise HTTPException(413, "Страница слишком велика: максимум 5 МБ HTML.")
            return response.text, current_url
    raise HTTPException(502, "Слишком много перенаправлений.")


def extract_markdown(html: str) -> str:
    extracted = trafilatura.extract(
        html,
        output_format="markdown",
        include_links=True,
        include_images=False,
        include_comments=False,
        favor_precision=True,
    )
    if not extracted or len(extracted.strip()) < 80:
        raise HTTPException(
            422,
            "Не удалось надёжно извлечь статью. Вставьте текст вручную; блокировки сайта не обходятся.",
        )
    return extracted.strip()


def build_codex_instruction(context: dict[str, str | None], style: str) -> str:
    return (
        "Переведи защищённый английский Markdown на русский. "
        f"Режим: {STYLE_PRESETS[style]} "
        f"Контекст: игра={context['game']}; патч={context['patch'] or 'не указан'}; "
        f"класс={context['class_name'] or 'не указан'}; специализация={context['spec'] or 'не указана'}. "
        "Сохрани Markdown, ссылки, числа, таблицы, код и все [[[TERM_n]]] без изменений. "
        "Не добавляй фактов. Затем проведи второй проход: проверь числа, ссылки, термины и пропуски."
    )


def prepare_material(text: str, request: PrepareRequest) -> dict[str, object]:
    if len(text) > MAX_SOURCE_CHARS:
        raise HTTPException(413, f"Материал длиннее лимита {MAX_SOURCE_CHARS} символов.")
    if request.style not in STYLE_PRESETS:
        raise HTTPException(422, f"Неизвестный стиль. Доступны: {', '.join(STYLE_PRESETS)}")
    terms = glossary()
    protected, replacements = protect_terms(text, terms)
    previous_protected, _ = protect_terms(request.previous_source or "", terms)
    memory = load_translation_memory(memory_path())
    segments = segment_markdown(protected)
    context = {
        "title": request.title,
        "game": request.game,
        "patch": request.patch,
        "class_name": request.class_name,
        "spec": request.spec,
    }
    return {
        "instruction_for_codex": build_codex_instruction(context, request.style),
        "context": context,
        "protected_markdown": protected,
        "terms": replacements,
        "review_candidates": find_review_candidates(text, terms),
        "segments": [
            {"id": segment.id, "text": segment.text, "memory_match": memory.get(segment.text)}
            for segment in segments
        ],
        "changed_segment_ids": changed_segment_ids(previous_protected, protected),
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(APP_DIR / "static" / "index.html")


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "translation_engine": "Codex chat",
        "style_presets": sorted(STYLE_PRESETS),
        "glossary_pairs": len(glossary()),
        "memory_pairs": len(load_translation_memory(memory_path())),
    }


@app.post("/prepare")
async def prepare(request: PrepareRequest) -> dict[str, object]:
    if bool(request.text and request.text.strip()) == bool(request.url and request.url.strip()):
        raise HTTPException(422, "Передайте ровно один источник: text или url.")
    if request.url:
        html, final_url = await fetch_html(request.url)
        result = prepare_material(extract_markdown(html), request)
        result["source_url"] = final_url
        return result
    return prepare_material(request.text or "", request)


@app.post("/qa")
async def qa(request: QaRequest) -> dict[str, object]:
    return qa_translation(request.protected_source, request.translated_markdown, request.terms)


@app.post("/memory/approve")
async def approve_memory(request: MemoryRequest) -> dict[str, object]:
    append_translation_memory(memory_path(), request.source_en, request.target_ru, request.context)
    return {"status": "approved", "memory_pairs": len(load_translation_memory(memory_path()))}
