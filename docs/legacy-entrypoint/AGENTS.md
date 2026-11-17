# ManacostTeam: рабочая точка входа

Основной репозиторий находится в `C:\Users\zulut\Documents\ManacostTeam-unified`.
Перед любой разработкой И перед любой работой с материалами (исследование под статью,
написание, обновление, пересборка или редактура статей, гайдов, тир-листов, перевод,
шорткоды, SEO, графика) прочитай в основном репозитории `AGENTS.md`, `CONTEXT.md`,
`docs/TEAM_STANDARD.md` и `docs/PLAYER_EDITORIAL_STANDARD.md`. Эта папка содержит
прежние рабочие копии и материалы; сохраняй их и не объединяй незавершённые правки без
просмотра diff.

Семь Teams и десять переносимых навыков описаны в основном репозитории:
`teams/registry.json`, `teams/README.md`, `release/team-skills/`.
Актуальный выпуск определяется полем release_version в registry.json.

## Обязательный пайплайн для статей, гайдов и обновлений материалов

1. **Никакой генерации статей в обход `manacost-publish`.** Даже если диалог начался со
   свободного поиска («поищи на Reddit / X / YouTube» по ссылке на старую статью), при
   переходе к написанию, обновлению или пересборке материала агент обязан вести запуск
   через `teams/manacost-publish/scripts/publish.py` (`sources → research → draft →
   deletion_pass → fact_review → literary_review → export`) и хранить запреты владельца
   в `author-context.json`. Запрещено писать готовые статьи напрямую в `output/` из
   памяти чата или подменять ревью диагностическим `editor_team.py audit`.
2. **Изоляция ревьюеров.** `fact_review` и `literary_review` запускаются отдельными
   чистыми субагентами без истории авторского чата.
3. **Поля сражений:** никогда не пиши «племя/племена» (только «тип существ»); собирай
   досье карт и дочерних токенов через `python -m editorteam.bg_dossier`, считай дуэли
   1-го хода через `python -m editorteam.bg_sim`, проверяй текст через
   `python -m editorteam.bg_mechanics_gate`, а для тир-листов используй профиль
   `battlegrounds-tierlist`.
4. **Связанный пакет выдачи:** версии со шорткодами и `seo.json` проверяй через
   `python -m editorteam.publication_bundle verify`, чтобы исключить расхождение текста,
   пропуск шорткодов заклинаний таверны и протухание `article_sha256` в SEO.

Команда `/funmeta` или `$funmeta` с необязательными аргументами запускает
`C:\Users\zulut\Documents\ManacostTeam-unified\skills\funmeta\SKILL.md`.
Команда `/bg-meta-report` или `$bg-meta-report` запускает
`C:\Users\zulut\Documents\ManacostTeam-unified\skills\bg-meta-report\SKILL.md`.
Команда `/meta-report` или `$meta-report` запускает
`C:\Users\zulut\Documents\ManacostTeam-unified\skills\meta-report\SKILL.md`.

По постоянному запросу владельца проверенные законченные изменения проекта
нужно коммитить и пушить в `origin` основного репозитория без повторного вопроса.
Сначала выполни подходящие проверки, просмотри diff и состав staged-файлов.
Не включай секреты, пользовательские материалы и чужие незавершённые правки;
не используй force push. При ошибке push сообщи точную причину и статус.
