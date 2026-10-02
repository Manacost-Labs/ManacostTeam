# MarketingTeam

Маркетинговая команда ManacostTeam для рекламы товаров, связанных с Hearthstone и Warcraft. Специализации находятся в `specializations/`; общий переносимый skill — [marketing-team](../teams/marketing-team/SKILL.md). Пакеты и импорт описаны в [TEAM_STANDARD](../docs/TEAM_STANDARD.md).

## Что уже подключено

`product-marketing`, `customer-research`, `ads`, `ad-creative`, `copywriting`, `social`, `video`, `emails`, `analytics`, `competitors`, `launch` и `cro` — импортированы из [Takinggg/codex-marketing-skills](https://github.com/Takinggg/codex-marketing-skills) на коммите `62f53561fc406b6449ce4095b3328b59fe9d885a`.

`warcraft-product-advertising` — собственный маршрутизатор: проверяет карточку товара и права на игровые материалы, затем собирает рекламный пакет из нужных специализаций.

`gpt-image-ad-creative` создаёт оригинальные визуальные концепты и промпты для GPT Image 2 / встроенного ImageGen, а `ad-visual-review` принимает готовый креатив по брифу, читабельности и правам на используемые материалы. По умолчанию используется встроенный ImageGen без API-ключа; прямой API/CLI-режим с `gpt-image-2` включается только по явному запросу и требует локально настроенный ключ. [Официальная модель GPT Image 2](https://developers.openai.com/api/docs/models/gpt-image-2).

## Старт работы

1. Заполните подтверждёнными фактами [`brand-context.md`](brand-context.md) и, при необходимости, запустите `$product-marketing` для полной продуктовой контекстной карты.
2. Попросите: `$warcraft-product-advertising подготовь рекламный пакет для [товар]`.
3. Для визуала: `$gpt-image-ad-creative сделай 3 концепта для рекламы [товар] на [площадка]` и затем `$ad-visual-review проверь этот баннер перед запуском`.
4. Перед запуском кампании отдельно запросите рекламный план, креативы, посадочную страницу и план аналитики — это оставляет проверяемый след от объявления до конверсии.

Внешние навыки не получают доступ к рекламным кабинетам сами по себе. Публикация и траты возможны только по отдельному явному запросу.

Лицензия и атрибуция внешнего набора — в [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
