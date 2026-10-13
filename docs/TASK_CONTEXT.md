# Общий контекст: редактура и перевод Hearthstone/WoW

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

## Создание и применение

Из корня репозитория:

```bash
python3 tools/resolve_context.py --game hearthstone --profile manacost --patch EXACT_BUILD > context.json
python3 tools/resolve_context.py --game world-of-warcraft --profile manacost --patch EXACT_BUILD > context.json
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
конфига. Совместимый жанр можно задать старым `--profile`. Старый автоанализ
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
Поддерживаются только Hearthstone и WoW; другие игры пока каталогизированы.
Изменённый каталог требует повторно разрешить контекст. Конфликт явного game,
жанра или patch с task_context — ошибка до модельных этапов. Редактор сохраняет
legacy идентификатор `wow` для своих анализаторов, а ответ дополнительно
возвращает канонический контекст `world-of-warcraft`.

## Словари и память переводов

В новом пути используются соответствующие существующие файлы:

- `hearthstone-names.en-ru.tsv`: только строки с совпадающим build;
- `world-of-warcraft-names.en-ru.tsv`: только совпадающие product и build.

Файлы по-прежнему готовятся существующими sync/import tools. Их содержимое
не переносится и не удаляется. При отсутствии подходящих строк ответ содержит
`resource_warnings: ["glossary_unavailable"]`, а имена не объявляются проверенными.
Хеш исходного TSV возвращается как `glossary_sha256`.

Память нового пути хранится в `data/memory/<game>/<scope-hash>/approved-segments.tsv`.
Scope включает игру, продукт, сборку, редакционный профиль, языки и хеш словаря.
Обновление словаря исключает старые совпадения памяти с прежними TERM-маркерами.
Старый `data/approved-segments.tsv` остаётся доступен только legacy пути;
автоматического копирования его записей в новые области нет.
В `/memory/approve` передавайте тот же task_context/product, что при подготовке.
Утверждение по-прежнему выполняется только по запросу пользователя.

Результат включает `task_context` и `resource_scope`; механические QA-проверки
чисел, ссылок и терминов сохранены. Новый контекст не подтверждает фактологию
или качество перевода автоматически. Нормы WoW-редактора остаются предварительными,
а проверка официальных WoW-имён в редакторе пока недоступна.

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
