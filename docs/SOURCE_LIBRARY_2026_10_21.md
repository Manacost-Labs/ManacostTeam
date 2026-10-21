# Постоянные источники и подкасты: проверка 21.10.2026

Реестр содержит все 38 точных адресов владельца: 15 сайтов/разделов и 23
YouTube-канала. Общая инструкция, ResearchTeam, manacost-publish, funmeta,
meta-report и гайды по героям направляют исследование к одному контракту.
Другие существующие источники сохранены. Тематический обход фиксируется
отдельно; главная страница и сгенерированный план не считаются изучением темы.

Постоянный архив находится в `research/library/transcripts/`, вне `build/`.
Расшифровки остаются локально между запусками, исключены из Git и ZIP.
Сетевой провайдер/ASR вызывается только после проверки архива; повторная
обработка требует явного refresh. Прежняя версия сохраняется, повреждённая
запись вызывает ошибку без автоматической повторной оплаты.

Проверки нового модуля: `python -X utf8 -m unittest discover -s
research/deep-research/tests -p test_source_library.py` — 16 тестов, успешно.

| Требование | Доказательство |
|---|---|
| Все 38 точных адресов | `test_owner_registry_contains_all_38_exact_urls` сравнивает полный набор URL, включая оба Shadybunny и оба guddum канала. |
| Попытка/план не равны изучению | `test_planned_or_missing_attempts_never_count_as_completed`, `test_all_outcomes_require_real_attempt_and_reason_or_material`. |
| Повтор не вызывает провайдера | `test_second_run_uses_archive_without_calling_producer`, `test_cached_youtube_alias_does_not_contact_any_provider`. |
| Сохранённый текст доступен без аудио/ASR | `test_audio_cache_survives_missing_audio_and_missing_runtime`. |
| Целостность и сохранение истории | `test_corrupted_archive_does_not_trigger_paid_retry`, `test_explicit_refresh_preserves_previous_version`, `test_failed_refresh_preserves_existing_archive`. |
| Пустой/некорректный ответ не кэшируется | `test_empty_or_invalid_transcript_is_never_cached`. |
| Одновременная обработка не дублируется | `test_concurrent_episode_lock_prevents_provider_call`. |
| Поиск сохраняет оригинал, время и источник | `test_search_preserves_exact_text_timestamps_and_source`. |
| Подкаст discovery сохраняет GUID/audio/дату | `test_rss_keeps_guid_date_enclosure_and_publisher_transcript`, `test_atom_and_empty_feed_remain_discovery`. |
| Транспорт и идентичность записей | `test_source_host_and_credential_guards_before_network`, `test_metadata_and_language_identity_prevent_false_cache_hits`. |

Смежные проверки: `test_source_breadth.py` — 9; `test_search_tools.py` — 36;
`test_community_sources.py` — 19. Для subprocess-тестов Windows задан
`PYTHONUTF8=1`; без него первоначальный search-tools прогон получил ошибку
декодирования stdout, а не функциональный отказ поиска. Ruff нового скрипта
и тестов проходит. Полный benchmark всех модулей не относится к этой задаче.

Живая проверка HTTP входных страниц: 37 ответов 200, HearthPwn Decks — 403.
HTTP 200 не доказывает отсутствие JS-оболочки, полноту комментариев или доступ
к расшифровке. Сохранённые операционные receipts находятся в ignored
`build/source-library-2026-10-21/`, а не в публикационных источниках.

Успешно прочитаны RSS из ссылок издателей:

- Coin Concede: `https://feeds.libsyn.com/70241/rss`, 483 записи;
- Born to Be Wild: `https://anchor.fm/s/14c0b64c/podcast/rss`, 345 записей;
- Data Reaper: `https://anchor.fm/s/e47aa0/podcast/rss`, 214 записей.

Последний выпуск в прочитанном RSS Data Reaper датирован 14.02.2026;
не объявлять его текущим анализом октября без проверки остальных площадок.
Количество записей RSS не означает полноту исторического архива.

Локально установлены Python 3.12 runtime, faster-whisper 1.2.1, PyAV 15.1.0,
youtube-transcript-api 1.2.4. Загружена модель `small`. Реальный CPU/INT8 прогон
на синтезированном английском WAV создал timed segments, второй вызов дал
HIT без ASR. Это проверка запуска и кэша на синтетической речи; точность
распознавания реального Hearthstone-подкаста и его полнота не подтверждены.
Начальная PyAV 19.0.2 оказалась несовместима с faster-whisper 1.2.1;
проверенная версия зафиксирована в optional requirements.

Токены TranscriptAPI и Scrape.do отсутствуют в текущем окружении. Их платные
живые обращения не проверялись. Публичный caption fallback для YouTube-зеркала
Coin Concede 568 сообщил недоступность; полной расшифровки этого выпуска в
архиве нет. Подключение провайдера не выдаётся за выполненную расшифровку.

Пакеты 1.12.0 собираются из чистого HEAD с наложенными только изменениями этой
задачи: соседние незавершённые правки editor не включаются. Сборка и повторная
проверка `--check` прошли; source-library doctor из обоих распакованных
пакетов подтвердил 38 источников. 26 тестов `test_team_packages.py` прошли в чистой сборочной копии.
Все девять локальных entrypoints прошли
quick_validate. Установленные manacost-publish и funmeta обновлены после
сверки с их прежними версиями; для standalone-пакетов задан пользовательский
HEARTHSTONE_SOURCE_LIBRARY на постоянный архив этого проекта. Это локальный portable release, без
отдельной публикации GitHub Release или развёртывания сервиса.
