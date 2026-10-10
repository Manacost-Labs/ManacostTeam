# Стандарт ManacostTeam

Основной Git-репозиторий — https://github.com/Manacost-Labs/ManacostTeam. Основная локальная рабочая копия — `C:\Users\zulut\Documents\ManacostTeam-unified`. Соседняя папка ManacostTeam сохраняется как источник прежних рабочих копий и локальных материалов; её команды должны направлять работу в основной репозиторий.

Семь направлений: EditorTeam, ResearchTeam, SVGTeam, TranslateTeam, XMLTeam, JobTeam и MarketingTeam. У модулей остаются собственные зависимости, инструменты и тесты. Общими являются карта команд, упаковка переносимых навыков и правила передачи результата.

## Источники и пакеты

`teams/registry.json` задаёт имя, Team, модуль, версию, исходную папку и явные mappings ресурсов каждого пакета. `teams/<name>/SKILL.md` — основной переносимый контракт, `skill.yaml` — версия, `agents/openai.yaml` — интерфейс Codex/ChatGPT. Старые специализированные workflows сохраняют свой исходник в модуле; сборщик вкладывает их как WORKFLOW.md или references, а не регистрирует несколько SKILL.md внутри одного навыка.

Исходные Teams и персональные материалы не удаляются. Старые Job `.skill` сохраняются; их редактируемые исходники теперь находятся в job/sources. Marketing перенесён с сохранением специализаций, лицензий и правил рекламы. Кампании, секреты, личные research bundles и непроверенные кандидатные корпусы не входят в общие пакеты.

Сборка всех девяти навыков:

```powershell
python tools/build_team_skills.py
python tools/build_team_skills.py --check
python -m unittest discover -s tests -p 'test_*.py'
```

Результат — release/team-skills/1.4.0: отдельные ZIP и их идентичные `.skill` aliases, combined plugin, index.json и SHA256SUMS. ZIP содержит одну верхнюю папку и ровно один SKILL.md. Архивы воспроизводимы, проверяются на внутренние ограничения проекта: до 500 файлов, 25 MiB на файл, 100 MiB после распаковки и 50 MiB на архив и исключают credentials, кэши и окружения. `build/` — локальная staging-папка и не входит в Git.

Версия и имя согласуются между registry, SKILL.md и skill.yaml. При изменении содержимого обновите версию затронутого навыка и release_version; неизменённые навыки могут сохранить прежнюю версию. Архив с тем же именем обязан сохранять байты во всех опубликованных выпусках. Сборщик проверяет историю до записи и публикует новую папку целиком. Существующий неполный, изменённый или содержащий лишние файлы выпуск отклоняется; его содержимое сохраняется для разбора. `--check` проверяет точный состав и байты всего выпуска.

## Импорт и вызов

| Team | ZIP/skill | Прямой вызов Claude Code |
| --- | --- | --- |
| EditorTeam | editor-team-1.4.0 | /editor-team |
| EditorTeam | manacost-publish-1.0.0 | /manacost-publish |
| ResearchTeam | research-team-1.2.0 | /research-team |
| SVGTeam | svg-team-1.0.1 | /svg-team |
| TranslateTeam | translate-team-1.0.1 | /translate-team |
| XMLTeam | xml-team-1.0.1 | /xml-team |
| JobTeam | job-team-1.0.1 | /job-team |
| MarketingTeam | marketing-team-1.0.1 | /marketing-team |
| Подсветка карт | card-shortcodes-1.0.3 | /card-shortcodes |

**Claude web:** загрузите отдельный ZIP в Customize → Skills при включённом Code execution. Доступность меню зависит от настроек аккаунта/организации. [Официальная инструкция](https://support.claude.com/en/articles/12512180-use-skills-in-claude).

**Claude Code:** распакуйте ZIP с папкой навыка в `.claude/skills/` проекта или в пользовательский каталог навыков. Имя SKILL.md становится `/name`. В этом репозитории уже есть тонкие `.claude/commands` с теми же именами; они разрешают локальные ресурсы через registry. Для combined plugin namespace будет `/manacost-team:research-team` и аналогично для остальных навыков. [Официальный контракт skills](https://code.claude.com/docs/en/skills).

**Локальный Codex:** `.agents/skills/` содержит девять тонких entrypoints для основного репозитория. Они читают канонический SKILL.md из `teams/` и разрешают ресурсы по registry. Исходная папка ManacostTeam тоже получила локальные entrypoints Codex/Claude, направляющие работу в основную копию. После обновления списка навыков их можно выбрать через `/skills`, `$name` или доступный slash picker.

**ChatGPT desktop / Codex:** отдельные ZIP предназначены для доступного интерфейса standalone/custom skills. В ChatGPT web/mobile используйте combined plugin через поддерживаемый интерфейс plugins/marketplace. Plugin содержит portable plugin.json и совместимый Claude manifest; MCP-сервер не требуется. Явный вызов навыка в ChatGPT — через `@`, в Codex — через `$`; enabled skills могут появляться в slash list, но стабильная команда `/name` зависит от клиента. Обычная отправка ZIP в сообщение не регистрирует постоянную команду. Не отправляйте пакет на публичную публикацию без отдельной задачи. [OpenAI: build skills](https://learn.chatgpt.com/docs/build-skills), [slash commands](https://learn.chatgpt.com/docs/reference/slash-commands), [упаковка plugins](https://developers.openai.com/plugins/build/plugins).

Пакет не добавляет аккаунту веб-доступ, API-ключи или отсутствующий runtime. Для каждого выполнения сообщайте только реальные проверки. Основные инструкции работают с доступными средствами ассистента; bundled Python scripts проверяют свои конкретные contracts. XML-пакет — source-assisted workflow: его исходники и lockfile требуют Node/TypeScript dependencies и доступной установки пакетов; отдельный CI smoke проверяет сборку из распакованного ZIP. Без Node или установки dependencies готовый XML runtime недоступен; при их отсутствии допустимо извлекать только наблюдаемые XML-факты с явными ограничениями.

## Завершение разработки

По постоянному запросу владельца завершённые, проверенные изменения проекта нужно коммитить и пушить в origin без повторного вопроса. Пуш — последняя стадия после тестов, просмотра diff и проверки отсутствия секретов/чужих незавершённых правок. Не используйте force push. Если доступ, branch protection или конфликт мешают push, сохраните результат и сообщите точную причину; не выдавайте локальный commit за отправленный.

Для исходной папки действуют те же правила маршрутизации. Изменения старых независимых репозиториев не нужно автоматически пушить в их старые remotes: согласованная разработка ведётся в основной копии.

## Проверка релиза

Минимум: module tests для изменения поведения; validation девяти entrypoints; импорт/запуск helpers из распакованных ZIP; повторная сборка с --check; plugin manifests; git diff --check; inspection staged paths; remote SHA после push. Полный прогон всех модулей нужен только когда затронуты их contracts/runtime. Не объединяйте устаревшие README-baselines с результатами свежих тестов.
