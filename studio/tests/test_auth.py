from __future__ import annotations

import time

from cryptography.hazmat.primitives.asymmetric import rsa

from app.signing import Signer
from conftest import ORIGIN, OWNER, PUBLIC, login, start_login


def test_health_is_public_and_offline(client, world):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert world.calls == []


def test_login_redirect_uses_pkce_s256_and_short_cookie(client):
    params = start_login(client)
    assert params["response_type"] == "code"
    assert params["client_id"] == "manacost-studio"
    assert params["redirect_uri"] == PUBLIC + "/auth/callback"
    assert params["scope"] == "openid profile"
    assert params["code_challenge_method"] == "S256"
    assert len(params["code_challenge"]) == 43 and params["state"] and params["nonce"]
    cookie = next(c for c in client.cookies.jar if c.name == "studio_auth")
    assert cookie.path == "/auth" and cookie.secure


def test_login_flow_creates_owner_session(client, world):
    response = login(client, world)
    assert response.status_code == 303 and response.headers["location"] == "/"
    set_cookie = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in set_cookie if c.startswith("studio_session="))
    lowered = session_cookie.lower()
    assert "httponly" in lowered and "secure" in lowered and "samesite=lax" in lowered
    assert "max-age=43200" in lowered
    token_call = world.calls_to("/token")[0]
    assert token_call["headers"]["authorization"].startswith("Basic ")
    assert "client_secret" not in token_call["body"]  # секрет только в Basic

    page = client.get("/")
    assert page.status_code == 200 and "Manacost Studio" in page.text
    info = client.get("/api/session").json()
    assert info["sub"] == OWNER and info["name"] == "Владелец"
    assert info["catalog_available"] is True


def test_foreign_sub_gets_owner_only_page(client, world):
    world.sub = "stranger"
    response = login(client, world)
    assert response.status_code == 403
    assert "Доступ только владельцу" in response.text
    assert not any(c.name == "studio_session" for c in client.cookies.jar)
    assert client.get("/api/session").status_code == 401


def test_state_mismatch_is_rejected(client, world):
    params = start_login(client)
    world.pending["c"] = {"challenge": params["code_challenge"], "nonce": params["nonce"]}
    response = client.get("/auth/callback", params={"code": "c", "state": "forged"}, follow_redirects=False)
    assert response.status_code == 400
    assert world.calls_to("/token") == []


def test_nonce_mismatch_is_rejected(client, world):
    world.claims_override = {"nonce": "other"}
    assert login(client, world).status_code == 401


def test_wrong_audience_and_expired_token_are_rejected(make_client, world):
    world.claims_override = {"aud": "another-client"}
    assert login(make_client(), world).status_code == 401
    world.claims_override = {"exp": int(time.time()) - 3600}
    assert login(make_client(), world).status_code == 401


def test_token_signed_by_unknown_key_is_rejected(client, world):
    published = world.jwks()  # JWKS продолжает отдавать прежний ключ
    world.jwks = lambda: published
    world.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert login(client, world).status_code == 401


def test_api_requires_session(client):
    response = client.post("/api/edit/analyze", json={"text": "x"}, headers=ORIGIN)
    assert response.status_code == 401
    assert response.json()["error"] == "Нужен вход через HeartPulse"
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 302 and root.headers["location"] == "/auth/login"


def test_tampered_or_expired_session_rejected(client):
    signer = Signer(b"s" * 48)
    expired = signer.dumps("session", {"sub": OWNER}, ttl=-10)
    client.cookies.set("studio_session", expired, domain="studio.test", path="/")
    assert client.get("/api/session").status_code == 401
    good = signer.dumps("session", {"sub": OWNER}, ttl=60)
    payload, mac = good.split(".")
    client.cookies.set("studio_session", payload + "." + mac[::-1], domain="studio.test", path="/")
    assert client.get("/api/session").status_code == 401
    client.cookies.set("studio_session", good, domain="studio.test", path="/")
    assert client.get("/api/session").status_code == 200


def test_csrf_origin_check(owner):
    body = {"text": "Текст", "format": "Стандарт"}
    assert owner.post("/api/shortcodes", json=body).status_code == 403
    evil = owner.post("/api/shortcodes", json=body, headers={"Origin": "https://evil.test"})
    assert evil.status_code == 403
    assert "Origin" in evil.json()["error"]
    assert owner.post("/api/shortcodes", json=body, headers=ORIGIN).status_code == 200
    assert owner.post("/auth/logout").status_code == 403


def test_logout_clears_session(owner):
    response = owner.post("/auth/logout", headers=ORIGIN)
    assert response.status_code == 200
    assert any(
        c.startswith("studio_session=") and "max-age=0" in c.lower()
        for c in response.headers.get_list("set-cookie")
    )
    assert owner.get("/api/session").status_code == 401


def test_body_limit_and_content_type(owner):
    big = {"text": "а" * (210 * 1024), "format": "Стандарт"}
    assert owner.post("/api/shortcodes", json=big, headers=ORIGIN).status_code == 413
    plain = owner.post("/api/shortcodes", content="text", headers={**ORIGIN, "Content-Type": "text/plain"})
    assert plain.status_code == 415


def test_security_headers(client):
    headers = client.get("/health").headers
    assert "default-src 'self'" in headers["content-security-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "same-origin"
    static = client.get("/static/app.js")
    assert static.status_code == 200 and "content-security-policy" in static.headers
