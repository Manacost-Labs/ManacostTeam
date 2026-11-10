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
