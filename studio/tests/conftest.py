"""Фейковый OIDC (RSA + JWKS) и замоканные апстримы через httpx.MockTransport."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote_plus, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

STUDIO = Path(__file__).resolve().parents[1]
REPO = STUDIO.parent
for path in (STUDIO, REPO / "shared", REPO / "editor" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PUBLIC = "https://studio.test"
ISSUER = "https://id.test"
CLIENT_ID = "manacost-studio"
CLIENT_SECRET = "client secret:with+symbols"
OWNER = "owner-sub"
GATEWAY_TOKEN = "gw-token-0123456789"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@dataclass
class FakeWorld:
    """Состояние фейковых сервисов: что пришло и что отвечать."""

    key: Any
    kid: str = "key-1"
    sub: str = OWNER
    claims_override: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)  # code -> {challenge, nonce}
    calls: list[dict] = field(default_factory=list)
    routes: dict[str, Callable[[httpx.Request, Any], httpx.Response]] = field(default_factory=dict)

    def jwks(self) -> dict:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [jwk]}

    def id_token(self, nonce: str) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": self.sub,
            "iat": now,
            "exp": now + 300,
            "nonce": nonce,
            "name": "Владелец",
        }
        claims.update(self.claims_override)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": self.kid})

    def calls_to(self, suffix: str) -> list[dict]:
        return [call for call in self.calls if call["url"].endswith(suffix)]

    # --- обработчик MockTransport ---
    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body: Any = request.content.decode("utf-8") if request.content else ""
        if request.headers.get("content-type", "").startswith("application/json") and body:
            body = json.loads(body)
        self.calls.append({"method": request.method, "url": url, "headers": dict(request.headers), "body": body})
        for suffix, handler in self.routes.items():
            if url.endswith(suffix):
                return handler(request, body)
        if url == ISSUER + "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": ISSUER + "/auth",
                    "token_endpoint": ISSUER + "/token",
                    "jwks_uri": ISSUER + "/jwks",
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        if url == ISSUER + "/jwks":
            return httpx.Response(200, json=self.jwks())
        if url == ISSUER + "/token":
            return self._token(request)
        return httpx.Response(404, json={"error": f"no mock for {url}"})

    def _token(self, request: httpx.Request) -> httpx.Response:
        # client_secret_basic: Basic base64(urlencode(id) ":" urlencode(secret)).
        scheme, _, value = request.headers.get("authorization", "").partition(" ")
        try:
            user, _, password = base64.b64decode(value).decode().partition(":")
        except ValueError:
            user = password = ""
        if scheme != "Basic" or (unquote_plus(user), unquote_plus(password)) != (CLIENT_ID, CLIENT_SECRET):
            return httpx.Response(401, json={"error": "invalid_client"})
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        pending = self.pending.pop(form.get("code", ""), None)
        if (
            pending is None
            or form.get("grant_type") != "authorization_code"
            or form.get("redirect_uri") != PUBLIC + "/auth/callback"
        ):
            return httpx.Response(400, json={"error": "invalid_grant"})
        challenge = _b64(hashlib.sha256(form.get("code_verifier", "").encode()).digest())
        if challenge != pending["challenge"]:
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": "PKCE"})
        return httpx.Response(200, json={"id_token": self.id_token(pending["nonce"]), "token_type": "Bearer"})


@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def catalog_file(tmp_path) -> Path:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "cards": [
                    {"name": "Пламенный шар", "id": "CS2_029", "formats": ["standard", "wild"]},
                    {"name": "Бранн Бронзобород", "id": "BG_LOE_077", "formats": ["battlegrounds"]},
                    {"name": "Ярость", "id": "EX1_607", "formats": ["standard"]},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def make_settings(**overrides) -> Settings:
    values = dict(
        public_url=PUBLIC,
        oidc_issuer=ISSUER,
        oidc_client_id=CLIENT_ID,
        oidc_client_secret=CLIENT_SECRET.encode(),
        session_secret=b"s" * 48,
        allowed_subs=frozenset({OWNER}),
        editor_gateway_url="http://gateway:8080",
        analyzer_url="http://analyzer:8731",
        translator_url="http://translator:8000",
        source_gateway_url="http://research:8777",
        source_gateway_token=GATEWAY_TOKEN.encode(),
        llm_url="http://adapter:8790/v1/chat/completions",
        llm_model="",
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def world(rsa_key) -> FakeWorld:
    return FakeWorld(key=rsa_key)


@pytest.fixture
def make_client(world, catalog_file):
    def build(**overrides) -> TestClient:
        overrides.setdefault("card_catalog_file", str(catalog_file))
        app = create_app(make_settings(**overrides), transport=httpx.MockTransport(world.handle))
        return TestClient(app, base_url=PUBLIC)

    return build


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


def start_login(client: TestClient) -> dict:
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 302, response.text
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == ISSUER + "/auth"
    return {k: v[0] for k, v in parse_qs(location.query).items()}


def login(client: TestClient, world: FakeWorld, code: str = "code-1") -> httpx.Response:
    params = start_login(client)
    world.pending[code] = {"challenge": params["code_challenge"], "nonce": params["nonce"]}
    return client.get(
        "/auth/callback", params={"code": code, "state": params["state"]}, follow_redirects=False
    )


@pytest.fixture
def owner(client, world) -> TestClient:
    response = login(client, world)
    assert response.status_code == 303, response.text
    return client


ORIGIN = {"Origin": PUBLIC}
