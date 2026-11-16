from __future__ import annotations

import pytest

from app.config import ConfigError, Settings


def test_from_env_reads_secret_files(tmp_path):
    (tmp_path / "client").write_text("client-secret\n")
    (tmp_path / "session").write_text("k" * 40)
    (tmp_path / "gw").write_text("gw-token\n")
    settings = Settings.from_env(
        {
            "OIDC_ISSUER": "https://id.hearthpulse.net/",
            "OIDC_CLIENT_SECRET_FILE": str(tmp_path / "client"),
            "STUDIO_SESSION_SECRET_FILE": str(tmp_path / "session"),
            "SOURCE_GATEWAY_TOKEN_FILE": str(tmp_path / "gw"),
            "STUDIO_ALLOWED_SUBS": " a , b ,",
        }
    )
    assert settings.public_url == "https://studio.hearthpulse.net"
    assert settings.oidc_issuer == "https://id.hearthpulse.net"
    assert settings.oidc_client_id == "manacost-studio"
    assert settings.oidc_client_secret == b"client-secret"
    assert settings.source_gateway_token == b"gw-token"
    assert settings.allowed_subs == frozenset({"a", "b"})
    assert settings.redirect_uri == "https://studio.hearthpulse.net/auth/callback"
    assert settings.llm_model == "" and settings.card_catalog_file == ""


def test_from_env_rejects_short_session_secret_and_empty_allowlist(tmp_path):
    (tmp_path / "client").write_text("c")
    (tmp_path / "short").write_text("short")
    base = {"OIDC_ISSUER": "https://id.test", "OIDC_CLIENT_SECRET_FILE": str(tmp_path / "client")}
    with pytest.raises(ConfigError):
        Settings.from_env({**base, "STUDIO_SESSION_SECRET_FILE": str(tmp_path / "short"), "STUDIO_ALLOWED_SUBS": "a"})
    (tmp_path / "long").write_text("k" * 40)
    with pytest.raises(ConfigError):
        Settings.from_env({**base, "STUDIO_SESSION_SECRET_FILE": str(tmp_path / "long")})
