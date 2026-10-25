# Готовые навыки ManacostTeam

Архивы навыков — ассеты [GitHub Release v1.19.0](https://github.com/Manacost-Labs/ManacostTeam/releases/tag/v1.19.0).
В этом каталоге хранится только манифест каждого выпуска: `index.json`
(SHA256 архивов и `download_base`) и `SHA256SUMS`. Ассет выпуска `X.Y.Z`
доступен по адресу `https://github.com/Manacost-Labs/ManacostTeam/releases/download/vX.Y.Z/<файл>`.
Для Claude загружайте ZIP; одноимённые `.skill` содержат идентичные байты.
Для ChatGPT web/mobile используйте combined plugin в поддерживающем импорт клиенте.

| Навык | ZIP |
| --- | --- |
| EditorTeam | [editor-team-1.14.0.zip](https://github.com/Manacost-Labs/ManacostTeam/releases/download/v1.19.0/editor-team-1.14.0.zip) |
| ResearchTeam | [research-team-1.11.0.zip](https://github.com/Manacost-Labs/ManacostTeam/releases/download/v1.19.0/research-team-1.11.0.zip) |
| SVGTeam | [svg-team-1.0.1.zip](https://github.com/Manacost-Labs/ManacostTeam/releases/download/v1.19.0/svg-team-1.0.1.zip) |
| TranslateTeam | [translate-team-1.2.1.zip](https://github.com/Manacost-Labs/ManacostTeam/releases/download/v1.19.0/translate-team-1.2.1.zip) |
| XMLTeam | [xml-team-1.0.1.zip](https://github.com/Manacost-Labs/ManacostTeam/releases/download/v1.19.0/xml-team-1.0.1.zip) |
| JobTeam | [job-team-1.0.1.zip](https://github.com/Manacost-Labs/ManacostTeam/releases/download/v1.19.0/job-team-1.0.1.zip) |
| MarketingTeam | [marketing-team-1.0.1.zip](https://github.com/Manacost-Labs/ManacostTeam/releases/download/v1.19.0/marketing-team-1.0.1.zip) |
| Контекстные шорткоды карт | [card-shortcodes-1.0.3.zip](https://github.com/Manacost-Labs/ManacostTeam/releases/download/v1.19.0/card-shortcodes-1.0.3.zip) |
| Подготовка и проверка статьи | [manacost-publish-1.12.0.zip](https://github.com/Manacost-Labs/ManacostTeam/releases/download/v1.19.0/manacost-publish-1.12.0.zip) |
| Все 9 в одном plugin | [manacost-team-1.19.0-plugin.zip](https://github.com/Manacost-Labs/ManacostTeam/releases/download/v1.19.0/manacost-team-1.19.0-plugin.zip) |

[Контрольные суммы](1.19.0/SHA256SUMS), [машинный индекс](1.19.0/index.json),
[импорт, вызов и ограничения среды](../../docs/TEAM_STANDARD.md),
[установка](../../docs/INSTALL.md).

Сборка: `python tools/build_team_skills.py` пишет архивы в игнорируемый
`build/team-skills/<версия>/` и манифест сюда. Публикация:
`python tools/publish_team_skills.py release --execute` после push манифеста.
Архивы всех выпусков 1.0.0–1.19.0 перенесены в GitHub Releases и сверены по SHA256.
