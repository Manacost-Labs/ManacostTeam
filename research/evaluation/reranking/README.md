# BGE: локальное ранжирование результатов поиска

Необязательный пилот после существующего `source_access.py search`.
Использует `BAAI/bge-reranker-v2-m3` через уже применяемый в проекте
Sentence Transformers, без дополнительного стека FlagEmbedding.
В production и переносимые skill-архивы этот пилот пока не включён.

Вход — сохранённый JSON `scrape.do/google-search`; запрос берётся из него.
Модель сравнивает запрос с `title + snippet`. Она предлагает порядок открытия
страниц, а не проверяет их содержание. `evidence_status: discovery_only`,
исходный `position`, URL, diagnostics и `out_of_scope_results` сохраняются.
Новые поля — `rerank_score` (сырой logit, не вероятность достоверности) и
`reranked_position`. При равных оценках сохраняется порядок входа.
Отсутствующие title/snippet (`null`) допустимы, если есть хотя бы одно
непустое текстовое поле; в исходных записях `null` сохраняется.

## Запуск из корня репозитория

Python 3.13, отдельное окружение. Зависимости и веса локальные; внешний LLM
и платный API для ранжирования не нужны. Первичная загрузка весов требует
сети и нескольких ГБ свободного места. Веса в Git не попадают.

```sh
uv venv --python 3.13 build/reranker/.venv
uv pip install --python build/reranker/.venv/bin/python -r research/evaluation/reranking/requirements.txt

# Существующий маршрут поиска, с обычным локальным доступом Scrape.do.
python3 research/deep-research/scripts/source_access.py search \
  --query 'Hearthstone deck statistics' --site hsguru.com \
  --output build/reranker/search.json

# Первый запуск: явно разрешить скачивание закреплённой ревизии модели.
build/reranker/.venv/bin/python research/evaluation/reranking/rerank_search.py \
  --input build/reranker/search.json --output build/reranker/ranked-first.json \
  --allow-download

# Повторно: только локальные веса, новый отчёт.
build/reranker/.venv/bin/python research/evaluation/reranking/rerank_search.py \
  --input build/reranker/search.json --output build/reranker/ranked-local.json
```

По умолчанию CPU, batch 4, первые 50 результатов, максимум 512 токенов
на пару запрос/кандидат. `--max-candidates N` допускает 1–100,
`--batch-size N` — 1–16. Оставшийся хвост сохраняется без оценок после
ранжированной части; его размер явно записан в `unscored_count`.
Длинные пары обрезаются токенизатором: это оценка заголовка/сниппета,
не полного документа. Другая ревизия модели требует явной правки константы.

Отчёт содержит SHA256 точных байтов входа, модель и commit ревизии,
версии ML-пакетов, время, параметры и число обработанных кандидатов.
Файл входа и существующий файл выхода не перезаписываются.
Ошибка модели не приводит к выдаче фиктивного ранжирования.

Дальше исследователь открывает выбранные URL прежними Collector/
`fetch_source.py`, фиксирует реально просмотренные результаты через
`candidates.py` и ведёт охват источников. Не подменяйте SERP `rank` в журнале
новой позицией. Scrape.do-first, RedditAPI-first для Reddit, все 39 источников
владельца, cooldown, проверка свежести и доказательств остаются обязательными.
Высокая оценка BGE не снимает ни одного из этих требований.

## Проверки

```sh
# 12 контрактных тестов без ML-зависимостей; реальный тест пропускается.
python3 -m unittest discover -s research/evaluation/reranking -p 'test_*.py' -v

# 13 тестов, включая настоящий CLI с заранее загруженными весами без сети.
MANACOST_BGE_LIVE_TEST=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  build/reranker/.venv/bin/python -m unittest discover \
  -s research/evaluation/reranking -p 'test_*.py' -v
```

5 ноября 2026 прошли оба режима. Отдельный smoke на трёх синтетических
русских результатах поднял тематический материал выше двух отвлекающих;
это проверка исполнения, не измерение качества на реальном поиске.
Далее нужен один и тот же сохранённый пул Scrape.do, собственные запросы,
человеческая разметка релевантности и сравнение NDCG@k/Recall@k/задержки.
Считайте также исходный охват: reranker не находит отсутствующие URL.

Контрактные тесты включены в существующий Research CI и
`python3 tools/check.py research`. Эти проверки не устанавливают ML-пакеты
и пропускают реальный inference; он запускается отдельной opt-in командой выше.

Первичные API-источники, проверены 5 ноября 2026:
[карточка модели BAAI](https://huggingface.co/BAAI/bge-reranker-v2-m3),
[CrossEncoder](https://sbert.net/docs/package_reference/cross_encoder/cross_encoder.html),
[FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding).

Ревизия весов: `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`.
При локальной проверке: sentence-transformers 5.7.0, torch 2.15.0,
transformers 5.22.1, macOS arm64, CPU. Зависимости вне прямого pin могут
обновляться; каждый отчёт фиксирует фактически установленные версии.
