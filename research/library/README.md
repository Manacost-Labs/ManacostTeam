# Постоянная библиотека источников

`transcripts/` хранит оригинальные расшифровки подкастов и видео с таймкодами,
метаданными и проверкой целостности. Она живёт между исследованиями; не удалять
при очистке `build/`. Полные расшифровки и аудио остаются локально, вне Git.

[Рабочий порядок и команды](../deep-research/references/hearthstone-source-library.md).
Сначала искать здесь, затем обращаться к провайдеру или распознавать аудио.
Явное обновление сохраняет прежнюю версию в `transcripts/revisions/`.

## Постоянный сбор

`feeds.json` перечисляет ленты: патчноуты Blizzard (en и китайский сайт),
отчёты и подкаст Vicious Syndicate, Coin Concede, Walk to Work (бывший
Hearthstone Commute), Born to Be Wild, статистику Koloda API (HSGuru-мета,
архетипы, существа Полей сражений, Арена) и новые треды r/hearthstone,
r/CompetitiveHS, r/BobsTavern, r/ArenaHS, r/wildhearthstone.

`../deep-research/scripts/library_refresh.py` забирает каждую ленту через
`source_collector.py` (кэш, паузы после отказов, явный `STALE_LKG`) и дописывает
в `catalog/` (локально, вне Git) только новые записи: `<лента>.jsonl`,
датированные снимки статистики в `catalog/snapshots/`, очередь расшифровок
`catalog/transcript-queue.jsonl` для выпусков за последние 14 дней, которых нет в
архиве, с готовой командой `source_library.py`, и журнал запусков
`catalog/refresh-log.jsonl` с вердиктом каждой ленты. Запись каталога — только
наводка: в исследовании страницу или расшифровку всё равно открывают.
Скрипт возвращает 1, если хотя бы одна лента не получена.

Ручной запуск из `research/deep-research`:

```bash
python3 scripts/library_refresh.py
```

Расписание создаёт владелец. Раз в шесть часов на macOS/Linux (`crontab -e`):

```bash
0 */6 * * * cd /ABSOLUTE/PATH/ManacostTeam/research/deep-research && /usr/bin/env python3 scripts/library_refresh.py >> ../library/catalog/cron.log 2>&1
```

На Windows (основная рабочая копия):

```bash
schtasks /Create /SC HOURLY /MO 6 /TN "ManacostTeam library refresh" /TR "cmd /c cd /d C:\Users\zulut\Documents\ManacostTeam-unified\research\deep-research && python scripts\library_refresh.py"
```

Ключи (Scrape.do, RedditAPI, TranscriptAPI) берутся из окружения или локального
хранилища `source_access.py`, в Git не попадают. Расшифровка из очереди —
отдельный явный шаг: аудио и модель faster-whisper тратят сеть и диск.
