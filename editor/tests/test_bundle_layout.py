"""Вёрстка Манакоста в связке публикации: панель обновления, ссылки, галереи, вступление."""

from __future__ import annotations

import json

import pytest

from editorteam import publication_bundle as pb

PANEL = (
    '[su_panel background="#e2eaff" color="#000000" border="1px double #b5b5b5" radius="6" text_align="left"]\n'
    "Материал обновлен **17 ноября 2026 года** для 14-го сезона (патч 37.0.2).\n"
    "[/su_panel]\n"
)
LINKS = (
    "---\n\n"
    "- [Изменения в сезоне](#izmeneniya)\n"
    "- [Лучшие тир-1 существа](#luchshie)\n"
    "- Подписывайтесь на [Манакост в Telegram](https://t.me/manacost_ru)\n\n"
    "---\n"
)
INTRO = (
    "Разбираем лучшие **тир-1 существа** для первого хода на **Полях сражений**.\n\n"
    "Почти у каждого есть любимые 1-е дропы, которые вы берете на автомате.\n\n"
)
BODY = (
    "## Лучшие тир-1 существа\n\n"
    '[gallery columns="3" size="medium" ids="101,102,103"]\n\n'
    "Подозрительный надзиратель держит стол на первом ходу.\n"
)


def article(*, intro=INTRO, panel=PANEL, links=LINKS, body=BODY, title="# Первый ход на Полях сражений\n\n"):
    return title + intro + panel + "\n" + links + "\n" + body


def check(text):
    report = pb.verify_texts(text)
    return report.codes(), [w for w in report.warnings if w.startswith("bundle.")]


def test_clean_layout_passes():
    codes, warnings = check(article())
    assert codes == set()
    assert warnings == []


# ── «Обратите внимание» ──────────────────────────────────────────────────────


def test_noise_inside_panel_is_an_error():
    panel = PANEL.replace("Материал обновлен", "Обратите внимание: материал обновлен")
    codes, _ = check(article(panel=panel))
    assert codes == {"bundle.banned_panel_noise"}


def test_noise_label_right_above_panel_is_an_error():
    codes, _ = check(article(panel="**Обратите внимание!**\n\n" + PANEL))
    assert codes == {"bundle.banned_panel_noise"}
    codes, _ = check(article(panel="### Обратите внимание\n" + PANEL))
    assert codes == {"bundle.banned_panel_noise"}


def test_long_prose_sentence_before_panel_is_not_a_label():
    prose = "Обратите внимание на силу героя и заклинание в таверне, прежде чем покупать первое существо.\n\n"
    codes, _ = check(article(intro=INTRO + prose))
    assert "bundle.banned_panel_noise" not in codes


# ── порядок панели и ссылок ──────────────────────────────────────────────────


def test_links_before_update_panel_are_an_error():
    text = "# Первый ход\n\n" + INTRO + LINKS + "\n" + PANEL + "\n" + BODY
    codes, _ = check(text)
    assert codes == {"bundle.panel_order"}


def test_links_panel_before_update_panel_is_an_error():
    links_panel = "[su_panel]\n[Больше гайдов по Полям сражений](https://hs-manacost.ru/bg/)\n[/su_panel]\n\n"
    codes, _ = check(article(intro=INTRO + links_panel))
    assert codes == {"bundle.panel_order"}


def test_inline_link_in_intro_is_not_a_links_block():
    intro = INTRO + (
        "Как считать бои первого хода, мы подробно разобрали в [отдельном разделе](#boi) ниже, "
        "там же есть таблица по героям.\n\n"
    )
    codes, _ = check(article(intro=intro))
    assert "bundle.panel_order" not in codes


def test_links_without_update_panel_are_not_checked_for_order():
    panel = "[su_panel]\nКороткая справка о режиме без даты.\n[/su_panel]\n"
    codes, _ = check("# Первый ход\n\n" + INTRO + LINKS + "\n" + panel + "\n" + BODY)
    assert "bundle.panel_order" not in codes


# ── галереи ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "gallery",
    ['[gallery columns="4" ids="1,2,3,4"]', "[gallery ids='1,2,3,4,5' columns='5']",
     "[gallery columns=6 ids=1,2,3,4,5,6]", "[gallery columns=»4″ ids=»1,2,3,4″]"],
)
def test_more_than_three_cards_in_a_row_is_an_error(gallery):
    codes, _ = check(article(body=BODY.replace('[gallery columns="3" size="medium" ids="101,102,103"]', gallery)))
    assert codes == {"bundle.gallery_columns"}


@pytest.mark.parametrize("gallery", ['[gallery columns="1" ids="1"]', '[gallery columns="2" ids="1,2"]',
                                     '[gallery ids="1,2,3,4,5,6"]'])
def test_three_or_fewer_columns_pass(gallery):
    codes, _ = check(article(body=BODY.replace('[gallery columns="3" size="medium" ids="101,102,103"]', gallery)))
    assert "bundle.gallery_columns" not in codes


# ── жирное во вступлении ─────────────────────────────────────────────────────


def test_intro_without_bold_is_a_warning_not_an_error():
    intro = INTRO.replace("**", "")
    report = pb.verify_texts(article(intro=intro))
    assert report.ok
    assert any(w.startswith("bundle.intro_bold_missing") for w in report.warnings)


def test_bold_only_inside_update_panel_does_not_count():
    _, warnings = check(article(intro=INTRO.replace("**", "")))
    assert warnings and warnings[0].startswith("bundle.intro_bold_missing")


def test_bold_in_third_paragraph_is_enough_but_not_after_heading():
    plain = "Первый абзац.\n\nВторой абзац.\n\n"
    _, warnings = check(article(intro=plain + "Третий про **Поля сражений**.\n\n"))
    assert warnings == []
    _, warnings = check(article(intro=plain + "Третий.\n\nЧетвертый про **Поля сражений**.\n\n"))
    assert warnings and warnings[0].startswith("bundle.intro_bold_missing")
    _, warnings = check("# Заголовок\n\n" + plain + "## Раздел\n\nЗдесь **Поля сражений**.\n")
    assert warnings and warnings[0].startswith("bundle.intro_bold_missing")


def test_intro_paragraphs_skip_title_and_service_blocks():
    text = "# Заголовок\n\n" + PANEL + "\n![схема](a.png)\n\n" + INTRO + "## Раздел\n\nТекст.\n"
    assert pb.intro_paragraphs(text) == [part for part in INTRO.strip().split("\n\n")]


# ── регресс: старая версия тир-листа 1-х дропов ─────────────────────────────

OLD_TIERLIST_TOP = (
    "Разбираем лучшие и худшие тир-1 существа для покупки в первый ход в 14-м сезоне Полей сражений.\n\n"
    "Почти у каждого есть любимые 1-е дропы, которые вы берете на автомате. Но куда полезнее знать, "
    "кого брать на первый ход, если в таверну зашли непривычные или слабые варианты.\n\n"
    "Конечно, выбор зависит от силы героя, доступных типов существ, заклинания в таверне и первого "
    "соперника.\n\n"
    + PANEL
    + "\n## Изменения в 14-м сезоне\n\n"
    "**Обратите внимание**\n"
    "[su_panel]\nНаги временно покинули игру.\n[/su_panel]\n\n"
    '[gallery columns="4" ids="1,2,3,4"]\n'
)


def test_old_tierlist_top_is_caught():
    report = pb.verify_texts(OLD_TIERLIST_TOP)
    assert report.codes() == {"bundle.banned_panel_noise", "bundle.gallery_columns"}
    assert any(w.startswith("bundle.intro_bold_missing") for w in report.warnings)


def test_cli_verify_reports_layout_errors(tmp_path, capsys):
    path = tmp_path / "article.md"
    path.write_bytes(article(body=BODY.replace('columns="3"', 'columns="4"')).encode("utf-8"))
    assert pb.main(["verify", "--article", str(path)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert {e["code"] for e in out["errors"]} == {"bundle.gallery_columns"}
    assert out["errors"][0]["line"] > 1
