# Мета-API kolodahearthstone

Собственный публичный API статистики: `https://api.kolodahearthstone.com/v1`. Только GET,
ключ не нужен. Ответ всегда имеет вид `{"data": ..., "meta": {...}}`. Запрос из Python без
своего заголовка User-Agent получает 403; `curl` и браузер работают.

## Какие маршруты нужны для теста

| Задача | Запрос |
|---|---|
| Топ-архетипы Стандарта в Легенде | `/hsguru/meta?format=standard&rank=legend&period=past_week` |
| То же для Вольного | `/hsguru/meta?format=wild&rank=legend&period=past_week` |
| Каталог архетипов с винрейтом, числом игр и долей в классе | `/constructed/archetypes?limit=100` |
| Популярные списки колод | `/constructed/decks?limit=50` |
| Существа и герои Полей сражений | `/battlegrounds/minions`, `/battlegrounds/heroes` |
| Классы Арены | `/arena/classes` |
| Список наборов данных и их свежесть | `/datasets`, `/sources` |

`rank` для `/hsguru/meta`: `diamond_4to1`, `legend`, `top_5k`, `top_legend`. Допустимые
периоды API возвращает в `meta.available_periods`; текущий патч — в `meta.current_patch_period`.
У каждой строки `items` есть `winrate`, `popularity` и `games`.

## Проверка свежести (обязательна)

- `meta.fetched_at` — когда снят срез. Указывай эту дату рядом с цифрой в задании.
- `meta.stale: true` или `meta.cached_after_failure` — срез устарел. Цифра идёт в тест только
  с явной датой снимка, иначе бери запасной источник.
- Архетип с малым числом игр (`games` меньше 300) не годится для задания: винрейт шумит.

## Как использовать в тесте

- Задание на мулиган: топ-архетип по `popularity` из `/hsguru/meta` в Легенде за неделю.
- Задание на заголовок: одна реальная цифра (`winrate` или `popularity`) с датой среза.
- Статистика показывает, что происходит, но не почему. Объяснение причин — работа кандидата,
  его и проверяй.

Если домен не разрешён в настройках сети, сообщи об этом одной строкой и работай по запасным
источникам из `sources.md`.
