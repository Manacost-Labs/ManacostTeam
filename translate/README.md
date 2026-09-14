# TranslateTeam

`translate/` — локальный Docker-сервис, который готовит материалы по World of Warcraft и Hearthstone для перевода в Codex. Он не скачивает и не запускает LLM, не использует API-ключи и не передаёт текст стороннему переводчику.

## Возможности

1. Собирает единый пакет для Codex: игра, патч, класс, специализация, заголовок и режим стиля.
2. Загружает подтверждённые EN→RU пары из локальных выгрузок HearthstoneJSON и WoW-клиента.
3. Защищает многословные игровые имена до перевода; спорные кандидаты выводит на редакторскую проверку.
4. Делит Markdown на стабильные сегменты с hash ID и показывает только изменившиеся сегменты при обновлении текста.
5. Находит точные совпадения с локальной утверждённой translation memory.
6. Поддерживает стили: literal, manacost, technical и summary.
7. Даёт отдельный QA-отчёт для чисел, ссылок, code spans, таблиц, терминов и утёкших маркеров.
8. Позволяет утвердить качественный сегмент в локальной памяти переводов.

## Запуск

Нужен Docker Desktop с WSL 2. После установки:

```powershell
cd C:\Users\zulut\Documents\ManacostTeam-unified\translate
docker compose up --build -d
```

Откройте `http://127.0.0.1:8787`. Контейнер доступен только на loopback-интерфейсе. Остановка:

```powershell
docker compose down
```

Docker на текущей машине пока не найден, поэтому запуск контейнера должен быть проверен после установки Docker Desktop.

## Данные и обновление терминов

Все локальные данные в `data/` игнорируются Git. Не кладите туда HTML-страницы, cookies или готовые переводы, если не хотите хранить их локально.

Hearthstone — используйте конкретную числовую сборку:

```powershell
python tools/sync_hearthstone_terms.py --build 123456
```

WoW — сначала подготовьте две UTF-8 TSV-выгрузки одного продукта и билда с колонками `id` и `name`, затем:

```powershell
python tools/import_wow_names.py --en enUS.tsv --ru ruRU.tsv --product retail --build 12.0.0
```

Чтобы ограничить допустимые сайты, создайте `.env` рядом с `docker-compose.yml`:

```text
ALLOWED_DOMAINS=www.wowhead.com,wowhead.com,www.reddit.com,reddit.com,old.reddit.com
```

Сервис не обходит CAPTCHA, авторизацию и антибот-защиту. Если страница не извлекается, вставьте текст вручную.

## Проверка

```powershell
python -m unittest discover -s tests -v
```
