"""Второй аудитор ru-text: корпус закреплён, отчёт проверяется, текст остаётся нетронутым."""

import hashlib
import json

import pytest

from editorteam import ru_audit as A
from editorteam.cli import main

TEXT = (
    "Давайте разберёмся, как играть эту колоду. Она не просто быстрая, а по-настоящему "
    "страшная на ладдере: у соперника нет времени ответить. Берите Охотника на демонов, "
    "оставляйте Рагнароса на пятый ход и не бойтесь отдавать лицо. По статистике колода "
    "выигрывает чаще половины матчей, но против контроля нужна другая подготовка и холодная голова "
    "в любой ситуации."
)

SCORES = {
    "Типографика": 8.0,
    "Чистота языка": 7.0,
    "Грамотность": 9.0,
    "Структура": 6.0,
    "Точность для читателя": 7.0,
}
REMARKS = {
    "Типографика": "«Рагнароса на пятый ход» — всё на месте",
    "Чистота языка": "«давайте разберёмся» — пустой зачин, AD-9",
    "Грамотность": "Замечаний нет",
    "Структура": "«не просто быстрая, а…» — ложная антитеза, AD-6",
    "Точность для читателя": "«По статистике» без источника, AD-13",
}


def build_report(scores=None, total=None, label=None, remarks=None, extra="", footer=True):
    scores = scores or SCORES
    remarks = remarks or REMARKS
    total = A.expected_total(scores) if total is None else total
    label = label or A.label_for(total)
    rows = "\n".join(f"| {name} | {score} | {remarks[name]} |" for name, score in scores.items())
    lines = [
        f"## Оценка: {total} / 10 — {label}",
        "",
        "| Измерение | Балл | Замечания |",
        "|---|---|---|",
        rows,
        "",
        f"**Формула:** T×0.15 + Ч×0.25 + Г×0.20 + С×0.20 + Ц×0.20 = {A.weighted_total(scores)}",
        extra,
    ]
    if footer:
        lines += ["", "### Что оценка не измеряет", "- фактическую точность"]
    return "\n".join(lines)


def check(report, text=TEXT, **kwargs):
    return A.validate_report(report, text, **kwargs)


# ── корпус ────────────────────────────────────────────────────────────────


def test_vendored_corpus_matches_pinned_hashes():
    record = json.loads((A.CORPUS / "SOURCE.json").read_text(encoding="utf-8"))
    assert record["commit"] == "c5d2ee5e6f64d7f59a6783b32a6afc54201ccc6e"
    for name, digest in record["sha256_lf"].items():
        data = (A.CORPUS / name).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(data).hexdigest() == digest, f"{name} отличается от закреплённого"
    assert (A.CORPUS / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")


def test_always_on_skill_is_not_vendored_and_corpus_is_not_discoverable_as_skill():
    assert not list(A.CORPUS.rglob("SKILL.md")), "постоянный режим ru-text не должен вкладываться"
    assert (A.CORPUS / "references" / "info-style.md").is_file()


def test_known_rules_cover_ad_1_to_18():
    assert A.known_rules() == set(range(1, 19))


# ── арифметика и ярлыки ───────────────────────────────────────────────────


def test_weighted_total_rounds_half_up_without_float_noise():
    assert A.weighted_total(SCORES) == 7.4  # 7.35 → 7.4
    assert A.expected_total({name: 10.0 for name in SCORES}) == 10.0


def test_caps_follow_scoring_md():
    low_dimension = {**SCORES, "Структура": 2.5}
    assert A.expected_total(low_dimension) == 5.0
    assert A.expected_total({**SCORES, "Типографика": 3.5}) == 6.7  # ниже порога 7.0, не режется
    strong = {name: 9.0 for name in SCORES}
    assert A.weighted_total({**strong, "Грамотность": 3.5}) == 7.9
    assert A.expected_total({**strong, "Грамотность": 3.5}) == 7.0
    assert A.expected_total({**strong, "Типографика": 3.5}) == 7.0


@pytest.mark.parametrize(
    ("total", "label"),
    [
        (9.0, "Эталонный"),
        (8.9, "Хороший"),
        (7.0, "Хороший"),
        (6.9, "Средний"),
        (3.0, "Слабый"),
        (2.9, "Критический"),
    ],
)
def test_label_bands(total, label):
    assert A.label_for(total) == label


# ── отчёт ─────────────────────────────────────────────────────────────────


def test_valid_report_is_accepted():
    result = check(build_report())
    assert result.valid, result.errors
    assert result.total == result.expected_total == 7.4 and result.label == "Хороший"
    assert result.quotes_checked == 4 and result.quotes_missing == []
    assert result.ad_rules == [6, 9, 13]


def test_total_that_does_not_follow_the_formula_is_rejected():
    result = check(build_report(total=8.9))
    assert any("не сходится с формулой" in error for error in result.errors)


def test_cap_must_be_applied_to_the_total():
    scores = {**SCORES, "Структура": 2.5}
    assert any("не сходится" in e for e in check(build_report(scores, total=7.0)).errors)
    assert check(build_report(scores, total=5.0)).valid


def test_label_must_match_the_score():
    result = check(build_report(label="Эталонный"))
    assert any("ярлык" in error for error in result.errors)


def test_label_may_be_capped_by_ad_14_or_ad_15():
    scores = {name: 9.5 for name in SCORES}
    remarks = {name: "Замечаний нет" for name in SCORES}
    note = "Ярлык ограничен до «Средний»: AD-15"
    assert check(build_report(scores, label="Средний", remarks=remarks, extra=note)).valid
    assert not check(build_report(scores, label="Средний", remarks=remarks)).valid


def test_missing_sections_and_unknown_labels_are_errors():
    assert any("не измеряет" in e for e in check(build_report(footer=False)).errors)
    assert any("неизвестный ярлык" in e for e in check(build_report(label="Отлично")).errors)
    broken = build_report().replace("| Структура | 6.0 |", "| Структурка | 6.0 |")
    assert any("«Структура»" in e for e in check(broken).errors)
    assert any("заголовка" in e for e in check("просто текст").errors)


# ── цитаты и правила ──────────────────────────────────────────────────────


def test_fabricated_quote_is_rejected():
    remarks = {**REMARKS, "Грамотность": "«Это предложение автор не писал» — выдумка"}
    result = check(build_report(remarks=remarks))
    assert not result.valid and result.quotes_missing == ["Это предложение автор не писал"]


def test_examples_of_rules_from_the_corpus_are_not_fabricated_quotes():
    """Аудитор ссылается на правило его словом или примером: («лучший», «Весьма существенно»)."""
    remarks = {name: "Замечаний нет" for name in SCORES}
    remarks["Чистота языка"] = (
        'info-style.md §B ("лучший", "надёжный"); anti-patterns.md, Vague Adjectives, '
        '"Весьма существенно"; и «давайте разберёмся» — из текста'
    )
    result = check(build_report(remarks=remarks))
    assert result.valid, result.errors
    assert result.quotes_missing == []
    assert "Весьма существенно" in result.quotes_from_catalog
    assert "давайте разберёмся" not in [q.lower() for q in result.quotes_from_catalog]


def test_quotes_tolerate_case_yo_quotes_markup_and_ellipsis():
    text = (
        "**Давайте** разберёмся, как играть: 'Рагнарос' — хорошая карта на ПЯТЫЙ ход. И ещё одна."
    )
    remarks = {name: "Замечаний нет" for name in SCORES}
    remarks["Чистота языка"] = "«давайте РАЗБЕРЕМСЯ» и «Рагнарос … пятый ход»"
    result = check(build_report(remarks=remarks), text=text)
    assert result.quotes_checked == 2 and result.quotes_missing == []


def test_replacement_after_an_arrow_is_not_a_quote():
    remarks = {**REMARKS, "Чистота языка": "«давайте разберёмся» → «разберём»"}
    assert check(build_report(remarks=remarks)).valid


def test_rule_ids_and_short_labels_are_not_treated_as_quotes():
    assert A.quoted_fragments("«AD-9», «T-3», «R37», «ё», `a`") == []


def test_unknown_rule_is_a_warning_and_strict_makes_it_an_error():
    remarks = {**REMARKS, "Грамотность": "Замечаний нет, AD-77"}
    result = check(build_report(remarks=remarks))
    assert result.valid and any("AD-77" in w for w in result.warnings)


def test_short_text_needs_a_caveat():
    result = check(
        build_report(), text="Короткий текст про «давайте разберёмся» и «Рагнароса на пятый ход»."
    )
    assert any("короче 50 слов" in w for w in result.warnings)


def test_check_mode_validates_quotes_only():
    findings = "- «давайте разберёмся» — AD-9, medium → «разберём»\n- «выдуманная фраза» — AD-6"
    result = check(findings, mode="check")
    assert result.quotes_missing == ["выдуманная фраза"] and result.ad_rules == [6, 9]


def test_read_only_guarantee_compares_hashes():
    digest = hashlib.sha256(TEXT.encode()).hexdigest()
    same = check(build_report(), expected_sha256=digest, text_sha256=digest)
    assert same.readonly == "verified" and same.valid
    other = check(build_report(), expected_sha256="0" * 64, text_sha256=digest)
    assert other.readonly == "violated" and not other.valid
    assert check(build_report(), text_sha256=digest).readonly == "unchecked"


# ── задание аудитору и команда ───────────────────────────────────────────


def test_prepare_builds_a_read_only_brief_with_house_overrides(tmp_path):
    source = tmp_path / "статья.md"
    source.write_text(TEXT, encoding="utf-8", newline="\n")
    brief = A.prepare(source)
    assert brief["text_sha256"] == hashlib.sha256(TEXT.encode()).hexdigest()
    prompt = brief["prompt"]
    assert "только на чтение" in prompt and "Read, Grep, Glob" in prompt
    assert str(A.CORPUS) in prompt and "AD-1…AD-18" in prompt
    assert "прямые кавычки" in prompt and "буква ё не ставится" in prompt
    assert "диапазоны через дефис" in prompt and "ставит отдельная стадия" in prompt


def test_prepare_rejects_unknown_mode(tmp_path):
    source = tmp_path / "a.md"
    source.write_text("текст", encoding="utf-8")
    with pytest.raises(ValueError, match="mode"):
        A.prepare(source, mode="rewrite")


def test_cli_prepare_and_validate(tmp_path, capsys):
    source = tmp_path / "статья.md"
    source.write_text(TEXT, encoding="utf-8", newline="\n")
    report = tmp_path / "отчёт.md"
    report.write_text(build_report(), encoding="utf-8")

    assert main(["--format", "json", "ru-audit", "prepare", str(source)]) == 0
    digest = json.loads(capsys.readouterr().out)["text_sha256"]

    assert (
        main(["ru-audit", "validate", str(source), "--report", str(report), "--sha256", digest])
        == 0
    )
    assert "отчёт принят" in capsys.readouterr().out

    source.write_text(TEXT + " Правка аудитора.", encoding="utf-8")
    code = main(
        [
            "--format",
            "json",
            "ru-audit",
            "validate",
            str(source),
            "--report",
            str(report),
            "--sha256",
            digest,
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 1 and payload["readonly"] == "violated" and not payload["valid"]


def test_cli_strict_turns_warnings_into_errors(tmp_path, capsys):
    source = tmp_path / "статья.md"
    source.write_text(TEXT, encoding="utf-8")
    report = tmp_path / "отчёт.md"
    report.write_text(build_report(remarks={**REMARKS, "Грамотность": "AD-77"}), encoding="utf-8")
    assert main(["ru-audit", "validate", str(source), "--report", str(report)]) == 0
    assert main(["ru-audit", "validate", str(source), "--report", str(report), "--strict"]) == 1
    capsys.readouterr()


def test_cli_reports_missing_files(tmp_path, capsys):
    assert (
        main(
            [
                "ru-audit",
                "validate",
                str(tmp_path / "нет.md"),
                "--report",
                str(tmp_path / "нет2.md"),
            ]
        )
        == 2
    )
    assert "ru-audit:" in capsys.readouterr().err
