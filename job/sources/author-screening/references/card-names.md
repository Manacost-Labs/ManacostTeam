# Проверка русских названий карт

Официальная локализация берётся из данных HearthstoneJSON (репозиторий hsdata). Она
закрывает почти все случаи; угадывать перевод названия нельзя.

## Источник

- Все локали сразу: `https://api.hearthstonejson.com/v1/latest/all/cards.collectible.json`.
  Поля `name`, `text`, `flavor` здесь — объекты по локалям: `name.enUS`, `name.ruRU`.
- Только русский клиент: `https://api.hearthstonejson.com/v1/latest/ruRU/cards.collectible.json`
  (около 4,5 МБ, удобнее для поиска по русскому названию).
- Для токенов и карт Полей сражений берите `cards.json` вместо `cards.collectible.json`.

## Пайплайн

```python
import json, urllib.request

URL = "https://api.hearthstonejson.com/v1/latest/all/cards.collectible.json"
# Без своего User-Agent сервер отвечает 403.
request = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
cards = json.load(urllib.request.urlopen(request))

def ru_name(english: str) -> list[str]:
    wanted = english.casefold()
    return sorted({
        card["name"].get("ruRU", "")
        for card in cards
        if card.get("name", {}).get("enUS", "").casefold() == wanted
    })

print(ru_name("Ragnaros the Firelord"))
```

Обратная проверка (кандидат написал русское название) — тот же перебор по `name.ruRU`.
Сравнивайте без учёта регистра и с заменой «ё» на «е»; падежную форму из ответа кандидата
сначала приведите к начальной.

## Что проверять

- Название существует в `ruRU` и относится к той же карте (`dbfId`), о которой речь.
- Стоимость, класс и текст — из того же объекта (`cost`, `cardClass`, `text.ruRU`), а не из
  памяти.
- Если карта не нашлась: возможна свежая карта, которой ещё нет в данных. Действуйте по
  «Правилу подстановки» из `sources.md`, а не выбрасывайте тему молча.
