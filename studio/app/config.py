"""Настройки только из окружения; секреты читаются из файлов `*_FILE`."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


class ConfigError(RuntimeError):
    """Сервис нельзя запустить с такими настройками."""


def _read_secret(path: str | None, name: str, *, minimum: int = 1) -> bytes:
    if not path:
        raise ConfigError(f"не задана переменная {name}")
    try:
        value = Path(path).read_bytes().strip()
    except OSError as exc:
        raise ConfigError(f"{name}: не удалось прочитать файл секрета") from exc
    if len(value) < minimum:
        raise ConfigError(f"{name}: секрет короче {minimum} байт")
    return value


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ConfigError("STUDIO_PUBLIC_URL должен быть абсолютным http(s) адресом")
    return f"{parts.scheme}://{parts.netloc}".lower()


@dataclass(frozen=True)
class Settings:
    public_url: str
    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: bytes
    session_secret: bytes
    allowed_subs: frozenset[str]
    editor_gateway_url: str = "http://gateway:8080"
    analyzer_url: str = "http://analyzer:8731"
    translator_url: str = "http://translator:8000"
    source_gateway_url: str = "http://research:8777"
    source_gateway_token: bytes = b""
    llm_url: str = "http://adapter:8790/v1/chat/completions"
    llm_model: str = ""
    card_catalog_file: str = ""
    session_ttl: int = 12 * 3600
    max_body_bytes: int = 200 * 1024
    timeouts: dict[str, float] = field(
        default_factory=lambda: {
            "analyzer": 60.0,
            "editor": 150.0,
            "translator": 60.0,
            "sources": 45.0,
            "llm": 180.0,
            "oidc": 15.0,
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_url", self.public_url.rstrip("/"))
        object.__setattr__(self, "oidc_issuer", self.oidc_issuer.rstrip("/"))
        origin_of(self.public_url)
        if not self.oidc_issuer.startswith(("https://", "http://")):
            raise ConfigError("OIDC_ISSUER должен быть абсолютным адресом")
        if len(self.session_secret) < 32:
            raise ConfigError("STUDIO_SESSION_SECRET_FILE: нужен секрет не короче 32 байт")
        if not self.allowed_subs:
            raise ConfigError("STUDIO_ALLOWED_SUBS пуст: никто не сможет войти")

    @property
    def public_origin(self) -> str:
        return origin_of(self.public_url)

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def redirect_uri(self) -> str:
        return self.public_url + "/auth/callback"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)

        def url(name: str, default: str) -> str:
            return (env.get(name) or default).strip().rstrip("/")

        token_file = env.get("SOURCE_GATEWAY_TOKEN_FILE")
        return cls(
            public_url=url("STUDIO_PUBLIC_URL", "https://studio.hearthpulse.net"),
            oidc_issuer=(env.get("OIDC_ISSUER") or "").strip()
            or _missing("OIDC_ISSUER"),
            oidc_client_id=(env.get("OIDC_CLIENT_ID") or "manacost-studio").strip(),
            oidc_client_secret=_read_secret(
                env.get("OIDC_CLIENT_SECRET_FILE"), "OIDC_CLIENT_SECRET_FILE"
            ),
            session_secret=_read_secret(
                env.get("STUDIO_SESSION_SECRET_FILE"),
                "STUDIO_SESSION_SECRET_FILE",
                minimum=32,
            ),
            allowed_subs=frozenset(
                item.strip()
                for item in (env.get("STUDIO_ALLOWED_SUBS") or "").split(",")
                if item.strip()
            ),
            editor_gateway_url=url("EDITOR_GATEWAY_URL", "http://gateway:8080"),
            analyzer_url=url("ANALYZER_URL", "http://analyzer:8731"),
            translator_url=url("TRANSLATOR_URL", "http://translator:8000"),
            source_gateway_url=url("SOURCE_GATEWAY_URL", "http://research:8777"),
            source_gateway_token=_read_secret(token_file, "SOURCE_GATEWAY_TOKEN_FILE")
            if token_file
            else b"",
            llm_url=(env.get("LLM_URL") or "http://adapter:8790/v1/chat/completions").strip(),
            llm_model=(env.get("LLM_MODEL") or "").strip(),
            card_catalog_file=(env.get("CARD_CATALOG_FILE") or "").strip(),
        )


def _missing(name: str) -> str:
    raise ConfigError(f"не задана переменная {name}")
