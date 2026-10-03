# Проверка Team standard 1.1.0

Локальная проверка Windows, Python 3.13, 2026-10-03 после улучшений EditorTeam
и ResearchTeam:

| Область | Результат |
| --- | --- |
| EditorTeam | 454 passed, 36 skipped; внешние интеграции локально не запускались |
| ResearchTeam | 233 tests OK |
| Research gates | Skill audit, benchmark release, semantic gold и recall plan PASS |
| Общие release/runtime tests | 28 tests OK; новые guards Editor и очередь Research проверены из распакованных ZIP без checkout/dependencies |
| Skills/plugin | 8 entrypoints и monorepo gate валидны; Claude Code strict plugin validation PASS |
| Сборка | Выпуск 1.1.0; `--check` подтверждает точный состав, воспроизводимость и неизменность старых архивов |
| Статические проверки | Ruff затронутых файлов, формат и diff check PASS; TRY004 для двух прежних ValueError в planner исключён из lint |

Итого: 715 успешных тестов, 36 пропущенных интеграционных тестов. Добавлены
12 сценариев сохранения фактов Editor, 9 сценариев очереди/широты Research и
2 проверки новых возможностей в переносимых пакетах. Тестовые игровые тексты
служат синтетическими примерами поведения, а не утверждениями о текущих картах.

Произвольный пересказ и соответствие цитаты конкретному совету требуют
ручной сверки по evidence; access coverage не доказывает независимость или
правильность выводов. Смысловые границы описаны в
[изменениях 1.1.0](EDITOR_RESEARCH_QUALITY.md). Импорт в облачные аккаунты
ChatGPT/Claude не выполнялся. Предыдущие результаты ниже относятся к своим выпускам.

### GitHub CI 1.1.0

Для commit `0a3f02c` прошли
[Research CI](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37127360918)
и [Portable Team skills](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37127361001):
Windows/Linux, воспроизводимость архивов и XML source-kit smoke.

Первый [Editor CI](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37127361023)
обнаружил несогласованность версии внутреннего standalone builder с
обновлённым workflow: `1.7.0` против `1.7.1`. Остальные проверки этого запуска,
включая корпус, Go, NLP, eval contracts и Docker E2E, прошли. Сборщик исправлен;
дополнительно проверена переносимость ссылки research-intake в автономном
пакете. Девять packaging tests проходят, `build_team_skills.py --check`
подтверждает, что опубликованные архивы 1.1.0 не изменились. После исправления
повторный полный локальный прогон дал 454 passed, 36 skipped.

Для commit `d82cc75` полностью прошли
[Editor CI](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37128034662)
и [Portable Team skills](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37128034647).
Editor CI подтвердил Python 3.11/3.12/3.13 на Windows/Linux/macOS, корпус, Go,
NLP, eval contracts, Docker AMD64/ARM64, Compose health и полный pipeline E2E.
Локально Go/Docker не запускались; их результат подтверждён в GitHub Actions.
ResearchTeam не менялся в исправлении сборщика; его успешный CI относится
к `0a3f02c`. Итоговый commit отчёта не меняет runtime или архивы.

## Предыдущий выпуск 1.0.3

Свежая локальная проверка Windows, Python 3.13, 2026-10-03:

| Область | Результат |
| --- | --- |
| EditorTeam | 442 passed, 36 skipped: внешние интеграции не запускались |
| ResearchTeam | 224 tests OK |
| Research gates | Skill audit, benchmark release, semantic gold, recall plan PASS |
| Общие release/runtime tests | 26 tests OK; реальные ZIP, отказ при несовпадении версий, неизменность старых архивов, отсутствие частичного релиза при ошибке копирования, проверки input/output и исправлений Research; запуск подсветки напрямую из checkout при другой рабочей папке |
| Skills | 8 переносимых entrypoints и общий monorepo gate валидны |
| Plugin | Распакованный 1.0.3: Claude Code strict validation PASS |
| Сборка | 1.0.3 собран; `--check` подтверждает точный состав и воспроизводимость; старые выпуски не изменены |
| Статические проверки | Ruff check/format затронутого Python, actionlint и diff check PASS |

Итого в трёх наборах: 692 успешных теста, 36 пропущенных интеграционных тестов.
Незатронутые модули отдельно повторно не проверялись; portable smoke выполняет
их существующие проверки из ZIP. XML source kit сохраняет прежние байты; его
сборка из ZIP остаётся отдельным job в CI. Импорт навыков в облачные аккаунты
ChatGPT/Claude не выполнялся.

Для commit `00b1d81`, содержащего изменения Editor/Research и выпуск 1.0.2,
уже прошли [Research CI](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37079749058)
и [Portable Team skills](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37079749065).
Последний включает воспроизводимость и сборку XML source kit из ZIP на
Windows/Linux. 1.0.3 добавляет исправление локального запуска и отдельный smoke,
сохраняя архивы EditorTeam/ResearchTeam из 1.0.2 без изменения байтов.
Для того же commit прошёл [Editor CI](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37079749082):
Python 3.11/3.12/3.13 на Windows/Linux/macOS, корпус, Go, NLP, eval contracts,
Docker toolchain, Compose health path и полный pipeline E2E. Go/Docker локально
не запускались; здесь указан их подтверждённый результат GitHub Actions.

[Portable Team skills 1.0.3](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37080514563)
для commit `cc1047d` также завершился успешно: 26 release/runtime tests,
воспроизводимая сборка и XML source-kit smoke на Windows/Linux. Последующие
изменения этого отчёта не меняют runtime или содержимое архивов.

## Предыдущий выпуск 1.0.1

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

GitHub Actions завершились успешно:

- [Portable Team skills 1.0.1](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37076560190): воспроизводимость и XML source-kit smoke на Windows/Linux, commit `18d54de`.
- [Editor CI](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37076078439): Python 3.11/3.12/3.13 на Windows/Linux/macOS, Go, NLP, корпус, eval contracts и Docker E2E.
- [Research CI](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37076078564), [SVG CI](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37076078446), [Translate CI](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37076078513), [XMLTeam CI](https://github.com/Manacost-Labs/ManacostTeam/actions/runs/37076078419).

Модульные проверки относятся к commit `f6371cd`; следующий `18d54de` изменяет упаковку/версии и проходит отдельный packaging CI. Go/Docker локально не запускались; их runtime подтверждён GitHub Actions. Облачный импорт навыков в аккаунты ChatGPT/Claude не выполнялся. Переносимость относится к структуре и проверенным helpers с требованиями к среде из SKILL.md.
