# Проход вычёркивания и рубрика владельца

Работа в `feat/owner-rejection-loop` поверх 69c626a и fe7365d. Исходное дерево
чистое, чужих изменённых путей не было. Ветка не переключалась; stash/reset,
слияние, push, сборка пакетов и платные API не выполнялись. Материалы набора
в build/ прочитаны без изменения и без переноса в Git; тестовые тексты синтетические.

Применены инженерный профиль EditorTeam, using-agent-skills,
planning-and-task-breakdown, test-driven-development, git-workflow-and-versioning,
codebase-design/domain-modeling/clean-architecture и context-engineering.
Manacost-ship применён с границами implementation-сессии из текущего задания:
без новых агентов, main, push и сборки. Синтетические проверки написаны по
code-testing; RED: отсутствующие Python owner_review и Go OwnerIDs/ApplyDeletion;
GREEN — результаты ниже. Serena/codegraph в клиенте отсутствуют, .codegraph нет;
использованы локальные исходники и rg. Новых библиотек, внешнего API или UI нет,
поэтому Context7, браузерные, нагрузочные и dependency-проверки не нужны.

## Поведение

Native v4 требует deletion_pass после draft и каждого revise/context до отзывов.
Редактор передаёт точные диапазоны удаления с причинами; runner воспроизводит
результат без поля нового текста. Исходник, результат и список остаются в artifacts.
На export проверяется воспроизведение receipt. Сокращение не подменяет проверку
смысла: независимые отзывы сохраняют полезные объяснения, условия и ограничения.
После сокращения ремонта baseline остаётся предыдущей редакцией статьи.

Десять owner_checks с цитатами обязательны в native и общем литературном
контракте. Неполнота и отсутствие цитаты блокируют приём. Отрицательные суждения
сохраняются с фрагментом для repair. Go не перепроверяет отрицательный owner
вердикт как ошибку формы: accept с issue становится repair с owner_review finding.

Замеры полного источника образца сохраняются в author-context; жанровый бюджет
выводится из выбранных образцов, не из общего корпуса или длины цитат. Проверка
не оценивает качество сравнения и не задаёт автоматического предела слов.
claim_kind передаётся без переклассификации старых claims. Writer/reviewer
получают одинаковую границу mechanic/observation/opinion и запрет слабого блока.

## Паритет Go

Морфологические анализаторы остаются в Python по контракту internal/analyzer.
Новые находки идут через server.analyze и server.validate; postflight Go получает
их через существующий adapter и передаёт cutter/critic. Отдельный перенос
словарей и порогов в Go не требуется. Явный запрет работает с author-context;
task_context метаданных игры не является author-context. Собственного поля
author-context в /v2/edit нет — новая точка входа для него не вводилась.

Go reconstruct/write выполняет отдельный deletion pass перед фактологическим
и литературным отзывами, включая каждый ремонт; receipts возвращаются отдельно
от статьи. Обычная ограниченная вычитка/facts_only не удаляет готовую авторскую
статью самовольно, но её критик обязан покрыть рубрику и дать точечный repair.
Retrieval Go содержит отрывки, поэтому бюджет полной статьи неизвестен; критик
получает прямую инструкцию не считать его по отрывкам.

## Проверяемые требования

| Требование | Синтетическое доказательство |
| --- | --- |
| Удаление до отзывов, receipts вне статьи | test_native_deletion_precedes_reviews_and_replays_saved_removals |
| Только точные удаления, без вставок и стирания всей статьи | test_deletion_replays_only_exact_nonoverlapping_removals; test_deletion_cannot_supply_new_text_or_erase_article; TestDeletionOnlyReceiptUsesRuneOffsetsAndRejectsAdditions |
| Полная рубрика и цитаты | test_rubric_requires_every_category_and_exact_nonempty_quotes; TestOwnerRubricCannotSkipCategoryOrQuote |
| Отрицательное суждение даёт repair с фрагментом | test_native_owner_verdict_blocks_export_and_preserves_fragment; TestOwnerIssueRemainsRepairWithQuoteWithoutSchemaRetry |
| Старые состояния читаются без нового экспорта | test_saved_v3_without_deletion_or_rubric_is_readable_but_cannot_export; test_historical_receipts_remain_readable_but_cannot_authorize_new_export |
| Жанровый бюджет из полных выбранных образцов | test_sample_budget_is_measured_from_whole_sources_and_not_excerpt |
| Четыре находки через server/analyze, audit/task-context и postflight | test_server_analyze_and_task_context_audit_receive_all_owner_findings; TestPythonAdapterKeepsOwnerDiagnosticsInAnalyzeAndPostflight |
| Детерминированные находки доходят cutter | TestDeletionStageReceivesDiagnosticsAndReturnsOnlyRemovals |
| Общие категории owner-eval и claim_kind без догадки | test_reviewer_categories_and_claim_guidance_match_owner_eval; TestClaimSemanticsSurvivePublicationHandoffWithoutClassifyingOldClaims |
| Полезные объяснения не удаляются ради длины | DELETION_GUIDANCE, OwnerPrompt и стандарт раздела 0; семантическая обязанность reviewer, не заявляемая как автоматическая гарантия |

## Проверки

Из каталога editor с PYTHONUTF8=1 и PYTHONIOENCODING=utf-8:
`.venv/Scripts/python -m pytest -q` — **1097 passed, 38 skipped,
5 subtests passed**, 393,14 секунды. Предыдущий полный прогон выявил два
устаревших сценария порядка/совместимости; они исправлены, финальный прогон чистый.

Из editor/go: `../../build/toolchains/go/bin/go.exe vet ./...` — exit 0;
`go.exe test -json ./...` — **629 успешных test cases (358 верхнего уровня),
18 пакетов с тестами**, exit 0. Обычный `go.exe test ./...` также выполнялся;
после дополнения сохранения reason выполнен итоговый полный JSON-прогон.
Ruff `.venv/Scripts/python -m ruff check src tests sidecars/nlp` — exit 0.
`.claude/skills/hs-edit/scripts/selftest.py` — 49 гайдов, 248157 слов,
все корпусные пороги пройдены, exit 0. Git diff --check — без ошибок.
Stdlib smoke с `python -S` прошёл на временной копии portable runtime:
next выдаёт deletion_pass, недоступный NLP честно помечается unavailable.
Живые прогоны не выполнялись; синтетика не доказывает улучшение статьи владельца.
Evals не менялись. Корневые package-проверки/сборка оставлены родителю по заданию.

## Перед сборкой у родителя

Добавить `editor/src/editorteam/owner_review.py` в resources manacost-publish
(`python/editorteam/owner_review.py`). EditorTeam копирует весь runtime; у
manacost-publish список файлов явный. teams/registry.json здесь запрещён к правке,
поэтому дополнение ресурса нужно выполнить вместе с родительским обновлением
версий и сборкой. Stdlib smoke проверен с этим единственным добавленным ресурсом.
Морфология не становится зависимостью минимального runner: без полного audit
он сообщает непроведённую диагностику и требует передать её редактору отдельно.

## Изменённые файлы

- `docs/OWNER_REJECTION_LOOP.md`
- `docs/PLAYER_EDITORIAL_STANDARD.md`
- `docs/PUBLICATION_CONTEXT.md`
- `docs/PUBLICATION_QUICKSTART.md`
- `docs/PUBLICATION_REVIEW_CONTRACT.md`
- `editor/.claude/skills/hs-edit/SKILL.md`
- `editor/.claude/skills/hs-edit/references/battlegrounds-strategy-template.md`
- `editor/docs/OWNER_EVAL.md`
- `editor/go/internal/analyzers/analyzer_test.go`
- `editor/go/internal/editorialreview/owner.go`
- `editor/go/internal/editorialreview/owner_test.go`
- `editor/go/internal/pipeline/contextual_review.go`
- `editor/go/internal/pipeline/factual.go`
- `editor/go/internal/pipeline/handoff.go`
- `editor/go/internal/pipeline/owner_review.go`
- `editor/go/internal/pipeline/owner_review_test.go`
- `editor/go/internal/pipeline/pipeline.go`
- `editor/go/internal/pipeline/pipeline_test.go`
- `editor/go/internal/pipeline/publication_context.go`
- `editor/go/internal/reviewfixture/review.go`
- `editor/src/editorteam/cli.py`
- `editor/src/editorteam/editorial_practices.py`
- `editor/src/editorteam/owner_eval.py`
- `editor/src/editorteam/owner_review.py`
- `editor/src/editorteam/publication_context.py`
- `editor/src/editorteam/publication_review.py`
- `editor/src/editorteam/publication_run.py`
- `editor/src/editorteam/server.py`
- `editor/tasks/owner-rejection-loop-2026-11-10.md`
- `editor/tests/test_article_structure.py`
- `editor/tests/test_editorial_integrity.py`
- `editor/tests/test_editorial_practices.py`
- `editor/tests/test_owner_review.py`
- `editor/tests/test_publication_context.py`
- `editor/tests/test_publication_run.py`
- `editor/tests/unit/test_owner_checks.py`
- `teams/editor-team/SKILL.md`
- `teams/manacost-publish/SKILL.md`
