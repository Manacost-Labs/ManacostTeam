from editorteam.server import _scripts, validate


def test_reconstruction_preserves_term_presence_without_copying_mention_count():
    report = _scripts().sibling("report")
    before = "ОТК план. ОТК ресурсы. ОТК ход."
    assert "ОТК" not in report.protected_lost(before, "ОТК план и ресурсы.", preserve_repetitions=False)
    assert "ОТК" not in report.protected_lost(before, "отк план и ресурсы.", preserve_repetitions=False)
    assert "ОТК" in report.protected_lost(before, "Другой план.", preserve_repetitions=False)
    assert "ОТК" in report.protected_lost(before, "ОТКашный план.", preserve_repetitions=False)
    assert "ОТК" in report.protected_lost(before, "ОТК план и ресурсы.")


def test_term_presence_does_not_relax_numeric_stat_or_deck_code_guards():
    report = _scripts().sibling("report")
    code = "AAECA" + "a" * 20
    before = f"ОТК ОТК 8 8 3/8 3/8 {code} {code}"
    after = f"ОТК 8 3/8 {code}"
    lost = report.protected_lost(before, after, preserve_repetitions=False)
    assert "ОТК" not in lost
    assert all(kind in lost for kind in ("числа", "статы", "коды колод"))
    assert "ГКД" not in report.protected_lost("ГКД ГКД", "ГКД", game="wow", protected=["ГКД"], preserve_repetitions=False)
    assert "ГКД" in report.protected_lost("ГКД ГКД", "текст", game="wow", protected=["ГКД"], preserve_repetitions=False)


def test_reconstruct_api_checks_term_presence_but_editing_keeps_its_contract():
    before = "ОТК помогает выиграть. ОТК требует подготовки."
    after = "ОТК помогает выиграть и требует подготовки."
    rewritten = validate(before, after, "hearthstone", "constructed-guide", depth="переплавка")
    assert not any(x["kind"] == "protected_lost" and x.get("signal") == "ОТК" for x in rewritten["violations"])
    edited = validate(before, after, "hearthstone", "constructed-guide")
    assert any(x["kind"] == "protected_lost" and x.get("signal") == "ОТК" for x in edited["violations"])
    omitted = validate(before, "Другой план помогает выиграть.", "hearthstone", "constructed-guide", depth="переплавка")
    assert any(x["kind"] == "protected_lost" and x.get("signal") == "ОТК" for x in omitted["violations"])
