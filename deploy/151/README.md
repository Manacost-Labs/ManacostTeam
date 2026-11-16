# Автодеплой на сервер 151

Пуш в `main`, затрагивающий `editor/`, `research/`, `translate/`, `studio/`,
`server/`, `shared/`, `games/`, `profiles/` или `deploy/151/`, обновляет
compose-проект `editorteam` на сервере 151. Ручной запуск — `workflow_dispatch`
в Actions (только с ветки `main`).

## Состав

| Файл | Назначение |
|---|---|
| `.github/workflows/deploy-151.yml` | gate по CI коммита, затем деплой на self-hosted раннере `manacost-151` |
| `deploy/151/wait_for_ci.py` | ждёт CI коммита; падает только на обязательных workflow |
| `deploy/151/deploy.sh <sha>` | обновление рабочей копии, сборка, запуск, проверка, откат |
| `deploy/151/compose.studio.yml` | третий оверлей: `studio`, `translator`, `research` |
| `deploy/151/editorteam-docker.service` | шаблон systemd-юнита с тремя compose-файлами |
| `deploy/151/nginx-studio.hearthpulse.net.conf` | vhost `studio.hearthpulse.net` → `127.0.0.1:8796` |

Стек: `docker compose -p editorteam --env-file /srv/editorteam/server.env
-f editor/docker-compose.yml -f /srv/editorteam/compose.server.yml
-f deploy/151/compose.studio.yml`. Относительные пути в оверлее считаются от
`editor/` (каталога первого файла).

## Как работает пайплайн

1. **CI gate** (GitHub-hosted, `ubuntu-latest`). Ждёт workflow runs этого
   коммита. Обязательные — Studio CI, Research CI, Translate CI: если какой-то
   из них запускался и упал, деплой отменяется. Падение прочих (Editor CI,
   Portable Team skills) выводится предупреждением и деплой не блокирует:
   на 2026-11-16 они красные по причинам вне деплоя (ruff format, ожидание
   Docker E2E, Windows-тест пакетов), а от поломки сервиса защищают
   health-check и откат в `deploy.sh`. Когда Editor CI снова станет зелёным,
   добавьте `--required "Editor CI"` в `deploy-151.yml`. При ручном запуске
   gate можно пропустить флагом `skip_ci_gate`.
2. **Деплой** (self-hosted `[self-hosted, manacost-151]`). Раннер делает
   sparse-checkout `deploy/151` и запускает `deploy.sh "$GITHUB_SHA"`. Скрипт
   работает над `/srv/projects/web/ManacostTeam`:
   - `flock` на `/run/lock/editorteam-deploy.lock` (плюс `concurrency:
     deploy-151` в Actions);
   - свободное место на разделе Docker: меньше 6 ГБ — `docker builder prune
     --filter until=72h` и `docker image prune -f`; всё ещё мало — выход до
     любых изменений;
   - рабочая копия с правками отслеживаемых файлов — остановка; иначе
     `git fetch origin` и `git checkout --detach <sha>`;
   - выбор состава: базовые сервисы editor + adapter всегда; `translator` — если
     в ревизии есть `compose.studio.yml`; `research` — если есть
     `/run/editorteam/research.env` с `SOURCE_GATEWAY_TOKEN`; `studio` — если
     есть `/srv/editorteam/studio.env` и три секрета в `/run/editorteam/studio/`.
     Пропущенное — предупреждение в логе, редактор обновляется всё равно;
   - `compose build` (старые контейнеры продолжают работать), затем `compose
     up -d` — пересоздаются только изменившиеся сервисы, простой gateway —
     секунды. `--remove-orphans` не используется, чтобы не задеть сервисы,
     временно выключенные из состава;
   - здоровье с ретраями до 300 с: `127.0.0.1:8740/health` (gateway),
     `127.0.0.1:8795/health` (adapter), `127.0.0.1:8796/health` (studio),
     healthcheck контейнеров `translator` и `research`;
   - провал любого шага после checkout — откат: checkout прежнего коммита,
     сборка, `up -d`, проверка здоровья. Код 1 — откат удался, код 2 — нет
     (нужно вмешательство). Если в прежней ревизии нет оверлея студии,
     контейнеры `studio/translator/research` удаляются;
   - уборка: `docker image prune -f` (только висячие образы), build cache
     старше 72 ч, вывод `df -h /`.

Сухой прогон (изменяющие команды печатаются, а не выполняются):

```bash
DRY_RUN=1 bash deploy/151/deploy.sh <sha>
```

Переопределения для тестов: `MANACOST_WORKDIR`, `EDITORTEAM_SERVER_DIR`,
`EDITORTEAM_SECRETS_DIR`, `MIN_FREE_GB`, `HEALTH_TIMEOUT` (см. шапку скрипта).

## Разовая настройка сервера

Пусть раннер работает от пользователя `gha-manacost` (подставьте своего).

1. **Раннер.** В репозитории Settings → Actions → Runners → New self-hosted
   runner; регистрация с метками `self-hosted,manacost-151`:
   ```bash
   ./config.sh --url https://github.com/Manacost-Labs/ManacostTeam --token <TOKEN> \
     --name manacost-151 --labels manacost-151 --unattended
   sudo ./svc.sh install gha-manacost && sudo ./svc.sh start
   ```
2. **Docker.** `sudo usermod -aG docker gha-manacost` и перезапуск сервиса
   раннера. Членство в группе `docker` равносильно root — раннер должен быть
   привязан только к этому репозиторию (не к организации).
3. **Рабочая копия.** Пользователь раннера должен писать в
   `/srv/projects/web/ManacostTeam` (git fetch/checkout):
   ```bash
   sudo chown -R gha-manacost: /srv/projects/web/ManacostTeam
   # либо общая группа: chgrp -R + chmod -R g+rwX + git config core.sharedRepository group
   ```
   Если владелец другой, добавьте `git config --global --add safe.directory
   /srv/projects/web/ManacostTeam` для пользователя раннера. Репозиторий
   публичный, `git fetch origin` по HTTPS ключей не требует. После первого
   автодеплоя копия стоит в detached HEAD на задеплоенном коммите — ручной
   `git pull` больше не нужен; правки в ней блокируют деплой.
4. **Чтение конфигурации.** Compose читает `env_file` на стороне клиента, то
   есть от пользователя раннера. Нужно чтение `/srv/editorteam/server.env`,
   `/srv/editorteam/compose.server.yml`, `/srv/editorteam/studio.env`,
   `/run/editorteam/research.env` и проход по `/run/editorteam/studio/`
   (секреты внутри монтируются демоном, скрипт лишь проверяет их наличие).
   Удобно: группа `editorteam`, файлы `0640 root:editorteam`, каталоги
   `0750`, `usermod -aG editorteam gha-manacost`.
5. **Студия — несекретные значения** в `/srv/editorteam/studio.env`:
   ```dotenv
   STUDIO_PUBLIC_URL=https://studio.hearthpulse.net
   OIDC_ISSUER=https://...
   OIDC_CLIENT_ID=...
   STUDIO_ALLOWED_SUBS=sub1,sub2
   LLM_MODEL=...
   CARD_CATALOG_FILE=...   # путь внутри образа studio
   ```
   Адреса внутренних сервисов и пути `*_FILE` задаёт сам оверлей.
6. **Студия — секреты** (tmpfs, готовит `prepare-secrets.sh`):
   `/run/editorteam/studio/oidc_client_secret`, `session_secret`,
   `source_gateway_token`. Монтируются read-only в `/run/secrets/studio/`.
7. **Research** — `/run/editorteam/research.env`:
   `SOURCE_GATEWAY_TOKEN=` (то же значение, что в `source_gateway_token`
   студии) и ключи провайдеров `REDDITAPIS_KEY`, `GETXAPI_KEY`,
   `TRANSCRIPTAPI_TOKEN`, `SCRAPE_DO_API_TOKEN`, `TINYFISH_API_KEY`. Кэш
   research лежит в tmpfs `/tmp` контейнера и при перезапуске сбрасывается.
   Translator хранит данные в томе `editorteam_translator-data`; необязательные
   `TRANSLATOR_ALLOWED_DOMAINS`/`TRANSLATOR_MAX_SOURCE_CHARS` — в `server.env`.
8. **Юнит.** Когда п. 5–7 готовы, замените юнит шаблоном (сохранив свой
   `ExecStartPre` подготовки секретов):
   ```bash
   sudo cp /etc/systemd/system/editorteam-docker.service{,.bak}
   sudo cp deploy/151/editorteam-docker.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```
   Перезапускать юнит не обязательно — следующий деплой поднимет студию сам.
9. **nginx + TLS** для `studio.hearthpulse.net` (DNS A/AAAA уже на 151):
   ```bash
   # 1) сначала только первый (HTTP) server{} и map из примера
   sudo cp deploy/151/nginx-studio.hearthpulse.net.conf /etc/nginx/sites-available/studio.hearthpulse.net
   #    временно закомментировать server{} на 443, затем:
   sudo ln -s ../sites-available/studio.hearthpulse.net /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot certonly --webroot -w /var/www/letsencrypt -d studio.hearthpulse.net
   # 2) вернуть блок 443
   sudo nginx -t && sudo systemctl reload nginx
   ```
   Продление: `certbot renew` уже идёт по webroot; добавьте
   `--deploy-hook "systemctl reload nginx"`, если его нет.

## Откат вручную

```bash
cd /srv/projects/web/ManacostTeam
git log --oneline -5                     # найти рабочий коммит
cp deploy/151/deploy.sh /tmp/deploy-151.sh   # скрипт не должен меняться под собой при checkout
sudo -u gha-manacost bash /tmp/deploy-151.sh <good-sha>
```

`deploy.sh` сам проверит место, соберёт, поднимет и проверит здоровье. Если
скрипт недоступен, вручную:

```bash
git checkout --detach <good-sha>
docker compose -p editorteam --env-file /srv/editorteam/server.env \
  -f editor/docker-compose.yml -f /srv/editorteam/compose.server.yml \
  -f deploy/151/compose.studio.yml up -d --build
curl -fsS 127.0.0.1:8740/health && curl -fsS 127.0.0.1:8795/health
```

Чтобы временно остановить автодеплой: Actions → Deploy 151 → Disable
workflow, либо остановить сервис раннера.
