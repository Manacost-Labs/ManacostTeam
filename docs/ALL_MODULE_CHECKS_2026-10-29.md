# Проверки всех модулей — 2026-10-29

База: `83db62b7`, чистая ветка `main`. Задача: выполнить модульные проверки,
исправить воспроизводимые ошибки и повторить затронутые проверки.
Команды взяты из модульных CI, README и `editor/.agents/profile.yaml`.
Локальные журналы команд, коды возврата и время выполнения сохранены в
`build/full-checks-2026-10-29/` (игнорируемый каталог, в Git не публикуется).

## Обнаруженные ошибки и исправления

1. **EditorTeam / Ruff:** форматирование 21 файла не соответствовало
   `ruff format --check src tests`. Исправлено штатным форматтером.
   Для каждого файла сравнены AST до/после: изменений логики нет.
2. **NLP:** стандартная очередь `ThreadingHTTPServer` в Python 3.13 равна 5;
   конкурентный тест получал сброс подключения. Выделен сервер с очередью
   128 подключений; лимит анализа `MAX_INFLIGHT=8` сохранён. Новый тест на
   16 ожидающих соединений воспроизвёл отказ на прежней реализации и прошёл
   после исправления. Основной конкурентный тест тоже проходит.
3. **XMLTeam:** `corpus:verify` напечатал успешный результат и завис внутри
   завершения Node/V8 (`WorkerThreadsTaskRunner::Shutdown`, `uv_thread_join`).
   `process.exit()` заменён на `process.exitCode`: CLI завершился за 0,29 с.
   Добавлен тест завершения, кода 0, кода 1 при несовпадении SHA-256 и CRLF.
   Проверочные данные создаются во временном каталоге; корпус не менялся.
4. **Vale:** интеграционный тест ожидал устаревший запрет обычного «подарка»,
   намеренно удалённый в `dd87353`. Позитивный пример проверяет действующее
   правило для «племени»; отдельный отрицательный пример защищает обычное
   значение слова «подарок». Правила редактора не ослаблялись.
5. **Compose E2E:** fake OpenAI возвращал старую схему critic, поэтому
   шлюз правильно отклонял её с `critic_invalid_response`. Фикстура теперь
   передаёт практики из настоящего prompt, проверки логики, сохранения,
   источников, исходника и локальных правок. Проверки repair-цикла,
   retrieval и защиты чисел, ссылок и разметки сохранены.
6. **Go / staticcheck:** исправлены девять сообщений ошибок с заглавной
   буквой, упрощено преобразование совместимых структур и убрана неиспользуемая
   обёртка `repair`; рабочий путь `repairWithSources` сохранён.
7. **Go / безопасность:** `govulncheck` обнаружил 16 достижимых известных
   уязвимостей стандартной библиотеки Go 1.26.4. Версия повышена до 1.26.10
   в `go.mod`, Dockerfile и CI; повторный скан: `No vulnerabilities found`.
   Это результат анализа достижимости для данного build, не доказательство
   отсутствия всех возможных уязвимостей. Источник исправленной версии:
   [официальный бюллетень Go](https://pkg.go.dev/vuln/GO-2026-6809).

## Результаты

Все 57 выбранных групп команд завершились с кодом 0. Дополнительно проверены
frontmatter навыков, staged diff через Gitleaks и неизменность AST форматируемых файлов.

| Область | Проверки | Результат |
| --- | --- | --- |
| Общий код, server, установка, WordPress, контракты | `python3 -m unittest discover -s tests -p 'test_*.py' -v`, включая PHP harness | 249 тестов прошли |
| ResearchTeam | 402 unit-теста; audit skill, benchmark release, semantic gold, recall plan, два search coverage | Прошли |
| EditorTeam / Python | compileall, Ruff format/check, полный pytest с установленным Vale | 1026 тестов прошли, пропусков нет |
| EditorTeam / редакционные данные | config validate, profiles, corpus validate/split, selftest 49 гайдов, sync skill, eval inputs | Прошли |
| EditorTeam / Vale | Все позитивные, отрицательные и профильные примеры | 38 тестов прошли |
| EditorTeam / Go | gofmt, vet, test, test -race, build, staticcheck, govulncheck | Прошли на Go 1.26.10 |
| EditorTeam / NLP | hash-locked зависимости, Ruff, pytest | 17 тестов прошли |
| EditorTeam / eval-контракты | 36 Node-тестов, pairs validate, два `promptfoo validate` | Прошли |
| EditorTeam / Docker ARM64 | integration target с настоящими Hunspell/Vale; gateway, analyzer, NLP; Compose health; NLP HTTP; toolchain; полный pipeline E2E | Прошли |
| EditorTeam / Docker AMD64 + ARM64 | Multiarch `gateway-integration` и `gateway` | Оба target прошли после замены QEMU |
| TranslateTeam | compileall, 13 unit-тестов, Compose config, сборка Docker ARM64 | Прошли |
| XMLTeam | typecheck, ESLint/Prettier, Vitest, build, corpus verify, pack smoke | 1126 тестов прошли; остальные команды прошли |
| SVGTeam | compileall, валидация существующих SVG, генерация/валидация всех 22 spec; PNG через resvg и визуальная проверка | Прошли |
| JobTeam / MarketingTeam | Frontmatter всех 2/15 исходных навыков; сборка и проверки ресурсов переносимых пакетов | Прошли; отдельных runtime-тестов в модулях нет |
| Переносимые skills | build, `--check`, XML source-kit smoke | 7 Teams, 9 skills; прошли |
| GitHub Actions | actionlint | Прошёл |
| Подготовленные изменения | Gitleaks по staged diff с редактированием секретов | Утечек не найдено |

## Пакеты и сохранность

Подготовлен новый манифест `release/team-skills/1.20.1/`: EditorTeam 1.15.1,
Manacost Publish 1.12.1. Версии повышены из-за изменения байтов упакованных
Python-исходников. Архивы находятся в `build/team-skills/1.20.1/`.
Прежние манифесты и архивы, игровые ассеты, корпуса, исследовательская
библиотека и чужие worktree не изменялись. GitHub Release и deploy не выполнялись.

## Охват и ограничения

- Хост macOS ARM64: Python 3.13.13, Node 24.16.0, pnpm 10.34.5,
  Go 1.26.10, Ruff 0.17.3, Vale 3.17.0. Linux-проверки выполнены в Colima.
- Первые AMD64-сборки падали внутри Go runtime под QEMU 7.0. Runtime-регистрация
  заменена на эмулятор из `tonistiigi/binfmt`, как в CI; обе multiarch-сборки
  завершились успешно. Код проекта для обхода эмулятора не менялся.
- Тестовые Compose-контейнеры остановлены; профиль Colima `bench` возвращён
  в исходное остановленное состояние. Docker context остался `default`.
  Установленные Compose/Buildx и локальные кэши проверок сохранены.
- Полные матрицы Windows/Linux/macOS и всех версий Python/Node локально
  не воспроизводились. Итог push не означает, что удалённый CI уже завершён.
- Живые LLM-evals и обновление карточной базы не запускались: они требуют
  внешних моделей/данных и не входят в детерминированный модульный gate.
- Не выполнялся новый аудит доступности 39 Hearthstone-источников: проверены
  исследовательский код и сохранённые benchmark bundles, а не свежие игровые факты.
- У pymorphy2 остаётся предупреждение об устаревающем `pkg_resources`;
  hash-locked набор зависимостей с совместимым setuptools установлен успешно.
- Серверные `/srv/projects/AGENTS.md`, `skillctl`, `ai-check` и
  `ai-security-check` на этом Mac отсутствуют. Использованы реальные локальные
  модульные gates; Semgrep/CodeQL/Trivy/OSV отдельно не запускались.
  Профилирование и браузерная проверка неприменимы к этим изменениям.

## Агентские проверки

Применены monorepo gate, skill-package-manager, SVG regression suite и
минимальный набор engineering skills из профиля `editorteam`: discovery,
планирование, systematic-debugging, TDD, git workflow, verification,
context-engineering, CI/CD; для toolchain — go-security-hardening.
Context7 использован для Python socketserver и pytest, официальный бюллетень
Go — для проверки исправленной версии toolchain.

Context Scout подтвердил границы задачи и затем отдельно проверил актуальный
critic-контракт. Независимый REVIEW BRIEF не выявил подтверждённых ошибок
и проверил отчёт. Требовавшийся полный повторный Python-прогон завершён: 1026 passed. Оба запроса
модели `5.6 Luna` отклонены инструментом как недоступные; фактически использован
разрешённый fallback `gpt-6-luna`. Агенты работали только на чтение.
