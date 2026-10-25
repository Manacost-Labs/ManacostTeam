# Установка ManacostTeam

Нужны Git и Python 3.11+. Для серверного запуска также нужны Docker и Compose v2.
Один checkout служит источником установки; установщик не скачивает зависимости
(только архивы навыков из GitHub Releases) и не меняет глобальные настройки агента. Выпуск навыков — 1.6.0.

```bash
git clone https://github.com/Manacost-Labs/ManacostTeam.git
cd ManacostTeam
```

## ИИ-агенты

Установить редактуру и перевод в **другой проект**, например `~/articles`:

```bash
python3 tools/install.py agent --client codex --directory ~/articles --game deadlock
```

Результат: `.agents/skills/editor-team`, `.agents/skills/translate-team`,
контекст `.manacost/context.json` и манифест `.manacost/install.json`.
Навыки распакованы из релизных ZIP с проверкой SHA256 и работают без checkout.
ZIP берутся из локальной сборки `build/team-skills/<версия>/`, иначе скачиваются
из GitHub Release `v<версия>`. Без сети скачайте ассеты релиза в каталог и
укажите `--archives DIR`; если ассет недоступен, установщик останавливается до записи.
В этом репозитории уже есть entrypoints; не устанавливайте поверх них.

Для Claude Code замените `--client codex` на `--client claude` — навыки попадут
в `.claude/skills/`. Для другого агента укажите `--client generic` и каталог,
который он использует для Agent Skills. Например, пользовательские навыки Codex:

```bash
python3 tools/install.py agent --client generic --directory ~/.agents/skills --game hearthstone
```

Выбрать возможности можно через `--skills editor-team,translate-team,research-team`.
Имена перечислены в `teams/registry.json`. Каждый навык сохраняет свои ограничения:
SVG и XML не становятся универсальными только из-за выбора другой игры.
Наличие навыка не добавляет веб-доступ, внешние connectors или Python-зависимости.
HTTP-подготовщик перевода устанавливается серверным способом, а перевод в агенте
выполняет сам агент с portable helpers.

Пример задания: «Используй $editor-team, отредактируй этот текст по контексту
`.manacost/context.json`». Для перевода используйте $translate-team и укажите
точную сборку; для WoW также продукт. [Официальный контракт локальных навыков Codex](https://learn.chatgpt.com/docs/build-skills).

Чтобы выбрать другую игру, создайте новый контекст bundled resolver:

```bash
python3 ~/articles/.agents/skills/editor-team/scripts/resolve_context.py --game overwatch --patch EXACT_BUILD > ~/articles/.manacost/overwatch.json
```

Передайте агенту этот файл. Основной стиль всех игр — Манакост. Выбор игры
в контексте не подтверждает свежесть патча или правильность локализации.

## Сервер

Выполняйте установку из checkout, который будет оставаться на сервере:

```bash
python3 tools/install.py server --directory /srv/manacost-instance --game world-of-warcraft
cd /srv/manacost-instance
docker compose config --quiet
docker compose up -d --build
```

Если нет прав на `/srv`, выберите каталог своего пользователя. Установщик создаёт
`compose.yaml`, `.env`, `context.json` и секрет `secrets/api-token.txt` с правами 0600.
Он не запускает Docker автоматически и не выводит значение токена. Build context
указывает на исходный checkout; не переносите и не удаляйте его после установки.

Стек содержит Python-анализатор, Go-редактор, переводческий подготовщик и единый
API. Платные вызовы отключены (`EDITOR_PROVIDER=none`). Проверка текста доступна;
редактура возвращает `dry_run` и не утверждает исправления как принятые.
LanguageTool и Natasha в этом лёгком составе не запускаются — отчёт показывает
пропущенные проверки. Для полного контура используйте настройки editor-модуля.

Проверка процесса API:

```bash
curl http://127.0.0.1:8800/health
```

`/health` показывает доступность API-процесса; успешность редакторских проверок
смотрите в отчёте конкретного запроса. Остальные endpoints требуют токен:

```bash
curl -H 'Authorization: Bearer YOUR_TOKEN' http://127.0.0.1:8800/v1/games
curl -H 'Authorization: Bearer YOUR_TOKEN' -H 'Content-Type: application/json' \
  -d '{"game":"league-of-legends","genre":"game-article","text":"Урон повышается на 20%."}' \
  http://127.0.0.1:8800/v1/editor/analyze
```

Не сохраняйте настоящий токен в документации, Git или публичных командах.
Для внешнего WordPress подключите HTTPS reverse proxy к loopback API; открывать
анализатор, редактор и переводчик отдельными публичными портами не нужно.
Токен передаётся только сервером WordPress, а не браузером пользователя.

Игра задаётся в каждом запросе или выбирается в WordPress. Значение по умолчанию
можно изменить в `.env` (`MANACOST_GAME=deadlock`), затем выполнить
`docker compose up -d`. `context.json` — снимок первоначального выбора для агентов,
сервер разрешает актуальный контекст заново для каждого запроса.

Автоматическая редактура требует собственного настроенного провайдера: задайте
`EDITOR_PROVIDER`, `EDITOR_MODEL`, `EDITOR_API_KEY` и при необходимости
`EDITOR_BASE_URL` в локальном `.env` по [контракту редактора](../editor/README.md),
затем пересоздайте контейнер. Установщик не получает ключи и не проверяет аккаунты.
Переводческий сервис подготавливает текст и инструкцию; готовый перевод делает агент.
Данные и словари переводчика хранятся в `data/translate/` установленного экземпляра.

## WordPress

Загрузите `release/install/1.0.0/manacost-team-wordpress-1.0.0.zip` через
«Плагины → Добавить плагин → Загрузить», затем активируйте ManacostTeam.
Либо установите папку на сервере вручную:

```bash
python3 tools/install.py wordpress --directory /var/www/site/wp-content/plugins
```

Администратор задаёт URL и токен в «Настройки → ManacostTeam».
Для WordPress в PHP-процессе на том же хосте URL по умолчанию —
`http://127.0.0.1:8800`. Для WordPress на другом сервере нужен адрес HTTPS reverse
proxy, например `https://manacost.example.com`. Сам reverse proxy установщик
не настраивает: домен и сертификат относятся к вашему серверу.

Если WordPress находится в контейнере, localhost означает сам контейнер:
подключите его к доступной API-сети или используйте адрес хоста. Для явно выбранной
частной HTTP-сети можно добавить в `wp-config.php`
`define('MANACOST_ALLOW_PRIVATE_HTTP', true);`; наружу используйте HTTPS.
Для HTTP внутри Docker API должен быть доступен из сети WordPress; сам по себе
loopback bind хоста не делает API доступным другому контейнеру.

В «Инструменты → ManacostTeam» доступны выбор игры, жанра и действия:
проверка текста, подготовка перевода или серверная ИИ-редактура. Список игр
приходит с API. Для перевода нужен точный patch/build, для WoW также product.
Результат и отчёт показываются для проверки и копирования. Плагин не меняет
статьи, не создаёт публикаций, не конвертирует Markdown в HTML и не добавляет шорткоды.

Права пользователя и nonce проверяются отдельно; токен не отображается в формах,
редиректы с ним отключены. Токен хранится в базе WordPress с autoload=false;
доступ к базе означает доступ к нему. Защита nonce не заменяет проверку прав —
[контракт WordPress](https://developer.wordpress.org/plugins/security/nonces/).

## Повторная установка и проверки

Повтор той же установки сохраняет байты файлов и токен. При несовпадении файлов
установщик останавливается до записи: он не перезаписывает правки, настройки и
данные. Для новой версии используйте новый каталог и перенесите конфигурацию/
данные осознанно; автоматического обновления поверх пользовательских правок нет.

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
php -l integrations/wordpress/manacost-team/manacost-team.php
php tests/wordpress_plugin.php
python3 tools/build_team_skills.py --check
```

PHP harness подменяет WordPress core и проверяет контракт плагина; он не заменяет
проверку на тестовом сайте. До production проверьте Docker Compose на сервере,
подключение WordPress, PHP/network timeout и фактическую полноту анализаторов.
Подготовка upload ZIP воспроизводима:

```bash
python3 tools/install.py wordpress --zip release/install/1.0.0/manacost-team-wordpress-1.0.0.zip
```
