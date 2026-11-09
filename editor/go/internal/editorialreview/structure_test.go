package editorialreview

import (
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"
)

func TestStructureInventoryMatchesSharedPythonFixtures(t *testing.T) {
	data, err := os.ReadFile("../../../tests/fixtures/article-structure.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Name   string           `json:"name"`
		Text   string           `json:"text"`
		Blocks []StructureBlock `json:"blocks"`
	}
	if err := json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) == 0 {
		t.Fatal("empty shared fixtures")
	}
	for _, tc := range cases {
		t.Run(tc.Name, func(t *testing.T) {
			actual, err := PrepareStructure(tc.Text)
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(actual.Blocks, tc.Blocks) {
				t.Fatalf("blocks=%+v, want=%+v", actual.Blocks, tc.Blocks)
			}
		})
	}
}

func structureString(s string) *string { return &s }

func structureFixture(t *testing.T, text string) *StructureReview {
	t.Helper()
	assignment, err := PrepareStructure(text)
	if err != nil {
		t.Fatal(err)
	}
	review := &StructureReview{ArticleSHA256: assignment.ArticleSHA256, ReaderQuestion: "Fixture question", MainAnswer: "Fixture answer", OrderReason: "Fixture order", EndingReason: "Fixture end"}
	for _, block := range assignment.Blocks {
		review.Blocks = append(review.Blocks, StructureBlockCheck{ID: block.ID, Quote: block.Quote, Function: "Fixture function", NewInformation: "Fixture information", LinkToPrevious: "Fixture connection", DependsOn: []string{}, RepeatOf: []string{}, RepeatReason: structureString(""), Status: "clear", Reason: "Fixture reason"})
	}
	return review
}

func TestStructureInventoryRetainsMarkdownAndHTMLBoundaries(t *testing.T) {
	text := "# Выбор\r\n\r\nПервое условие.\r\nПродолжение.\r\n\r\n- Вариант\r\n  пояснение\r\n- Исключение\r\n\r\n```md\r\n# Не заголовок\r\n\r\n<p>Не отдельный блок</p>\r\n```\r\n<p>Причина</p><p>Вывод</p>"
	a, err := PrepareStructure(text)
	if err != nil {
		t.Fatal(err)
	}
	if len(a.Blocks) != 7 {
		t.Fatalf("blocks=%d: %+v", len(a.Blocks), a.Blocks)
	}
	kinds := []string{"heading", "text", "list", "list", "code", "text", "text"}
	for i, block := range a.Blocks {
		if block.Kind != kinds[i] || !strings.Contains(text, block.Quote) {
			t.Fatalf("block %d: %+v", i, block)
		}
	}
	if !strings.Contains(a.Blocks[4].Quote, "# Не заголовок\r\n\r\n<p>") {
		t.Fatal("fence content split")
	}
	if a.Blocks[5].Quote != "<p>Причина</p>" || a.Blocks[6].Quote != "<p>Вывод</p>" {
		t.Fatal("adjacent HTML blocks merged")
	}
}

func TestStructureRejectsIncompleteOrStaleCoverage(t *testing.T) {
	text := "Первое основание.\n\nВторой шаг.\n\nИтог."
	for name, mutate := range map[string]func(*StructureReview){
		"missing middle":      func(r *StructureReview) { r.Blocks = append(r.Blocks[:1], r.Blocks[2:]...) },
		"duplicate":           func(r *StructureReview) { r.Blocks[1] = r.Blocks[0] },
		"reordered":           func(r *StructureReview) { r.Blocks[0], r.Blocks[1] = r.Blocks[1], r.Blocks[0] },
		"stale":               func(r *StructureReview) { r.ArticleSHA256 = strings.Repeat("0", 64) },
		"wrong quote":         func(r *StructureReview) { r.Blocks[1].Quote = "Первое основание." },
		"future prerequisite": func(r *StructureReview) { r.Blocks[0].DependsOn = []string{"b003"} },
		"self reference":      func(r *StructureReview) { r.Blocks[1].DependsOn = []string{"b002"} },
		"missing connection":  func(r *StructureReview) { r.Blocks[1].LinkToPrevious = "" },
		"null dependencies":   func(r *StructureReview) { r.Blocks[1].DependsOn = nil },
	} {
		t.Run(name, func(t *testing.T) {
			r := structureFixture(t, text)
			mutate(r)
			if ValidateStructure(text, r) == nil {
				t.Fatal("accepted invalid structure review")
			}
		})
	}
	if ValidateStructure(text, nil) == nil {
		t.Fatal("missing review accepted")
	}
}

func TestStructureAllowsExplainedRepriseButNeverUnresolvedAcceptance(t *testing.T) {
	text := "Условие.\n\nПрименение.\n\nУсловие."
	r := structureFixture(t, text)
	r.Blocks[1].DependsOn = []string{"b001"}
	r.Blocks[2].RepeatOf = []string{"b001"}
	r.Blocks[2].RepeatReason = structureString("Fixture: reminder at the decision point.")
	if err := ValidateStructure(text, r); err != nil {
		t.Fatal(err)
	}
	if HasUnresolvedStructure(r) {
		t.Fatal("clear reprise marked unresolved")
	}
	r.Blocks[2].RepeatReason = structureString("")
	if ValidateStructure(text, r) == nil {
		t.Fatal("unexplained declared reprise accepted")
	}
	r.Blocks[2].RepeatReason = structureString("Fixture: unnecessary repetition.")
	r.Blocks[2].Status = "issue"
	if err := ValidateStructure(text, r); err != nil {
		t.Fatalf("truthful issue must parse: %v", err)
	}
	if !HasUnresolvedStructure(r) {
		t.Fatal("unresolved issue accepted")
	}
}

func TestStructureBoundsAndFenceClosing(t *testing.T) {
	for _, text := range []string{" ", strings.Repeat("Абзац.\n\n", 257)} {
		if _, err := PrepareStructure(text); err == nil {
			t.Fatal("invalid/oversize inventory accepted")
		}
	}
	a, err := PrepareStructure("~~~~\n# literal\n~~~\n<p>literal</p>\n~~~~\n\nText.")
	if err != nil || len(a.Blocks) != 2 || a.Blocks[0].Kind != "code" {
		t.Fatalf("short fence closed block: %+v %v", a, err)
	}
}
