# Браузерные маршруты и аудит 39 источников — 21 октября 2026

Последний полный прогон завершён в 2026-10-21T08:38:43.862660+00:00. Учтены все **39** записей: **36 доступны**, **3 недоступны**; пропусков и повторов id нет. Доступность означает успешный контракт получения данных, а не подтверждение фактов для статьи. NGA и HSGuru проверены дополнительно к 39 обязательным записям.

В 36 успешных результатах: **23 каталога YouTube через TranscriptAPI**, **4 RSS подкастов**, **9 страниц/поисковых выдач**. Каталог канала не означает просмотр ролика или получение субтитров. RSS не означает повторное распознавание аудио.

Первый прогон этого запуска дал 38 успешных результатов. При повторной сетевой проверке Hearthpwn /decks вернул блокировку, а /forums попал в паузу того же origin. Старые успешные ответы сохранены, но не выданы за свежую доступность. Китайская главная Blizzard не прошла контракт содержимого в обоих прогонах.

## NGA, Bilibili и HSGuru

| Источник | Проверенный результат | Граница результата |
|---|---|---|
| [NGA, Hearthstone](https://bbs.nga.cn/thread.php?fid=422) | Автоматически: Scrape.do super 403/CSR → direct 403/CSR → Patchright/Chrome 200. Прочитан список тем и отдельно [публичная тема](https://bbs.nga.cn/read.php?tid=47758376). | Только открытый гостевой интерфейс; полного охвата всех страниц/комментариев не заявляем. |
| [Bilibili: 炉石传说](https://search.bilibili.com/all?keyword=%E7%82%89%E7%9F%B3%E4%BC%A0%E8%AF%B4) | Поиск работает через Scrape.do super и отдельно через браузер. Открыта [страница ролика](https://www.bilibili.com/video/BV1JHpv6sEEK/), получены публичный текст, дата, описание и список частей. | Медиа и субтитры не получены; на странице есть ограничения отдельных частей, платные/закрытые части не считаются прочитанными. |
| [HSGuru /meta](https://www.hsguru.com/meta) | Scrape.do super, direct, Playwright и Patchright получили Cloudflare 403; отдельный видимый Chrome также не открыл данные. Платный render вернул target 307 и PARSE_FAIL. | Рабочего браузерного доступа к статистике пока нет. Редирект и challenge не считаются данными. |
| [HSGuru через Koloda API](https://api.kolodahearthstone.com/v1/hsguru/meta) | Native JSON 200, контракт data.items.0 выполнен. Ответ содержит fetched_at=2026-10-21T00:16:43.333032+00:00, stale=false, black_empire, patch_36.6.3. | Это доступный альтернативный набор данных; текущий патч нельзя выводить из времени запроса. Для материала требуется явная сверка периода/патча. |

Заимствованы практики [ParsesUnix](https://github.com/Manacost-Labs/ParsesUnix): один браузер, изолированные контексты по хостам, ограничение/переиспользование ресурсов, закрытие страниц и наблюдение публичных JSON-запросов. Собственная реализация последовательная, привязана к одному потоку; очередь worker из upstream не переносилась.

В NGA нажимается реальная публичная ссылка гостевого продолжения один раз. Cookies создаёт сама страница внутри временного контекста. Личный профиль, cookies и заголовки авторизации не импортируются. Наблюдения сети сохраняют только ограниченные метаданные, без значений query и тел ответов; подписанные/сессионные запросы не воспроизводятся и не становятся API автоматически.

## Все обязательные источники

| № | Источник | Последний результат | Реальный объём проверки | Маршрут |
|---|---|---|---|---|
| 1 | [blizzard-cn](https://hs.blizzard.cn/) | PARSE_FAIL | Нет принятого содержимого | см. отказ |
| 2 | [hearthstone-decks](https://www.hearthstone-decks.com/) | OK | Страница / тематический поиск | scrape-super |
| 3 | [judgehype](https://hearthstone.judgehype.com/) | OK | Страница / тематический поиск | scrape-super |
| 4 | [ptt-hearthstone](https://www.ptt.cc/bbs/Hearthstone/index.html) | OK | Страница / тематический поиск | scrape-super |
| 5 | [gamer-hearthstone](https://forum.gamer.com.tw/B.php?bsn=24044) | OK | Страница / тематический поиск | scrape-super |
| 6 | [outofgames](https://outof.games/realms/hearthstone/) | OK | Страница / тематический поиск | scrape-super |
| 7 | [hearthpwn-decks](https://www.hearthpwn.com/decks) | BLOCKED | Нет принятого содержимого | см. отказ |
| 8 | [hearthpwn-forums](https://www.hearthpwn.com/forums) | COOLDOWN | Нет принятого содержимого | см. отказ |
| 9 | [note-hearthstone](https://note.com/) | OK | Страница / тематический поиск | scrape-super |
| 10 | [coin-concede](https://coinconcede.com/episodes/) | OK | RSS; последний GUID есть в архиве | native |
| 11 | [born-to-be-wild](https://www.borntobewildhs.com/podcast) | OK | RSS; последний GUID есть в архиве | native |
| 12 | [beerbrick](https://beerbrick.com/category/deck/) | OK | Страница / тематический поиск | scrape-super |
| 13 | [inven](https://hs.inven.co.kr/) | OK | Страница / тематический поиск | scrape-super |
| 14 | [vs-podcast](https://www.vicioussyndicate.com/data-reaper-podcast/) | OK | RSS; последний GUID есть в архиве | native |
| 15 | [hearthstone-commute](https://hearthstonecommute.libsyn.com/) | OK | RSS; последний GUID есть в архиве | native |
| 16 | [jeefhs](https://www.youtube.com/@JeefHS) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 17 | [shadybunny](https://www.youtube.com/@Shadybunny) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 18 | [xqn](https://www.youtube.com/@xqn_thesad) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 19 | [kris-o-five](https://www.youtube.com/@KrisOFiveHearthstone) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 20 | [zeddy](https://www.youtube.com/@ZeddyHearthstone) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 21 | [youtube-hearthtech7354](https://www.youtube.com/@HearthTech7354) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 22 | [youtube-breadandbutterhs](https://www.youtube.com/@BreadandButterHs) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 23 | [youtube-guddumpog](https://www.youtube.com/@guddumpog) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 24 | [youtube-shadybunny2](https://www.youtube.com/@Shadybunny2) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 25 | [youtube-rduhs](https://www.youtube.com/@RduHS) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 26 | [youtube-slyders_hs](https://www.youtube.com/@Slyders_HS) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 27 | [youtube-dogdogtwitch](https://www.youtube.com/@dogdogtwitch) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 28 | [youtube-sevel07](https://www.youtube.com/@Sevel07) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 29 | [youtube-guddummit](https://www.youtube.com/@guddummit) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 30 | [youtube-asmodaitv](https://www.youtube.com/@AsmodaiTV) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 31 | [youtube-rechotgames](https://www.youtube.com/@RechotGames/videos) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 32 | [youtube-markmckz](https://www.youtube.com/@MarkMcKz) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 33 | [youtube-thijstcg](https://www.youtube.com/@ThijsTCG) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 34 | [youtube-funkimonki](https://www.youtube.com/@FunkiMonki) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 35 | [youtube-hearthstonemathematics](https://www.youtube.com/@HearthstoneMathematics) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 36 | [youtube-chumphs](https://www.youtube.com/@ChumpHS) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 37 | [youtube-regishearthbin](https://www.youtube.com/@RegisHearthbin) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 38 | [youtube-warshack](https://www.youtube.com/@Warshack) | OK | Каталог канала; без видео/субтитров | transcriptapi-channel |
| 39 | [bilibili](https://www.bilibili.com/) | OK | Страница / тематический поиск | scrape-super |

Bilibili и note.com проверены именно с локализованным запросом Hearthstone; доступной общей главной страницы было бы недостаточно. PTT, Gamer и Inven прошли контракт публичной страницы; это не доказывает доступ ко всем отдельным темам.

Для Coin Concede, Born to Be Wild, Data Reaper и Hearthstone Commute самый новый GUID RSS совпал с сохранённой полной расшифровкой. Архив не изменялся, повторного ASR не было. Полные тексты остаются в локальном `research/library/transcripts/` и не входят в Git/переносимые архивы.

## Повторение

Инструкция и ограничения: [browser-source-access.md](../research/deep-research/references/browser-source-access.md). Основные команды из корня проекта:

```powershell
research/library/.venv/Scripts/python.exe research/deep-research/scripts/audit_owner_sources.py --browser --browser-engine patchright --browser-channel chrome --output build/owner-access
research/library/.venv/Scripts/python.exe research/deep-research/scripts/source_access.py collect --url "https://bbs.nga.cn/thread.php?fid=422" --browser --browser-engine patchright --browser-channel chrome --output build/nga.json
```

Аудит пишет по одной квитанции на id, общую таблицу и owner-source-coverage.json. `--refresh` повторно проверяет сеть, сохраняя обязательные паузы после отказов. Ненулевой код означает хотя бы один отказ; `checklist_complete=true` означает учёт всех попыток. `evidence_validated=false` сохранён во всех результатах.

Локальные квитанции этого запуска: `build/browser-source-audit-2026-10-21/owner-release/`; предыдущие прогоны `owner/`, `owner-final/` и отдельные браузерные диагностики оставлены для сравнения. Сырые тела, локальная база и credentials в выпуск не включены.

## Проверки и переносимый выпуск

| Требование | Проверка |
|---|---|
| Переиспользование и изоляция браузера | `test_one_browser_reuses_context_within_domain_and_isolates_domains`; `test_context_limit_evicts_oldest_and_page_limit_recycles`; `test_context_ttl_boundary_recycles_and_close_is_idempotent` |
| Публичный гостевой маршрут и настоящий отказ | `test_public_guest_continue_uses_real_link_once_without_cookie_injection`; `test_public_guest_bootstrap_is_csr_but_permission_denial_stays_terminal`; `test_browser_does_not_follow_genuine_access_denial` |
| Браузерный резерв и ограничение платных повторов | `test_browser_resolves_csr_after_http_routes_and_keeps_one_paid_call`; `test_browser_pause_preserves_paid_render_reserve_after_proven_block`; `test_browser_cooldown_is_scoped_to_engine_and_channel` |
| Безопасность наблюдения сети и ошибок | `test_discovery_redacts_values_and_never_promotes_session_or_signed_request`; `test_route_guard_blocks_private_requests_media_and_writes`; `test_navigation_failure_closes_page_and_hides_exception_text` |
| Учёт всех источников и честный объём | `test_every_registered_source_has_one_receipt_and_explicit_scope`; `test_generic_homepage_does_not_hide_failed_topic_search`; `test_channel_route_returns_metadata_without_opening_or_transcribing_video` |
| Архив без повторной обработки | `test_podcast_archive_is_checked_by_identity_without_rewriting` |

Python 3.13: 154 профильных теста (source*, audit, Chinese adapter, community adapters); Python 3.11: 61 тест изменённых/новых компонентов. Ruff для трёх скриптов и трёх тестовых файлов прошёл. Живые проверки выше дополняют тесты с подставными transport/browser, а не следуют из них.

Выпуск **1.15.0**: research-team **1.10.0**, manacost-publish **1.9.0**. Пакеты собираются и проверяются в изолированном research-снимке от принятого выпуска 1.14.0 с наложением только перечисленных изменений этой задачи. Так сохраняются неизменные опубликованные байты editor-team 1.11.1; параллельные незавершённые изменения editor не включаются. Это не доказательство сборки текущего рабочего editor. Сборка и `--check` прошли; 26 package-тестов, валидация всех 9 entrypoints и 8 CLI smoke-команд из распакованных research-team/manacost-publish завершились успешно без ключей и без установленного браузерного runtime. Рабочий навык manacost-publish обновлён до 1.9.0 после побайтовой сверки с предыдущим выпуском 1.8.0.
