# Использование Manacost Publish

Для работы в Codex используйте установленный `$manacost-publish`. Генерацию,
поиск и независимые отзывы выполняет Codex через доступные инструменты.
Python helper сохраняет этапы, проверяет артефакты и позволяет продолжить запуск.

## Первый запрос в чате

```text
$manacost-publish
Подготовь практическую статью по теме [тема] для [аудитория].
Используй Manacost MCP и проверь актуальность советов.
Формат: [гайд/статья/разбор], объём: [ориентир].
Без WordPress-шорткодов. Сохрани рабочий запуск и выдай полный материал.
```

Для предоставленной статьи можно написать:

```text
$manacost-publish
Пересобери этот материал: [ссылка или текст]. Сохрани условия и оговорки,
проверь факты по источникам и убери повторы. Без шорткодов.
```

Если нужна только полировка уже готового текста, используйте `$editor-team`:

```text
$editor-team Отполируй этот материал и сделай его живее.
Сохрани все существующие шорткоды, числа, составы, условия и оговорки.
Не добавляй новые факты. Выдай полный текст и файл.
```

Для такой правки пользовательский исходник сохраняется отдельно; отзывы
сверяют смысл с ним. HTTP-источники и research handoff runner нужны для
исследования или пересборки по evidence. Не придумывайте URL для текста из чата.

Старый материал можно адаптировать как архивный пример; его дата должна быть
явной, а советы о текущей мете требуют отдельной свежей проверки.

Продолжение:

```text
$manacost-publish Продолжи запуск из [абсолютный путь к папке запуска].
```

Для source skill в checkout используйте `teams/manacost-publish/scripts/publish.py`.
Для установленного или распакованного навыка — `scripts/publish.py` от его корня.
На Windows для русских subprocess установите `$env:PYTHONUTF8 = '1'`.
Новый навык обнаруживается Codex из его skills folder; при необходимости
начните новый чат, чтобы обновился список доступных навыков.

## Команды runner

Пример из корня репозитория; замените параметры темы и патча:

```powershell
$env:PYTHONUTF8 = '1'
python teams/manacost-publish/scripts/publish.py init build/publication-runs/my-article --brief 'Тема, аудитория и границы статьи' --patch 'проверенный-патч-или-период' --profile battlegrounds-guide --shortcodes off
python teams/manacost-publish/scripts/publish.py next build/publication-runs/my-article
python teams/manacost-publish/scripts/publish.py status build/publication-runs/my-article
```

`next` возвращает роль, инструкции, пути к сохранённым входам и хеши. Это
задание для Codex, а не свидетельство выполненного поиска или генерации.

| Этап | Что подготовить | Что проверяется |
| --- | --- | --- |
| sources | JSON массив полных source candidates | full/public, ID, URL, текст, SHA256, provenance и время доступа |
| research | publication-handoff.json | патч, статус, вопросы/claims, цитаты из уже сохранённых источников |
| draft | UTF-8 article.md | непустой текст; далее проверяют два reviewer |
| fact_review | factual.json | хеши, цитаты, советы/условия/уверенность, источники, отсутствие новых неподтверждённых сущностей |
| literary_review | literary.json | хеши, польза, цельность, русский язык, голос и отсутствие неисправленных замечаний |
| ready | новый final.md | обе проверки относятся к текущему тексту и handoff |

Пример сохранения этапа:

```powershell
python teams/manacost-publish/scripts/publish.py submit build/publication-runs/my-article --stage sources --artifact build/local-inputs/sources.json
```

Для следующего этапа меняются stage и artifact. Копии входов сохраняются в
папке запуска; исходные файлы не перезаписываются. Схема отзывов — в
[контракте проверок](PUBLICATION_REVIEW_CONTRACT.md).

## Подготовка источников и handoff

Manacost MCP get_content сохраняется как массив
`{request:{id,textOffset},response:{data,retrievedAt}}`; все nextOffset
дочитываются до null. Для его импорта в checkout:

```powershell
$env:PYTHONPATH = 'editor/src'
python -m editorteam.editorial_lab import-mcp build/local-inputs/mcp-pages.json --output build/local-inputs/sources.json
```

В portable skill используйте PYTHONPATH=python. Публичные оригинальные веб-
источники также можно сохранить в нормализованный source candidate: id,
source, url, text, access=public, sha256, retrieved_at. Access=public означает
сохранённое полное содержимое, а не доступность только preview.

Research сохраняет ledgers и план по [контракту handoff](EDITORIAL_PIPELINE_V3.md).
Из checkout:

```powershell
python research/deep-research/scripts/editorial_handoff.py RUN --plan editorial-plan.json --output RUN/publication-handoff.json --report RUN/decision-coverage.json
```

В portable skill compiler лежит в scripts/editorial_handoff.py. Включены и
обычные scripts/references ResearchTeam для применимых bundle validators.
Не присваивайте ready неподтверждённому пакету и не выдумывайте результаты поиска.

## Исправления и экспорт

```powershell
python teams/manacost-publish/scripts/publish.py revise build/publication-runs/my-article --artifact build/local-inputs/corrected.md
python teams/manacost-publish/scripts/publish.py export build/publication-runs/my-article --output build/publication-runs/my-article/final.md
```

Максимум две ревизии. Каждая сбрасывает обе проверки, сохраняя прежние версии.
Для исправленного текста нужны новые независимые отзывы. Gate нельзя обходить
подстановкой pass или переписыванием state.json. Повреждение сохранённого
артефакта обнаруживается при status/next. Итоговый файл создаётся только новым.

Если ошибка находится в отчёте (например, reviewer записал неверный хеш),
для текущего blocked review допускается один повторный отзыв без изменения статьи:

```powershell
python teams/manacost-publish/scripts/publish.py submit build/publication-runs/my-article --stage fact_review --artifact build/local-inputs/rechecked-factual.json --retry-review
```

Такой recheck сохраняет предыдущий отчёт и не расходует две ревизии текста.
Содержательная ошибка статьи требует revise. Перенос экспортированного final.md
отображается в export_status и не повреждает внутренние сохранённые артефакты.

## Человеческая оценка

В подготовленном локальном benchmark есть source.md и annotation.json на
каждый материал. Поля фактов, условий, ошибок и reference сначала pending/null.

```powershell
python teams/manacost-publish/scripts/publish.py benchmark prepare build/editorial-lab/candidates.json --output build/editorial-lab/my-benchmark --seed 17
python teams/manacost-publish/scripts/publish.py benchmark export-approved build/editorial-lab/my-benchmark --output build/editorial-lab/approved.json
python teams/manacost-publish/scripts/publish.py benchmark summarize build/editorial-lab/ratings.json --key build/editorial-lab/blind-key.json --output build/editorial-lab/comparison.json
```

Approval содержит human_confirmed, reviewer и reviewed_at ISO с timezone;
также нужны исправленный reference, reference_edit_confirmed и тезисы с
реальными цитатами. Экспорт не создаёт исследование или research_handoff.
Promptfoo cases дополняются проверенным handoff по прежнему publication contract.
Числа времени/ошибок отражают только реальные заполненные парные оценки.

Источники, отзывы, ключ вариантов и разметка остаются локальными. Ready по
модельным проверкам не равняется человеческому одобрению или публикации.
