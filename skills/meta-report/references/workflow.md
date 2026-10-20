# Workflow и контракт мета-отчета

## Кто выполняет работу

ResearchTeam собирает доказательства; EditorTeam пишет статью; независимые
reviewer проверяют смысл и литературную подачу. Codex оркестрирует доступными
MCP/веб-инструментами. Для исследования нужны обычные протоколы ResearchTeam,
для текста — правила голоса и стиля EditorTeam. Дополнительный API модели
не требуется. Python helper только проверяет структуру и сохраняет этапы.

## Источники и остановка поиска

Начинай с действующего патча и последующих серверных исправлений Blizzard.
На HSReplay, HSGuru и Vicious Syndicate проверяй фактический период и фильтры,
а не только дату страницы. Два доступных статистических источника полезны
для сопоставления; недоступность одного не повод изобретать его показатели.
Не усредняй проценты разных сайтов и не делай из них общую выборку.
Официальные страницы подтверждают изменения, но не силу колоды в ладдере.

Для всех классов проверь популярные архетипы, сильные непопулярные варианты
и основания слабых результатов. EN/RU запросы, X, Reddit, YouTube и веб
используются по исследовательскому протоколу; фиксируй реально прочитанное,
ограничения доступа, контрдоказательства и еще открытые вопросы. Обсуждения
дают идеи и практику, не статистическую репрезентативность. Чужая перепечатка
не независимое подтверждение. При недоступных страницах используй публичные
оригиналы и пометь ограничение; не обходи платный доступ.

После первого прохода ищи адресно по пробелам. Остановись, когда вопросы
читателя обоснованно отвечены либо дальнейшие доступные поиски не меняют
ответ. Нерешенные вопросы сохраняются явно. Не набирай источники ради квоты.
Для изменения относительно прошлого выпуска нужны сопоставимые периоды,
патчи и фильтры. Для бюджетной рекомендации проверь цену именно выбранного
состава; не переноси стоимость и винрейт с другой версии архетипа.

## Папка запуска

В `build/meta-reports/<unique-run>/` находятся:

- `research/`: стандартный research bundle, план, ledgers, snapshots и аудит;
- `meta-report.json`: дополнительный контракт мета-отчета;
- `sources.json`: полные source candidates стандартного publication runner;
- `publication-handoff.json`: результат compiler ResearchTeam;
- `accepted.json`: хеши трех принятых файлов; создается `prepare`;
- `publication/`: существующий publication state, версии статьи и отзывы;
- новый `final.md` после успешного экспорта.

Исследовательские записи и пользовательские исходники остаются локальными.
Два исторических TXT владельца можно читать для формы, не копировать в Git,
не добавлять автоматически в одобренный корпус и не использовать как текущую мету.

`init` создает стандартный исследовательский шаблон. Заполни его plan.json:
аудитория, статистический/стратегический тип, reader questions, provisional
sections (обзор + классы + статистика), EN/RU phrases и приоритет источников.
Порядок классов в статье выбирается редактором, а не порядком JSON-ключей.

Перед handoff выполни релевантные validators ResearchTeam и независимый
semantic audit, привязанный к текущим хешам claims/evidence/sources. Затем:

```powershell
python research/deep-research/scripts/editorial_handoff.py RUN/research --plan RUN/editorial-plan.json --output RUN/publication-handoff.json --report RUN/decision-coverage.json
```

Схема editorial-plan и handoff — в docs/EDITORIAL_PIPELINE_V3.md; не создавай
второй несовместимый компилятор. В handoff нужны обзор и классовые главы,
проверенные claims, цитаты, условия, исключения и confidence. При пробелах
используй `research_ready_with_gaps`; обязательный вопрос остается отвеченным
в доступной области, а неизвестное не превращается в утверждение.

## Дополнительный JSON

`init` создает schema_version=1. Заполняются следующие поля.

| Поле | Контракт |
| --- | --- |
| `as_of`, `format`, `patch` | Дата YYYY-MM-DD, standard/wild, подтвержденный патч. Не подставляй latest. |
| `rank`, `region`, `window_hours`, `scope_note` | Целевой срез и читательские ограничения. Фактически доступные срезы указаны у каждой метрики. |
| `official_checks` | Проверка patch и нужных hotfix: kind, claim_id, evidence_ref, checked_on, effective_on. Ссылка evidence ведет на Blizzard, дата действия не позже as_of. |
| `trend_claim_ids` | Непустые ссылки на поддержанные claims общей картины. |
| `classes` | Ровно 11 ключей из init. status=covered/gap, chapter_id, assessment_claim_ids, deck_ids, gap. У класса без списка нужен объясненный gap и подтвержденная оценка в собственной главе. |
| `decks` | Опубликованные выбранные составы; несколько на класс допустимы. |
| `statistics`, `statistics_gap` | Метрики либо честное объяснение, почему точной статистики нет. |
| `rankings` | Отдельные сопоставимые рейтинги. Нет статистики — нет численного топа. |
| `assessments` | Необязательные оценки underrated/overrated/emerging с subject, claim_ids и scope_note. |
| `gaps` | Существенные ограничения простыми строками. |

Каждая запись `decks` содержит:

```json
{
  "id": "unique-list-id",
  "class": "mage",
  "name": "Точное название сборки",
  "archetype": "Название архетипа",
  "plan_claim_ids": ["CLM-plan"],
  "limitation_claim_ids": ["CLM-limit"],
  "legality_claim_ids": ["CLM-legality"],
  "list_evidence_ref": "E-list",
  "code_provenance": "author-export",
  "code": "полный проверенный deckstring из источника",
  "deck_list": {
    "format": 2,
    "heroes": [637],
    "cards": [[12345, 2]],
    "sideboards": []
  }
}
```

Пример схематичен, не игровая сборка. В deck_list перепиши полный независимый
опубликованный список с проверенными DBF ID/количествами. format=2 для Стандарта,
1 для Вольного; cards — пары [DBF,count], sideboards — [DBF,count,ownerDBF].
Проверь героя/класс, размер колоды, лимиты копий/легендарок, дополнительные зоны,
допуски по формату и рунам отдельно в legality claims. Декодер их не устанавливает.
Авторский код должен присутствовать в полном сохраненном источнике.
`reconstructed-list` требует `reconstruction_note` и пометки читателю под кодом:
«Код восстановлен из опубликованного состава». Для encode/decode доступен
`python skills/funmeta/scripts/funmeta.py --help`. Неполный список остается gap.

Запись `statistics`:

```json
{
  "id": "metric-id",
  "metric": "winrate",
  "value": 56.2,
  "grain": "deck",
  "subject_id": "unique-list-id",
  "source_id": "snapshot-id-from-sources-json",
  "evidence_ref": "E-stat",
  "claim_id": "CLM-stat",
  "patch": "verified-patch",
  "format": "standard",
  "rank": "diamond-to-legend",
  "region": "all-regions",
  "start": "2026-10-19T12:00:00Z",
  "end": "2026-10-20T12:00:00Z",
  "population": "описание учитываемых партий источника",
  "sample_games": null,
  "sample_note": "Источник не раскрывает число партий"
}
```

Это синтетический пример полей, не подтвержденная цифра. metric=winrate/popularity;
grain=deck/archetype. У архетипа subject_id задает его однозначную идентичность,
а не произвольно выбранный лист. Процент должен быть в дословной цитате evidence.
sample_games — положительное целое либо null с объяснением. Отсутствие выборки
не означает нулевую выборку. При малом/неизвестном числе партий сохраняй
осторожность. Не вычисляй процент без подтвержденных числителя/знаменателя.
Не назначай сборке винрейт всего архетипа и не выдавай сравнение за причинность.

`rankings` содержит title, stat_ids в порядке убывания, universe и scope_note.
Метрики одного рейтинга должны совпадать по source_id, metric, grain, patch,
format, rank, region, периоду и population. `universe=selected-decks` означает
«среди проверенных сборок». `source-table` требует table_evidence_ref на полную
таблицу того же источника. Reviewer проверяет полноту и границы слова «топ».
Лидерства на всех рангах и в Легенде описываются раздельно.

Числа, evidence, план игры, редкость/стоимость, класс/герой и законность состава
требуют смысловой проверки. Существование ссылки и совпадение числа не доказывают
поддержку утверждения. Это ограничение всех структурных проверок helper.

## Передача и независимые отзывы

```powershell
python skills/meta-report/scripts/meta_report.py check RUN
python skills/meta-report/scripts/meta_report.py prepare RUN
python skills/meta-report/scripts/meta_report.py next RUN
python skills/meta-report/scripts/meta_report.py submit RUN --stage draft --artifact RUN/article.md
python skills/meta-report/scripts/meta_report.py next RUN
```

Дальше `next` возвращает роли и входы для двух независимых reviewer. Передай
субагенту инструкции текущего этапа, candidate/handoff/source paths и требуемую
схему из docs/PUBLICATION_REVIEW_CONTRACT.md. Весь meta-report.json доступен как
дополнительный контекст: цифры, срезы, выбранные составы и пробелы. Не передавай
проверяющим чужие verdict. Литературный reviewer работает с brief, голосом,
ограничениями и текстом; фактологический — также с полным evidence.

```powershell
python skills/meta-report/scripts/meta_report.py submit RUN --stage fact_review --artifact RUN/factual.json
python skills/meta-report/scripts/meta_report.py next RUN
python skills/meta-report/scripts/meta_report.py submit RUN --stage literary_review --artifact RUN/literary.json
python skills/meta-report/scripts/meta_report.py export RUN --output RUN/final.md
```

Для содержательной правки: `revise RUN --artifact RUN/revised.md`, затем оба
новых отзыва. Для технически поврежденного отчета reviewer один
`submit --retry-review`, по правилам базового publication runner. Он проверяет
актуальные хеши, версии, независимые отзывы и лимит ревизий. Нельзя править
state.json или accepted.json ради смены статуса. После prepare изменившееся
исследование передается в новом запуске; прежние материалы сохраняются.

Структурная проверка статьи требует все классовые `##` заголовки и каждый
выбранный код под соответствующим `###` названием в своем классе. Проценты
сверяются со списком метрик. Корректную привязку цифры к колоде, условия,
оговорки и причинность устанавливает независимый reviewer. Служебные поля
не превращаются в заголовки читательских абзацев.
