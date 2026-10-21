# ResearchTeam: устойчивое получение источников — 21.10.2026

Добавлен `source_access.py collect`: повторяемое чтение публичных источников
с проверкой тела, постоянным локальным состоянием и явными причинами отказов.
До изменения каждый вызов низкоуровневого `fetch` заново обращался к провайдеру;
автоматического повторного использования прочитанной страницы и памяти пауз
между исследованиями у этого пути не было.

## Какие практики использованы

Из [ParsesUnix](https://github.com/Manacost-Labs/ParsesUnix/tree/6c0820d0b2a6c279225a0f3f53e2cdd24a0e5a3e)
взяты проверка содержимого после каждой попытки, раздельные причины отказа,
память маршрутов и учёт каждого URL. Из
[Koloda API](https://github.com/Manacost-Labs/api.kolodahearthstone.com/tree/8d409543bd904f829e85bcae5d4a5187f6ab1fd1)
— отдельные контракты транспорта и публикации, сохранение последнего
валидного ответа и запрет выдавать неудачное обновление за свежие данные.
Прочитаны реализации contracts/triage/freshness, response contracts,
publication gate, fetch routes и HTTP resilience. Основные ссылки на файлы
закреплены в [рабочем контракте](../research/deep-research/references/source-acquisition.md).

Фреймворки не вендорятся и не устанавливаются. Это собственная небольшая
реализация на стандартной библиотеке Python. Порядок провайдеров владельца
сохранён: Scrape.do super для веба, RedditAPI для Reddit; публичные RSS и
первичный JSON Koloda читаются напрямую. Автоматического браузера, расписания
и управления сессиями/аккаунтами этот выпуск не добавляет.

## Что изменилось

- HTML требует содержательную canary в читаемом тексте; script/nav не подходят.
  JSON требует непустые поля, RSS/Atom — реальные записи. Пустой ответ и
  challenge с HTTP 200 не считаются успехом.
- Валидный ответ сохраняется транзакционно в SQLite вне репозитория.
  Cache HIT сохраняет исходное время наблюдения и возраст. TTL по умолчанию —
  6 часов; контракт, версия политики и ожидаемый патч входят в идентичность.
- Неудачный ответ не затирает исходник. `--allow-stale` явно возвращает
  `STALE_LKG` не старше семи дней с причиной отказа и ненулевым exit code.
  Без этого флага старый текст при неудачном обновлении не возвращается.
- Паузы переживают новый процесс: блокировка маршрута — 30 минут;
  404/410 — отрицательный кэш URL/контракта на сутки; ошибки разбора/патча —
  короткая пауза. После её окончания основной маршрут проверяется снова.
- `Retry-After` поддерживает секунды и HTTP date. Ограничение origin действует
  на все его маршруты, ограничение провайдера — между доменами. Блокирующего
  ожидания нет: исследование получает причину и срок для следующей попытки.
- Ошибки origin, доступа и контракта не вызывают новые платные маршруты.
  Один render-повтор возможен лишь после фактической блокировки и неудачного
  прямого чтения; пустая CSR-оболочка сама по себе его не разрешает.
- Batch даёт один результат на каждое входное вхождение, включая дубли и
  ошибочные адреса; `unaccounted=0`. Тело не попадает в журнал попыток.
  Прямой HTTP проверяет публичность адреса перед запросом и каждым redirect.
- `meta.stale`, `cached_after_failure`, `serving_cached_dataset` и ожидаемый
  патч проверяются отдельно от успешного HTTP. Все результаты сохраняют
  `evidence_validated=false`: фактический аудит не подменяется транспортом.

## Живая проверка

Receipts сохранены локально в ignored `build/source-collector-2026-10-21/`.

| Источник | Получение | Повтор |
|---|---|---|
| PTT, конкретная тема | direct, 12610 символов; заблокированный Scrape.do уже находился на паузе | HIT, 0 сетевых попыток |
| Bahamut/Gamer, конкретная тема | Scrape.do 403/challenge → direct, 9499 символов | HIT, 0 сетевых попыток |
| Reddit, CompetitiveHS | RedditAPI, 6494 символа нормализованного дерева; полнота не подтверждена | HIT, 0 сетевых попыток |
| Walk to Work RSS | native, 397879 символов feed | HIT, 0 сетевых попыток |
| Koloda HSGuru API | native, 13340 символов JSON; путь `data.items.0` | HIT, 0 сетевых попыток |
| NGA | 403 с указанием необходимых прав/условий; ACCESS_DENIED | отрицательный кэш, 0 сетевых попыток |

Первый контракт Koloda `data.0` был отклонён: `data` — объект, строки лежат
в `data.items`. Это зафиксированный отрицательный опыт, а не успешная попытка.
В живом ответе `stale=false`, `current_period=black_empire`, но
`current_patch_period=patch_36.6.3`. Сборщик сохраняет эти поля; текущая мета
этим тестом не подтверждается. Для публикации требуется независимо проверенный
ожидаемый патч и совпадающие фильтры выборки.

Все 39 площадок повторно не сканировались ради изменения кода; их полный
предыдущий проход — [в отчёте доступности](SOURCE_ACCESS_AUDIT_2026_10_21.md).
Этот выпуск не объявляет NGA/Bilibili/HSGuru web разблокированными.
Четыре полные расшифровки подкастов не изменялись и не распознавались повторно.

## Проверки

129 целевых unittest: `test_source*.py` — 80, Chinese — 30, community — 19.
Новые требования проверены 36 тестами `test_source_collector.py`; остальные
защищают существующие контракты. Ruff нового collector/его тестов и изменённого
source_access проходит. Реальные credentials в тестах не используются.

| Requirement | Evidence |
|---|---|
| Проверка реального содержимого | `test_challenge_200_is_not_success_and_security_script_is_not_a_block`; `test_canary_only_in_script_or_menu_does_not_prove_an_article`; `test_html_contract_rejects_json_or_plain_text_with_matching_words`; `test_json_requires_nonempty_data_and_preserves_zero_values`; `test_rss_and_atom_require_actual_titled_entries` |
| Проверка до расходования провайдера | `test_explicit_contract_is_required_before_spending_on_unknown_source`; `test_response_statuses_remain_distinct_and_do_not_validate_content`; `test_js_shell_and_thin_content_have_different_outcomes` |
| Постоянный кэш и идентичность | `test_primary_preference_and_cache_hit_make_no_second_network_call`; `test_new_collector_process_reuses_durable_snapshot_and_health`; `test_cache_expiry_boundary_and_contract_identity_trigger_revalidation` |
| Последний валидный ответ защищён | `test_failed_refresh_never_replaces_last_good_and_stale_is_explicit`; `test_stale_limit_is_inclusive_and_expired_snapshot_is_not_returned`; `test_checksum_corruption_stops_without_network_or_overwriting_data`; `test_promotion_rejects_unvalidated_candidate_and_keeps_previous_snapshot` |
| Причина отказа управляет маршрутами | `test_terminal_target_failures_never_buy_another_route`; `test_actual_block_can_render_once_after_native_block`; `test_csr_without_block_does_not_trigger_paid_render`; `test_native_origin_down_does_not_trigger_paid_render_after_block`; `test_incomplete_native_response_is_origin_failure_without_render_spend`; `test_native_success_is_reused_while_failed_provider_is_in_cooldown`; `test_dead_url_negative_cache_is_scoped_to_url_and_contract` |
| Ограничения частоты сохраняются | `test_retry_after_pauses_provider_across_domains_and_does_not_sleep`; `test_target_rate_limit_stops_all_routes_on_same_origin`; `test_retry_after_accepts_http_date_and_rejects_nonfinite_delays` |
| Reddit и API сохраняют происхождение | `test_reddit_uses_redditapi_before_any_other_provider`; `test_redditapi_failure_uses_explicit_reserve_provenance`; `test_reddit_reserve_normalizes_public_json_and_never_claims_completeness`; `test_known_rss_and_first_party_api_use_native_structured_transport`; `test_patch_and_stale_flags_override_a_newly_fetched_valid_shape` |
| Учёт URL и транспортные границы | `test_batch_accounts_for_duplicates_and_invalid_inputs_without_leaking_url`; `test_redirect_rejects_private_resolution_before_following`; `test_direct_transport_preserves_target_error_and_enforces_size`; `test_scrape_transport_requests_super_and_render_only_when_requested`; `test_cli_collect_dispatches_through_existing_source_access`; `test_unexpected_adapter_failure_is_accounted_and_next_url_still_runs` |

## Выпуск и оставшиеся границы

Подготовлен research-выпуск 1.14.0: research-team 1.9.0 и manacost-publish
1.8.0. Сборка ведётся в изолированном снимке предыдущего research-выпуска
с наложением только этой задачи. Параллельные редакторские изменения не
включаются; editor-team 1.11.1 сохраняет опубликованные байты, как в 1.13.0.
Это не утверждение о пересборке изменённого runtime editor из текущего HEAD.

Память маршрутов пока содержит счётчики/последний вердикт и паузы, а не
Wilson-ranking, shadow probes или браузерную разведку ParsesUnix. Условные
ETag/304 запросы также не реализованы: повтор экономит запрос через локальный
TTL. Кэш — локальная рабочая копия, не резервная копия на другом устройстве.
Подтверждение формы/доступа не доказывает правильность игровых советов,
полноту форума, независимость авторов или актуальность статистики.

Выпуск проверен: сборка и повторный --check из изолированного снимка,
26 пакетных тестов, валидация девяти entrypoints, запуск doctor и collect
--health/--help из распакованных research-team и manacost-publish. Новые
36 тестов также проходят на Python 3.11 (основной прогон — Python 3.13).
Установленный manacost-publish обновлён до 1.8.0 после побайтовой сверки
с прежним 1.7.0; локальных пользовательских расхождений не было. Секреты,
SQLite, receipts, исходные материалы и расшифровки в ZIP не включены.
