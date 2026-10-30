# Evaluation через Promptfoo

Быстрый режим `prompt-direct` в `evals/promptfooconfig.yaml` сравнивает два полных
системных prompt: `baseline` воспроизводит бережную редактуру до
нового pipeline, `candidate` добавляет практическую пользу, защиту
авторского голоса и удаление AI-шаблонов. Provider принимает только
точное содержимое этих двух файлов. Произвольный system prompt
отклоняется до вызова модели; production API не принимает system prompt.

Режим `pipeline-e2e` в `evals/promptfooconfig.pipeline.yaml` отправляет исходный
текст в `POST /v2/edit` и тем самым проверяет весь production-конвейер:
analysis, rewrite, critic, targeted repair, postflight и все подключённые
анализаторы. Вариант prompt задаётся только при запуске каждого gateway через
`EDITOR_PROMPT_VARIANT=baseline|candidate`; другое значение останавливает
сервис. Тело `/v2/edit` не содержит поля для system prompt.

В наборе 48 обезличенных кейсов для гайдов, новостей, мета-отчётов,
аналитики, Hearthstone, World of Warcraft и League of Legends. Он включает
сленг, числа, URL, ссылки, таблицы, списки и fenced code blocks. Шесть кейсов
`corpus-05`…`corpus-10` — настоящие обезличенные фрагменты авторского корпуса
`гайды/` по 600–1100 знаков с заголовками, жирным и защищёнными названиями
карт; поле `vars.origin` помечает их. Они проверяют не удаление дефекта, а
сохранение живого текста: `remove_ai_slop=false`, потому что «важно понимать»
в `corpus-10` написал автор. Остальные кейсы — короткие синтетические
предложения под конкретный дефект.

## Без API-ключа

Этот запуск не оценивает качество prompt: identity-provider возвращает исходник.
Он проверяет подключение обоих prompt и детерминированных затворов:

```bash
EDITOR_EVAL_OFFLINE=1 PROMPTFOO_DISABLE_TELEMETRY=1 \
  npx promptfoo eval -c evals/promptfooconfig.yaml --no-cache \
  --no-table --no-progress-bar -o /tmp/editorteam-promptfoo-offline.json
```

В identity-режиме неотредактированные кейсы с AI-фразами и канцеляритом
обязаны завершиться `fail`: это доказывает, что assertions ловят дефект, а не
ошибку запуска. Поэтому общий exit code будет ненулевым.
Такой результат честно хранит `accepted=null`, `checks_complete=false` и
`deterministic_only=true`: offline-прогон не выдаётся за проверку моделью и
внешними анализаторами.

## Реальное прямое A/B-сравнение

Поднимите EditorTeam, задайте обе модели и запустите:

```bash
EDITOR_EVAL_PROVIDER=openai \
EDITOR_EVAL_API_KEY="$OPENAI_API_KEY" \
EDITOR_EVAL_BASELINE_MODEL="$BASELINE_MODEL" \
EDITOR_EVAL_CANDIDATE_MODEL="$CANDIDATE_MODEL" \
EDITOR_GATEWAY_URL=http://127.0.0.1:8740 \
PROMPTFOO_DISABLE_TELEMETRY=1 \
  npx promptfoo eval -c evals/promptfooconfig.yaml --no-cache \
  -o /tmp/editorteam-promptfoo-real.json
```

Можно раздельно задать `EDITOR_EVAL_BASELINE_PROVIDER`,
`EDITOR_EVAL_CANDIDATE_PROVIDER`, `EDITOR_EVAL_BASELINE_API_KEY`,
`EDITOR_EVAL_CANDIDATE_API_KEY` и `EDITOR_EVAL_*_BASE_URL`. Для OpenAI-compatible endpoint
используйте `EDITOR_EVAL_PROVIDER=openai-compatible` и `EDITOR_EVAL_BASE_URL`.

Каждый результат сохраняет `provider`, `model`, `prompt_version`, `accepted`,
`checks_complete`, вердикт validation и SHA-256 итога. Если EditorTeam отклонил
кандидата или не завершил все проверки, provider возвращает исходный текст.

## Критерии

`evals/assertions/deterministic.js` обязательно проверяет непустой ответ,
сохранение и отсутствие новых чисел/процентов и URL, отрицания, Markdown,
таблицы, code blocks, игровые сущности, AI-фразы, канцелярит,
`checks_complete` и возврат исходника при отклонении.

Субъективные метрики вынесены в дополнительный
`evals/promptfooconfig.judge.yaml`: восемь `llm-rubric` с `weight: 0` и
именами `judge-clarity`, `judge-naturalness`, `judge-structure`,
`judge-usefulness`, `judge-voice`, `judge-ai-slop`, `judge-bureaucracy`,
`judge-false-positives`. Тексты рубрик лежат в `evals/assertions/judge/*.txt`
и всегда сравнивают ответ с исходником `{{text}}`. Нулевой вес означает, что
Promptfoo записывает балл как именованную метрику, но pass/fail кейса
определяют только детерминированные затворы. LLM-as-a-judge никогда не
заменяет их.

```bash
EDITOR_EVAL_JUDGE_PROVIDER=openai:gpt-4o-mini \
EDITOR_EVAL_PROVIDER=openai EDITOR_EVAL_API_KEY="$OPENAI_API_KEY" \
EDITOR_EVAL_BASELINE_MODEL="$BASELINE_MODEL" EDITOR_EVAL_CANDIDATE_MODEL="$CANDIDATE_MODEL" \
PROMPTFOO_DISABLE_TELEMETRY=1 \
  npx promptfoo eval -c evals/promptfooconfig.judge.yaml --no-cache \
  -o /tmp/editorteam-promptfoo-judge.json
```

## Candidate без retrieval и с retrieval

`evals/promptfooconfig.retrieval.yaml` гоняет candidate через production
`/v2/edit` дважды: с `retrieval: "off"` в запросе и с включённым подбором
примеров авторского стиля из корпуса. Оба провайдера ходят в один gateway
(`EDITOR_EVAL_CANDIDATE_GATEWAY_URL`). Запускайте только на реальных
фрагментах корпуса:

```bash
EDITOR_EVAL_CANDIDATE_GATEWAY_URL=http://127.0.0.1:8740 \
EDITOR_EVAL_ANALYZER_URL=http://127.0.0.1:8731 \
EDITOR_EVAL_JUDGE_PROVIDER=openai:gpt-4o-mini \
PROMPTFOO_DISABLE_TELEMETRY=1 \
  npx promptfoo eval -c evals/promptfooconfig.retrieval.yaml --filter-pattern corpus \
  --no-cache -o /tmp/editorteam-retrieval.json
```

Краткий отчёт по JSON-выводу строит `evals/report.js`: число кейсов,
accepted/rejected/unchanged rate, `checks_complete` rate, счётчики
`corpus_copy` и `corpus_fact_leak`, сохранение фактов и Markdown, средний
объём изменений, candidate win rate, разрезы по профилям и играм. Без
результатов настоящей модели (offline-провайдер, пустой или отсутствующий
файл) он печатает `real model evaluation not executed` и ничего не
придумывает. CI проверяет парсер на `evals/fixtures/promptfoo-retrieval-sample.json`;
платный прогон остаётся ручным.

```bash
node evals/report.js /tmp/editorteam-retrieval.json
```

Модели сравниваются переменными `EDITOR_EVAL_BASELINE_MODEL`,
`EDITOR_EVAL_CANDIDATE_MODEL`, `EDITOR_EVAL_PROVIDER` (принимается и
`EDITOR_EVAL_PROVIDER_PROVIDER`) и `EDITOR_EVAL_JUDGE_PROVIDER`; для локальной
модели через Ollama задайте `EDITOR_EVAL_PROVIDER=ollama` и
`EDITOR_EVAL_BASE_URL=http://127.0.0.1:11434/v1`. В pipeline-режиме модель
выбирает gateway, поэтому две модели сравниваются двумя gateway
(`EDITOR_EVAL_BASELINE_GATEWAY_URL`, `EDITOR_EVAL_CANDIDATE_GATEWAY_URL`).
Запрос может задать `retrieval`: `auto` (по умолчанию: включён для edit и
rewrite, выключен для proofread), `on` или `off`.

Детерминированный затвор тот же плюс `no-corpus-copy`: провайдер берёт
тексты примеров у сайдкара (`/corpus/examples`, публичный API их не
отдаёт) и проваливает кейс, если в ответе появился словесный 10-граммный
фрагмент из примера, которого нет в исходнике. Числа, URL и защищённые
сущности из примеров ловят существующие проверки `no-new-*`. Judge-метрики
с нулевым весом: `judge-voice`, `judge-naturalness`, `judge-clarity`,
`judge-usefulness`, `judge-facts`, `judge-example-copying`. В metadata
каждого результата есть `retrieval_variant`, `retrieval_status`,
`retrieval_examples_used` и `retrieval_example_ids`.

## Модель через CLI-агент: Claude Code, Codex, Gemini CLI

Если API-ключа нет, но есть подписочный CLI, его можно подставить как модель
через локальный мост `tools/cli_model_bridge.py`. Он поднимает
OpenAI-совместимый `POST /v1/chat/completions`, склеивает system и user в
один prompt, запускает CLI в неинтерактивном режиме и возвращает ответ.
Prompt идёт через stdin, ответ CLI снимается с markdown-ограждения, в логах
только длительность и код возврата. Сбой CLI (не залогинен, лимит) — HTTP 503,
таймаут — HTTP 504, то есть в отчёте это `critic_unavailable` или
`critic_timeout`, а не провал качества.

Мост передаёт stdin и читает stdout/stderr в UTF-8 независимо от системной
кодовой страницы Windows. Пользовательская команда `--backend custom` также
должна работать в UTF-8; для Python-команды можно указать `python -X utf8`.
Вывод с некорректной кодировкой приводит к HTTP 503 с указанием UTF-8,
ответ сохраняет обычный JSON-формат ошибки моста.

```bash
python tools/cli_model_bridge.py --backend codex --port 8790            # codex exec, read-only sandbox
python tools/cli_model_bridge.py --backend claude --model sonnet         # isolated claude -p, subscription login
python tools/cli_model_bridge.py --backend gemini                        # gemini -p, здесь не проверялся
python tools/cli_model_bridge.py --backend custom --command 'my-cli --stdin'
curl -s http://127.0.0.1:8790/health
```

Claude запускается с пустыми tools/MCP/settings sources и без сохранения сессии.
`--bare` не используется: актуальный CLI не читает подписочный OAuth в этом режиме.
System передается отдельным временным UTF-8 файлом, user — через stdin.
Мост читает `stream-json --verbose`: поле финального `result` может содержать
только последний фрагмент автоматического продолжения. Поэтому собираются все
текстовые блоки основного ассистента; thinking и повтор события с тем же UUID
исключаются. Нужны успешный финальный result, `end_turn` и согласованный хвост.
Ошибки, незавершенный или некорректный поток не выдаются как готовый текст.

Для Claude лимит ответа по умолчанию — 64000 токенов. Мост проверяет `max_tokens`:
целое число 1-128000; ноль, boolean и неверный тип отклоняются. Только Claude
получает этот бюджет через переменную окружения. Codex и остальные backend
сохраняют собственные ограничения; для Codex используется бюджет модели по
умолчанию, без явного переопределения `max_tokens`. Таймаут одного вызова CLI —
900 секунд (`--timeout`). Для длинного полного pipeline настройте общий
`EDITOR_TIMEOUT_SEC` отдельно; в трех прогонах длинного гайда использовано 3600.
Таймауты Hunspell и retrieval по умолчанию — 30 и 15 секунд; явные настройки
`HUNSPELL_TIMEOUT_SEC` и `EDITOR_RETRIEVAL_TIMEOUT_SEC` сохраняют приоритет.

Для `write/reconstruct` research reader может передать необязательный
`research_handoff.evidence_snapshots`: объекты `{url, text, sha256}` с SHA-256
UTF-8 текста. URL должен совпадать с уже переданным source, каждая его исходная
цитата — встретиться ровно один раз. Сервер добавляет дословный `context_quote`
вокруг цитаты; исходные quote и refs сохраняются. Формы имен из проверенного
снимка разрешены для проверки написания, числовые утверждения из него не
импортируются в базу. Из patch разрешены только версия и корректная дата
объявленного исторического среза; прочие числа по-прежнему требуют claims.
Снимки не скачиваются сервером. Ограничения: 8 снимков, 100000 символов в одном,
150000 суммарно; к каждой цитате добавляется до 200 символов до и 1000 после,
не более 100000 дополнительных символов всего. Контекст не заменяет независимую
проверку фактов и не разрешает дополнительные evidence_refs.

В `editorteam-go-v54` реконструкционный ремонт текста длиннее 2000 Unicode-кодовых
точек (rune) возвращает JSON с точечными `edits`, а не всю статью заново. Каждая замена
ссылается на индекс текущего замечания и пересекается с его дословной цитатой,
если такая цитата есть. Якоря уникальны в исходном тексте, не перекрываются,
ограничены 2000 rune до и 2500 после; максимум 64 замены, суммарно не более
трети исходных rune в `before`. Весь список проверяется до применения,
остальные байты и абзацы сохраняются. Ошибка формата или якорей оставляет
исходный candidate. Короткие тексты сохраняют прежний полный ответ. После
ремонта обоих видов обязательны новые проверки всего текста; лимит двух
ремонтов и условия приемки не изменены.

Живой тройной прогон `editorteam-go-v56` на одном историческом длинном гайде
дал 1/3 приемки одновременно API и слепым фактологическим/литературным отзывом.
Все 20 вызовов CLI завершились; примеры и правила стиля действительно переданы,
локальные ремонты сохранили остальные байты и абзацы. Это подтверждает технические
исправления, но не полную стабильность написания: ложные составные имена и
непригодные отрицательные подтверждения все еще могут остановить выдачу.
Все исходы и ограничения описаны в
[`docs/LONG_GUIDE_RUNTIME_2026_10_21.md`](../../docs/LONG_GUIDE_RUNTIME_2026_10_21.md).

Прямой A/B prompt-ов через мост:

```bash
EDITOR_EVAL_PROVIDER=openai-compatible \
EDITOR_EVAL_BASE_URL=http://127.0.0.1:8790/v1 \
EDITOR_EVAL_API_KEY=cli EDITOR_EVAL_MODEL=codex \
EDITOR_GATEWAY_URL=http://127.0.0.1:8740 PROMPTFOO_DISABLE_TELEMETRY=1 \
  npx promptfoo eval -c evals/promptfooconfig.yaml --no-cache -o /tmp/editorteam-cli.json
node evals/report.js /tmp/editorteam-cli.json
```

Полный production pipeline через мост: gateway ходит к CLI как к
OpenAI-совместимому провайдеру. Из Compose хост доступен как
`host.docker.internal`; для локального `go run` достаточно `127.0.0.1`.

```bash
EDITOR_PROVIDER=openai EDITOR_API_KEY=cli EDITOR_MODEL=codex \
EDITOR_BASE_URL=http://host.docker.internal:8790/v1/chat/completions \
EDITOR_BIND_ADDRESS=127.0.0.1 docker compose up -d --wait
EDITOR_EVAL_CANDIDATE_GATEWAY_URL=http://127.0.0.1:8740 \
EDITOR_EVAL_ANALYZER_URL=http://127.0.0.1:8731 PROMPTFOO_DISABLE_TELEMETRY=1 \
  npx promptfoo eval -c evals/promptfooconfig.editorial.yaml --no-cache -o /tmp/editorteam-editorial.json
node evals/report.js /tmp/editorteam-editorial.json
```

Ограничения: один вызов CLI занимает секунды, а pipeline делает от трёх до
семи вызовов на кейс, поэтому начинайте с `--filter-pattern`; температуру
у CLI задать нельзя, поэтому прогоны менее воспроизводимы, чем через API;
`--parallel` больше 1 быстро упирается в лимиты подписки. В отчёте всегда
указывайте backend и модель: `report.js` печатает их в поле `model` как
`codex:<модель>`.

## Редакторский набор и порог качества

`evals/cases/editorial.json` — 36 кейсов в каноническом формате (`id`, `game`,
`profile`, `source`, `reference`, `expected_action`, `defects`,
`must_preserve`, `allowed_changes`); собирается командой
`python tools/build_editorial_cases.py`. Кейсы `unchanged` — настоящие
абзацы `гайды/`, которые нельзя переписывать; кейсы `edit` — те же абзацы с
детерминированно внесёнными дефектами (AI-рамки, канцелярит, повторы,
перегруженные предложения, сломанная структура), где reference — авторский
оригинал. WoW и LoL в корпусе нет: их кейсы помечены `synthetic: true`.
Промптфу-загрузчик `evals/cases/editorial.js` переводит набор в переменные
без дублирования данных.

```bash
EDITOR_EVAL_CANDIDATE_GATEWAY_URL=http://127.0.0.1:8740 \
EDITOR_EVAL_ANALYZER_URL=http://127.0.0.1:8731 \
EDITOR_EVAL_JUDGE_PROVIDER=openai:gpt-4o-mini \
PROMPTFOO_DISABLE_TELEMETRY=1 \
  npx promptfoo eval -c evals/promptfooconfig.editorial.yaml --no-cache \
  -o /tmp/editorteam-editorial.json
node evals/report.js /tmp/editorteam-editorial.json
```

`evals/report.js` печатает по каждому варианту accepted/rejected/unchanged
rate, `checks_complete` rate, счётчики `corpus_copy` и `corpus_fact_leak`,
сохранение фактов и Markdown, объём изменений по token-level edit distance с
учётом перенесённых предложений и переставленных слов, переходы
`edit → unchanged` и `unchanged → edit`, средние judge-оценки по метрикам,
разрезы по профилям и играм, полноту A/B-пар с перечнем отсутствующих и
дублирующихся, win/loss rate candidate и итоговый verdict `pass|fail`
по порогам `evals/thresholds.json`. При провале порогов exit code равен 1.
Пороги применяются только к настоящему прогону: для offline-, fake- и
fixture-результатов скрипт печатает `real model evaluation not executed`
и завершается нулём.

## Слепая человеческая оценка

При `write` с пустыми `text` и `candidate_text` критик получает
`new_article=true`: исходник здесь является реестром фактов, поэтому доказательства
редактуры его формулировок в `improvements` не требуются. Проверка всех обязательных
утверждений, условий, исключений и добавлений, положительный вердикт критика и
полные инструментальные проверки остаются обязательными. Для существующего
черновика доказательство полезной правки сохраняется. Необязательная шлифовка
удачной новой статьи относится к `info`; конкретная смысловая ошибка требует
ремонта независимо от высоких средних оценок.

Словарное совпадение со строчным оборотом без явного указания на карту является
предупреждением для смысловой проверки. Заглавная буква в начале предложения
сама по себе не доказывает название карты. Явные названия с указанием на карту,
разыгрывание или кавычками сохраняют жесткую проверку покрытия. Допустимые падежи
известных имен и точная объявленная дата словами не заменяют проверку фактов.

В начале предложения или заголовка закрытый список грамматических слов
не считается частью следующего известного имени: «Текст Сферы», «Ранний Полкелт».
Весь остаток должен совпасть с проверенной полной формой имени; строчный оборот
или часть слова не дает такого разрешения. Время, условия и модальность совета
по-прежнему проверяются по всей статье.

Полный положительный фактологический отзыв с недословной обязательной цитатой
получает одну попытку исправить подтверждение, в пределах общего повтора формата.
Текст статьи при этом не меняется. Если смысл отсутствует, проверяющий должен
вернуть `insufficient`; отрицательные или неполные отзывы не переголосовываются.
После исправления действует тот же строгий валидатор всех утверждений и цитат.

```bash
node evals/blind_review.js prepare /tmp/editorteam-editorial.json --out build/blind
# оценщику отдать build/blind/pairs.md и ratings.template.json; key.json хранить отдельно
node evals/blind_review.js import build/blind/ratings.json --key build/blind/key.json --out build/blind
```

`prepare` случайно (криптографический источник) скрывает, какой вариант
стал A, а какой B, и пишет ключ рандомизации в отдельный `key.json`.
Оценщик ставит 1–5 за читаемость, естественность русского, полезность для
игрока и сохранение авторского голоса и указывает предпочтение. `import`
раскрывает ключ и строит `report.json` и `report.md` со средними по
вариантам и распределением предпочтений.

## Пары черновик → эталон

Главная метрика качества — доля пар, где правка ИИ не хуже правки владельца
в слепом сравнении. Формат пар и команда «поправка → кейс» описаны в
[`evals/pairs/README.md`](../evals/pairs/README.md); формат проверяет
`node evals/pairs.js validate`.

```bash
node evals/blind_review.js pairs --out build/blind-pairs                     # заглушки, без ключей
node evals/blind_review.js pairs --out build/blind-pairs --real-only \
  --editor prompt --judge api                                               # настоящий прогон
node evals/blind_review.js rate build/blind-pairs --reviewer owner           # оценка владельца
node evals/blind_review.js import build/blind-pairs/ratings.json \
  --key build/blind-pairs/key.json --out build/blind-pairs/human
```

`pairs` прогоняет правку ИИ по каждой паре, кладёт её рядом с эталоном
владельца в слепые A/B (случайная сторона, ключ в `key.json`, правки ИИ и
сводка — в `private/`; до конца оценки их не открывать) и сразу оценивает пары
LLM-судьёй. Редактор: `offline` (возвращает черновик, только смоук),
`prompt` (candidate prompt, переменные как у `prompt-direct`), `pipeline`
(`/v2/edit`, `EDITOR_EVAL_CANDIDATE_GATEWAY_URL`) или `cmd` с
`--editor-cmd "команда"`: черновик на stdin, правка на stdout, `PAIR_ID` и
`PAIR_TYPE` в окружении. Судья `api` — OpenAI-совместимый endpoint:
`EDITOR_EVAL_JUDGE_MODEL`, `EDITOR_EVAL_JUDGE_BASE_URL`,
`EDITOR_EVAL_JUDGE_API_KEY` (или `EDITOR_EVAL_API_KEY`/`OPENAI_API_KEY`).

Судья — дешёвый прокси, главный сигнал — владелец. `rate` показывает в
терминале черновик и версии A/B без меток, спрашивает рубрику и выбор,
сохраняет `ratings.json` после каждой пары и продолжает с места остановки.
`import` даёт `metric.human`: пара засчитана, если ИИ выиграл не реже
эталона (ничья — не хуже). Метрика с offline-редактором, offline-судьёй или
синтетическими парами помечена `measured: false`.

Пары с `expected_edit: "none"` проверяют работу с уже хорошим исходником:
их эталон совпадает с черновиком. Они исключены из `metric.human/model` и
показаны отдельно в `control_results.human/model`. Отчёт различает наблюдение
«текст изменён/сохранён» и предпочтение оценщика. Буквальное совпадение не
означает автоматической победы; допустимая альтернативная формулировка не
считается ошибкой из-за отличия от эталона. Ничья разрешена.
Синтетический или offline-контроль не становится измерением качества.
Метка контроля передаётся только в закрытый ключ и журнал, а не судье.
Подробности и создание пары из отменённой правки — в
[`evals/pairs/README.md`](../evals/pairs/README.md#как-читать-контрольные-результаты).

Рубрика «интересно / механично» лежит в `evals/rubric/interest.json` и общая
для владельца и судьи: узнал ли читатель новое, нет ли места, которое хочется
пропустить, есть ли конкретные игровые решения, звучит ли текст как автор.
Шкала 1–5: 1 — механично, 5 — интересно.

В сравнении редакторских вариантов оценивайте голос относительно исходника:
сохранён ли его акцент и манера объяснения. Общая выразительность и новые
подробности сами по себе не доказывают улучшения. Факты, ограничения и
уверенность нельзя обменивать на высокий балл интереса.

### Правило: новое правило редактуры — только через метрику

Правило редактуры (промпт, затвор, словарь, практика) принимается, только
если подняло долю «ИИ не хуже человека» на тех же парах. Порядок:

1. Прогон `pairs` и оценка до изменения — базовый `report.json`.
2. Изменение и повторный прогон в новый `--out` на том же наборе пар.
3. `node evals/blind_review.js gate --baseline до/human/report.json --candidate после/human/report.json`
   — exit 0 (`ACCEPT`) только при росте доли на том же наборе и только для
   измеренных прогонов. `--rater model` проверяет по судье: этого достаточно,
   чтобы отбросить правило, но не чтобы принять его без владельца.

Каждая поправка владельца к правке ИИ становится парой через
`node evals/pairs.js case`, поэтому набор растёт из реальных ошибок.

## Production A/B через два gateway

Запустите два gateway с одинаковой моделью и анализаторами, но с разными
`EDITOR_PROMPT_VARIANT`, затем выполните ручной внешний прогон:

```bash
EDITOR_EVAL_BASELINE_GATEWAY_URL=http://127.0.0.1:8740 \
EDITOR_EVAL_CANDIDATE_GATEWAY_URL=http://127.0.0.1:8741 \
PROMPTFOO_DISABLE_TELEMETRY=1 \
  npx promptfoo eval -c evals/promptfooconfig.pipeline.yaml --no-cache \
  -o /tmp/editorteam-pipeline-real.json
```

CI не использует платный API: локальный OpenAI-compatible fake проверяет
фактические вызовы модели, последовательность стадий, repair и защитный отказ.
Внешний прогон оставлен ручным, поскольку он требует выбранных владельцем
моделей и ключей.

Новый кейс добавляется объектом в `evals/cases/cases.json` с `vars.id`, `vars.text`,
`vars.game`, `vars.profile`, `vars.protected_entities` и `vars.expected_properties`.
Фрагменты корпуса дополнительно получают `vars.origin`, каждое защищённое
название должно встречаться в тексте дословно, ссылки и ники не допускаются.
Не добавляйте имена реальных авторов или приватные материалы.

## Диагностика

```bash
node --test evals/tests/evals.test.js
npx promptfoo validate -c evals/promptfooconfig.yaml
npx promptfoo validate -c evals/promptfooconfig.pipeline.yaml
npx promptfoo validate -c evals/promptfooconfig.judge.yaml
python3 -c "import json;d=json.load(open('evals/cases/cases.json'));print(len(d))"
npx promptfoo view   # таблица baseline/candidate по последнему прогону
```

В JSON-выводе каждого прогона поле `results[].response.metadata` содержит
`provider`, `model`, `prompt_version`, `accepted`, `checks_complete`; в offline-режиме
там же стоит `deterministic_only=true`.
