# Changelog

## Unreleased

- `editor/research` (Team skills 1.3.0): контракт проверенных утверждений и вопросов игрока, режим `reconstruct`, отдельный фактологический review и необязательная проверяющая модель; CLI decision coverage и очередь пробелов. Добавлены приватный импорт полных материалов Manacost MCP, подготовка слепого benchmark, Promptfoo edit/reconstruct и необязательные адаптеры Trafilatura/LangExtract/Sentence Transformers с экспортом для DSPy/RAGChecker. Реальные человеческие оценки и Council остаются следующими экспериментами. Контракт и команды — `docs/EDITORIAL_PIPELINE_V3.md`.
- `translate`: добавлен Docker-подготовщик материалов для Codex без локальной LLM: терминологические выгрузки, контекст, стили, сегментный diff, translation memory и механический QA.
- `skills`: добавлен `wow-hearthstone-translator` для двухпроходного перевода игровых материалов.
- `editor` (EditorTeam 1.2.0): типографика через Typograf (`editor-team typography`: тире и неразрывные пробелы, кавычки прямые по `СТИЛЬ.md`, названия карт и разметка защищены, результат проверяется), необязательные подсказки опечаток SAGE (`editor-team spelling-hints`, веса не скачиваются без `--download`) и второй читающий аудитор ru-text 2.9.3 (`editor-team ru-audit`, агент `.claude/agents/ru-auditor.md` только с Read/Grep/Glob). Подробности — `editor/.claude/skills/hs-edit/references/external-checks.md`.

Все заметные изменения монорепозитория документируются в этом файле. Изменения внутри отдельного модуля могут вести собственные release notes; здесь фиксируются миграции, общая структура и межмодульные решения.

Формат основан на принципах Keep a Changelog. Даты указаны в формате `YYYY-MM-DD`.

## [Unreleased]

### Added

- Добавлен каталог общих skills: monorepo gate, packaging, research-to-publication, SVG regression, freshness audit и release/migration.
- В редакторский workflow добавлен обязательный вопрос о WordPress-шорткодах до редактуры, если пользователь не выбрал режим сам.
- `hearthstone-replay` импортирован в `XMLTeam/` с полной Git-историей; метаданные npm-пакета переведены на monorepo remote.
- Добавлен `xml-replay-analysis`: chat-workflow для извлечения из `.hsreplay.xml` анонимизированных фактов для гайдов — муллигана, ключевых эпизодов и вероятных архетипов.

### Planned

- Отдельно разобрать и исправить базовую синтаксическую ошибку в `svg`.
- Воспроизвести и классифицировать падающие benchmark-тесты `research`.
- Определить, нужен ли общий CI для независимых модулей и какие проверки в него входят.

## [2026-09-12] — создание монорепозитория

### Added

- Создан публичный репозиторий `Manacost-Labs/ManacostTeam`.
- Добавлены корневые `README.md`, `CONTEXT.md`, `CHANGELOG.md` и `AGENTS.md`.
- Добавлен модуль `job/` с пакетами оценки вакансий и отбора игровых авторов.

### Changed

- `EditorTeam` импортирован в `editor/` с сохранением Git-истории.
- `ResearchTeam` импортирован в `research/` с сохранением Git-истории.
- `SVGTeam` импортирован в `svg/` с сохранением Git-истории.

### Migration notes

- Локальные незакоммиченные изменения прежнего `SVGTeam` не вошли в `main` и сохранены в исходной рабочей папке.
- Существующие ошибки импортированных модулей не исправлялись в рамках структурной миграции.
