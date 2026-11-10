package editorialreview

import (
	"crypto/sha256"
	"fmt"
	"testing"
)

func TestOwnerRubricRequiresCoverageAndRealQuotes(t *testing.T) {
	text := "Условный совет."
	var rows []Check
	for _, id := range OwnerIDs() {
		rows = append(rows, Check{ID: id, Status: "clear", Quote: text, Reason: "Synthetic check."})
	}
	if err := ValidateOwner(text, rows); err != nil {
		t.Fatal(err)
	}
	if ValidateOwner(text, rows[:len(rows)-1]) == nil {
		t.Fatal("missing category accepted")
	}
	rows[0].Quote = ""
	if ValidateOwner(text, rows) == nil {
		t.Fatal("empty quote accepted")
	}
	rows[0].Quote, rows[0].Status = text, "issue"
	if err := ValidateOwner(text, rows); err != nil {
		t.Fatal("truthful issue lost", err)
	}
	if !HasUnresolved(rows) {
		t.Fatal("issue cannot pass")
	}
}

func TestDeletionOnlyReceiptUsesRuneOffsetsAndRejectsAdditions(t *testing.T) {
	text := "🙂 Совет. Рамка."
	raw := fmt.Sprintf(`{"article_sha256":"%x","deletions":[{"start":8,"quote":" Рамка.","reason":"No decision."}]}`, sha256.Sum256([]byte(text)))
	result, _, err := ApplyDeletion(text, raw)
	if err != nil || result != "🙂 Совет." {
		t.Fatalf("%q %v", result, err)
	}
	if _, _, err := ApplyDeletion(text, raw[:len(raw)-1]+`,"text":"новое"}`); err == nil {
		t.Fatal("new text accepted")
	}
}

func TestDeckGuideRubricExtensionIsAllOrNothing(t *testing.T) {
	text := "Условный совет."
	row := func(id string) Check { return Check{ID: id, Status: "clear", Quote: text, Reason: "Synthetic check."} }
	var base []Check
	for _, id := range OwnerIDs() {
		base = append(base, row(id))
	}
	if err := ValidateOwner(text, base); err != nil {
		t.Fatal("base rubric must stay valid without a genre signal", err)
	}
	full := append([]Check(nil), base...)
	for _, id := range DeckGuideOwnerIDs() {
		full = append(full, row(id))
	}
	if err := ValidateOwner(text, full); err != nil {
		t.Fatal(err)
	}
	if ValidateOwner(text, full[:len(full)-1]) == nil {
		t.Fatal("partial deck guide extension accepted")
	}
	full[len(full)-1].Status = "issue"
	if ValidateOwner(text, full) != nil || !HasUnresolved(full) {
		t.Fatal("negative deck guide judgment must stay valid evidence and block acceptance")
	}
}
