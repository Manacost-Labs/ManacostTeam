"""Тир-лист Полей сражений как отдельный жанр и связка файлов публикации."""

from __future__ import annotations

import json

import markers
import pytest

from editorteam import profiles, publication_bundle as pb, rules
from editorteam.cli import main as cli_main

TIERLIST = """# Лучшие и худшие тир-1 существа на Полях сражений

Рейтинг тир-1 существ для первого хода на Полях сражений: кого брать с первой
монетки таверны, а кого продавать сразу. Список от лучших к худшим.

## Лучшие

- **Подозрительный надзиратель**
- **Мурлок-налётчик**
- **Дикий клыкарь**
- **Огненный бесёнок**

Эти существа держат стол до третьего хода и окупаются при продаже.

## Плохие

- **Старый пират**
- **Ржавый механизм**
- **Вялый бес**

Их берут только ради типа, когда другого выбора нет.

## Вывод

Первый ход решает меньше, чем кажется, но хороший старт бережёт здоровье.
"""


def _marker_ids(text, profile):
    hits = markers.scan(text, markers.load_patterns())
    return [h["id"] for h in rules.filter_marker_hits(hits, text, profile)]


# ── профиль ──────────────────────────────────────────────────────────────────


def test_tierlist_profile_loads_without_single_build_sections():
    p = profiles.load("battlegrounds-tierlist")
    assert p.id == "battlegrounds-tierlist"
    assert p.required_sections == []
    assert {"changes", "best", "good", "decent", "bad", "conclusion"} <= {s.id for s in p.sections}
    assert not {"idea", "minions", "curve"} & {s.id for s in p.sections}
    assert p.require_classes is False
    assert p.norms["provisional"] is True
    assert p.form["allow_bold_index_lists"] is True


def test_tierlist_lexicon_matches_battlegrounds_article():
    import yaml

    def lexicon(name):
        raw = (profiles.PROFILES_DIR / f"{name}.yaml").read_text(encoding="utf-8")
        return yaml.safe_load(raw)["lexicon"]

    assert lexicon("battlegrounds-tierlist") == lexicon("battlegrounds-article")


@pytest.mark.parametrize(
    "text",
    [
        TIERLIST,
        "Лучший первый ход на Полях сражений: тир-лист 1-х дропов. Таверна решает многое.",
        "Рейтинг тир-2 существ Полей сражений. Кого брать в таверне и кого продавать.",
        "1-е дропы на Полях сражений: лучшие тир-1 существа сезона и что поменялось.",
    ],
)
def test_detect_tierlist(text):
    name, confidence = profiles.detect(text)
    assert name == "battlegrounds-tierlist"
    assert confidence > 0.5


def test_single_build_guide_with_tierlist_word_stays_guide():
    text = (
        "Тир-лист стратегий Полей сражений нам не нужен.\n"
        "Идея стратегии\nСобираем мурлоков в тавернах.\n"
        "Ключевые существа\nБрановый мурлок.\n"
        "План по ходам\nНа четвертом ходу ищем тройку существ.\n"
    )
    assert profiles.detect(text)[0] == "battlegrounds-guide"


def test_tierlist_needs_battlegrounds_context():
    # без Полей сражений «тир-лист» — примета мета-отчёта Constructed
    text = "Мета-отчёт: тир-лист колод, процент побед 54% и 52%."
    assert profiles.detect(text)[0] == "meta-report"


OTHER_PROFILES = {
    "battlegrounds-guide": (
        "Идея стратегии\nСобираем мурлоков в тавернах и держим темп.\n"
        "Ключевые существа\nБрановый мурлок и Мурлок-налетчик.\n"
        "План по ходам\nНа четвертом ходу ищем тройку существ.\n"
        "Герой таверны выбирается под аксессуары в лобби.\n"
    ),
    "battlegrounds-article": (
        "Поля сражений меняются. Почему новые эффекты ускоряют игру и что это значит для игрока? "
        "Сильный старт оставляет меньше времени на ответ."
    ),
    "analytics-article": (
        "Обзор патча 32.0.3: что изменилось и почему это важно. "
        "Нерф замедлит колоду, но не уберет ее из меты."
    ),
    "constructed-guide": (
        "Сборки архетипа\nМуллиган\nСтратегия игры\nМатч-апы\n"
        "Вопросы декбилдинга\nКолода играет через размен и добор.\n"
    ),
    "anti-guide": (
        "Title: 3 колоды против Терран Шамана\nCategories: Анти-гайды, Шаман\n\n"
        "Терран Шаман захватил ладдер, но его можно победить. "
        "Первая контрколода давит его до Жажды крови.\n"
    ),
    "news": "Патчноут 33.2: разработчики объявили изменения. Анонс следующего патча 33.4.",
    "meta-report": "Мета-отчёт: тир-лист и расстановка сил, процент побед 55% у лидера, 53% у второго.",
}


@pytest.mark.parametrize("expected", sorted(OTHER_PROFILES))
def test_other_profiles_detection_unchanged(expected):
    assert profiles.detect(OTHER_PROFILES[expected])[0] == expected


def test_audit_of_tierlist_has_no_single_build_requirements(tmp_path, capsys):
    path = tmp_path / "tier.md"
    path.write_text(TIERLIST, encoding="utf-8")
    cli_main(["--format", "json", "audit", str(path)])
    data = json.loads(capsys.readouterr().out)
    assert data["profile"] == "battlegrounds-tierlist"
    missing = [f["id"] for f in data["findings"] if f["id"].startswith("structure.missing")]
    assert missing == []


def test_bold_index_list_is_not_bold_spam_in_tierlist():
    raw = [h["id"] for h in markers.scan(TIERLIST, markers.load_patterns())]
    assert "bold-spam" in raw, "без флага профиля список жирных имён считается спамом"
    tier = profiles.load("battlegrounds-tierlist")
    ids = _marker_ids(TIERLIST, tier)
    assert "bold-spam" not in ids
    assert "bold-label-list" not in ids


def test_other_profiles_keep_bold_markers():
    guide = profiles.load("battlegrounds-guide")
    assert "bold-spam" in _marker_ids(TIERLIST, guide)
    assert rules.filter_marker_hits([{"id": "bold-spam"}], TIERLIST, None) == [{"id": "bold-spam"}]


def test_tierlist_still_flags_real_bold_spam_and_label_lists():
    tier = profiles.load("battlegrounds-tierlist")
    text = (
        "# Тир-лист\n\n"
        "Это **очень** важно, **всегда** берите **сразу** и **без** раздумий.\n\n"
        "## Плюсы и минусы\n"
        "- **Плюс** — быстрый старт\n"
        "- **Минус**: дорогая основа\n"
        "- **Итог** — брать\n"
    )
    raw = [h["id"] for h in markers.scan(text, markers.load_patterns())]
    ids = _marker_ids(text, tier)
    assert ids == raw
    assert "bold-spam" in ids
    assert "bold-label-list" in ids


# ── связка публикации ────────────────────────────────────────────────────────

ARTICLE = (
    "# Лучшие 1-е дропы\n\n"
    "Подозрительный надзиратель держит стол на первом ходу.\n"
    "Дикий клыкарь растёт от каждого Зверя.\n"
)
SHORTCODES = (
    "# Лучшие 1-е дропы\n\n"
    '[hs_bg id="BG_001"]Подозрительный надзиратель[/hs_bg] держит стол на первом ходу.\n'
    '[hs_bg id="BG_002"]Дикий клыкарь[/hs_bg] растёт от каждого Зверя.\n'
)
CATALOG = {
    "cards": [
        {"name": "Подозрительный надзиратель", "id": "BG_001", "formats": ["battlegrounds"], "types": ["Pirate"]},
        {"name": "Дикий клыкарь", "id": "BG_002", "formats": ["battlegrounds"], "types": ["Beast"]},
        {"name": "Огненный шар", "id": "CS2_029", "formats": ["standard", "wild"]},
    ]
}


def _seo(**overrides):
    data = {
        "title": "Лучшие 1-е дропы на Полях сражений",
        "description": "Какие существа брать на первом ходу Полей сражений и почему они держат стол.",
        "focus_keyword": "1-е дропы",
        "answer": '[hs_bg id="BG_001"]Подозрительный надзиратель[/hs_bg] держит стол на первом ходу.',
        "faq": [
            {"question": "Кого брать первым?",
             "answer": '[hs_bg id="BG_002"]Дикий клыкарь[/hs_bg] растёт от каждого Зверя.'},
        ],
        "schema_type": "article",
        "article_sha256": pb.article_digest(ARTICLE),
    }
    data.update(overrides)
    return data


@pytest.fixture
def bundle(tmp_path):
    def write(article=ARTICLE, shortcodes=SHORTCODES, seo=None, context=None):
        paths = {
            "article": tmp_path / "article.md",
            "shortcodes": tmp_path / "article-shortcodes.md",
            "seo": tmp_path / "seo.json",
            "catalog": tmp_path / "catalog.json",
        }
        # байты как есть: write_text на Windows сам превратил бы \n в \r\n
        paths["article"].write_bytes(article.encode("utf-8"))
        paths["shortcodes"].write_bytes(shortcodes.encode("utf-8"))
        paths["seo"].write_text(json.dumps(seo or _seo(), ensure_ascii=False), encoding="utf-8")
        paths["catalog"].write_text(json.dumps(CATALOG, ensure_ascii=False), encoding="utf-8")
        if context is not None:
            paths["author_context"] = tmp_path / "author-context.json"
            paths["author_context"].write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
        return paths

    return write


def _verify(paths, **extra):
    return pb.verify(
        paths["article"], shortcodes=paths["shortcodes"], seo=paths["seo"], catalog=paths["catalog"],
        author_context=paths.get("author_context"), game_format="battlegrounds", **extra,
    )


def test_valid_bundle_passes(bundle):
    report = _verify(bundle(), require_seo_hash=True)
    assert report.ok, report.to_dict()


def test_crlf_is_the_only_allowed_normalization(bundle):
    report = _verify(bundle(article=ARTICLE.replace("\n", "\r\n")))
    assert report.ok, report.to_dict()


def test_prose_mismatch_between_article_and_shortcodes(bundle):
    edited = ARTICLE.replace("держит стол", "уверенно держит стол")
    report = _verify(bundle(article=edited, seo=_seo(article_sha256=pb.article_digest(edited))))
    assert report.codes() == {"text_mismatch"}
    issue = report.errors[0]
    assert issue.line == 3
    assert "уверенно" in issue.message


def test_stale_seo_after_article_edit(bundle):
    edited = ARTICLE + "Свежая строка после генерации SEO.\n"
    shortcodes = SHORTCODES + "Свежая строка после генерации SEO.\n"
    report = _verify(bundle(article=edited, shortcodes=shortcodes))
    assert report.codes() == {"stale_seo"}


def test_missing_hash_is_error_only_when_required(bundle):
    seo = _seo()
    del seo["article_sha256"]
    paths = bundle(seo=seo)
    assert _verify(paths).ok
    assert _verify(paths, require_seo_hash=True).codes() == {"seo_hash_missing"}


def test_missing_indexpilot_fields(bundle):
    seo = _seo()
    del seo["focus_keyword"]
    del seo["schema_type"]
    report = _verify(bundle(seo=seo))
    assert report.codes() == {"seo_missing_field"}
    assert {i.field for i in report.errors} == {"focus_keyword", "schema_type"}


def test_hs_card_instead_of_hs_bg_in_battlegrounds(bundle):
    wrong = SHORTCODES.replace('[hs_bg id="BG_002"]Дикий клыкарь[/hs_bg]',
                               '[hs_card id="BG_002"]Дикий клыкарь[/hs_card]')
    report = _verify(bundle(shortcodes=wrong))
    assert report.codes() == {"shortcode_wrong_tag"}


def test_hs_card_inside_seo_faq_in_battlegrounds(bundle):
    seo = _seo(faq=[{"question": "Кого брать?",
                     "answer": '[hs_card id="BG_002"]Дикий клыкарь[/hs_card] растёт от Зверей.'}])
    report = _verify(bundle(seo=seo))
    assert report.codes() == {"shortcode_wrong_tag"}
    assert report.errors[0].field == "faq[1].answer"


@pytest.mark.parametrize(
    ("broken", "code"),
    [
        ('[hs_bg id="BG_001"]Подозрительный надзиратель держит стол на первом ходу.\n', "shortcode_unbalanced"),
        ('[hs_bg id="BG_001"][hs_bg id="BG_002"]Подозрительный надзиратель[/hs_bg][/hs_bg] держит стол'
         ' на первом ходу.\n', "shortcode_nested"),
        ('Подозрительный надзиратель[hs_bg id="BG_001"] [/hs_bg] держит стол на первом ходу.\n', "shortcode_empty"),
        ('[hs_bg id="BG_404"]Подозрительный надзиратель[/hs_bg] держит стол на первом ходу.\n',
         "shortcode_unknown_id"),
        ('[hs_bg id="CS2_029"]Подозрительный надзиратель[/hs_bg] держит стол на первом ходу.\n',
         "shortcode_wrong_format"),
    ],
)
def test_shortcode_integrity(bundle, broken, code):
    lines = SHORTCODES.splitlines(keepends=True)
    lines[2] = broken
    if code == "shortcode_empty":
        article = ARTICLE.replace("Подозрительный надзиратель держит", "Подозрительный надзиратель  держит")
        paths = bundle(article=article, shortcodes="".join(lines),
                       seo=_seo(article_sha256=pb.article_digest(article)))
    else:
        paths = bundle(shortcodes="".join(lines))
    assert code in _verify(paths).codes()


def test_forbidden_literal_in_seo_faq(bundle):
    context = {"requirements": [{"id": "types", "instruction": "Только «типы существ».",
                                 "forbidden_literals": ["племя"]}]}
    seo = _seo(faq=[{"question": "Какое племя сильнее?",
                     "answer": "Пиратское племя сильнее остальных на первом ходу."}])
    report = _verify(bundle(seo=seo, context=context))
    assert report.codes() == {"forbidden_literal"}
    assert {i.field for i in report.errors} == {"faq[1].question", "faq[1].answer"}


def test_lobby_tautology_in_seo_faq(bundle):
    seo = _seo(faq=[{"question": "Когда брать Дикого клыкаря?",
                     "answer": 'Этот Зверь хорош в лобби со Зверями.'}])
    report = _verify(bundle(seo=seo))
    assert report.codes() == {"lobby_tautology"}


def test_lobby_tautology_by_catalog_type(bundle):
    seo = _seo(answer='[hs_bg id="BG_002"]Дикий клыкарь[/hs_bg] особенно силён в лобби со Зверями.')
    assert _verify(bundle(seo=seo)).codes() == {"lobby_tautology"}


def test_lobby_with_other_type_is_fine(bundle):
    seo = _seo(answer='[hs_bg id="BG_002"]Дикий клыкарь[/hs_bg] хорош в лобби с Нежитью.')
    assert _verify(bundle(seo=seo)).ok


def test_stamp_seo_then_pack(bundle, tmp_path):
    seo = _seo()
    del seo["article_sha256"]
    paths = bundle(seo=seo)
    edited = ARTICLE + "Ещё строка.\n"
    paths["article"].write_text(edited, encoding="utf-8")
    paths["shortcodes"].write_text(SHORTCODES + "Ещё строка.\n", encoding="utf-8")

    out = tmp_path / "bundle"
    report, manifest = pb.pack(paths["article"], out, shortcodes=paths["shortcodes"], seo=paths["seo"],
                               catalog=paths["catalog"], game_format="battlegrounds")
    assert manifest is None and report.codes() == {"seo_hash_missing"}
    assert not out.exists()

    assert pb.stamp_seo(paths["article"], paths["seo"]).ok
    stamped = json.loads(paths["seo"].read_text(encoding="utf-8"))
    assert stamped["article_sha256"] == pb.article_digest(edited)

    report, manifest = pb.pack(paths["article"], out, shortcodes=paths["shortcodes"], seo=paths["seo"],
                               catalog=paths["catalog"], game_format="battlegrounds", slug="pervye-dropy")
    assert report.ok, report.to_dict()
    assert sorted(p.name for p in out.iterdir()) == sorted(pb.BUNDLE_NAMES)
    on_disk = json.loads((out / pb.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert on_disk["article_sha256"] == pb.article_digest(edited)
    assert on_disk["files"]["article.md"]["sha256"] == pb.article_digest(edited)
    assert set(on_disk["files"]) == {"article.md", "article-shortcodes.md", "seo.json"}
    # повторная сборка в существующий каталог тоже проходит
    report, manifest = pb.pack(paths["article"], out, shortcodes=paths["shortcodes"], seo=paths["seo"],
                               game_format="battlegrounds")
    assert report.ok and manifest is not None


def test_cli_verify_exit_codes(bundle, capsys):
    paths = bundle()
    argv = ["verify", "--article", str(paths["article"]), "--shortcodes", str(paths["shortcodes"]),
            "--seo", str(paths["seo"]), "--catalog", str(paths["catalog"]), "--format", "battlegrounds"]
    assert pb.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    paths["article"].write_text(ARTICLE + "Правка.\n", encoding="utf-8")
    assert pb.main(argv) == 1
    codes = {e["code"] for e in json.loads(capsys.readouterr().out)["errors"]}
    assert codes == {"text_mismatch", "stale_seo"}
