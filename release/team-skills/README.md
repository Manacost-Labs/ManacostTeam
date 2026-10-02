# Готовые навыки ManacostTeam

Версия 1.0.1: семь Teams и отдельная подсветка карт. Для Claude загружайте ZIP;
одноимённые `.skill` содержат идентичные байты. Для ChatGPT web/mobile используйте
combined plugin в поддерживающем импорт клиенте.

| Навык | ZIP |
| --- | --- |
| EditorTeam | [editor-team](1.0.1/editor-team-1.0.1.zip) |
| ResearchTeam | [research-team](1.0.1/research-team-1.0.1.zip) |
| SVGTeam | [svg-team](1.0.1/svg-team-1.0.1.zip) |
| TranslateTeam | [translate-team](1.0.1/translate-team-1.0.1.zip) |
| XMLTeam | [xml-team](1.0.1/xml-team-1.0.1.zip) |
| JobTeam | [job-team](1.0.1/job-team-1.0.1.zip) |
| MarketingTeam | [marketing-team](1.0.1/marketing-team-1.0.1.zip) |
| Контекстные шорткоды карт | [card-shortcodes](1.0.1/card-shortcodes-1.0.1.zip) |
| Все восемь в одном plugin | [manacost-team plugin](1.0.1/manacost-team-1.0.1-plugin.zip) |

[Импорт, вызов и ограничения среды](../../docs/TEAM_STANDARD.md).
[Контрольные суммы](1.0.1/SHA256SUMS), [машинный индекс](1.0.1/index.json).

XML включает workflow, исходники и lockfile; сборка требует Node.js, pnpm и
установки dependencies. Остальные Python helpers и 22 SVG-примера проверены
из распакованных архивов. Облачные аккаунты навыки автоматически не устанавливают.
