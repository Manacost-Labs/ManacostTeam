# Manacost Studio

Веб-инструмент одного владельца (https://studio.hearthpulse.net). В нём четыре вкладки поверх уже существующих сервисов ManacostTeam:

| Вкладка | Эндпоинт | Куда идёт | Платно |
|---|---|---|---|
| Исследование | `POST /api/research` | шлюз источников `POST /v1/source` (по одному запросу на провайдера), затем один запрос к LLM | да |
| Редактура: проверка | `POST /api/edit/analyze` | analyzer `/analyze` | нет |
| Редактура: правка | `POST /api/edit/run` | gateway `/v2/edit` | да |
| Шорткоды | `POST /api/shortcodes` | в процессе: `editorteam.card_shortcodes.apply_shortcodes` | нет |
| Перевод | `POST /api/translate` | translator `/prepare`, затем LLM, затем `/qa` | да |

Служебные маршруты: `GET /health` (без авторизации и без обращения к апстримам), `GET /auth/login`, `GET /auth/callback`, `POST /auth/logout`, `GET /api/session`.

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `STUDIO_PUBLIC_URL` | `https://studio.hearthpulse.net` | публичный адрес: redirect_uri и проверка Origin |
| `OIDC_ISSUER` | — (обязательна) | issuer HeartPulse; метаданные берутся из `<issuer>/.well-known/openid-configuration` |
| `OIDC_CLIENT_ID` | `manacost-studio` | клиент OIDC |
| `OIDC_CLIENT_SECRET_FILE` | — (обязательна) | файл с секретом клиента (client_secret_basic) |
| `STUDIO_SESSION_SECRET_FILE` | — (обязательна) | файл с ключом HMAC для cookie, не короче 32 байт |
| `STUDIO_ALLOWED_SUBS` | — (обязательна) | допущенные `sub` через запятую |
| `EDITOR_GATEWAY_URL` | `http://gateway:8080` | Go-шлюз редактора |
| `ANALYZER_URL` | `http://analyzer:8731` | Python-анализатор |
| `TRANSLATOR_URL` | `http://translator:8000` | TranslateTeam |
| `SOURCE_GATEWAY_URL` | `http://research:8777` | шлюз источников ResearchTeam |
| `SOURCE_GATEWAY_TOKEN_FILE` | — | токен шлюза; если не задан, исследование отвечает 503 |
| `LLM_URL` | `http://adapter:8790/v1/chat/completions` | OpenAI-совместимый chat/completions |
| `LLM_MODEL` | пусто | если пусто, `model` не отправляется и модель выбирает адаптер. `temperature` не отправляется никогда |
| `CARD_CATALOG_FILE` | пусто | каталог карт для шорткодов (см. ниже); если не задан, `/api/shortcodes` отвечает 503 |

### Каталог карт

В репозитории нет каталога с подтверждёнными card ID и режимами. `cards-ru.json` редактора содержит только имена, а пример в `teams/card-shortcodes` служит лишь схемой. Поэтому каталог подключается файлом (например, volume только для чтения) в формате `editorteam.wordpress.load_catalog`:

```json
{"cards": [{"name": "Бранн Бронзобород", "id": "BG_LOE_077", "formats": ["battlegrounds"]}]}
```

Файл перечитывается при изменении. Studio подставляет шорткоды только по точным именам выбранного режима (Стандарт, Вольный, Арена, Поля сражений; см. `parse_format`). Падежи, сокращения и контекстные `mentions` не угадываются. Спорные слова («Ярость», «Монетка»…) выносятся на проверку.

## Безопасность

- Вход: OIDC code + PKCE S256. state, nonce и verifier хранятся в подписанной cookie `studio_auth` (10 минут, путь `/auth`). Токен получается через client_secret_basic. id_token проверяется по JWKS: RS256, iss, aud, exp, iat и nonce. `sub` должен входить в `STUDIO_ALLOWED_SUBS`, иначе пользователь получает 403 «Доступ только владельцу».
- Сессия хранится в cookie `studio_session` с подписью HMAC-SHA256. Флаги: HttpOnly, Secure, SameSite=Lax. Срок жизни 12 ч.
- Каждому `/api/*` нужна сессия (иначе 401). У POST-запросов Origin (или Referer) должен совпадать со `STUDIO_PUBLIC_URL` (иначе 403).
- Тело запроса ограничено 200 КБ (иначе 413), принимается только JSON (иначе 415). Ответ апстрима ограничен 4 МБ. У каждого апстрима свой таймаут: анализатор 60 с, редактор 150 с, переводчик 60 с, источники 45 с, LLM 180 с.
- Заголовки ответа: CSP `default-src 'self'` с `frame-ancestors 'none'`, `X-Content-Type-Options`, `Referrer-Policy: same-origin`, `X-Frame-Options`, HSTS (только при https).
- Журнал uvicorn отключён, потому что в query callback передаётся код авторизации. Studio записывает в журнал только метод, путь, статус и длительность. Тексты и токены не записываются.
- В исследовании содержимое источников передаётся модели как данные: модели прямо сказано игнорировать инструкции внутри источников, а угловые скобки экранируются.

## Тела запросов к апстримам

Редактура и перевод с патчем формируют тела так же, как `server/api.py:prepare_request`: `{text, task_context, profile?, mode?}` и `{text, task_context, product?}`. Логика повторена в `app/context.py`, а её равенство оригиналу проверяет тест `tests/test_context_parity.py`.

Перевод без патча отправляет `{text, game, style}`: используется общий глоссарий TranslateTeam. Модель получает `instruction_for_codex` и указание сохранить `[[[TERM_n]]]`. Затем Studio подставляет утверждённые термины и передаёт результат в `/qa`.

Шлюз источников проверяет заголовок `X-Source-Gateway-Token` (см. `source_gateway.py`). Studio отправляет его вместе с `Authorization: Bearer`.

## Локальный запуск

```powershell
py -3.12 -m venv studio\.venv   # 3.13 тоже подходит
studio\.venv\Scripts\python -m pip install -r studio\requirements.txt pytest==8.3.5
studio\.venv\Scripts\python -m pytest -q studio\tests

$env:PYTHONPATH = "$PWD\studio;$PWD\shared;$PWD\editor\src"
$env:STUDIO_PUBLIC_URL = "http://127.0.0.1:8080"
$env:OIDC_ISSUER = "https://<issuer HeartPulse>"
$env:OIDC_CLIENT_SECRET_FILE = "<путь к файлу>"
$env:STUDIO_SESSION_SECRET_FILE = "<путь к файлу>"
$env:STUDIO_ALLOWED_SUBS = "<sub владельца>"
cd studio; .venv\Scripts\python -m uvicorn app.main:create_app --factory --port 8080 --no-access-log
```

Docker (контекст — корень репозитория):

```sh
docker build -f studio/Dockerfile -t manacost-studio .
```

## Архитектура

- `app/main.py`: фабрика FastAPI, middleware (CSRF, лимит тела, заголовки, журнал), маршруты `/api/*`.
- `app/auth.py`: клиент OIDC (кэш метаданных и JWKS), `/auth/*`. `app/signing.py`: подписанные cookie.
- `app/context.py`: тела для редактора и переводчика. `app/upstream.py`: HTTP к сервисам и русские ошибки.
- `app/research.py`, `app/translate.py`, `app/shortcodes.py`, `app/llm.py`: логика вкладок.
- `static/`: HTML, CSS и ванильный JS-модуль без сборщика и CDN.
- Все исходящие HTTP-запросы идут через один `httpx.AsyncClient`. В тестах ему подставляется `MockTransport`, а OIDC подменяется фейком с RSA-ключом и JWKS.
