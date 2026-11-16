"""Подписанные (HMAC-SHA256) значения cookie с назначением и сроком жизни."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Signer:
    def __init__(self, secret: bytes) -> None:
        # Отдельный ключ, производный от секрета: сам секрет нигде не используется напрямую.
        self._key = hmac.new(secret, b"manacost-studio/cookie-v1", hashlib.sha256).digest()

    def _mac(self, purpose: str, payload: str) -> str:
        message = f"{purpose}.{payload}".encode("ascii")
        return _b64(hmac.new(self._key, message, hashlib.sha256).digest())

    def dumps(self, purpose: str, data: dict, ttl: int, *, now: float | None = None) -> str:
        body = dict(data)
        body["exp"] = int((time.time() if now is None else now) + ttl)
        payload = _b64(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode())
        return f"{payload}.{self._mac(purpose, payload)}"

    def loads(self, purpose: str, value: str | None, *, now: float | None = None) -> dict | None:
        if not value or value.count(".") != 1:
            return None
        payload, mac = value.split(".")
        try:
            if not hmac.compare_digest(mac, self._mac(purpose, payload)):
                return None
            data = json.loads(_unb64(payload))
        except (ValueError, UnicodeError):
            return None
        if not isinstance(data, dict) or type(data.get("exp")) is not int:
            return None
        if data["exp"] <= (time.time() if now is None else now):
            return None
        return data
