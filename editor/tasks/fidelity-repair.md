# Сохранение степени и локальная проверка цитат

База: 5bddeb0, чистый main, единственная рабочая копия. Пользователь просит
устранить четыре дефекта v17, сохранить полезную редактуру/абзацы и показать
новое сравнение тех же десяти фрагментов прямо в чате. Старые результаты
build/live-manacost-local-final-2026-10-19 сохраняются как исторические данные.

Gate A: GPT-6 Luna по прямому запросу владельца вместо серверного 5.6 Luna.
Подтверждены причины: в prose недооценены полная фраза/смысловой дубль/степень;
в bugfix сообщение finding не включает конечную точку reading_quote.

План: общий контекстный контроль, без списка запрещённых фраз и подмены
результатов. Только одиночная конечная точка необязательна при связи finding
с цитатой; слова, внутренние знаки, вопросы/восклицания/многоточия и точное
совпадение цитаты с candidate сохраняются. Критик оценивает степень внутри
scope и не путает её с избыточной словесной обвязкой. Никаких новых стадий,
расширения retry/repair или снятия fact/negation/keep_span guards.

Применены EditorTeam, Go language/testing и code-testing. Server skillctl,
ai-check/ai-security-check, Serena/codegraph, staticcheck/golangci/govulncheck
недоступны в Windows-клиенте; локальные rg и Go gates доступны. Исходники и
вызовы модели локальные/замороженные, новое исследование игровых фактов не нужно.

- [x] RED: терминальная точка и полный маршрут локального repair воспроизвели отказ v17.
- [x] GREEN: адресный repair сохраняет соседнее упрощение и абзац.
- [x] v18 Go test/vet/build; Gate B GPT-6 Luna; просмотр diff.
- [x] Контроль четырёх прежних черновиков; свежий полный v17/v19 и v20 на тех же 10 входах (полный v17/v18 не запускался).
- [x] Два свежих независимых слепых отзыва; полный before/after подготовлен для ответа в чате.
- [x] Итоговый отчёт и проверенные собственные коммиты; push/remote SHA фиксируются в финальном ответе.

Контроль v17/v18: 8 HTTP 200, 16 живых вызовов и 16 явно помеченных fixtures
analysis/draft. Gods восстанавливает степень с сохранённым двоеточием;
bugfix complete=true, но teaser всё ещё принят с эхом, decks оставляет повтор.
Это отрицательный диагностический результат, не основание объявлять v18 готовой.
Каталог build/live-manacost-fidelity-replay-2026-10-19 сохранён без перезаписи.

v19 расширяет только advisory диагностику: до пяти слов; короткое общее начало
из двух букв допускается для слов от пяти букв при общей согласной в следующих
четырёх рунах. Это не морфология и не запрет. Возможны ложные подсказки, которые
критик обязан оценить в контексте; unrelated/functional по-прежнему допустимы.
Границы предложений/строк, лимит четырёх подсказок, source suppression сохранены.
RED/GREEN воспроизводит пропущенное чередование, дальнюю границу и отрицательный
случай без общей согласной. Повторённый полный gate пройден.

v19 полный опыт завершён: targets кроме decks, все 20 checks complete.
v20 (f36323b) переносит контраст функций определений в analysis/writer/critic.
В новом полном v20 проходе decks/gods/bugfix исправлены, но teaser ложно
прошёл односторонний regex и сохранил «выйдут … выхода». Не повторено полезное
редакторское разделение description/CTA в patch37. В source эта граница отсутствует,
поэтому первоначальная трактовка «исходная граница» неверна. Сырые тексты сохранены
в build/live-manacost-fidelity-accepted-2026-10-19. Два слепых отзыва: new 4,
old 2, tie 3, disagreement 1; human 0. Все промежуточные опыты остаются отдельно.

v21: обычный edit восстанавливает уникальные неизменённые 3+3 словесные опоры
исходных границ перед QA/critic и после repair. Только пробельная замена,
новые split не удаляются; другие режимы не затронуты. Неуверенные опоры,
код/HTML/маркированные и нумерованные списки пропускаются. RED/GREEN и тесты
лексической неизменности, повторного применения, Unicode/CRLF, неоднозначных
опор и обоих pipeline hooks прошли. Gate B GPT-6 Luna clear; все Go gates pass.
Заключительный проход берёт все десять фактических v20 итогов как начальные
candidates; generation reuse маркируется, QA/critic/repair выполняются заново.
Это не десять новых генераций с нуля.

V21: 13 живых вызовов + 20 fixtures, 7 edited / 2 unchanged / 1 rejected.
Rewards не проходит exact strength_changes после retry, source возвращён
fail closed; teaser сохраняет эхо. Сбой и все raw results сохранены.
V22: общая оценка наследованного эха; actionable retry называет полный keep_span
без ослабления exact quote и лимитов. RED/GREEN TestStrengthRetryNamesWholeMissingSpan.
Все Go gates и Gate B pass. 12 живых вызовов + 20 fixtures, все complete,
8 edited / 2 unchanged / 0 rejected; тизер исправлен. Но CTA split не создан,
поскольку отсутствует в source; целевая проверка абзацев честно падает.

V23: разделение функций content description/самостоятельный CTA в анонсе,
без разрыва одного практического шага. Go test/vet/build и Gate B pass.
Контрольный проход единообразно берёт все десять returned v22 candidates,
analysis/draft reuse явно помечен с SHA256; QA/critic/retry/repair живые.
Результаты build/live-manacost-fidelity-complete-2026-10-19; ни один прежний
эксперимент не перезаписан. Metadata-only preflight assertion отдельно разобран,
источники/входы/snapshot/80 файлов контроля и 20 fixtures подтверждены.

Контрольный v23 также не создал CTA split: 13 live + 20 fixtures,
8 edited / 2 unchanged / 0 rejected, все complete. Поэтому выполнены десять
полных свежих v23 запусков на прежних десяти requests, без fixtures и ручной
замены результатов. Контроль v17 целиком прежний. Manifest SHA256
9f48ceb6a16fe3570130522b57a78bdfb220808947c6a429db47b0c9c9760fea.
40 новых модельных вызовов, все checks complete, 9 edited / 1 unchanged /
0 rejected. Наблюдаемые targets проходят, включая CTA split. 48 точных
наблюдений границ сохранены, 8 автоматически непроверяемы и не объявляются
успехом. Markdown footnote render pass; два новых слепых отзыва в работе.

Свежие отзывы v23: new2/old4/tie4 и new3/old2/tie5; консенсус new1/old2/tie4,
3 расхождения. Обоим старые decks/streams лучше; первое мнение предпочло также
прежние gods/bugfix. Фактических подмен не подтверждено, но задача сохранения
полезной редактуры не выполнена свежей регенерацией; результат не объявлен успехом.

V24 f97d509 добавляет нормальный API путь candidate_text для mode edit:
fresh source analysis, QA/critic/repair без нового draft. Source fact guards,
точные цитаты, один retry/два repair прежние. При rejection/dry run возвращается
source. Candidate не попадает в QA source при LLMnil. Source + provided/current
candidate anchors сохраняются после repair. Отсутствующее поле сохраняет старый
путь; invalid modes/whitespace дают HTTP400 до работы. V2-only и body limit
документированы; RED/GREEN и все Go gates + Gate B clear.

Финальная итерационная проверка берёт **все десять** реально выданных текстов
с последней пользовательской страницы local-final v17; source/прочие поля прежние,
добавлен candidate_text. Before целиком тот же user-visible набор, включая
неуспешный bugfix, а не отдельные выбранные результаты. Все ответы новые,
fixtures нет; нового draft нет. Build live-manacost-preserved-revision-2026-10-19,
manifest b07071906d66b71ef825e8f7f57d15daec324084c20c2ff296115836a06ff1f8.

V24 finished: 29 new calls, 7 edited / 2 unchanged / 1 rejected teaser;
repair loop and unmet decks goal retained as negative evidence.
V25 repair history is separate advisory context; its prepared snapshot had no calls.
V26 explicit revision_brief routes task separately from source facts, requires
candidate/edit, absent field leaves prompts unchanged. Go gates/Gate B passed.
Its teaser exposed first-error-only strength validation: repaired prose rejected
because retry explained first missing span and then encountered the hidden second.
V27 aggregates every invalid span diagnostic in the same retry; exact validation
and attempt limits unchanged. TestStrengthRetryReportsAllInvalidSpansTogether
RED/GREEN, all Go gates pass, GPT-6 Luna Gate A/B no required findings.
New ten-case snapshot uses identical v26 briefs and original whole v17 before set;
no result replacement, no draft generation, no injected responses.

Итог editor-reviewed: три явные редакторские input corrections подготовлены до
calls, остальные семь candidates точные прежние v17. Все10 returned текстов
равны подготовленным candidates; изменены лишь teaser/decks/gods, переносы
сохранены. 22 live calls=10 analysis+12 critic, no draft/repair/fixtures.
10 complete, 8 edited/2 unchanged/0 rejected относительно source; bugfix
unchanged complete вместо прежнего rejected incomplete. Все7 analyzers healthy,
цитаты/сноска/known targets/provenance passed. Два свежих blind reviews завершены: new1/tie7/disagreement2; human0.
Автономные v26/v27 отрицательны и сохранены отдельно; итог подтверждает
подготовленную редактуру, не самостоятельную надёжность модели.

Финальные отзывы: reviewer1 new2/old1/tie7; reviewer2 new2/old0/tie8.
Консенсус new1 gods/tie7/disagreement2 teaser+decks. Новых factual regressions
в after не найдено, но общего литературного выигрыша всех трёх не доказано.
Унаследованные замечания streams/brawl сохранены в отчёте. Final full texts
подготовлены в chat-before-after.md; raw outputs/manifest не изменены.
