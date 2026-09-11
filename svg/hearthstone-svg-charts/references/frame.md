# Рамка и пергамент

График = пергаментная панель в деревянной рамке; всё СНАРУЖИ рамки прозрачно. Никогда не заливай весь viewBox фоном.

Генератор `make_chart.py` рисует «парадную» версию рамки (мягкая тень предмета, бевелы под единый источник света сверху-слева, золотые уголки-накладки, пятна выцветания на пергаменте, тканевая лента заголовка) — при ручной вёрстке бери его вывод за образец (`examples/`). Ниже — базовая версия для ручных случаев.

Два режима. По умолчанию — векторный. Аутентичный — когда пользователь просит «настоящую рамку из игры» или график заглавный.

## Режим 1: векторная рамка (по умолчанию)

Лёгкая (~2 КБ), масштабируется без артефактов, ничего не качает. Вставляй блок сразу после `<svg>`, до контента графика. Координаты даны для viewBox `0 0 800 450` — при другой высоте меняй только `H` (высота) в отмеченных местах.

```svg
<defs>
  <linearGradient id="wood" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#6b3f21"/>
    <stop offset="0.35" stop-color="#5f371d"/>
    <stop offset="0.65" stop-color="#472712"/>
    <stop offset="1" stop-color="#2e160b"/>
  </linearGradient>
  <linearGradient id="parchment" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#f7e8bf"/>
    <stop offset="1" stop-color="#ead6a7"/>
  </linearGradient>
  <linearGradient id="goldEdge" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#efc96f"/>
    <stop offset="0.5" stop-color="#d9ab49"/>
    <stop offset="1" stop-color="#a67c2e"/>
  </linearGradient>
  <radialGradient id="vignette" cx="0.5" cy="0.5" r="0.75">
    <stop offset="0.75" stop-color="#30251c" stop-opacity="0"/>
    <stop offset="1" stop-color="#30251c" stop-opacity="0.18"/>
  </radialGradient>
  <filter id="grain" x="0" y="0" width="100%" height="100%">
    <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" result="n"/>
    <feColorMatrix in="n" type="matrix"
      values="0 0 0 0 0.45  0 0 0 0 0.36  0 0 0 0 0.26  0 0 0 0.06 0"/>
    <feComposite operator="in" in2="SourceGraphic"/>
  </filter>
</defs>

<!-- пергамент (кромка уходит под рамку) -->
<rect x="14" y="14" width="772" height="422" rx="10" fill="url(#parchment)"/>
<rect x="14" y="14" width="772" height="422" rx="10" fill="url(#vignette)"/>
<rect x="14" y="14" width="772" height="422" rx="10" filter="url(#grain)" fill="#fff"/>

<!-- деревянная рамка -->
<rect x="9" y="9" width="782" height="432" rx="14" fill="none"
      stroke="#1c0d06" stroke-width="2"/>
<rect x="10" y="10" width="780" height="430" rx="13" fill="none"
      stroke="url(#wood)" stroke-width="12"/>
<rect x="17.5" y="17.5" width="765" height="415" rx="8" fill="none"
      stroke="url(#goldEdge)" stroke-width="1.6"/>

<!-- золотые заклёпки по углам -->
<g fill="url(#goldEdge)" stroke="#5d3f12" stroke-width="0.8">
  <circle cx="17.5" cy="17.5" r="4"/><circle cx="782.5" cy="17.5" r="4"/>
  <circle cx="17.5" cy="432.5" r="4"/><circle cx="782.5" cy="432.5" r="4"/>
</g>
```

При высоте H≠450: `422→H-28`, `432→H-18`, `430→H-20`, `415→H-35`, заклёпки `432.5→H-17.5`.

Заголовочная плашка (опционально, для заголовка в стиле красной панели Arena):

```svg
<rect x="40" y="34" width="720" height="44" rx="8" fill="#8d171d" stroke="#5d0d13" stroke-width="1.5"/>
<rect x="42" y="36" width="716" height="20" rx="6" fill="#a8262d" opacity="0.5"/>
<text x="400" y="64" text-anchor="middle" font-family="Cinzel, 'Palatino Linotype', Georgia, serif"
      font-size="26" font-weight="700" fill="#f7e8bf" letter-spacing="0.5">ЗАГОЛОВОК</text>
```

Для контента Battlegrounds замени `#8d171d`/`#5d0d13` на `#3d2335`/`#2a1725`.

## Режим 2: аутентичная рамка (ассеты из игры)

Настоящие рамки HS-Arena с прозрачным центром накладываются ПОВЕРХ пергамента. Внешние URL в SVG запрещены (не загрузятся через `<img>`) — только data-URI из `assets/datauri/`.

Два ассета:
- `main-page-rail-border.png` (1190×698, ~24 КБ, тонкое тёмное дерево) — основной, аспект близок к 16:9.
- `deck-border.png` (239×95, ~3 КБ, золочёная компактная рамка) — для широких низких панелей: бейджи, шапки, легенды.

Генерация 9-slice разметки (углы не искажаются при любом размере панели):

```bash
python3 scripts/frame9.py main-page-rail-border.png --x 6 --y 6 --w 788 --h 438 --corner 45
```

Скрипт печатает готовый `<g>...</g>` с data-URI внутри — вставь его после пергаментного прямоугольника. Пергамент в этом режиме рисуй с отступом ~12 от краёв рамки, скругление 6.

Если аспект панели в пределах ±20% от аспекта ассета, допустимо проще — одна растянутая картинка вместо 9-slice:

```svg
<image href="<data-URI из assets/datauri/main-page-rail-border.png.txt>"
       x="6" y="6" width="788" height="438" preserveAspectRatio="none"/>
```

Пергамент-текстура из игры (`arena-parchment.jpg`, 77 КБ) — только для заглавных графиков, когда размер файла не критичен: `<image>` с `preserveAspectRatio="xMidYMid slice"` внутри `<clipPath>` со скруглённым прямоугольником панели, поверх — vignette из векторного режима.

## Каталог игровых иконок (assets/datauri/*.txt)

Все data-URI уже в PNG (webp-оригиналы конвертированы при загрузке — поэтому PNG-экспорт через resvg их рендерит). Вставка:

```svg
<image href="<data-URI>" x="..." y="..." width="26" height="26"/>
```

| Группа | Файлы | Применение |
|---|---|---|
| Классы (11) | `class-mage`, `class-paladin`, … | подписи в графиках по классам |
| Типы существ BG (12) | `tribe-murlocs`, `tribe-demons`, `tribe-dragons`, `tribe-beasts`, `tribe-mechs`, `tribe-nagas`, `tribe-undead`, `tribe-pirates`, `tribe-quilboar`, `tribe-elementals`, `tribe-duo`, `tribe-all` | статистика по типам в BG |
| Тир таверны (7) | `bg-tier1` … `bg-tier7` | тирлисты существ/героев BG |
| Редкости (4) | `rarity-common`, `rarity-rare`, `rarity-epic`, `rarity-legendary` | распределение редкостей, пыль |
| Прочее | `mana` | мана-кривые, плейсхолдеры |
| Герои BG | `bg-hero-<Имя>` — скачивается по требованию: `python3 scripts/fetch_assets.py --bg-hero "Alexstrasza"` (английское имя) | графики/дайджесты по героям |

Цвета редкостей (из дизайн-системы, для баров/сегментов рядом с гемами): обычная `#858585`, редкая `#315376`, эпическая `#644c82`, легендарная `#866027`, счётчики `#f7db48`.

Иконки не тонировать, не обрезать, минимум 22×22 единиц.
