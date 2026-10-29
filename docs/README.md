# Документация ManacostTeam

Для изменения кода начните с [руководства разработчика](../CONTRIBUTING.md).
[Корневая карта](../README.md#структура) показывает каталоги;
[CONTEXT.md](../CONTEXT.md) объясняет границы семи модулей.

## Действующие контракты и команды

| Задача | Документ |
| --- | --- |
| Выбрать модуль, исходник и тесты | [Как менять проект](../CONTRIBUTING.md) |
| Установить навыки, сервер или WordPress | [INSTALL](INSTALL.md) |
| Понять общий процесс и переносимые пакеты | [TEAM_STANDARD](TEAM_STANDARD.md), [каталог Teams](../teams/README.md) |
| Изменить игру, редакционный профиль или формат контекста | [TASK_CONTEXT](TASK_CONTEXT.md) |
| Подготовить статью в Codex | [PUBLICATION_QUICKSTART](PUBLICATION_QUICKSTART.md) |
| Изменить публикационный процесс и допуск материала | [EDITORIAL_PIPELINE_V3](EDITORIAL_PIPELINE_V3.md), [PUBLICATION_REVIEW_CONTRACT](PUBLICATION_REVIEW_CONTRACT.md) |
| Проверить связь утверждений с источниками | [FACTUAL_BOUNDARY](FACTUAL_BOUNDARY.md) |
| Изменить практики редактуры и подачи | [EDITORIAL_PRACTICES](EDITORIAL_PRACTICES.md), [PLAYER_EDITORIAL_STANDARD](PLAYER_EDITORIAL_STANDARD.md) |
| Изменить доступ к источникам | [source-acquisition](../research/deep-research/references/source-acquisition.md), [browser-source-access](../research/deep-research/references/browser-source-access.md) |
| Работать с расшифровками и локальным архивом | [research/library](../research/library/README.md), [библиотека источников](../research/deep-research/references/hearthstone-source-library.md) |
| Узнать изменения выпуска | [CHANGELOG](../CHANGELOG.md), [release notes](releases/), [манифесты](../release/team-skills/) |

## Архитектурные планы

[ARCHITECTURE](ARCHITECTURE.md), [PUBLICATION_IMPLEMENTATION_PLAN](PUBLICATION_IMPLEMENTATION_PLAN.md)
и [RESEARCH_EDITOR_IMPLEMENTATION](RESEARCH_EDITOR_IMPLEMENTATION.md) объясняют
этапы и проектные решения. Сверяйте статус конкретного этапа с реализацией:
план не означает, что описанная возможность уже работает.

## Проверки и исследования по датам

[Полные проверки модулей от 2026-10-29](ALL_MODULE_CHECKS_2026-10-29.md)
содержат найденные ошибки, исправления, результаты и ограничения среды.

[TEAM_VALIDATION](TEAM_VALIDATION.md), [QUALITY_AUDIT](QUALITY_AUDIT.md),
документы с датой в имени и [анализ от 2026-10-27](analysis/2026-10-27/README.md)
сохраняют результаты конкретного прогона, ограничения и аргументы изменений.
Для нового изменения нужны свежие проверки из руководства разработчика и CI.
Исторические отчёты сохраняются на прежних путях, чтобы ссылки оставались рабочими.

[legacy-entrypoint](legacy-entrypoint/README.md) относится к прежней точке входа;
для текущей работы используйте корневые инструкции.
