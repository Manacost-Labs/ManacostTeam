# Проверка Team standard 1.4.0

Windows, Python 3.13, 2026-10-10–11. План — [PUBLICATION_IMPLEMENTATION_PLAN.md](PUBLICATION_IMPLEMENTATION_PLAN.md), начало работы — [PUBLICATION_QUICKSTART.md](PUBLICATION_QUICKSTART.md).

| Область | Фактически выполненная проверка |
| --- | --- |
| EditorTeam Python | Полный прогон из editor: 639 passed, 36 skipped. После обнаруженного в пилоте дефекта и финального исправления отдельно пройдены 76 publication tests; эти числа пересекаются и не суммируются |
| Portable runtime | 31 tests OK; новый helper init/sources/next/status и отказ от непроверенного export проверены из ZIP с python -S, без checkout и site-packages, с русскими путями и пробелами |
| Код и навыки | Ruff check/format затронутых Python файлов, quick_validate source/installed skill и git diff --check PASS |
| Выпуск | Team skills 1.4.0, EditorTeam 1.4.0, новый manacost-publish 1.0.0; сборка и --check PASS; семь неизменённых навыков сохраняют прежние байты |
| Установка | Полный portable manacost-publish установлен в пользовательский skills folder; validate_bundle, quick_validate и --help PASS. Обновление picker в уже открытом чате не проверялось |
| Native MCP pilot | Фактически прочитан полный архивный источник; native researcher/author создал sources/handoff/draft. Первый литературный отзыв выявил недостаток и блокировал export. Исследование расширено двумя дословными цитатами в отдельном run; другой автор исправил текст, отдельные factual/literary reviewers проверили его; установленный helper с python -S довёл run до ready/export/status=unchanged |
| Дефект, найденный пилотом | Склонение названия ошибочно считалось новым фактом. Теперь капитализация и теги без ID дают untrusted entity_hints; hard gates сохраняют числа, точные URL и type:ID. Новые ID/тип тега блокируются; имя с другим падежом при том же ID допустимо. Смысл проверяет независимый reviewer |
| Пользовательский материал | Два автора отполировали все 10 рас, отдельный reviewer сверил полный текст с исходником. 331 шорткод/118 DBF сопоставлены живому каталогу, заменены string cardID и выделены целиком жирным. Обратная конверсия точно восстанавливает reviewed prose; labels/order сохранены. Исходная неоднозначность шага Нежити отмечена, клиент и актуальная мета не проверялись |
| Кандидатный benchmark | 12 реальных локальных полных MCP-материалов → 12 pending карточек; frozen train/holdout. Без реального human confirmation экспорт approved отклоняется; человеческое сравнение ещё не выполнено |

Начальный full pytest из корня вместо editor остановился на поиске локальных fixtures; корректный запуск из editor завершился успешно. На Windows задан PYTHONUTF8=1. Go/Research/Promptfoo в этой итерации не менялись и повторно не запускались; их результаты предыдущего выпуска приведены ниже как исторические.

Native reviews подтверждают выполненную модельную проверку источников и формы статьи, а не человеческое утверждение или текущую мету. Материалы/отзывы/каталог остаются локальными вне Git. Человеческая калибровка, измерение времени, LangExtract с моделью, semantic embeddings, DSPy/RAGChecker и расширенный Council не завершены. Снижение времени на 30% не измерено. Импорт в облачные аккаунты и публикация статей на сайте не выполнялись.

## Предыдущий выпуск 1.3.0

Локальная проверка Windows, Python 3.13, Go 1.26.9 и Node 24, 2026-10-10.
Контракт и границы реализации — [редакционный конвейер](EDITORIAL_PIPELINE_V3.md).

| Область | Результат |
| --- | --- |
| EditorTeam Python | 569 passed, 36 skipped; для subprocess на Windows установлен PYTHONUTF8=1. Начальный прогон без UTF-8 дал 7 ошибок кодировки; исходные файлы и эталоны не изменялись |
| EditorTeam Go | `go test ./...` и `go vet ./...` PASS; отдельные регрессии проверяют reconstruct, потерю условий/ссылок, блокировку handoff и разделение контекстов автора/проверяющего |
| ResearchTeam | 238 tests OK; пять новых сценариев chapter handoff и decision coverage |
| Promptfoo contracts | 22 Node tests PASS; реальный модельный benchmark не запускался |
| Общие release/runtime tests | 30 tests OK; новые Python CLI запускаются из распакованного ZIP без optional dependencies и checkout |
| Сборка | Выпуск 1.3.0, EditorTeam 1.3.0 и ResearchTeam 1.2.0; `--check` подтверждает состав и воспроизводимость. Шесть неизменённых навыков сохраняют прежние байты |
| Статические проверки | Ruff затронутых Python файлов, Go vet и diff check PASS |
| Manacost MCP | 12 полных материалов, 196 482 символа; проверены все части и UTF-16 offsets. Тексты находятся только в локальном ignored `build/editorial-lab`, статус candidate |
| Необязательные adapters | Trafilatura 2.3.1: реальное извлечение HTML проверено. LangExtract 1.7.1: установлен и проверен контракт объектов/интервалов; вызов модели не выполнялся |

Новые игровые примеры тестов синтетические. Фактологический review проверяет
форму модельного доказательства и дословные цитаты; истинность советов и
соответствие источников требуют отдельной проверки. Council, LangExtract с
моделью, semantic embedding, DSPy/RAGChecker и человеческий benchmark пока не
запускались. Снижение времени редактора на 30% не измерено. Импорт ZIP в
облачные аккаунты и production deployment не выполнялись; результаты CI
этого выпуска сюда не включены.

## Предыдущий выпуск 1.2.0

Локальная проверка Windows, Python 3.13 (набор editor — Python 3.12 в `.venv`),
Node 24, 2026-10-06 после добавления Typograf, SAGE и ru-text в EditorTeam:

| Область | Результат |
| --- | --- |
| EditorTeam | 563 passed, 36 skipped (было 454/36): 109 новых тестов — typography 55, ru_audit 31, spell_hints 23; Go, Docker и Vale локально не запускались |
| Общие release/runtime tests | 29 tests OK (было 28): typography и ru-audit запущены из распакованного ZIP без checkout и установленных зависимостей |
| Сборка | Выпуск 1.2.0; `--check` подтверждает точный состав и воспроизводимость; семь неизменённых архивов побайтно совпадают с 1.1.0 |
| Статические проверки | `ruff format --check` и `ruff check` для `src` и `tests`, `compileall`, `sync_skill.py --check`, `editor-team config validate`, `git diff --check` PASS |
| Typograf на корпусе автора | 49 гайдов: проверка и повторный запуск проходят, число слов и символов, заголовки и разделы `structure.py` прежние; `editor-team audit` на шести гайдах даёт те же находки и метрики для текста до и после |
| ru-text | два реальных аудита (контрольный гайд 7.9, слоп 6.2) приняты `ru-audit validate`, аудитор текст не менял |
| SAGE | только подставная модель; веса не скачивались, на реальной модели не запускался |

Типографика проверена на авторском корпусе, а не на всех жанрах: заголовки в
других форматах и склонённые названия карт защищены не полностью (см.
`editor/.claude/skills/hs-edit/references/external-checks.md`). Качество SAGE на
корпусе не измерено. Результаты GitHub CI выпуска 1.2.0 в этот отчёт не
включены.

## Предыдущий выпуск 1.1.0

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
