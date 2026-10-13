package guards

import "testing"

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
