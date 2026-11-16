"""Один запрос к OpenAI-совместимому chat/completions адаптеру."""

from __future__ import annotations

import httpx

from .config import Settings
from .upstream import UpstreamError, ensure_ok, post_json

LABEL = "Языковая модель"


async def complete(
    http: httpx.AsyncClient, settings: Settings, system: str, user: str
) -> tuple[str, str]:
    """Вернуть (текст ответа, имя модели). `temperature` не отправляется сознательно."""
    payload: dict = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    }
    if settings.llm_model:
        payload["model"] = settings.llm_model
    status, body = await post_json(
        http, LABEL, settings.llm_url, payload, timeout=settings.timeouts["llm"]
    )
    data = ensure_ok(LABEL, status, body)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise UpstreamError(502, f"{LABEL}: ответ без choices[0].message.content") from exc
    if isinstance(content, list):  # контент частями: [{type: text, text: ...}]
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    if not isinstance(content, str) or not content.strip():
        raise UpstreamError(502, f"{LABEL}: пустой ответ")
    return content.strip(), str(data.get("model") or settings.llm_model or "")
