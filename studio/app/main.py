"""FastAPI-приложение Manacost Studio.

Запуск: `uvicorn app.main:create_app --factory --port 8080 --no-access-log`.
Журнал доступа uvicorn отключён: в query callback лежит код авторизации.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import research, shortcodes, translate
from .auth import OIDCClient, build_router, read_session
from .config import Settings
from .context import ANALYZE, EDIT, RequestError, prepare_request
from .signing import Signer
from .upstream import UpstreamError, ensure_ok, post_json

STATIC = Path(__file__).resolve().parent.parent / "static"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
log = logging.getLogger("studio")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)


class ApiError(Exception):
    def __init__(self, status: int, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.status, self.message, self.detail = status, message, detail


def error_response(status: int, message: str, detail: Any = None) -> JSONResponse:
    body: dict[str, Any] = {"error": message}
    if detail:
        body["detail"] = detail
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


async def read_json(request: Request) -> dict:
    """Прочитать JSON-объект с жёстким лимитом размера (и для chunked-тел)."""
    limit: int = request.app.state.settings.max_body_bytes
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise ApiError(415, "Нужен JSON (Content-Type: application/json)")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise ApiError(413, f"Текст слишком большой: максимум {limit // 1024} КБ")
        chunks.append(chunk)
    try:
        value = json.loads(b"".join(chunks) or b"null")
    except ValueError as exc:
        raise ApiError(400, "Некорректный JSON") from exc
    if not isinstance(value, dict):
        raise ApiError(400, "Тело запроса должно быть JSON-объектом")
    return value


def pick(value: dict, allowed: tuple[str, ...]) -> dict:
    unknown = set(value) - set(allowed)
    if unknown:
        raise ApiError(400, "Неизвестные поля: " + ", ".join(sorted(unknown)))
    out = {}
    for key in allowed:
        item = value.get(key)
        if isinstance(item, str):
            item = item if key == "text" else item.strip()
        if item not in (None, ""):
            out[key] = item
    return out


def require_session(request: Request) -> dict:
    session = read_session(request)
    if session is None:
        raise ApiError(401, "Нужен вход через HeartPulse", "/auth/login")
    return session


def api_router() -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=[Depends(require_session)])

    @router.get("/session")
    async def session_info(request: Request, session: dict = Depends(require_session)) -> dict:
        state = request.app.state
        return {
            "sub": session["sub"],
            "name": session.get("name", ""),
            "expires_at": session["exp"],
            "catalog_available": state.catalog.available(),
            "sources_configured": bool(state.settings.source_gateway_token),
            "providers": {key: item["title"] for key, item in research.PROVIDERS.items()},
        }

    async def editor_call(request: Request, path: str, fields: tuple[str, ...]) -> Response:
        state = request.app.state
        settings: Settings = state.settings
        payload = prepare_request(path, pick(await read_json(request), fields))
        if path == ANALYZE:
            label, url, timeout = "Анализатор", settings.analyzer_url + "/analyze", settings.timeouts["analyzer"]
        else:
            label, url, timeout = "Редактор", settings.editor_gateway_url + "/v2/edit", settings.timeouts["editor"]
        status, body = await post_json(state.http, label, url, payload, timeout=timeout)
        return JSONResponse(ensure_ok(label, status, body), headers={"Cache-Control": "no-store"})

    @router.post("/edit/analyze")
    async def edit_analyze(request: Request) -> Response:
        return await editor_call(request, ANALYZE, ("text", "game", "patch", "genre"))

    @router.post("/edit/run")
    async def edit_run(request: Request) -> Response:
        return await editor_call(request, EDIT, ("text", "game", "patch", "genre", "mode"))

    @router.post("/shortcodes")
    async def make_shortcodes(request: Request) -> dict:
        value = pick(await read_json(request), ("text", "format"))
        text = value.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ApiError(400, "Текст пустой")
        if not isinstance(value.get("format"), str):
            raise ApiError(400, "Выберите режим: Стандарт, Вольный, Арена или Поля сражений")
        try:
            return shortcodes.run(request.app.state.catalog, text, value["format"])
        except shortcodes.CatalogUnavailable as exc:
            raise ApiError(503, str(exc)) from exc
        except shortcodes.ExportError as exc:
            raise ApiError(400, str(exc)) from exc

    @router.post("/translate")
    async def run_translate(request: Request) -> dict:
        value = pick(await read_json(request), ("text", "game", "patch", "product", "style", "title"))
        return await translate.run(request.app.state.http, request.app.state.settings, value)

    @router.post("/research")
    async def run_research(request: Request) -> dict:
        value = pick(await read_json(request), ("query", "providers", "timeframe"))
        query = value.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ApiError(400, "Сформулируйте вопрос")
        if len(query) > 500:
            raise ApiError(400, "Вопрос слишком длинный: максимум 500 символов")
        providers = value.get("providers") or ["web", "reddit"]
        if (
            not isinstance(providers, list)
            or not providers
            or any(p not in research.PROVIDERS for p in providers)
        ):
            raise ApiError(400, "Провайдеры: " + ", ".join(research.PROVIDERS))
        timeframe = value.get("timeframe") or "month"
        if timeframe not in research.TIMEFRAMES:
            raise ApiError(400, "Период: " + ", ".join(research.TIMEFRAMES))
        return await research.run(
            request.app.state.http,
            request.app.state.settings,
            query.strip(),
            list(dict.fromkeys(providers)),
            timeframe,
        )

    return router


def _request_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin and origin != "null":
        return origin.rstrip("/").lower()
    referer = request.headers.get("referer")
    if referer:
        parts = urlsplit(referer)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}".lower()
    return None


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False
    http =httpx.AsyncClient(transport=transport, follow_redirects=False)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await http.aclose()

    app = FastAPI(title="Manacost Studio", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.signer = Signer(settings.session_secret)
    app.state.http = http
    app.state.oidc = OIDCClient(settings, http)
    app.state.catalog = shortcodes.CatalogStore(settings.card_catalog_file)

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> Response:
        return error_response(exc.status, exc.message, exc.detail)

    @app.exception_handler(UpstreamError)
    async def _upstream_error(_request: Request, exc: UpstreamError) -> Response:
        return error_response(exc.status, exc.message, exc.detail)

    @app.exception_handler(RequestError)
    async def _request_error(_request: Request, exc: RequestError) -> Response:
        return error_response(400, str(exc))

    @app.middleware("http")
    async def guard(request: Request, call_next) -> Response:
        started = time.monotonic()
        path = request.url.path
        if request.method in UNSAFE and _request_origin(request) != settings.public_origin:
            response: Response = error_response(403, "Запрос с чужого сайта отклонён (проверка Origin)")
        else:
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > settings.max_body_bytes:
                response = error_response(
                    413, f"Текст слишком большой: максимум {settings.max_body_bytes // 1024} КБ"
                )
            else:
                try:
                    response = await call_next(request)
                except Exception:  # noqa: BLE001 — тексты и токены в журнал не пишем
                    log.exception("необработанная ошибка: %s %s", request.method, path)
                    response = error_response(500, "Внутренняя ошибка Studio")
        headers = response.headers
        headers["Content-Security-Policy"] = CSP
        headers["X-Content-Type-Options"] = "nosniff"
        headers["Referrer-Policy"] = "same-origin"
        headers["X-Frame-Options"] = "DENY"
        headers["Cross-Origin-Opener-Policy"] = "same-origin"
        headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if settings.secure_cookies:
            headers["Strict-Transport-Security"] = "max-age=31536000"
        if path.startswith(("/api/", "/auth/")):
            headers["Cache-Control"] = "no-store"
        # Только метод, путь и статус: без query (код OIDC), тел и cookie.
        if path != "/health":
            log.info("%s %s %s %dms", request.method, path, response.status_code, (time.monotonic() - started) * 1000)
        return response

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/")
    async def index(request: Request) -> Response:
        if read_session(request) is None:
            return RedirectResponse("/auth/login", status_code=302)
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    app.include_router(build_router())
    app.include_router(api_router())
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
