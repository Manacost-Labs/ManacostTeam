---
name: research-to-publication
description: "Ведёт задачу по цепочке research → manacost-publish/editor → shortcodes → seo → svg. Используй при любом написании, обновлении или пересборке статьи на основе поиска (включая переход от поиска в чате к команде «напиши/перепиши статью»)."
---

# От исследования к публикации

Этот skill координирует модули и закрывает обход пайплайна при живом диалоге («сначала поищи на Reddit/YouTube, а теперь перепиши статью»). Не пиши и не переписывай статью напрямую в `output/` из памяти чата.

1. Зафиксируй тему, режим игры, аудиторию, профиль жанра (`battlegrounds-guide`, `battlegrounds-tierlist`, `battlegrounds-article`, `constructed-guide`, `meta-report` и др.), патч и требуемые артефакты. Все замечания и запреты владельца сразу сохраняй в `author-context.json`, чтобы они переживали `/compact` и смену модели. Если пользователь запросил только исследование, остановись после research.
2. Если источником служит `.hsreplay.xml`, сначала загрузи `skills/xml-replay-analysis/SKILL.md` и получи anonymized replay evidence bundle: муллиган, события, card IDs/русские названия, build, packet evidence и ограничения. Один реплей — наблюдение, не доказательство меты или винрейта.
3. Загрузи `research/deep-research/SKILL.md` и собери проверяемый research bundle: утверждения, источники, даты/патч, confidence и ограничения. Для Полей сражений дополнительно собери полное досье карт, дочерних токенов и заклинаний пула через `python -m editorteam.bg_dossier` (а для расчёта боёв 1-го хода — `python -m editorteam.bg_sim`, не одноразовые скрипты в `Temp`). Пробелы не дополняй из памяти.
4. Если пользователь запросил текст, обновление статьи или глубокую пересборку, веди работу через `teams/manacost-publish/scripts/publish.py` (`teams/manacost-publish/SKILL.md`): `sources → research → draft → deletion_pass → fact_review → literary_review → export`. Спроси один раз о WordPress-шорткодах, если ответ ещё не дан.
5. Перед ревью для текстов о Полях сражений запусти детерминированный чекер `python -m editorteam.bg_mechanics_gate` (анти-тавтология лобби, запрет слова «племя», проверка `Боевого клича` в руке, таймингов 2-го хода и зон токенов).
6. Этапы `fact_review` и `literary_review` (включая все строки `owner_checks`) запускай **в отдельных изолированных субагентах** без истории авторского окна и саморецензии автора. Диагностический `editor_team.py audit` не заменяет ревью.
7. При подготовке версии со шорткодами (`teams/card-shortcodes/SKILL.md`, включая подсветку заклинаний таверны БГ из `build_shortcode_catalog`) и/или SEO для IndexPilot (`teams/article-seo/SKILL.md`) свяжи и проверь итоговые файлы через `python -m editorteam.publication_bundle verify` (`article.md`, `article-shortcodes.md`, `seo.json` с актуальным `article_sha256`). После любой правки текста статьи пересобирай шорткоды и `seo.json`, не оставляя устаревшие копии во временных папках.
8. Если пользователь запросил графику, загрузи `svg/hearthstone-svg-charts/SKILL.md`: каждая цифра происходит из research bundle; рядом с графиком сохрани JSON-спек, источник, период и размер выборки.

Не используй стиль авторского корпуса как источник фактов и не выдавай график за доказательство без исходных данных и периода.
