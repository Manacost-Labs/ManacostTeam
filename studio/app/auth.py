"""Вход через OIDC HeartPulse: code + PKCE S256, client_secret_basic, id_token RS256."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import secrets
import time
from urllib.parse import quote_plus, urlencode

import httpx
import jwt
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .config import Settings
from .signing import Signer

AUTH_COOKIE = "studio_auth"
SESSION_COOKIE = "studio_session"
AUTH_TTL = 600
METADATA_TTL = 3600


class AuthError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def pkce_pair() -> tuple[str, str]:
    verifier = _b64(secrets.token_bytes(48))
    challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class OIDCClient:
    """Метаданные и JWKS с кэшем; HTTP-клиент передаётся извне (в тестах — mock)."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http
        self._metadata: tuple[float, dict] | None = None
        self._jwks: tuple[float, dict] | None = None

    async def _get_json(self, url: str) -> dict:
        try:
            response = await self.http.get(url, timeout=self.settings.timeouts["oidc"])
        except httpx.HTTPError as exc:
            raise AuthError(502, "Сервер входа HeartPulse недоступен") from exc
        if response.status_code != 200:
            raise AuthError(502, "Сервер входа HeartPulse вернул ошибку")
        try:
            body = response.json()
        except ValueError as exc:
            raise AuthError(502, "Сервер входа HeartPulse вернул некорректный ответ") from exc
        if not isinstance(body, dict):
            raise AuthError(502, "Сервер входа HeartPulse вернул некорректный ответ")
        return body

    async def metadata(self) -> dict:
        now = time.monotonic()
        if self._metadata and now - self._metadata[0] < METADATA_TTL:
            return self._metadata[1]
        issuer = self.settings.oidc_issuer
        body = await self._get_json(issuer + "/.well-known/openid-configuration")
        if str(body.get("issuer", "")).rstrip("/") != issuer:
            raise AuthError(502, "Метаданные OIDC относятся к другому issuer")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not isinstance(body.get(key), str) or not body[key].startswith(("https://", "http://")):
                raise AuthError(502, f"В метаданных OIDC нет {key}")
        self._metadata = (now, body)
        return body

    async def jwks(self, *, refresh: bool = False) -> dict:
        now = time.monotonic()
        if not refresh and self._jwks and now - self._jwks[0] < METADATA_TTL:
            return self._jwks[1]
        body = await self._get_json((await self.metadata())["jwks_uri"])
        if not isinstance(body.get("keys"), list):
            raise AuthError(502, "JWKS сервера входа некорректен")
        self._jwks = (now, body)
        return body

    async def _signing_key(self, kid: str | None):
        for refresh in (False, True):
            keys = (await self.jwks(refresh=refresh))["keys"]
            candidates = [
                key
                for key in keys
                if isinstance(key, dict)
                and key.get("kty") == "RSA"
                and key.get("use", "sig") == "sig"
                and (kid is None or key.get("kid") == kid)
            ]
            if len(candidates) == 1 or (kid is None and candidates):
                return jwt.PyJWK(candidates[0], algorithm="RS256").key
            if kid is None:
                break
        raise AuthError(401, "Подпись id_token не найдена в JWKS")

    async def exchange_code(self, code: str, verifier: str) -> dict:
        meta = await self.metadata()
        s = self.settings
        # RFC 6749 §2.3.1: client_id и secret кодируются form-urlencoded до Basic.
        basic = base64.b64encode(
            f"{quote_plus(s.oidc_client_id)}:{quote_plus(s.oidc_client_secret.decode('utf-8'))}".encode()
        ).decode("ascii")
        try:
            response = await self.http.post(
                meta["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": s.redirect_uri,
                    "code_verifier": verifier,
                },
                headers={"Authorization": f"Basic {basic}", "Accept": "application/json"},
                timeout=s.timeouts["oidc"],
            )
        except httpx.HTTPError as exc:
            raise AuthError(502, "Сервер входа HeartPulse недоступен") from exc
        if response.status_code != 200:
            raise AuthError(401, "Сервер входа отклонил код авторизации")
        try:
            tokens = response.json()
        except ValueError as exc:
            raise AuthError(502, "Сервер входа вернул некорректный ответ") from exc
        if not isinstance(tokens, dict) or not isinstance(tokens.get("id_token"), str):
            raise AuthError(502, "Сервер входа не вернул id_token")
        return tokens

    async def verify_id_token(self, token: str, nonce: str) -> dict:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthError(401, "id_token повреждён") from exc
        if header.get("alg") != "RS256":
            raise AuthError(401, "id_token подписан не RS256")
        key = await self._signing_key(header.get("kid"))
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.settings.oidc_client_id,
                issuer=self.settings.oidc_issuer,
                leeway=60,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(401, "id_token не прошёл проверку") from exc
        if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            raise AuthError(401, "nonce в id_token не совпадает")
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise AuthError(401, "в id_token нет sub")
        return claims


def _cookie_args(settings: Settings, path: str = "/") -> dict:
    return {"httponly": True, "secure": settings.secure_cookies, "samesite": "lax", "path": path}


def message_page(status: int, title: str, text: str, *, login_link: bool = False) -> HTMLResponse:
    link = '<p><a href="/auth/login">Войти снова</a></p>' if login_link else ""
    body = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · Manacost Studio</title><link rel="stylesheet" href="/static/app.css"></head>
<body class="message-page"><main class="message"><h1>{html.escape(title)}</h1><p>{html.escape(text)}</p>{link}</main></body></html>"""
    return HTMLResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def read_session(request: Request) -> dict | None:
    settings: Settings = request.app.state.settings
    signer: Signer = request.app.state.signer
    data = signer.loads("session", request.cookies.get(SESSION_COOKIE))
    if not data or data.get("sub") not in settings.allowed_subs:
        return None
    return data


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/auth/login")
    async def login(request: Request) -> Response:
        settings: Settings = request.app.state.settings
        oidc: OIDCClient = request.app.state.oidc
        try:
            meta = await oidc.metadata()
        except AuthError as exc:
            return message_page(exc.status, "Вход недоступен", exc.message, login_link=True)
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": settings.oidc_client_id,
                "redirect_uri": settings.redirect_uri,
                "scope": "openid profile",
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        separator = "&" if "?" in meta["authorization_endpoint"] else "?"
        response = RedirectResponse(meta["authorization_endpoint"] + separator + query, status_code=302)
        cookie = request.app.state.signer.dumps(
            "auth", {"state": state, "nonce": nonce, "verifier": verifier}, AUTH_TTL
        )
        response.set_cookie(AUTH_COOKIE, cookie, max_age=AUTH_TTL, **_cookie_args(settings, "/auth"))
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/auth/callback")
    async def callback(request: Request) -> Response:
        settings: Settings = request.app.state.settings
        signer: Signer = request.app.state.signer
        oidc: OIDCClient = request.app.state.oidc
        params = request.query_params
        pending = signer.loads("auth", request.cookies.get(AUTH_COOKIE))

        def fail(status: int, title: str, text: str) -> Response:
            response = message_page(status, title, text, login_link=True)
            response.delete_cookie(AUTH_COOKIE, **_cookie_args(settings, "/auth"))
            return response

        if params.get("error"):
            return fail(400, "Вход отменён", "Сервер входа вернул отказ. Попробуйте ещё раз.")
        state, code = params.get("state", ""), params.get("code", "")
        if not pending or not state or not hmac.compare_digest(state, str(pending.get("state", ""))):
            return fail(400, "Вход не завершён", "Сессия входа устарела или подменена. Начните вход заново.")
        if not code:
            return fail(400, "Вход не завершён", "Сервер входа не передал код авторизации.")
        try:
            tokens = await oidc.exchange_code(code, str(pending["verifier"]))
            claims = await oidc.verify_id_token(tokens["id_token"], str(pending["nonce"]))
        except AuthError as exc:
            return fail(exc.status, "Вход не выполнен", exc.message)
        if claims["sub"] not in settings.allowed_subs:
            return fail(403, "Доступ только владельцу", "Этот аккаунт HeartPulse не допущен к Manacost Studio.")
        name = claims.get("name") or claims.get("preferred_username") or claims.get("nickname") or ""
        session = signer.dumps(
            "session",
            {"sub": claims["sub"], "name": str(name)[:80], "iat": int(time.time())},
            settings.session_ttl,
        )
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(AUTH_COOKIE, **_cookie_args(settings, "/auth"))
        response.set_cookie(SESSION_COOKIE, session, max_age=settings.session_ttl, **_cookie_args(settings))
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.post("/auth/logout")
    async def logout(request: Request) -> Response:
        settings: Settings = request.app.state.settings
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE, **_cookie_args(settings))
        return response

    return router
