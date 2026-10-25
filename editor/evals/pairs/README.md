# Пары «черновик → эталон»

Главная метрика качества редактуры: доля пар, где правка ИИ **не хуже**
правки владельца в слепом сравнении. Соблюдение правил её не заменяет.

## Как положить пару

Одна пара — один каталог `evals/pairs/<id>/`, где `<id>` — латинский slug
(`guide-druid-mulligan-2026-10`):

| Файл | Что внутри |
| --- | --- |
| `draft.md` | черновик, который получает редактор (ИИ или человек) |
| `reference.md` | правка владельца того же черновика — эталон |
| `meta.json` | метаданные, см. ниже |

```json
{
  "id": "guide-druid-mulligan-2026-10",
  "type": "GUIDE",
  "topic": "муллиган Друида",
  "date": "2026-10-25",
  "origin": "owner",
  "synthetic": false,
  "notes": "необязательно"
}
```

- `type`: `GUIDE`, `ANALYSIS` или `REPORT` (это же `editorial_mode` редактора).
- `origin`: `owner` — пара владельца; `owner-correction` — создана из поправки
  (см. ниже); `synthetic` — заглушка. `synthetic: true` ровно у заглушек, и
  только их `id` начинается с `synthetic-`.
- Черновик и эталон не должны совпадать. Лишние поля отклоняются.

Проверка формата: `node evals/pairs.js validate`.

Три пары `synthetic-*` — синтетические заглушки для проверки протокола, не
тексты владельца. Метрика на них помечается «НЕ ИЗМЕРЕНИЕ»; после появления
настоящих пар запускайте с `--real-only` или удалите заглушки.

## Прогон

```bash
node evals/blind_review.js pairs --out build/blind-pairs --editor prompt --judge api
node evals/blind_review.js rate build/blind-pairs --reviewer owner
node evals/blind_review.js import build/blind-pairs/ratings.json --key build/blind-pairs/key.json --out build/blind-pairs/human
```

Подробности, режимы редактора и переменные судьи — в `docs/evals.md`,
раздел «Пары черновик → эталон».

## Поправка → кейс

Поправку владельца к правке ИИ сохраняйте как регрессионную пару:

```bash
node evals/pairs.js case --source черновик.md --ai правка-ии.md --fixed правка-владельца.md \
  --type GUIDE --topic "муллиган Друида" --id fix-druid-mulligan --note "убрал пересказ карты"
```

Команда кладёт `draft.md` (черновик), `reference.md` (поправленный текст),
`ai_rejected.md` (отвергнутая правка ИИ) и `meta.json` с
`regression.must_not_contain` — предложениями ИИ, которые владелец убрал.
Сузьте их до точной фразы, если предложение длинное. Если новая правка ИИ
снова содержит такую фразу, прогон `pairs` печатает регрессию.
