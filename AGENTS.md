# Инструкция для ИИ-агентов (Codex, Cursor, любые LLM-инструменты)

Этот репозиторий — генератор SVG-графиков в стиле Hearthstone для статей hs-manacost.ru.
Прочитай этот файл, если тебя попросили сделать график, диаграмму, инфографику,
дайджест, тир-лист или любую картинку со статистикой Hearthstone.

## Как сделать график

1. **Живые данные** (мета, Арена, Поля сражений, легендарки, дайджест статей) — готовые команды:
   ```bash
   python3 hearthstone-svg-charts/scripts/from_api.py meta --png
   python3 hearthstone-svg-charts/scripts/from_api.py --help   # все 11 команд
   ```
2. **Данные пользователя или собранные тобой** — собери JSON-спек и передай через stdin:
   ```bash
   echo '{"type":"bars","title":"...","data":[...]}' | \
     python3 hearthstone-svg-charts/scripts/make_chart.py - -o chart.svg
   ```
   21 тип: bars, line, donut, tierlist, beforeafter, matchup, badge, timeline,
   digest, scatter, radar, stackbars, author, versus, quote, mulligan,
   facts, cards, bump, notice, poster.
   Полный справочник спеков: `hearthstone-svg-charts/references/generator.md`.
   Эталоны каждого типа со спеками: `hearthstone-svg-charts/examples/`.
3. **Проверь**: `python3 hearthstone-svg-charts/scripts/validate.py chart.svg` — ERRORs чини обязательно.
4. **PNG для соцсетей**: `python3 hearthstone-svg-charts/scripts/export_png.py chart.svg` (нужен resvg: `brew install resvg`).

## Правила (нарушать нельзя)

- Фон вокруг деревянной рамки прозрачный: никаких фоновых прямоугольников на весь viewBox.
- Внутри SVG только data-URI и `#`-ссылки — внешние URL не загрузятся при вставке через `<img>`.
- Значения на графике сходятся с данными до последней цифры; доли в сумме дают 100.
- Данные не выдумывать. В сноске исследований: источник, период, размер выборки.
- Золото `#d9ab49` — только мелкие акценты. Иконки классов/героев не перекрашивать.
- Проценты с одним знаком после точки. Дельты со знаком и стрелкой ▲/▼.

## Первый запуск

```bash
python3 hearthstone-svg-charts/scripts/fetch_assets.py        # игровые ассеты
python3 -m pip install --user fonttools brotli                # вшивание шрифта Belwe
```

Дизайн-система: `hearthstone-svg-charts/references/design-tokens.md` (палитра, шрифты),
`frame.md` (рамки и ассеты). Скилл-инструкция для Claude Code: `hearthstone-svg-charts/SKILL.md`.
