# Как менять ManacostTeam

Начните с [AGENTS.md](AGENTS.md) и инструкций выбранного модуля.
[Карта каталогов](README.md#структура) показывает расположение исходников,
[указатель документации](docs/README.md) — действующие контракты и отчёты.
У модулей собственные зависимости; устанавливайте только необходимые для задачи.

## Найти место изменения

| Что меняем | Канонические исходники | Проверка из корня |
| --- | --- | --- |
| Редакторский Python CLI, анализ и публикационный процесс | `editor/src/editorteam/`; инструкции — `editor/AGENTS.md`, `editor/tools/SKILL.md` | `python tools/check.py editor` в окружении EditorTeam |
| Редакторский Go-сервис | `editor/go/` | `python tools/check.py editor-go` |
| Источники, research bundle, валидаторы | `research/deep-research/scripts/`, `references/`; процесс — `research/deep-research/SKILL.md` | `python tools/check.py research`; для данных ещё соответствующий bundle validator |
| Перевод и терминология | `translate/app/`, `translate/tools/` | `python tools/check.py translate` |
| XML-парсер, состояние и семантика | `XMLTeam/src/` | `python tools/check.py xml` |
| SVG-генератор | `svg/hearthstone-svg-charts/scripts/` | Генерация затронутого spec и `validate.py`; см. ниже |
| Найм и маркетинг | `job/sources/`, `marketing/specializations/` | Проверка инструкций, ссылок и соответствующего checklist; при изменении состава пакета — `packages` |
| Игры, профили и общий контекст | `shared/manacost_context.py`, `games/registry.json`, `profiles/` | `python tools/check.py context`; затем проверки затронутых потребителей |
| Серверный API | `server/api.py` | `python tools/check.py server` |
| Установка, Compose и WordPress | `tools/install.py`, `deploy/compose.yaml`, `server/Dockerfile`, `integrations/wordpress/` | `python tools/check.py install server`; контейнерные изменения дополнительно проверяются Docker |
| Переносимые навыки и упаковка | `teams/`, `teams/registry.json`, `tools/build_team_skills.py`, `tools/publish_team_skills.py` | `python tools/check.py packages` |
| Локальные сценарии статей | `skills/funmeta/`, `skills/meta-report/`, `skills/battlegrounds-hero-guides/` | `python tools/check.py funmeta`, `meta-report` или `hero-guides` |
| Каталог редакционных практик | `editor/src/editorteam/editorial_practices.json`; Go-копия синхронизируется существующим helper | `python tools/check.py editorial` и тесты затронутых потребителей |
| Корневая инфраструктура и межмодульные контракты | `tools/`, `tests/`, `docs/`, `.github/workflows/` | `python tools/check.py root`; упаковка — отдельно `packages` |

`root` запускает корневой каталог `tests/`, включая smoke распакованных пакетов.
Это не полный прогон семи модулей. В `tests/` остаются проверки общих контрактов
и локальных workflows; внутренние тесты модуля добавляйте рядом с его кодом.

## Запустить нужные проверки

`tools/check.py` — небольшой stdlib CLI для существующих команд. Он сам выбирает
рабочий каталог; Python-проверки выполняются тем интерпретатором, которым запущен
CLI. Для команд ниже подойдёт Python 3.11+; на macOS/Linux это обычно `python3`.

```bash
python tools/check.py --list
python tools/check.py context server --dry-run
python tools/check.py context server
```

Без области проверки ничего не запускается. Повтор одной области выполняется
один раз; при первой ошибке дальнейшие команды останавливаются с ненулевым кодом.
`--dry-run` показывает команды и рабочие каталоги, не требуя установленного Go,
pnpm или зависимостей модулей. CLI не устанавливает зависимости и не публикует
релизы. Команды отдельных наборов остаются доступны напрямую.

Перед `editor` активируйте окружение EditorTeam и установите зависимости согласно
его README; `translate` требует свои `requirements.txt`; `xml` — Node.js 20+,
pnpm из `XMLTeam/package.json` и установку по `XMLTeam/pnpm-lock.yaml`.
`editor-go` использует Go из `PATH`. Общий venv для всех модулей не нужен.

Для одного Python-теста можно использовать штатный discovery, например:

```bash
python -m unittest discover -s tests -p test_server_api.py -v
python -m unittest discover -s research/deep-research/tests -p test_source_access.py -v
```

SVG проверяется на затронутом spec. Сохраняйте новый результат в игнорируемом
`build/`, чтобы не перезаписать эталоны:

```bash
python -c "from pathlib import Path; Path('build/svg-check').mkdir(parents=True, exist_ok=True)"
python svg/hearthstone-svg-charts/scripts/make_chart.py svg/hearthstone-svg-charts/examples/specs/spec-bars.json -o build/svg-check/bars.svg
python svg/hearthstone-svg-charts/scripts/validate.py build/svg-check/bars.svg
```

Выборочные команды — базовая проверка, а не замена полного CI. Дополнительные
lint, corpus, benchmark, Docker и package smoke описаны в
[модульных workflows](.github/workflows/) и локальных инструкциях.

## Исходники, точки входа и сборки

- `teams/<имя>/SKILL.md` — переносимый workflow. Ресурсы берутся из путей
  `source` в [teams/registry.json](teams/registry.json) и получают путь
  `destination` внутри архива. Исправляйте ресурс в его `source`, затем проверяйте
  упаковку. Часть legacy-ресурсов EditorTeam пока находится в `editor/release/`:
  принадлежность определяет registry, а не только имя каталога.
- `skills/` — общие и локальные workflows. `.agents/skills/` и
  `.claude/commands/` — адаптеры вызова; основную логику храните в каноническом
  workflow, указанном внутри адаптера.
- `release/team-skills/<версия>/` — зафиксированные манифесты выпуска.
  Архивы новых сборок попадают в `build/team-skills/`, публикуются ассетами
  GitHub Release. `packages` сверяет текущие исходники с зафиксированным
  манифестом и может выявить необходимость отдельного выпуска.
- `build/` — результаты запусков и временные проверки. Постоянный локальный
  архив источников находится в `research/library/`, переводческие данные —
  в `translate/data/`; их нельзя очищать вместе с `build/`.
- `docs/` содержит контракты и исторические отчёты. Дата или успешный тест в
  старом отчёте не подтверждают текущее состояние checkout.

## Изменение общего контракта

У `task_context` уже есть явные потребители: EditorTeam, TranslateTeam,
серверный API, установщик и переносимые пакеты. При изменении `shared/`,
`games/` или `profiles/` проверяйте затронутых потребителей по
[контракту контекста](docs/TASK_CONTEXT.md), а не только тест resolver.
Состав переносимых ресурсов сверяйте по registry; дополнительные потребители
видны в импортах и CI-фильтрах путей.

Перед межмодульной правкой зафиксируйте вход, выход, владельца каждого шага и
общую проверку. Новый файл кладите в модуль, которому принадлежит поведение;
в `shared/` — только код с реальными потребителями в нескольких модулях.
Существующие пути сохраняйте: на них опираются импорты, CI, skills и упаковка.

## Перед передачей изменений

1. Сравните `git status --short` с состоянием до работы; исключите чужие изменения.
2. Запустите выбранные проверки и `git diff --check`. Запишите реальные сбои и
   пропуски; Docker, внешние сервисы и модели проверяйте только когда они нужны.
3. Обновите документацию изменённого поведения и `CHANGELOG.md`, если изменение
   заметно пользователю. Новый исходник или тест не требует нового релиза сам по себе.
4. Просмотрите `git diff --cached`, включая состав файлов; затем сделайте узкий
   commit с префиксом модуля или `repo:` и push без переписывания истории.
