package pipeline

import (
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/guards"
)

func TestReconstructionListOrdinalsAreNotFacts(t *testing.T) {
	before := "Сохраните 3 ресурса. Проверьте выбор."
	for _, after := range []string{
		"1. Сохраните 3 ресурса.\n4) Проверьте выбор.",
		"   123456789. Сохраните 3 ресурса.",
		"~~~\nпример\n~~~\n4. Сохраните 3 ресурса.",
		"````\nпример\n```\n````\n4. Сохраните 3 ресурса.",
	} {
		if report := reconstructionGuard(before, after); report.HasHardChanges() {
			t.Errorf("list ordinal treated as a fact: %q: %+v", after, report)
		}
	}
	// Source ordinals must not authorize the same number in the article body.
	if !reconstructionGuard("4. Сохраните 3 ресурса.", "Сохраните 4 ресурса.").HasHardChanges() {
		t.Fatal("source list ordinal authorized a new factual quantity")
	}
	if !guards.Compare("4. Сохраните 3 ресурса.", "Сохраните 3 ресурса.").HasHardChanges() {
		t.Fatal("reconstruction allowance leaked into ordinary editing")
	}
}

func TestReconstructionStillGuardsBodyAndLiteralNumbers(t *testing.T) {
	before := "Сохраните 3 ресурса."
	for _, after := range []string{
		"1. Сохраните 4 ресурса.",
		"1) Сохраните 4 ресурса.",
		"4.0 ресурса.", "4.10.2026", "версия 4.0", "4%",
		"    4. пример", "\t4. пример", "`4. пример`", "4\\. пример", "\\4. пример",
		"1000000000. пример", "4.пример",
		"```\n4. пример\n```", "~~~\n4. пример\n~~~",
		"````\n```\n4. пример\n````",
		"~~~\n```\n4. пример\n~~~",
	} {
		if !reconstructionGuard(before, after).HasHardChanges() {
			t.Errorf("new factual or literal number admitted: %q", after)
		}
	}
}
