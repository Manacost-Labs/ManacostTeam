# Редакционный конвейер: исследование, автор и независимые проверки

Плохой черновик пересобирается по проверенным утверждениям и вопросам игрока.
Условия, исключения и источники проходят отдельную проверку до приёма текста.
Обычная редактура и старый `rewrite` сохраняют свой API; новый контракт явно
включается через `mode=reconstruct` и `research_handoff`.

## Выполнено

- Go `POST /v2/edit` принимает versioned ResearchHandoff и новый режим.
- `reconstruct` не получает установку минимальной правки, не наследует план
  исходника и защищает факты из handoff, а не непроверенные цифры черновика.
- Фильтр source_claims сохраняет action, condition, exception, evidence_refs,
  status, confidence, patch, meta_epoch и research_context. Произвольное поле
  source не передаётся.
- Обязательные вопросы главы связаны с переданными утверждениями. Пробел в
  критическом вопросе, неизвестный источник или другой патч блокирует пересборку.
- Фактологический review видит только candidate и handoff. Для каждого
  обязательного совета он возвращает дословные цитаты действия, условия и
  исключения; отсутствующая/вымышленная цитата или неподтверждённый статус
  отклоняет результат и возвращает исходник. Это модельная оценка с проверкой
  формы доказательства, а не автоматическое доказательство истины.
- `EDITOR_REVIEW_MODEL` позволяет отделить проверяющую модель от автора на
  текущем provider, включая существующий AG-UI маршрут. Без настройки
  используется та же модель с отдельным контекстом. Result сообщает обе модели.
- Ведущий автор и литературный critic проверяют цельность статьи и повторы
  между главами. Максимум targeted repair остаётся равным двум.
- Необязательные контексты источника, evidence и утверждения сохраняют
  происхождение, основания уверенности, ограничения и контрдоказательства.
  Структурированные decision_cards связывают каждую фактическую деталь с
  проверенными утверждениями и evidence своей главы.
- Author analysis фиксирует точные strengths до изменения. Draft, repair и
  critic получают keep_spans; потеря такого фрагмента при приёме требует
  конкретного объяснения, а не только высокого style score.
- Новые native Codex runs используют review_contract_version=2: литературный
  review включает функции абзацев и проверку вопросов читателя. Старые runs
  без этого поля читаются как v1; schema_version handoff и state остаётся 1.
- CLI компилирует chapter handoff и очередь вопросов для одной адресной волны
  поиска. Наличие очереди не означает, что поиск или дебаты выполнены.
- MCP corpus importer проверяет полную цепочку частей, UTF-16 offsets, длину,
  URL, снимок и access; удаляет дубли URL, предпочитая full. Все новые статьи
  получают candidate, unassigned и требование перепроверки текущего патча.
- Подготовлены слепые сравнения с отдельным ключом вариантов и полями времени
  редактора. Незаполненные оценки остаются null.
- Promptfoo сравнивает edit/reconstruct по private human-approved cases.
- Trafilatura и LangExtract подключены через необязательные Python extras;
  извлечённые советы требуют проверки и не попадают автоматически в claims.
- Sentence Transformers имеет отключаемый адаптер поиска похожих абзацев.
  RAGChecker и DSPy получают экспорт размеченных данных с отдельным holdout.
  Автоматическая оптимизация промптов и эти модельные проверки пока не запускались.

## Масштаб работы и реальный прогресс

Объём исследования выбирается по вопросу и жанру. Короткий ответ или локальная
правка не требуют полного дерева вопросов, карточек решений или нескольких
вариантов вступления. Для сложного гайда полезны условия, цена выбора,
альтернативы и исключения, способные изменить рекомендацию.

`plan.json` может содержать reader, reader_questions, research_budget и
query_localization. Для RU/EN нужны осмысленные отдельные search_phrases и
подтверждённые языковые имена сущностей. Планировщик не переводит и не выполняет
поиск. После чтения observations сохраняют новые факты, условия, исключения,
контрдоказательства, изменение уверенности и followup_questions с evidence.
`plan_queries.py RUN --question-gaps --json` формирует ограниченную очередь
вопросов; `--coverage-gaps` по-прежнему отвечает за охват площадок и разделов.

Search coverage раздельно считает планы, попытки, успешные поиски, просмотренные
материалы и полезное evidence. failed/blocked не закрывают ветку; skipped не
является попыткой. no_results фиксирует выполненный поиск, но не прочитанный
источник и не насыщение. Насыщение требует трёх последовательных разных
просмотренных материалов без полезной новизны; повтор URL, snippet или ошибка
доступа этот счётчик не продвигают. Новое условие либо контрдовод сбрасывает его.
Незакрытые вопросы сохраняются даже после search_exhausted; это не готовность
статьи. Бюджет — верхний предел, а не число запросов, которое нужно заполнить.

Текущую актуальность подтверждают реальные official_checks справочника с
checked_at и покрываемым through. Дата изменения файла updated_at этого не
доказывает. Для исторического вопроса задаётся temporal_scope.as_of; к нему не
подставляется сегодняшний патч. Все свежие даты — записи выполненных проверок,
не способ сделать validator зелёным.

## Контракт исследования

Существующий evidence bundle сначала проходит его обычные provenance,
freshness и semantic validators. Затем подготовьте отдельный editorial plan:

```json
{
  "brief": "Объяснить решения игрока в заданной теме",
  "patch": "подтвержденный-патч",
  "style_profile": "battlegrounds-guide",
  "editorial_context": {"reader": "возвращающийся игрок", "reader_task": "понять условия выбора"},
  "chapters": [{
    "chapter_id": "CH-1", "title": "Когда выбирать стратегию",
    "required_claim_ids": ["CLM-1"],
    "decision_examples": [], "counterexamples": [], "unresolved_questions": []
  }],
  "decisions": [{
    "question_id": "Q-1", "chapter_id": "CH-1",
    "question": "При каких условиях выбирать стратегию?",
    "required": true, "status": "answered", "claim_ids": ["CLM-1"]
  }]
}
```

`claims.jsonl` содержит claim_id, claim/meaning, action, condition, exception,
confidence (high/medium/low), patch, status (supported/supported_with_conditions)
и supporting_evidence_ids. Evidence содержит дословный quote/verbatim_quote,
source_id и locator; аналитическая faithful_paraphrase не подменяет цитату.
Sources содержит URL и access_integrity=full_text/full/inspected. Компилятор
сохраняет отдельные evidence IDs и locators, даже когда URL один.

Расширения v1 необязательны; старый корректный handoff принимается без них:

| Поле | Содержание и граница |
| --- | --- |
| `editorial_context` | Аудитория, задача и редакционный замысел; это не новый источник фактов. |
| `claim.research_context` | Тип evidence, confidence_basis, inference_steps, scope, limitations, contradictions и прочие сохранённые исследовательские поля. |
| `source.source_context` | Автор/издатель, даты, период, тип источника, выборка, ранг, ограничения, lineage/upstream — если они были установлены. |
| `source.evidence_context` | Контекст конкретной выдержки; цитата и locator остаются отдельными полями. |
| `source.semantic_reviews`, `claim_hashes` | Проверки и хеши привязанных записей; одна выдержка может подтверждать несколько claims без потери их хешей. |
| `claim.research_context.counterevidence` | Самостоятельные записи контрдоказательств: evidence_id, original_source_id, URL, quote, locator, content/evidence/source SHA256, source_context, evidence_context, semantic_reviews. |

Связанные записи `contradictions.jsonl` сохраняются в
`research_context.contradictions` вместе с outcome, reason и record_sha256.
Их counter_evidence_ids также разрешаются в проверенные снимки и цитаты;
открытый спор остаётся в gap queue. Native submit сверяет контрдоказательства
с полными собранными текстами и content_sha256. Прямой Go API проверяет
структуру и ссылки handoff, но не имеет доступа к локальным снимкам bundle;
это не замена предварительной проверки исследования.

Поля `author`, `meaning`, `reader_level` в Go Request передают квалификаторы
в подбор правил; author/meaning доходят и до postflight. Новые поля объяснения
правки reader_problem/benefit/meaning_risk сохраняются в Result.
| `chapter.decision_cards` | Необязательные карточки решений с проверяемыми основаниями каждого заполненного поля. |

Контекст переносится без полного тела исходного документа; полные snapshots
остаются в рабочем наборе. Отсутствующее значение остаётся неизвестным.
Контрдоказательство не добавляется в supporting evidence как будто оно
подтверждает совет. Writer и factual reviewer видят ограничения вместе с
выводом; ссылки и хеши устанавливают прослеживаемость, но не смысловую истинность.

В decision_card задаются card_id, question, kind, status, fields и gaps.
Kind различает `observed` (наблюдаемый случай), `derived` (вывод) и
`illustrative` (явно условный пример). Status: supported, inference, disputed
или unknown. В fields допустимы situation, options, action, reason, tradeoff,
exception, example, counterexample; заполняются только полезные и подтверждённые.
Каждое поле содержит `{text, claim_ids, evidence_refs}` с непустыми ссылками
на claims этой главы и их evidence. Не требуется заполнять весь шаблон.

Условный пример не выдаётся за реально сыгранную партию. Его фактические
компоненты и последствия также требуют оснований. Disputed/unknown карточка
содержит gaps и не становится готовым советом; gaps порождают адресные вопросы
и исключают статус research_ready. При карточках factual report обязан явно
подтвердить `decision_cards_checked=true` после проверки смысла каждого поля.
Старые decision_examples/counterexamples со строками продолжают требовать
проверенный meaning своей главы; более богатые примеры используют decision_cards.

```powershell
python research/deep-research/scripts/editorial_handoff.py RUN --plan editorial-plan.json --output RUN/publication-handoff.json --report RUN/decision-coverage.json
```

В переносимом research-team та же команда находится в `scripts/`.
Выходные файлы должны быть новыми. Статусы: research_ready,
research_ready_with_gaps и research_blocked. Контроль схемы не подтверждает,
что вручную указанный supported соответствует реальному источнику.

В `/v2/edit` передайте исходник в text, mode=reconstruct, а содержимое
publication-handoff.json объектом research_handoff. При необходимости передайте
current_patch: он должен совпадать с handoff.patch. Ответ accepted означает
приём редакторского результата, а не разрешение на публикацию.

## Работа автора и редактора

Сначала определить читателя, его задачу, жанр и тезис из материала. Если выбор
начала действительно влияет на понимание, сравнить до трёх вариантов и оставить
один; это не обязательный этап для любой новости. Обратный план обозначает
функцию абзаца: что он добавляет и почему стоит здесь. Проверка всей статьи
ищет повторы между главами, пропущенные связи и противоречащие рекомендации.

Для совета объяснить действие, причину, условия и альтернативу настолько,
насколько это нужно читателю и поддержано evidence. Авторская позиция возникает
из обоснованного выбора и оценки, а не выдуманного личного опыта. Если данных
для объяснения нет, сохранить пробел или передать адресный вопрос research.
Содержательная правка называет проблему читателя, пользу и риск смены смысла.

Go analysis сохраняет `strengths:[{quote,reason}]` из исходника. Native runner
переносит в `keep_spans` точные сильные фрагменты, отмеченные независимым
литературным reviewer в предыдущих версиях. Новая утрата требует единственного
`strength_changes` с quote, reason и дословной replacement_quote либо объяснённым
удалением. Это защита полезного фрагмента, а не запрет на исправление факта.
Сильный исходник может остаться unchanged.

Retrieval ищет по всем подходящим абзацам и по функции: механизм, сравнение,
предупреждение, вывод, переход, авторское замечание. Спокойному абзацу не нужна
квота soul-сигналов. Фильтры игры/жанра/автора, дедупликация, исключение исходника
и лимиты контекста сохраняются. Уровень читателя учитывается при известных
метаданных. Функциональная классификация эвристическая, не оценка качества;
образцы дают форму и не подтверждают факты или право копировать формулировки.

Corrections сохраняют author/game/genre/meaning/scope/context/reason и при
наличии предложение модели. Только явно установленные language_norm и
author_global дают обязательные term/phrase замены. Local, fact и structure
остаются контекстными примерами; старые записи без scope читаются как local.
Неизвестная квалификация не считается совпадением. Python выбирает одну
политику для prompt и postflight, Go и CLI передают тот же контекст.
Learn поддерживает вставки, удаления и длинные изменения, а не только термины.

Голос, ритм и отсутствие слова в архиве — диагностика во всех глубинах.
Их снижение не требует добавить «вы», союз, скобку или короткую фразу и не
отклоняет правку само по себе. Защита фактов, условий, исключений, отрицаний,
числовых ролей и осторожности остаётся обязательной.

## Native review v2 и совместимость

Новый `publication_run init` устанавливает review_contract_version=2.
Литературный report содержит strengths (допустим пустой список), непустой
paragraph_functions с реальными quote/function, whole_article_checked=true и
reader_check с action/reason/conditions/alternative. Для неприменимого вопроса
нужно пояснение по жанру, а не выдуманный совет. Findings содержат benefit и
meaning_risk наряду с quote/reason/suggestion. Это форма отчёта рецензента,
не обязательная композиция читательской статьи.

Независимые reviewer tasks получают source snapshots, research и draft без
чужих отзывов и ожидаемого verdict. Keep_spans из прошлых ревизий сохраняются
отдельно как цитаты с причиной. Обе проверки привязаны к текущим article/handoff
хешам и повторяются после ревизии. Старые runs без review_contract_version
остаются v1; существующие хеши и receipts не переписываются. Даже для v1
присутствующие strengths/paragraph_functions и объяснения потерь keep_spans
должны быть корректными. Модельный pass
не является человеческим утверждением или доказательством истины.

## Материалы MCP и оценка

Для каждого get_content сохраняйте `{request:{id,textOffset},response:{data,retrievedAt}}`.
Переходите по nextOffset до null; поисковый text длиной 500 знаков не является
полным материалом. Не используйте get_source_status counts как оценку качества.

```powershell
$env:PYTHONPATH = 'editor/src'
python -m editorteam.editorial_lab import-mcp mcp-pages.json --output candidates.json
python -m editorteam.editorial_lab blind variants.json --output blind.json --key key.json --seed 17
python -m editorteam.editorial_lab summarize measured-reviews.json --output summary.json
```

В portable editor-team используйте PYTHONPATH=python. Файлы candidates,
variants, оценки и ключ хранятся локально. Не включайте платные статьи в Git,
release ZIP, публичные traces или примеры. До использования как gold человек
проверяет факты, обязательные вопросы и эталонную версию; split train/holdout
фиксируется до настройки. В blind variants каждая статья имеет минимум два
варианта, один baseline, одинаковый patch и непустой text. Reviewed строка
содержит реально измеренные editor_minutes и critical_errors.

В репозитории отдельный набор:

```powershell
$env:EDITOR_EVAL_PUBLICATION_CASES = 'путь-к-локальному-approved-gold.json'
$env:EDITOR_EVAL_CANDIDATE_GATEWAY_URL = 'http://127.0.0.1:8741'
npx promptfoo eval -c editor/evals/promptfooconfig.publication.yaml
```

Формат cases: id, source, reference, research_handoff, review_status=approved,
split=train/holdout. Загрузка опубликованных статей не устанавливает approved.
Этот эксперимент сравнивает режимы одного нового gateway; прежний baseline
pipeline проверяется отдельным существующим promptfooconfig.pipeline.yaml.

## Необязательные инструменты

```powershell
python -m pip install -e 'editor[editorial-extraction]'
python -m editorteam.editorial_tools doctor
python -m editorteam.editorial_tools html source.html --output extracted.json
python -m editorteam.editorial_tools advice source.txt --model HOSTED_MODEL_ID --output advice-candidates.json
python -m editorteam.editorial_tools duplicates paragraphs.json --model EMBEDDING_MODEL_ID --output duplicate-candidates.json
python -m editorteam.editorial_tools export-evals approved-cases.json --output evaluation-exports.json
```

Cloud LangExtract требует настроенного provider/key; установка библиотеки не
запускает модель. Непривязанные к исходнику извлечения отклоняются. Для
semantic adapter отдельно установите extra editorial-semantic и явно выберите
многоязычную embedding-модель; локальная генеративная LLM не устанавливается.
Похожие абзацы отмечаются для редактора, автоматически ничего не удаляется.
Для DSPy и RAGChecker предусмотрены extras editorial-optimization и
editorial-rag-eval. Экспорт требует case_id, question, response, reference,
retrieved_context, review_status=approved и split. Holdout не входит в dspy_train.

## Следующие этапы и критерии

Состояние измерений и воспроизводимый запуск описаны в
[docs/RESEARCH_EDITOR_PILOT.md](https://github.com/Manacost-Labs/ManacostTeam/blob/main/docs/RESEARCH_EDITOR_PILOT.md).
Зафиксированы десять синтетических development cases и контроль повреждения
числа; это проверка механики, не сравнение качества реальных статей. Живые
baseline/candidate прогоны, новые проверенные материалы и человеческие оценки
остаются отдельным этапом. Незаполненная оценка не считается ничьей или нулём.

1. Разметить первые 10–20 материалов и измерить время текущего процесса.
2. Запустить hosted extraction и слепое сравнение на одинаковых источниках,
   патче и бюджетах; отдельно проверить полезность и естественность русского.
3. Подключать Council из трёх независимых исследователей только отдельным
   экспериментом: official/statistics, expert practice, gaps/counterexamples.
   До объединения роли не читают выводы друг друга. Gap Hunter сначала получает
   brief, вопросы и IDs утверждений; существенный спор решается evidence,
   максимум два раунда, затем сохраняется неопределённость. Голосование не gate.
4. Запускать DSPy/GEPA, RAGChecker и semantic ranking после калибровки по
   человеческим оценкам. Jev, Graphiti, новая observability и медиатранскрипция
   остаются отдельными экспериментами по измеренной потребности.

Нулевая критическая ошибка и сохранение всех обязательных условий — критерии
приёма материала. −30% времени редактора и ≥90% покрытия — гипотезы для
человеческого benchmark, не достигнутые показатели этого выпуска.
