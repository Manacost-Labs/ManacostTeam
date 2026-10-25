# Team standard

Канонические инструкции и переносимые пакеты перечислены в [registry](../teams/registry.json).

- [job-team](../teams/job-team/SKILL.md) — `/job-team`.

Сборка: `python tools/build_team_skills.py` из корня репозитория. Архивы собираются в build/team-skills/<версия>/ и публикуются в GitHub Releases; в Git — только манифест release/team-skills/<версия>/. Зависимости и тесты модуля остаются в его собственном каталоге.
