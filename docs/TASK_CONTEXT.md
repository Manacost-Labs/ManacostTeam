# Общий контекст: Манакост и отдельные игровые термины

Подключённые входы: редакторские CLI `audit` и `validate-edit`, Python HTTP
`/analyze`, `/validate`, `/rules`, `/outline/validate`, Go `/v2/edit`, переводческие
`/prepare` и `/memory/approve`. Остальные команды продолжают прежний workflow.

## Совместимость

`task_context` — новое необязательное поле. Без него JSON-ответы, правила,
игровые defaults и прежние функции переводчика сохраняются. Для редактора
это Hearthstone, для подготовщика перевода — `wow`. Старые ZIP не изменяются;
новые выпуски EditorTeam/TranslateTeam сохраняют команды и сигнатуры старых helper-ов.

Старый `profile` редактора означает **жанр**, например `constructed-guide`,
`wow-guide` или `news`. `task_context.profile` означает **редакционный профиль**.
Редактор сейчас поддерживает `manacost`; `neutral` отклоняется явно, пока не
отделены все авторские проверки/нормы. Переводчик поддерживает оба профиля.
Для neutral по умолчанию выбирается literal; явно заданный manacost style конфликтует.

Манакост — основной стиль для Hearthstone, WoW, League of Legends, Deadlock,
Overwatch и Heroes of the Storm. Resolver без `--profile` выбирает manacost
для игровых задач; для задачи без игры сохраняется neutral. Общий голос и
оформление хранятся в `profiles/manacost/style.json`, игровые пакеты редактора —
в `editor/config/games/`. Правила Hearthstone не задают термины других игр.
При обновлении профиля до 0.2.0 создайте context.json заново: хеш каталога изменён.
Ранее опубликованные навыки и их архивы остаются доступными.

## Создание и применение

Из корня репозитория:

```bash
python3 tools/resolve_context.py --game hearthstone --profile manacost --patch EXACT_BUILD > context.json
python3 tools/resolve_context.py --game world-of-warcraft --profile manacost --patch EXACT_BUILD > context.json
python3 tools/resolve_context.py --game deadlock --patch EXACT_BUILD > context.json
```

В распакованном EditorTeam/TranslateTeam замените путь на
`scripts/resolve_context.py`. Runtime и каталоги включены в пакет;
исходная рабочая копия не нужна. `--execution agent` и `--execution server`
фиксируют способ выполнения; оба подходят для обращения к вспомогательному API.
Поле `resolution_scope=metadata_only` характеризует resolver, а не результат редакторской проверки.

Редактор:

```bash
PYTHONPATH=editor/src python3 -m editorteam.cli audit article.md --task-context context.json --format json
PYTHONPATH=editor/src python3 -m editorteam.cli validate-edit before.md after.md --task-context context.json --format json
```

В навыке используйте `python scripts/editor_team.py` вместо вызова модуля.
Для WoW выбирается `wow-guide`, для Hearthstone — первый профиль игрового
конфига. Для остальных игр выбирается `game-guide`; доступны также
`game-article` и `news`. Общие жанры не требуют колоды, муллигана или классов
Hearthstone. Совместимый жанр можно задать старым `--profile`. Старый автоанализ
жанра при отсутствии task_context сохраняется. Новый context-аудит выполняет
серверный набор анализаторов; legacy флаги `--deep`/`--strict` к нему пока не
применяются и не должны использоваться вместе с task_context.

В HTTP передайте объект из context.json в поле `task_context`, например:

```python
import json
from urllib.request import Request, urlopen

context = json.load(open("context.json", encoding="utf-8"))
payload = {"text": "Исходный материал", "mode": "edit", "task_context": context}
request = Request("http://127.0.0.1:8740/v2/edit",
                  data=json.dumps(payload).encode("utf-8"),
                  headers={"Content-Type": "application/json"})
with urlopen(request) as response:
    result = json.load(response)
```

Для `/prepare` передайте `text` и `task_context`; для WoW также `product`
той выгрузки, например `retail`. Генерация точного контекста не доказывает
свежесть патча: `EXACT_BUILD` нужно заменить проверенной сборкой.
Переводческий новый путь требует patch/build; этот идентификатор сравнивается
с `build=...` в TSV. Пары локализации остаются EN (`enUS`) → RU (`ruRU`).

Общий валидатор сверяет версии/хеши установленных каталогов и форму JSON.
Поддерживаются все шесть игр каталога. Для LoL сохраняется legacy alias `league`,
для WoW — `wow`; канонический ID остаётся в task_context.
Изменённый каталог требует повторно разрешить контекст. Конфликт явного game,
жанра или patch с task_context — ошибка до модельных этапов. Редактор сохраняет
legacy идентификатор `wow` для своих анализаторов, а ответ дополнительно
возвращает канонический контекст `world-of-warcraft`.

## Словари и память переводов

В новом пути используются соответствующие существующие файлы:

- `hearthstone-names.en-ru.tsv`: только строки с совпадающим build;
- `world-of-warcraft-names.en-ru.tsv`: только совпадающие product и build.
- `<game-id>-names.en-ru.tsv` для остальных игр: только совпадающий build,
  без product. Словари разных игр не объединяются.

Для HS/WoW файлы готовятся существующими sync/import tools; для новых игр
предоставьте проверенный TSV `source_en`, `target_ru`, `comment` (без обязательного
заголовка), где comment содержит `build=EXACT_BUILD`. Неподтверждённые переводы
не добавляйте как официальные. Автоматических загрузчиков новых игр пока нет. Их содержимое
не переносится и не удаляется. При отсутствии подходящих строк ответ содержит
`resource_warnings: ["glossary_unavailable"]`, а имена не объявляются проверенными.
Хеш исходного TSV возвращается как `glossary_sha256`.

Память нового пути хранится в `data/memory/<game>/<scope-hash>/approved-segments.tsv`.
Scope включает игру, продукт, сборку, редакционный профиль и его версию,
языки и хеш словаря. Новая версия профиля использует отдельную область памяти;
прежние файлы сохранены и автоматически не переносятся.
Обновление словаря исключает старые совпадения памяти с прежними TERM-маркерами.
Старый `data/approved-segments.tsv` остаётся доступен только legacy пути;
автоматического копирования его записей в новые области нет.
В `/memory/approve` передавайте тот же task_context/product, что при подготовке.
Утверждение по-прежнему выполняется только по запросу пользователя.

Результат включает `task_context` и `resource_scope`; механические QA-проверки
чисел, ссылок и терминов сохранены. Новый контекст не подтверждает фактологию
или качество перевода автоматически. Нормы WoW-редактора остаются предварительными,
а проверка официальных имён всех игр кроме Hearthstone в редакторе пока недоступна.
Игровые проверки Hearthstone (специальные термины, consistency, коды колод)
к другим играм не применяются. Числа, ссылки, отрицания и выбранные защищённые
слова продолжают проверяться. Hunspell получает общий языковой список и список
выбранной игры; общий стиль не делает её имена подтверждёнными.
В переплавке словарь/лексика корпуса и покрытие карт Hearthstone также
изолированы. Для остальных игр покрытие игровых сущностей проверяйте вручную;
структурированные claims, числа, ссылки и ограничения сохраняют свои проверки.

## Сервер и переносимость

`cd editor`/`cd translate` → `docker compose up --build` сохраняется.
Compose использует корень монорепозитория как build context, чтобы включить
общий runtime и каталоги. Для ручной сборки из корня:

```bash
docker build -f editor/Dockerfile --target analyzer .
docker build -f translate/Dockerfile .
```

Go `/v2/edit` получает нормализованный контекст у `/context/resolve` Python-сайдкара.
Без context-capable сайдкара запрос с task_context не выполняется; legacy запросам
дополнительный endpoint не нужен. Это сохраняет единый валидатор на stdlib Python
и не дублирует игровые каталоги в Go.
