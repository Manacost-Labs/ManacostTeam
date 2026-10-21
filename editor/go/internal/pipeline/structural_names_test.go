package pipeline

import "testing"

func TestKnownNamesInGrammaticalClausesDoNotBecomeCompoundCards(t *testing.T) {
	before := "Полкелт. Полкелта. Сфера. Мозаки. Ученица. Северная Империя."
	for _, text := range []string{"Сам Полкелт", "Механики Полкелта", "До Полкелта Сфера", "После Полкелта Ученица", "Выставленная Мозаки", "Разыгранный Полкелт"} {
		if reconstructionGuard(before, text).HasHardChanges() {
			t.Errorf("grammatical clause became an invented name: %q", text)
		}
	}
	for _, text := range []string{"Сам Неизвестный Полкелт", "До Полкелта Неведомая Сфера", "Полкелт Сфера", "Великий Полкелт Сфера", "До Полкелта Сфера Мозаки", "До Полкелта 17 урона", "До Полкелта https://foreign.example/"} {
		if !reconstructionGuard(before, text).HasHardChanges() {
			t.Errorf("unknown identity, composition or fact admitted: %q", text)
		}
	}
}
