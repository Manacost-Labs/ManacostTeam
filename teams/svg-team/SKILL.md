---
name: svg-team
description: "Графики, тир-листы и инфографика Hearthstone из проверенных данных."
metadata:
  version: "1.0.0"
---

# SVGTeam

Работай по [SVG workflow](references/svg-workflow.md), где scripts/assets/references/examples относятся к корню пакета. Прочитай подходящий тип из [generator reference](references/generator.md).

Вход — подтверждённые данные и задача читателя. Выбери подходящий из 22 типов, укажи источник, период и выборку, когда применимо. Не выдумывай цифры; не представляй устаревший API-срез текущим.

Собери JSON-спек и выполни `python scripts/make_chart.py spec.json -o chart.svg`, затем `python scripts/validate.py chart.svg`. Просмотри результат, проверь цифры и читаемость. SVG должен быть автономным, с прозрачным фоном вокруг рамки. Для PNG используй scripts/export_png.py, если доступен resvg. Дай SVG вместе со спеком; не утверждай, что PNG создан, если exporter недоступен.
