# Гайд по колоде: шаблон, план, рубрика и однообразные начала

Работа в `feat/deck-guide-experience` поверх 7a950db. Другая сессия параллельно
меняла `research/**`; её пути не затрагивались, коммиты — только по своим путям.
Ветки не переключались; stash/reset, слияние, push, сборка пакетов, версии и
платные API не выполнялись. Эталонный гайд по Раза ОнД прочитан из ignored
`build/gold-references/` и в Git не переносился; тесты и шаблон синтетические.

## Что добавлено

- **Шаблон** `editor/.claude/skills/hs-edit/references/deck-guide-template.md`:
  порядок решений, подготовка (пакет опыта, тексты карт, коды колод, план),
  шесть форм совета, проверка перед сдачей, чего не делать. Примеры придуманы.
- **Правила автору**: раздел 6 `docs/PLAYER_EDITORIAL_STANDARD.md`,
  `DECK_GUIDE_GUIDANCE` в `owner_review.py` (попадает в `craft_guidance` для
  draft, deletion_pass и literary_review гайда по колоде), блок `deck_guide` в
  `next` (сводка пакета опыта, `mastery_allowed`), тексты трёх навыков.
- **План**: `article_plan.genre = "deck_guide"`, разделы получают `role` и
  `card_ids`. Проверяется ровно один раздел `mechanics` сразу после вступления,
  его присутствие в `depends_on` зависящих ролей (прямо или цепочкой), `card_ids`
  раздела мастерства и наличие среди них карточки `threshold`/`order`. Порядок
  фактических блоков проверяет прежний `plan_checks`. Прежние планы валидны.
- **Рубрика**: `advice_has_condition_and_reason`, `mastery_has_threshold_or_order`,
  `term_before_definition` включаются только при `genre = deck_guide`. Остальные
  статьи, мета-отчёты и прежние запуски проверяются десятью строками без
  изменений. Отзыв из десяти строк для гайда по колоде не разрешает submit/export
  (`missing category`), состояние читается. Категории добавлены в
  `owner_eval.NEEDS_REVIEWER`.
- **Handoff**: необязательные `advice_form` (шесть форм) и `first_person`
  (bool) в `decision_cards`; Python и Go отклоняют неизвестную форму, старые
  bundle проходят. Пакет опыта читается из `chapters[*].decision_cards`;
  сводка покрытия считается по карточкам, поле сводки в handoff не требуется.
- **Проверка** `owner.paragraph_starts` (review): серия ≥ 10 абзацев одного
  раздела «Название — …» с допуском одного постороннего абзаца либо ≥ 6 подряд
  с одним первым словом. Профили Полей сражений и `constructed-guide`. Числа
  калибровки и результат на гайде-эталоне — `editor/docs/OWNER_EVAL.md`.

## Решения и ограничения

- Расширенная рубрика включается планом, а не профилем: `constructed-guide` —
  профиль по умолчанию для любой constructed-статьи, и менять для всех них
  рубрику, фикстуры и Go было бы шире задачи. Если план забыл `genre`, рубрика
  остаётся десятистрочной; жанр задаёт редактор в `context`.
- Go (`editorialreview.ValidateOwner`) принимает расширение «всё или ничего»
  (10 либо 13 строк), промпт перечисляет три категории, `DecisionCard` читает
  `advice_form`/`first_person`. `/v2/edit` жанра гайда не получает, поэтому Go
  само расширенную рубрику не запрашивает.
- `owner.paragraph_starts` в архиве срабатывает на 172 из 297 гайдов:
  «Карта — роль и условие» — собственная форма автора. Структура не отличает роль от
  пустой оценки; находка лишь отправляет автора на проверку серии.
- Имя контейнера пакета опыта в handoff не было задано контрактом; принято
  `decision_cards[*].advice_form`. Если research положит пакет в другое место,
  править нужно `article_structure.experience_cards`.
- Новых Python-модулей нет: `article_structure.py` и `owner_review.py` уже в
  ресурсах manacost-publish. Шаблон гайда по колоде попадает в EditorTeam вместе
  с каталогом `references`; для manacost-publish его нужно добавить в ресурсы
  отдельно (registry здесь запрещён), в навыке ссылка дана по имени файла.

## Проверки

Из `editor` с `PYTHONUTF8=1 PYTHONIOENCODING=utf-8`:
`.venv/Scripts/python -m pytest -q` — **1126 passed, 38 skipped, 5 subtests
passed** (было 1097; +29 в `tests/test_deck_guide.py`), 443,98 с.
Ruff `src tests sidecars/nlp` — чисто. Go из `editor/go`: `go.exe vet ./...` —
exit 0, `go.exe test ./...` — 18 пакетов ok. Корневой
`python -m unittest discover -s tests -q`: 225 тестов, 2 ошибки setUpClass
(`test_installation`, `test_team_packages`: архив editor-team-1.15.15 уже
опубликован, версия не поднята — ожидаемо), `test_meta_report` проходит.
`editor-team owner-eval` на apm-2026-11-09: 0 error, 2 review на эталонах
(как до изменения), принятая версия 0 / 0.
