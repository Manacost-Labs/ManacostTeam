"""Вызовы внутренних сервисов: таймауты, лимит ответа и понятные ошибки."""

from __future__ import annotations

import json
from typing import Any

import httpx

MAX_UPSTREAM_BYTES = 4 * 1024 * 1024


class UpstreamError(Exception):
    def __init__(self, status: int, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


def error_text(body: Any) -> str | None:
    """Достать сообщение об ошибке из типичных форм ответа сервисов."""
    if not isinstance(body, dict):
        return None
    for key in ("error", "detail", "message"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = error_text(value)
            if nested:
                return nested
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict) and isinstance(first.get("msg"), str):
                return first["msg"]
    return None


async def post_json(
    client: httpx.AsyncClient,
    label: str,
    url: str,
    payload: dict,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    """POST JSON; вернуть (статус, разобранное тело). Сетевые сбои — UpstreamError."""
    try:
        async with client.stream(
            "POST",
            url,
            content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json", **(headers or {})},
            timeout=timeout,
        ) as response:
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_UPSTREAM_BYTES:
                    raise UpstreamError(502, f"{label}: ответ сервиса слишком большой")
                chunks.append(chunk)
            status = response.status_code
    except httpx.TimeoutException as exc:
        raise UpstreamError(504, f"{label}: сервис не ответил за {int(timeout)} с") from exc
    except httpx.HTTPError as exc:
        raise UpstreamError(502, f"{label}: сервис недоступен") from exc
    raw = b"".join(chunks)
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = None
    if body is None and 200 <= status < 300:
        raise UpstreamError(502, f"{label}: сервис вернул не JSON")
    return status, body


def ensure_ok(label: str, status: int, body: Any) -> dict:
    """Превратить ошибочный ответ апстрима в UpstreamError с русским заголовком."""
    if 200 <= status < 300 and isinstance(body, dict):
        return body
    if 200 <= status < 300:
        raise UpstreamError(502, f"{label}: неожиданная форма ответа")
    reason = error_text(body)
    if status in (400, 413, 415, 422):
        out = 400 if status != 413 else 413
        raise UpstreamError(out, f"{label}: запрос отклонён", reason)
    if status in (401, 403):
        raise UpstreamError(502, f"{label}: сервис отказал в доступе (проверьте токен)", reason)
    if status == 504:
        raise UpstreamError(504, f"{label}: сервис не уложился во время", reason)
    raise UpstreamError(502, f"{label}: ошибка сервиса ({status})", reason)
