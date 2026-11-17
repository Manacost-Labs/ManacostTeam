# Контракты пайплайна EditorTeam

Справочник для агента, который запускает runner, CLI и проверки. Правила
авторской работы над текстом — в ядре `SKILL.md`; здесь — как их исполняют
и проверяют инструменты. Ссылки ниже — на соседние файлы `references/`.

## Контекст автора в native runner

В native runner обязателен `context --artifact author-context.json`: пакет
возвращается при каждом `next` и проверяется по каждому пункту (порядок работы
с образцами — [publication-context](publication-context.md)).

## Полный запуск manacost-publish

Для полного возобновляемого запуска в Codex используй отдельный manacost-publish.
Он выполняет источники → handoff → draft → deletion_pass → независимые factual/literary reviews,
сохраняет версии и экспортирует результат после проверок. Runtime stdlib:
`PYTHONPATH=python python -m editorteam.publication_run --help`. Контроль цитат
и хешей не заменяет смысловую проверку reviewer и человеческое утверждение.
Новые native runs используют review_contract_version=4: функции абзацев,
вопросы читателя, strengths и объяснения потерь keep_spans; прежние runs без
поля версии читаются как v1 для истории. Export старых v1/v2/v3 требует нового
текущего run и независимой повторной проверки; не меняй state.json ради допуска.
Проверяющие не получают чужой verdict. Состояние
сравнительного исследования — в [пилоте](research-editor-pilot.md):
синтетические проверки механики не доказывают улучшение естественности статей.

В native v4 вычёркивание лишнего — отдельный этап `submit --stage deletion_pass`;
после revise/context он повторяется.

## Отзыв reviewer: структура и практики

Reviewer получает structure_assignment и проверяет каждый блок через
structure_review. Общее «связность хорошая» не заменяет разбор всей статьи.

Каталог [26 практик](editorial-practices.md)
`python/editorteam/editorial_practices.json` содержит вопрос, допустимый случай,
пример дефекта и действие для каждого подраздела статьи.
Для отдельной правки используй `editor-team editorial-review prepare/validate`
с `--text`, `--original` и независимым `--review`; источники передавай через
`--handoff`. В native v3 обязательны practice_checks, logic_checks,
preservation_checks и source_checks по назначению reviewer из `next`.

В Go `/v2/edit`, legacy `/edit` и
AG-UI обязательны все 26 практик, 5 logic_checks и 7 preservation_checks,
включая facts_only. В native отзывы делят 7 factual и 19 literary практик.
Обнаружение исходной ошибки отдельно оформляется original_factual_checks;
сохранение такой ошибки не даёт pass.
Исправление допускается с точными
цитатами исходника, результата и полного источника, подтверждающего замену.

Для изменённого текста author_voice и strengths требуют change_evidence
с точными парами цитат, disposition, reason, benefit и meaning_risk.

Бюджет слов genre_fit выводится из полных выбранных образцов author-context;
`genre_review` возвращает измерения из next и собственное объяснение объёма
и манеры. Не подставляй фиксированную норму или длину короткой цитаты.

## Вход для вычёркивания и owner-eval

На вход прохода вычёркивания подай `card_paraphrase.retelling`, `owner.overused_word`,
`owner.section_repeat`, `owner.forbidden_literal`, `owner.paragraph_starts` из
`editor-team audit статья.md --author-context context.json`; флаг совместим
с `--task-context`. Находка не приказывает удалять полезное. Если NLP недоступен
в минимальном runtime, получи audit полным EditorTeam; пустые findings при
`diagnostic_status=unavailable` не означают чистый текст.
[owner-eval](https://github.com/Manacost-Labs/ManacostTeam/blob/main/editor/docs/OWNER_EVAL.md):
`editor-team owner-eval <набор> --author-context context.json` измеряет охват
отклонений, а не одобрение владельца.

## Проверка источников

DOI проверяется
по метаданным и содержанию, ISBN также по контрольной цифре. 404 и UTM не
доказывают происхождение текста.

При сверке источников standalone factual/all CLI требует --handoff и --sources
sources.json: полные snapshots с provenance/SHA256 и report с sources_sha256.
Без handoff проверка исходника/кандидата не объявляет внешнее подтверждение:
source_verification=not_performed. Невалидные доказательства блокируют допуск.

При чтении переданных источников source_checks.access=snapshot. Заявленные
данные сбора, URL и SHA256 не подтверждают новый live-доступ или все факты.
Без источников явно укажи not_performed; возможно проверить сохранение текста,
но нельзя объявлять его внешне подтверждённым.
Для validate-edit передай --review и, при сверке
источников, --handoff/--sources.

## Инструменты: audit, semantic guard, корпус

Для инструментальной проверки запускай `python scripts/editor_team.py --help`, затем соответствующий audit или validate-edit.

Semantic guard проверяет оба направления отрицания, подмену чисел в совпадающих словесных формулировках и потерю ссылок с таймкодами. Перестановки предложений и объединение одинаковых ссылок допустимы. Глубокий пересказ и правильную привязку цитаты к совету сверяй вручную: автоматическая проверка не доказывает смысловую эквивалентность.

Для проверки корпуса используй
[независимый аудит](quality-audit.md) и `python -m editorteam.quality_audit`.
Сохраняй удачные фрагменты; указывай выборочный охват и исторический период.

## Общий контекст игр (task_context)

Для всех игр каталога можно передать [общий контекст](task-context.md):
`python scripts/resolve_context.py --game world-of-warcraft --profile manacost`
создаёт JSON для `audit`/`validate-edit --task-context context.json` и `/v2/edit`.
Редакционный profile внутри task_context — manacost; прежний `--profile` задаёт
жанр, например wow-guide или news. Если --profile resolver не задан, выбирается manacost. Без task_context прежний workflow сохраняется.
Neutral-профиль редактора пока не подключён; не выдавай его за выполненную проверку.

## Research handoff v1

Материал ResearchTeam принимай по [проверке входящего исследования](research-intake.md): прочитай handoff и банк деталей, сохрани ограничения и сверь каждое значимое число с его картой, действием и источником. Статус ready_with_warnings сохраняет оговорки; not_ready требует ограничить вывод или уточнить исследование. В готовом GUIDE условия нужны читателю, внутренние claim IDs — редактору.

В publication handoff v1 прочитай research_context, source_context,
evidence_context и контрдоказательства вместе с выводами. Decision_cards —
необязательные карточки: observed, derived и illustrative различают случай,
вывод и условный пример. Каждый заполненный фактический элемент опирается на
claims/evidence своей главы. Unknown/disputed и gaps не превращаются в советы.
Если для объяснения не хватает причины или исключения, верни адресный вопрос
research. Старый корректный v1 без новых полей остаётся поддержанным.

## Контекстные исправления: retrieval

В retrieval [контекстных исправлений](contextual-corrections.md) допускаются
спокойные сильные абзацы и образцы по функции,
с сохранением фильтров автора/игры/жанра и запрета копировать факты из стиля.

## Manacost MCP

В Manacost MCP ищи дополнительные материалы и читай все части до nextOffset=null.
Импорт `python -m editorteam.editorial_lab import-mcp` выполняется при
PYTHONPATH=python. Новые статьи остаются candidate; опубликованный текст не
становится автоматически gold и не подтверждает текущую мету. Платные тексты
и человеческие оценки храни отдельно от переносимого пакета.
