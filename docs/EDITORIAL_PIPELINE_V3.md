# Редакционный конвейер: первый этап реализации

Плохой черновик пересобирается по проверенным утверждениям и вопросам игрока.
Условия, исключения и источники проходят отдельную проверку до приёма текста.
Обычная редактура и старый `rewrite` сохраняют свой API; новый контракт явно
включается через `mode=reconstruct` и `research_handoff`.

## Выполнено

- Go `POST /v2/edit` принимает versioned ResearchHandoff и новый режим.
- `reconstruct` не получает установку минимальной правки, не наследует план
  исходника и защищает факты из handoff, а не непроверенные цифры черновика.
- Фильтр source_claims сохраняет action, condition, exception, evidence_refs,
  status, confidence, patch и meta_epoch. Произвольное поле source не передаётся.
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

## Контракт исследования

Существующий evidence bundle сначала проходит его обычные provenance,
freshness и semantic validators. Затем подготовьте отдельный editorial plan:

```json
{
  "brief": "Объяснить решения игрока в заданной теме",
  "patch": "подтвержденный-патч",
  "style_profile": "battlegrounds-guide",
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
