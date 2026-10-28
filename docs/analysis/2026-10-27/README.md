# Анализ качества текста и исследований, 2026-10-27

Пять независимых сессий только читали код и данные: ничего не меняли и не запускали платные API.
Внешние источники искали скиллом research-team.

| Отчёт | Что разобрано |
|---|---|
| [1-editor-quality.md](1-editor-quality.md) | Как EditorTeam правит реальные статьи: оценки, отказы, ложные исправления |
| [2-writing-quality.md](2-writing-quality.md) | Качество текста пишущих Teams: funmeta, marketing, translate, job, svg |
| [3-research-audit.md](3-research-audit.md) | Как ResearchTeam ищет и проверяет информацию; пробный прогон на 11 утверждениях |
| [4-editing-sota.md](4-editing-sota.md) | Практики LLM-редактуры русского текста 2025–2026 в сравнении с EditorTeam |
| [5-research-sota.md](5-research-sota.md) | Практики deep-research-агентов в сравнении с ResearchTeam |

## Статус рекомендаций

- Сделано: приведение salvage к `editor/config/typography.yaml` (отчёт 1, рекомендация 2),
  коммит `5dee120`.
- Остальные рекомендации не выполнены. Первым по всем отчётам стоит настоящее измерение:
  пары «черновик → правка владельца» для `editor/evals/blind_review.js gate`.
