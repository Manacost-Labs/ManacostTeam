# Отзывы native Codex: контракт и независимость

Автор и reviewers работают в отдельных контекстах. Фактологический reviewer
получает полный candidate, handoff и сохранённые source snapshots. Литературный
получает candidate, brief/жанр, голос и необходимые исследовательские ограничения.
Не сообщайте ожидаемый verdict и не передавайте self-review автора.

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
  "patch_matches": true,
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
  "findings": []
}
```

Для ошибки dimension получает fail, status=repair/blocked; finding содержит
category, severity (info/warning/error/blocker), quote, reason, suggestion.
Quote дословно из candidate. Проверяйте практические вопросы читателя,
последовательность объяснений и причин, повторы/противоречия между главами,
штампованные связки, ритм и естественность языка. Предпочтение одного вкусового
варианта не является ошибкой без конкретной причины. Info не блокирует,
а неисправленные warning/error/blocker требуют ревизии.

Обе схемы отражают фактически проведённую модельную проверку. Человек может
не согласиться с выводом. Human gold и разрешение на публикацию — отдельные
артефакты, не поля, которые модель проставляет за редактора.
