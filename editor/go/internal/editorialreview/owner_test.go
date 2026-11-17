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

func TestBGRubricExtensionsAreAllOrNothingAndNeverMixed(t *testing.T) {
	text := "Ставьте на 2-м ходу."
	row := func(id string) Check { return Check{ID: id, Status: "clear", Quote: text, Reason: "Synthetic check."} }
	var base []Check
	for _, id := range OwnerIDs() {
		base = append(base, row(id))
	}
	extend := func(ids []string) []Check {
		rows := append([]Check(nil), base...)
		for _, id := range ids {
			rows = append(rows, row(id))
		}
		return rows
	}
	for name, ids := range map[string][]string{"bg_tierlist": BGTierlistOwnerIDs(), "bg_guide": BGGuideOwnerIDs()} {
		full := extend(ids)
		if err := ValidateOwner(text, full); err != nil {
			t.Fatal(name, err)
		}
		if len(full) != len(OwnerIDs())+len(ids) {
			t.Fatal(name, "unexpected rubric size")
		}
		if ValidateOwner(text, full[:len(full)-1]) == nil {
			t.Fatal(name, "partial extension accepted")
		}
		full[len(full)-1].Status = "issue"
		if ValidateOwner(text, full) != nil || !HasUnresolved(full) {
			t.Fatal(name, "negative judgment must stay valid evidence and block acceptance")
		}
	}
	if len(BGTierlistOwnerIDs()) != 4 || len(BGGuideOwnerIDs()) != 3 {
		t.Fatal("bg extensions must add 4 and 3 categories")
	}
	mixed := extend(append(BGTierlistOwnerIDs(), BGGuideOwnerIDs()[0]))
	if ValidateOwner(text, mixed) == nil {
		t.Fatal("rows of two genres accepted together")
	}
	mixed = extend(append(DeckGuideOwnerIDs(), BGTierlistOwnerIDs()...))
	if ValidateOwner(text, mixed) == nil {
		t.Fatal("deck guide and tierlist rows accepted together")
	}
	if err := ValidateOwner(text, base); err != nil {
		t.Fatal("/v2/edit without plan context must keep the ten-row rubric", err)
	}
}
