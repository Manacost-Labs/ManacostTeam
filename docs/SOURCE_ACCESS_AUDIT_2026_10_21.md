# Проверка источников и подкастов — 21.10.2026

Проверены все 39 постоянных источников владельца: исходные 38 адресов и Hearthstone Commute. Дополнительно проверены NGA, IYingdi, TapTap, GamerSky, 17173, Reddit и HSGuru — всего 46 источников/маршрутов в основном проходе. Затем выполнены адресные повторы и резервные публичные чтения.

Не все маршруты работают. Ответ 200, сгенерированный запрос и чужая ссылка из общей выдачи не считаются прочитанным источником. Успешное чтение одной темы не доказывает полноту сайта или доступность всех комментариев.

## Основные результаты

- TranscriptAPI: health отвечает; все 23 выбранных YouTube-канала разрешились по handle и вернули по три недавних видео. Это проверка discovery, а не расшифровка всех роликов. Пробное получение субтитров последнего HearthTech (`W6roW25u8Hc`) вернуло 404 `TranscriptsDisabled`, retryable=false, credits_refunded=true; повтор не выполнялся.
- Scrape.do structured Google Search работает, но в первом проходе только 17 из 46 запросов дали непустой результат в запрошенном домене. Есть 502/429 и выдача с ослабленным site-фильтром. Более широкие брендовые запросы успешно нашли NGA, Reddit и HSGuru.
- Для проблемных форумов, Reddit и HSGuru в новом публичном reader включён super по умолчанию. Проверены super, render, ожидание до 5 секунд и региональные варианты; это не гарантирует прохождение защиты.
- Исправлен HTML cleaner: void-теги и необязательные закрывающие теги внутри меню/форм раньше могли скрывать последующую статью. Живой JudgeHype после исправления дал 5666 символов вместо 72.
- Полные оригинальные расшифровки четырёх подкастов сохранены локально с разрешением пользователя: 21865.93 секунды аудио, около 6 часов 4 минут. Все четыре контрольных повторных обращения дали HIT без ASR. Полные тексты, аудио, модель, venv и ключи не входят в Git/ZIP.

## Все постоянные источники

| Источник | Поиск Scrape.do, первоначальный запрос | Рабочее чтение / ограничение |
|---|---|---|
| [blizzard-cn](https://hs.blizzard.cn/) | ошибка 502 | Полная новость /news/24304163/index.html через super: SUCCESS, 664 символа; корневая страница частичная |
| [hearthstone-decks](https://www.hearthstone-decks.com/) | ошибка 502 | Scrape.do super: 5164 символов; Hearthstone-Decks : news, decks et base de données de cartes Hearthstone |
| [judgehype](https://hearthstone.judgehype.com/) | 1 ссылок нужного домена | Scrape.do super: 5666 символов; Guides et news pour Hearthstone - JudgeHype |
| [ptt-hearthstone](https://www.ptt.cc/bbs/Hearthstone/index.html) | 1 ссылок нужного домена | Публичная тема прочитана прямым HTTP: 12610 символов; Scrape.do super/render/tw остался заблокирован |
| [gamer-hearthstone](https://forum.gamer.com.tw/B.php?bsn=24044) | 0 ссылок нужного домена | Scrape.do super: 9499 символов; 【心得】【心得】G9《黑暗帝國霸業》新卡評分(下)+6勝亂鬥牌組分享 @爐石戰記 哈啦板 - 巴哈姆特 |
| [outofgames](https://outof.games/realms/hearthstone/) | 10 ссылок нужного домена | Обычный Scrape.do прочитал страницу: 4646 символов; super-проход отдельно получил challenge |
| [hearthpwn-decks](https://www.hearthpwn.com/decks) | 10 ссылок нужного домена | Scrape.do: ERROR; PROVIDER_HTTP_ERROR |
| [hearthpwn-forums](https://www.hearthpwn.com/forums) | ошибка 429 | Scrape.do: BLOCKED; ['challenge_page'] |
| [note-hearthstone](https://note.com/) | ошибка 502 | Scrape.do: BLOCKED; ['access_blocked'] |
| [coin-concede](https://coinconcede.com/episodes/) | ошибка 502 | Scrape.do super: 6203 символов; Episodes / Coin Concede |
| [born-to-be-wild](https://www.borntobewildhs.com/podcast) | ошибка 502 | RSS и публичное MP3 доступны; последний выпуск полностью распознан. HTML через super заблокирован |
| [beerbrick](https://beerbrick.com/category/deck/) | ошибка 502 | Scrape.do super: 2873 символов; Deck - デッキ アーカイブ / BeerBrick Hearthstone |
| [inven](https://hs.inven.co.kr/) | 0 ссылок нужного домена | Scrape.do super: 11526 символов; 하스스톤 인벤 |
| [vs-podcast](https://www.vicioussyndicate.com/data-reaper-podcast/) | 9 ссылок нужного домена | Scrape.do super: 14623 символов; Data Reaper Podcast – Vicious Syndicate |
| [hearthstone-commute](https://hearthstonecommute.libsyn.com/) | 10 ссылок нужного домена | RSS и публичное MP3 доступны; последний выпуск полностью распознан. HTML через super заблокирован |
| [JeefHS](https://www.youtube.com/@JeefHS) | 2 ссылок нужного домена | TranscriptAPI: канал JeefHS, 3 видео; полные видео не исследовались |
| [Shadybunny](https://www.youtube.com/@Shadybunny) | ошибка 502 | TranscriptAPI: канал Shadybunny, 3 видео; полные видео не исследовались |
| [XQN](https://www.youtube.com/@xqn_thesad) | 1 ссылок нужного домена | TranscriptAPI: канал XQN, 3 видео; полные видео не исследовались |
| [Hearthstone Tips by Kris O Five](https://www.youtube.com/@KrisOFiveHearthstone) | 0 ссылок нужного домена | TranscriptAPI: канал Hearthstone Tips by Kris O Five, 3 видео; полные видео не исследовались |
| [Zeddy Hearthstone](https://www.youtube.com/@ZeddyHearthstone) | 0 ссылок нужного домена | TranscriptAPI: канал Zeddy Hearthstone, 3 видео; полные видео не исследовались |
| [HearthTech7354](https://www.youtube.com/@HearthTech7354) | 0 ссылок нужного домена | TranscriptAPI: канал Hearth Tech, 3 видео; полные видео не исследовались |
| [BreadandButterHs](https://www.youtube.com/@BreadandButterHs) | 7 ссылок нужного домена | TranscriptAPI: канал Bread and Butter, 3 видео; полные видео не исследовались |
| [guddumpog](https://www.youtube.com/@guddumpog) | 0 ссылок нужного домена | TranscriptAPI: канал GuddumPog, 3 видео; полные видео не исследовались |
| [Shadybunny2](https://www.youtube.com/@Shadybunny2) | 0 ссылок нужного домена | TranscriptAPI: канал Shadybunny2, 3 видео; полные видео не исследовались |
| [RduHS](https://www.youtube.com/@RduHS) | 2 ссылок нужного домена | TranscriptAPI: канал Rdu Hearthstone, 3 видео; полные видео не исследовались |
| [Slyders_HS](https://www.youtube.com/@Slyders_HS) | 0 ссылок нужного домена | TranscriptAPI: канал Slyders_HS, 3 видео; полные видео не исследовались |
| [dogdogtwitch](https://www.youtube.com/@dogdogtwitch) | 0 ссылок нужного домена | TranscriptAPI: канал dogdog, 3 видео; полные видео не исследовались |
| [Sevel07](https://www.youtube.com/@Sevel07) | 0 ссылок нужного домена | TranscriptAPI: канал Sevel, 3 видео; полные видео не исследовались |
| [guddummit](https://www.youtube.com/@guddummit) | 2 ссылок нужного домена | TranscriptAPI: канал GuDDummit, 3 видео; полные видео не исследовались |
| [AsmodaiTV](https://www.youtube.com/@AsmodaiTV) | 0 ссылок нужного домена | TranscriptAPI: канал Asmodai Hearthstone, 3 видео; полные видео не исследовались |
| [RechotGames](https://www.youtube.com/@RechotGames/videos) | 2 ссылок нужного домена | TranscriptAPI: канал Rechot, 3 видео; полные видео не исследовались |
| [MarkMcKz](https://www.youtube.com/@MarkMcKz) | 0 ссылок нужного домена | TranscriptAPI: канал MarkMcKz, 3 видео; полные видео не исследовались |
| [ThijsTCG](https://www.youtube.com/@ThijsTCG) | 0 ссылок нужного домена | TranscriptAPI: канал Thijs Hearthstone, 3 видео; полные видео не исследовались |
| [FunkiMonki](https://www.youtube.com/@FunkiMonki) | 0 ссылок нужного домена | TranscriptAPI: канал Funki Monki, 3 видео; полные видео не исследовались |
| [HearthstoneMathematics](https://www.youtube.com/@HearthstoneMathematics) | 1 ссылок нужного домена | TranscriptAPI: канал Hearthstone Mathematics, 3 видео; полные видео не исследовались |
| [ChumpHS](https://www.youtube.com/@ChumpHS) | 3 ссылок нужного домена | TranscriptAPI: канал Chump, 3 видео; полные видео не исследовались |
| [RegisHearthbin](https://www.youtube.com/@RegisHearthbin) | 0 ссылок нужного домена | TranscriptAPI: канал RegisHearthbin, 3 видео; полные видео не исследовались |
| [Warshack](https://www.youtube.com/@Warshack) | 1 ссылок нужного домена | TranscriptAPI: канал Warshack, 3 видео; полные видео не исследовались |
| [bilibili](https://www.bilibili.com/) | ошибка 502 | Поиск/страница/публичный search API не дали пригодного материала: challenge/тонкая оболочка; прямой API 412 |

## Китайские площадки и форумы

- **Bahamut/Gamer.com.tw:** через super+render прочитана конкретная тема G9 о новых картах и колодах для шести побед, 9499 символов. Первоначальная site-выдача была посторонней; нужная тема найдена через ссылки раздела и брендовый запрос.
- **PTT:** доступен прямой публичный HTTP, прочитана конкретная тема G9 (12610 символов). Super, render, ожидание и регион tw не сделали Scrape.do рабочим для проверенных URL. Похожие темы G9 на двух площадках нельзя считать независимыми подтверждениями без проверки автора/перепоста.
- **IYingdi:** Scrape.do для выбранного поста возвращал 502, в том числе super/render/hk. Прямой публичный запрос прочитал статью и коды (4172 символа). Это исторический пример с датой 05.09.2026, а не текущая мета октября.
- **NGA:** брендовый поиск через Scrape.do находит реальные страницы bbs.nga.cn и ngabbs.com; чтение bbs.nga.cn заблокировано 403/access_blocked даже с super/render/hk. Alias JSON route не дал содержимого. Полный пост и ответы не получены.
- **Bilibili:** homepage — оболочка; поиск с super/render/hk — challenge; API — error/412. Не заявлять проверенные видео, субтитры или комментарии по этому проходу.
- **TapTap:** поиск и публичная страница гайдов доступны, 3140 символов. Это каталог; конкретный гайд нужно читать отдельно.
- **GamerSky:** super прочитал портал (17472 символа), но это не подтверждает прочитанный Hearthstone-гайд; конкретная статья остаётся отдельной задачей.
- **17173:** подходящий текст по проверенному URL не получен; ошибка/тонкий ответ.
- **hs.blizzard.cn:** super прочитал саму новость о запуске, а не только список заголовков. Китайский регион и глобальные сроки проверяются раздельно.

## Reddit и HSGuru

По последнему указанию владельца RedditAPI (`redditapis.com`) закреплён как основной путь Reddit, Scrape.do — резерв. Ключ подключён через закрытое локальное хранилище. Живые проверки RedditAPI успешны: два поиска (r/CompetitiveHS — 8 постов, r/wildhearthstone — 2), лента r/hearthstone — 8 постов; прочитаны 16 комментариев из трёх разных обсуждений (8 + 5 + 3). Среди них есть возражения по техкартам, личные результаты и неудачный сценарий новой колоды. Полнота дерева комментариев провайдером не подтверждена (`listing_status=unknown`), поэтому 16 — полученная выборка. Это доступ к сообществу, а не статистика меты. В постоянных инструкциях закреплены регулярные отдельные Reddit-проходы, независимые темы и содержательные комментарии с возражениями.

Проверенные темы: [выбор карт и муллиган](https://www.reddit.com/r/CompetitiveHS/comments/1x8cxex/), [возвращение и бюджетные колоды](https://www.reddit.com/r/wildhearthstone/comments/1x3gp1u/), [сборки дополнения и первый опыт](https://www.reddit.com/r/hearthstone/comments/1xavg5q/).

Брендовые запросы `Hearthstone decks reddit` и `HSGuru decks` через Scrape.do находят оригинальные URL. Однако чтение проверенных страниц Reddit и HSGuru, включая JSON Reddit и отдельную колоду HSGuru, осталось заблокировано после super+render+wait+us. Поисковый сниппет не подменяет пост, комментарии, состав колоды или фильтры статистики.

Публичный Koloda HSGuru API работает как явно названный резерв: fetched_at=2026-10-21T00:16:43Z, stale=false. Но metadata одновременно содержит current_period=black_empire и current_patch_period=patch_36.6.3. Поэтому свежесть загрузки не считается доказательством актуальности конкретной статистической выборки; перед использованием нужно проверить период/патч каждого результата.

## Проверки кода и выпуска

Выполнены 126 целевых тестов: source_access 16, source_library 16, chinese_hearthstone 30, community_sources 19, source_breadth 9, search_tools 36. PYTHONUTF8=1; тесты используют отсутствующий/временный credential store, реальные аккаунты не расходуются. Ruff новых source_access/source_library и их тестов проходит. Более старые два адаптера имеют семь прежних lint-замечаний вне затронутой логики.

| Requirement | Evidence |
|---|---|
| Секреты вне материалов и выводов | test_local_credentials_allowlist_and_environment_precedence; test_nested_output_redacts_keys_values_and_provider_urls; test_network_error_hides_token_bearing_exception_without_retry |
| Посторонняя выдача не подтверждает форум | test_search_never_accepts_google_results_outside_requested_site; test_site_filter_accepts_real_subdomains_and_records_empty_scope |
| Super и browser options сохранены | test_protected_sources_use_super_and_browser_options_are_preserved |
| Статья не теряется после меню | test_fetch_preserves_article_after_void_tags_in_dropped_navigation; 30 прежних Chinese tests |
| Повтор не запускает ASR | test_second_run_uses_archive_without_calling_producer; test_audio_cache_survives_missing_audio_and_missing_runtime; 4 живых HIT |
| Все 39 адресов учтены | test_owner_registry_contains_all_39_exact_urls |

GPU: faster-whisper 1.2.1, large-v3, CUDA/float16, batch=8; NVIDIA runtime wheels локально вне Git. Отдельно проверен CUDA-запуск постоянного source_library.py после настройки DLL. Семантическая точность всех реплик/имён не подтверждается одним успешным запуском ASR.

Пакеты 1.13.0 собраны из изолированного снимка базы 65856bb с наложением только изменений источников этой задачи. Соседний commit 848c7c9 меняет runtime редактора без новой версии его portable skill; его изменения не включаются в этот research-выпуск, editor-team-1.11.1 сохраняет прежние опубликованные байты. Сборка/--check и 26 пакетных тестов выполнены на указанном снимке; это не подтверждает пересборку нового runtime editor из HEAD.

Операционные receipts и публичные snapshots находятся локально в ignored build/podcasts-source-audit-2026-10-21. Полные расшифровки — в research/library/transcripts, редакционные заметки — в research/library/notes. Ключи находятся в закрытом пользовательском хранилище за пределами репозитория; значения в отчёт не включаются.

Дополнительная проверка выпуска: девять entrypoints прошли quick_validate в UTF-8; source_access, source_library и community_sources успешно запустили doctor из распакованных research-team-1.8.0 и manacost-publish-1.7.0. В smoke использован отсутствующий credential store. Все 21 файла нового выпуска скопированы в release/team-skills/1.13.0. Установленные manacost-publish и funmeta сверены с предыдущими версиями перед обновлением; пользовательских расхождений не было.
