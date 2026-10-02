# Проверка Team standard 1.0.1

Локальная проверка Windows, Python 3.13, 2026-10-03:

| Область | Результат |
| --- | --- |
| EditorTeam | 431 passed, 36 skipped: внешние сервисы не запускались |
| Редакторские Node eval contracts | 20 passed |
| ResearchTeam | 221 tests OK; затем focused source-breadth 6/6 и CLI scopes smoke |
| Research gates | Skill audit, benchmark release, semantic gold, recall plan PASS |
| SVGTeam | 22 распакованных specs созданы/валидированы; 22 прежних SVG валидны |
| TranslateTeam | 4/4 tests OK; portable QA подтверждён |
| XMLTeam | 1125 tests passed; typecheck/build/lint/package smoke PASS |
| XML source kit | ZIP → чистая temp-папка → frozen install → build → parse raw packet PASS |
| Общие пакеты | 14 tests OK: реальные ZIP, manifests, SHA, relative links, runtime helpers |
| Формат skills/plugin | 8 entrypoints valid; Claude Code strict plugin validation PASS |
| Сборка | Повторная сборка `--check` воспроизводима |
| Статические проверки | Ruff затронутых runtime/tests, actionlint и staged diff check PASS |

Go/Docker и остальные ОС проверяются отдельными jobs в GitHub Actions. Их
локальный запуск не заявляется. Облачный импорт навыков в аккаунты ChatGPT/Claude
не выполнялся. Утверждение «пакет переносим» относится к его структуре и
проверенным helpers, с указанными в SKILL.md требованиями к среде.
