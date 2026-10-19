# Отзывы native Codex: контракт и независимость

Автор и reviewers работают в отдельных контекстах. Фактологический reviewer
получает полный candidate, handoff и сохранённые source snapshots. Литературный
получает candidate, brief/жанр, голос и необходимые исследовательские ограничения.
Не сообщайте ожидаемый verdict и не передавайте self-review автора.
`next` не включает отчёт одного reviewer во входы другого. Сильные цитаты
прошлых литературных проверок передаются отдельно как keep_spans с причиной,
без прежнего verdict. Это не утверждение, что разные модели независимы
статистически: речь об отдельных контекстах и отсутствии подсказанного ответа.

Новые runs имеют `state.review_contract_version=2`, при `state.schema_version=1`.
Старые runs без поля review_contract_version читаются как v1 и не требуют
перезаписи артефактов. Схема handoff также остаётся 1: research_context,
source_context/evidence_context, decision_cards и editorial_context —
необязательные расширения. Проверка хешей и смысловые обязанности сохраняются.

## Привязка к версии

`article_sha256` считается от UTF-8 строки candidate. В runner не меняйте
переводы строк между чтением и проверкой: используйте bytes.decode('utf-8').
`handoff_sha256` — SHA256 UTF-8 JSON с sort_keys=true, ensure_ascii=false,
separators=(',', ':'), finite JSON. Функции article_hash/handoff_hash в
editorteam.publication_review задают точный контракт; next возвращает хеши.

## Factual

```json
{
  "article_sha256": "хеш текущего текста",
  "handoff_sha256": "хеш текущего handoff",
  "status": "pass",
  "confidence_preserved": true,
  "candidate_checked": true,
  "patch_matches": true,
  "decision_cards_checked": true,
  "unsupported_claims": [],
  "conflicts": [],
  "claims": [{
    "claim_id": "CLM-1",
    "status": "supported",
    "action_quote": "дословный совет из candidate",
    "condition_quote": "дословное условие из candidate",
    "exception_quote": "дословное исключение из candidate",
    "confidence_quote": "дословная оговорка уверенности из candidate",
    "evidence_refs": ["EVD-1"]
  }]
}
```

Для каждого required claim нужен ровно один row. action_quote обязательна,
condition_quote/exception_quote обязательны, когда соответствующее поле
claim непустое. confidence_quote обязательна для medium/low; она должна
показывать сохранение ограниченной силы совета, а не произвольный фрагмент.
Для high допустима пустая confidence_quote. Ссылки в статье должны быть точными
URL соответствующих evidence_refs. Нельзя ссылаться на другой claim/source.

`candidate_checked=true` обязательно: это подтверждение проведённой проверки
всех фактических утверждений, а не только строк из claims. Отсутствие поля,
false или null блокируют готовность даже при остальных положительных оценках.
Проверяющий оценивает ВСЮ статью: любой новый неподтверждённый совет заносится
в unsupported_claims; противоречие — в conflicts. При ошибке используйте
status=repair/blocked, false для нарушенного confidence_preserved/patch_matches
и объяснение с конкретной цитатой. Не назначайте supported только из-за
совпадения слов. Программа контролирует наличие цитат, хеши, новые числа,
точные URL и идентификаторы карт вместе с типом шорткода. Падеж названия внутри
шорткода не меняет ID. Слова с заглавными буквами и шорткоды без ID возвращаются
как непроверенные entity_hints для reviewer, а не автоматические ошибки:
склонение "Налаа Искупительница" не доказывает появления новой карты.
Проверь смысл подсказок по evidence и занеси выдуманные советы в unsupported_claims.
Семантическую истину программа не доказывает.

Если хотя бы одна глава содержит decision_cards, требуется
`decision_cards_checked=true`. Его ставит reviewer после проверки смысла
каждого заполненного поля, его claim_ids/evidence_refs, причинного вывода и
статуса примера. Без карточек это поле необязательно. Наблюдаемый эпизод,
вывод и условный illustrative пример не взаимозаменяемы. Неизвестное и
спорное из gaps не становится поддержанным советом.

Проверяйте provenance, confidence_basis, inference_steps, ограничения выборки
и периода в research_context/source_context/evidence_context. Отдельные
research_context.counterevidence содержат цитаты, locators и хеши возражений;
не интерпретируйте их как положительное подтверждение. Новые сохранённые
поля доступны reviewer, но их наличие не является автоматической проверкой.

## Literary

```json
{
  "article_sha256": "хеш текущего текста",
  "handoff_sha256": "хеш текущего handoff",
  "status": "pass",
  "dimensions": {
    "usefulness": "pass",
    "coherence": "pass",
    "natural_russian": "pass",
    "author_voice": "pass"
  },
  "strengths": [{"quote": "точная удачная цитата из candidate", "reason": "чем она полезна читателю"}],
  "paragraph_functions": [{"quote": "точная цитата абзаца из candidate", "function": "объясняет условие выбора"}],
  "whole_article_checked": true,
  "reader_check": {
    "action": "что предлагается делать, либо почему вопрос неприменим",
    "reason": "почему это обосновано, либо пояснение по жанру",
    "conditions": "при каких условиях, либо пояснение по жанру",
    "alternative": "когда выбрать иначе, либо пояснение по жанру"
  },
  "strength_changes": [],
  "findings": []
}
```

Для ошибки dimension получает fail, status=repair/blocked; finding содержит
category, severity (info/warning/error/blocker), quote, reason, suggestion.
В v2 также нужны benefit и meaning_risk для каждого finding: ожидаемая
читательская польза и риск смыслового сдвига. Quote дословно из candidate.
Проверяйте практические вопросы читателя,
последовательность объяснений и причин, повторы/противоречия между главами,
штампованные связки, ритм и естественность языка. Предпочтение одного вкусового
варианта не является ошибкой без конкретной причины. Info не блокирует,
а неисправленные warning/error/blocker требуют ревизии.

V2 требует strengths (список может быть пустым: не выдумывайте достоинства),
непустой paragraph_functions, whole_article_checked=true и четыре непустых
ответа reader_check. Quote в strengths/paragraph_functions должен присутствовать
в candidate; reason/function непустые. Обратный план проверяет функции абзацев
и цельность материала. Ответ «неприменимо» нужно объяснить жанром; это не повод
добавлять к новости искусственную стратегическую рекомендацию.

Keep_spans — точные удачные фрагменты и причины их сохранения. Если цитата
исчезла, strength_changes должен ровно один раз назвать её в quote, дать
конкретную reason и replacement_quote, присутствующую в новой версии. Для
обоснованного удаления replacement_quote может быть пустой. Сохранённые цитаты
не требуют записи об изменении. Хорошая причина может позволять исправить
ошибку или связность; эта проверка не запрещает полезную редактуру.

V1 не требует новые strengths/paragraph_functions/reader_check/whole_article_checked,
но проверяет присутствующие strengths, paragraph_functions и strength_changes.
Требование объяснить потерю реально
переданного keep_span действует независимо от версии. Ни одна версия не
требует заданного числа замечаний, обращений, союзов, скобок или коротких фраз.
Сильный спокойный текст и результат unchanged допустимы. Голос, ритм и
лексическое сходство служат диагностикой; отказ обосновывается содержанием.

Обе схемы отражают фактически проведённую модельную проверку. Человек может
не согласиться с выводом. Human gold и разрешение на публикацию — отдельные
артефакты, не поля, которые модель проставляет за редактора.
