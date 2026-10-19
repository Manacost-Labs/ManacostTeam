package guards

import "testing"

func TestEvaluativeModalitySurvivesFormEditing(t *testing.T) {
	for _, hedge := range []string{"можно назвать", "можно считать", "можно предположить", "можно ожидать"} {
		before := "Мы думаем: " + hedge + " такой результат. Следим за ситуацией."
		if !Compare(before, "Мы считаем результат таким.\n\nСледим за ситуацией.").HasHardChanges() {
			t.Errorf("lost evaluative modality %q was not detected", hedge)
		}
		if Compare(before, "Мы думаем: "+hedge+" такой результат.\n\nСледим за ситуацией.").HasHardChanges() {
			t.Errorf("paragraph split falsely changed %q", hedge)
		}
	}
	if uncertaintyCount("Можно выбрать карту. Можно разыграть существо.") != 0 {
		t.Fatal("ordinary permission must not become an evaluative hedge")
	}
}

func TestSelectedTermInflectionsKeepIdentityAndEvidence(t *testing.T) {
	forms := []string{"Поля сражений", "Полей сражений", "Полям сражений", "Полями сражений", "Полях сражений"}
	for _, form := range forms {
		text := "Изменения: " + form + "."
		report := Compare("Изменения: Поля сражений.", text)
		if report.HasHardChanges() || len(report.Added) != 0 {
			t.Errorf("inflection changed identity %q: %+v", form, report)
		}
		found := false
		for _, entity := range Extract(text) {
			if entity.Kind == "game_entity" && entity.Value == form {
				found = true
				if text[entity.Start:entity.End] != form {
					t.Errorf("surface evidence lost: %+v", entity)
				}
			}
		}
		if !found {
			t.Errorf("inflected term not protected: %q", form)
		}
		if !Compare(text, "Изменения: Арена.").HasHardChanges() {
			t.Errorf("removed game mode not detected: %q", form)
		}
	}
	if len(ExtractWithTerms("Полях сражений", []string{"ГКД"})) != 0 {
		t.Fatal("Hearthstone aliases leaked into selected terms for another game")
	}
	if !Compare("Поля сражений. Полях сражений.", "Поля сражений.").HasHardChanges() {
		t.Fatal("canonical identity must still protect occurrence count")
	}
	if report := Compare("Основной фокус будет сосредоточен на Полях сражений.", "Основной упор будет сделан на Поля сражений."); report.HasHardChanges() || len(report.Added) != 0 {
		t.Fatalf("natural phrase edit still blocked by entity inflection: %+v", report)
	}
	if report := CompareWithTerms("Полях сражений", "Поля сражений", []string{"Полях сражений"}); !report.HasHardChanges() {
		t.Fatal("aliases activated without selected canonical term")
	}
}

func TestSelectedTermsDoNotUseHearthstoneEntities(t *testing.T) {
	got := ExtractWithTerms("Темные дары и ГКД, 20% https://example.test", []string{"ГКД"})
	found := map[string]bool{}
	for _, entity := range got {
		found[entity.Kind+":"+entity.Value] = true
	}
	if found["game_entity:Темные дары"] || !found["game_entity:ГКД"] || !found["percent:20%"] {
		t.Fatalf("wrong game protection: %+v", got)
	}
	if !CompareWithTerms("урон 20% ГКД", "урон 30%", []string{"ГКД"}).HasHardChanges() {
		t.Fatal("selected terms and numbers must remain protected")
	}
}

func TestCompareProtectsLinksNumbersAndNegation(t *testing.T) {
	before := "Не оставляйте карту за 3 маны: https://example.test/a."
	after := "Оставляйте карту за 4 маны: https://example.test/a."
	report := Compare(before, after)
	if len(report.Missing) == 0 || len(report.Changed) == 0 {
		t.Fatalf("затронутые элементы не найдены: %+v", report)
	}
	if !report.HasHardChanges() {
		t.Fatal("изменение защищенного элемента должно быть жестким")
	}
}

func TestCompareAllowsPureProseEdit(t *testing.T) {
	if got := Compare("Карта за 3 маны.", "Эта карта стоит 3 маны."); got.HasHardChanges() {
		t.Fatalf("ложное срабатывание: %+v", got)
	}
}

func TestCompareDetectsCyrillicNegationAndUncertaintyChanges(t *testing.T) {
	if negationCount("Не спешите. Никогда не жадничайте, нельзя.") != 4 {
		t.Fatalf("negations: %d", negationCount("Не спешите. Никогда не жадничайте, нельзя."))
	}
	if negationCount("Спешите, немного не так: нечего.") != 1 {
		t.Fatalf("prefixes must not count: %d", negationCount("Спешите, немного не так: нечего."))
	}
	if uncertaintyCount("Обычно может помочь, но редко.") != 3 {
		t.Fatalf("uncertainty: %d", uncertaintyCount("Обычно может помочь, но редко."))
	}
	if report := Compare("Не спешите с разменом.", "Спешите с разменом."); !report.HasHardChanges() {
		t.Fatalf("dropped negation must be a hard change: %+v", report)
	}
	if report := Compare("Карта обычно помогает.", "Карта всегда помогает."); !report.HasHardChanges() {
		t.Fatalf("dropped hedge must be a hard change: %+v", report)
	}
	if report := Compare("Не спешите с разменом.", "Не  спешите с разменом."); report.HasHardChanges() {
		t.Fatalf("whitespace must not be a hard change: %+v", report)
	}
}
