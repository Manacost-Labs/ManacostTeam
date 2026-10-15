# Готовые навыки ManacostTeam

Версия 1.8.0: семь Teams и девять навыков, включая подготовку статьи и подсветку карт. Для Claude загружайте ZIP;
одноимённые `.skill` содержат идентичные байты. Для ChatGPT web/mobile используйте
combined plugin в поддерживающем импорт клиенте.

| Навык | ZIP |
| --- | --- |
| EditorTeam | [editor-team](1.8.0/editor-team-1.8.0.zip) |
| ResearchTeam | [research-team](1.8.0/research-team-1.3.1.zip) |
| SVGTeam | [svg-team](1.8.0/svg-team-1.0.1.zip) |
| TranslateTeam | [translate-team](1.8.0/translate-team-1.2.1.zip) |
| XMLTeam | [xml-team](1.8.0/xml-team-1.0.1.zip) |
| JobTeam | [job-team](1.8.0/job-team-1.0.1.zip) |
| MarketingTeam | [marketing-team](1.8.0/marketing-team-1.0.1.zip) |
| Контекстные шорткоды карт | [card-shortcodes](1.8.0/card-shortcodes-1.0.3.zip) |
| Подготовка и проверка статьи | [manacost-publish](1.8.0/manacost-publish-1.2.0.zip) |
| Все девять в одном plugin | [manacost-team plugin](1.8.0/manacost-team-1.8.0-plugin.zip) |

[Импорт, вызов и ограничения среды](../../docs/TEAM_STANDARD.md).
[Контрольные суммы](1.8.0/SHA256SUMS), [машинный индекс](1.8.0/index.json).
[Релиз на GitHub](https://github.com/Manacost-Labs/ManacostTeam/releases/tag/v1.8.0),
[изменения и совместимость](../../docs/QUALITY_AUDIT.md).

XML включает workflow, исходники и lockfile; сборка требует Node.js, pnpm и
установки dependencies. Остальные Python helpers и 22 SVG-примера проверены
из распакованных архивов. Облачные аккаунты навыки автоматически не устанавливают.
