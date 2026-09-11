# ManacostTeam skills

Этот каталог — канонический исходник общих навыков монорепозитория. Не редактируйте `.skill`-архивы как источник: меняйте `SKILL.md`, валидируйте его и собирайте новый пакет отдельным выпуском.

| Skill | Назначение |
|---|---|
| `manacost-monorepo-gate` | Выбор модулей и точечных проверок по diff. |
| `skill-package-manager` | Проверка и выпуск воспроизводимых `.skill`-пакетов. |
| `research-to-publication` | Контракт `research → editor → svg`. |
| `svg-regression-suite` | Регрессия генератора SVG и эталонных спеков. |
| `hearthstone-freshness-audit` | Аудит свежести патча, меты, названий и визуализаций. |
| `release-notes-and-migration` | Межмодульные release notes и безопасные миграции. |

Локальные runtime-skills модулей остаются в `editor/`, `research/` и `svg/`. Общие skills не копируют их правила, а маршрутизируют к ним.
