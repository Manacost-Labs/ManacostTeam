# Редакторский toolchain

EditorTeam использует Go как оркестратор. Он принимает текст, собирает
компактный RuleBundle, вызывает модель, а затем повторяет проверки и не
принимает результат с изменёнными защищёнными данными.

Проверки разделены по назначению:

- существующие Python-анализаторы EditorTeam — голос, структура, карточные
  названия, semantic diff и rewrite gate;
- Natasha + Razdel — границы предложений и токенов, морфология, сущности,
  повторы и слишком длинные предложения;
- Hunspell — только подсказки о возможных опечатках и неизвестных словах;
- LanguageTool — пунктуация и общеязыковые правила через `/v2/check`;
- Vale — мягкие редакторские сигналы в Markdown;
- markdownlint — структура Markdown;
- Native Go — обязательные термины «Темные дары» и «тип существа».

Внешние проверки ничего не исправляют. Модель получает findings, а итог
проходит сравнение ссылок, чисел, сущностей, отрицаний, осторожных условий и
разметки. Невозможность запуска инструмента возвращается как
`rule_id=analyzer_unavailable`, поэтому отсутствие проверки видно клиенту.
Razdel fallback аналогично помечается `analyzer_degraded` и никогда
не поднимает `checks_complete=true`.

## Запуск

```bash
docker compose config
docker compose build
docker compose up -d --wait
curl http://127.0.0.1:8740/health
curl -X POST http://127.0.0.1:8740/v2/edit \
  -H 'content-type: application/json' \
  -d '{"text":"Поля сражений: 42% побед","mode":"edit","game":"hearthstone","profile":"battlegrounds-article"}'
docker compose down
```

В health поле `natasha` отдельно показывает `status` (`ok`, `degraded` или
`unavailable`), `complete`, engine и версию NLP. Любой обязательный
анализатор не в полном состоянии переводит общий `checks_complete` в `false`.

## Диагностика

### Windows без Docker

Локальный комплект устанавливается в игнорируемый `build/editor-windows-tools`
от корня монорепозитория. Нужны `uv`, Node.js >=22 с npm и Go; для распаковки
zstd используется отдельный Python 3.14, для Natasha — изолированный Python 3.12.
Пути к `uv`, `node` и `go`, которых нет в PATH, можно передать аргументами
`--uv`, `--node`, `--go`.

Из корня репозитория:

```powershell
uv run --python 3.14 --no-project editor/tools/windows_toolchain.py install
. ./editor/tools/Start-EditorTools.ps1
python editor/tools/windows_toolchain.py check
# Затем запустите обычный gateway и Python-анализатор в этом окружении.
# Повторно загрузить только переменные в текущий PowerShell:
. ./editor/tools/Start-EditorTools.ps1 -Action Env
# Статус и остановка только созданных этим скриптом сервисов:
./editor/tools/Start-EditorTools.ps1 -Action Status
./editor/tools/Start-EditorTools.ps1 -Action Stop
```

Перед повторной установкой остановите сервисы. `Start` проверяет полный
Natasha health и настоящий запрос LanguageTool; `check` дополнительно проверяет
русский словарь Hunspell, findings Vale и Markdownlint и сохраняет
`smoke-check.json`. `environment.json` содержит пути и адреса, без ключей.
`EDITOR_ALLOW_UNAVAILABLE=false`: неполный комплект не считается проверенным.
Это не системная установка и не автозапуск после перезагрузки.

Версии и SHA256 архивов закреплены в `config/windows-toolchain.lock.json`:
[Hunspell из MSYS2](https://packages.msys2.org/packages/mingw-w64-x86_64-hunspell)
1.7.5 с runtime-зависимостями и русским словарём 1.0.8,
[Vale](https://github.com/vale-cli/vale/releases/tag/v3.17.0) 3.17.0,
[LanguageTool](https://languagetool.org/download/) 6.6 и Temurin JRE 21.
Natasha использует существующий requirements.lock. Для
[markdownlint-cli](https://github.com/igorshubovych/markdownlint-cli) 0.49.1
закреплён отдельный npm lock с исправленными транзитивными зависимостями.
Эти версии применяются одинаково к обеим сторонам живого сравнения.

Два маленьких native launcher исполняют настоящие CLI без shell: npm `.cmd`
нельзя запустить через Go `exec` как `.exe`; MinGW Hunspell требует явной
кодировки UTF-8 и имени словаря относительно его каталога. Launchers сохраняют
stdout/stderr и код завершения; они не подменяют findings. HTTP-сервисы слушают
только loopback. Для остановки сверяются PID, полный путь и время создания
процесса, чтобы не остановить чужой процесс после переиспользования PID.

### Docker

```bash
docker compose ps
docker compose logs --no-color --tail=200 gateway nlp analyzer languagetool
curl --fail -s http://127.0.0.1:8740/health | python3 -m json.tool
curl --fail -s http://127.0.0.1:8742/health | python3 -m json.tool        # Natasha: ok и complete
curl --fail -s --data 'language=ru-RU&text=Простой+тест' http://127.0.0.1:8010/v2/check >/dev/null
docker compose exec gateway vale --version
docker compose exec gateway vale --config=/app/.vale.ini /app/evals/cases/cases.json 2>/dev/null; true
docker compose exec gateway sh -c 'printf "сабака\n" | hunspell -a -d "${RU_DICT_PATH%.dic}"'
docker compose exec gateway markdownlint-cli2 --version
docker build --target gateway --tag editorteam-gateway:test . && tests/integration/docker_toolchain.sh editorteam-gateway:test
docker buildx build --platform linux/amd64,linux/arm64 --target gateway-integration .   # настоящий словарь и опечатка
python tests/integration/nlp_sidecar_http.py
python tests/integration/pipeline_e2e.py     # нужен docker-compose.e2e.yml с fake-openai
```

Что должно быть в ответе `/health` при стандартном запуске: `ok=true`,
`checks_complete=true`, в `analyzers` все семь значений `ok`
(`native-go`, `python`, `natasha-razdel`, `hunspell`, `languagetool`, `vale`,
`markdownlint`), `natasha.status=ok` и `natasha.complete=true`. Если один из
инструментов остановить, его имя останется в `analyzers` со статусом
`unavailable`, а `checks_complete` станет `false`; `/v2/edit` тогда вернёт
исходный текст с `rule_id=analyzer_unavailable`.

Для локального запуска без Docker поднимите существующий Python-сайдкар,
`sidecars/nlp/server.py`, LanguageTool Server и установите `vale`, `hunspell`,
`markdownlint-cli2`. Адреса и таймауты задаются только переменными окружения.

## Игровой термин

Добавьте термин отдельной строкой в соответствующий файл
`config/dictionaries/*.txt`. Это allowlist для Hunspell, а не команда модели
заменять слово. Спорные варианты не добавляйте: их должен решить редактор.
В Docker словарь всегда доступен по пути
`/usr/share/hunspell/ru_RU.dic`; его версия и хеш закреплены в `Dockerfile`.
