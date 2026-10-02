# Готовые навыки ManacostTeam

Версия 1.0.0: семь Teams и отдельная подсветка карт. Для Claude загружайте ZIP;
одноимённые `.skill` содержат идентичные байты. Для ChatGPT web/mobile используйте
combined plugin в поддерживающем импорт клиенте.

| Навык | ZIP |
| --- | --- |
| EditorTeam | [editor-team](1.0.0/editor-team-1.0.0.zip) |
| ResearchTeam | [research-team](1.0.0/research-team-1.0.0.zip) |
| SVGTeam | [svg-team](1.0.0/svg-team-1.0.0.zip) |
| TranslateTeam | [translate-team](1.0.0/translate-team-1.0.0.zip) |
| XMLTeam | [xml-team](1.0.0/xml-team-1.0.0.zip) |
| JobTeam | [job-team](1.0.0/job-team-1.0.0.zip) |
| MarketingTeam | [marketing-team](1.0.0/marketing-team-1.0.0.zip) |
| Контекстные шорткоды карт | [card-shortcodes](1.0.0/card-shortcodes-1.0.0.zip) |
| Все восемь в одном plugin | [manacost-team plugin](1.0.0/manacost-team-1.0.0-plugin.zip) |

[Импорт, вызов и ограничения среды](../../docs/TEAM_STANDARD.md).
[Контрольные суммы](1.0.0/SHA256SUMS), [машинный индекс](1.0.0/index.json).

XML включает workflow, исходники и lockfile; сборка требует Node.js, pnpm и
установки dependencies. Остальные Python helpers и 22 SVG-примера проверены
из распакованных архивов. Облачные аккаунты навыки автоматически не устанавливают.
