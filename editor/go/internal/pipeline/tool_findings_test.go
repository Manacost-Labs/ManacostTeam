package pipeline

import (
	"fmt"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzers"
)

func TestCriticToolFindingsSummarizeNoisyWarningsAndKeepErrors(t *testing.T) {
	var items []analyzers.Finding
	for i := 0; i < 40; i++ {
		items = append(items, analyzers.Finding{Analyzer: "natasha-razdel", RuleID: "repeat.word", Severity: "warning", Message: "Повтор слова", Evidence: fmt.Sprintf("слово%d", i)})
	}
	items = append(items,
		analyzers.Finding{Analyzer: "python", RuleID: "ARITHMETIC_INCONSISTENCY", Severity: "error", Message: "Счёт 39-16 даёт 70.91%"},
		analyzers.Finding{Analyzer: "guards", RuleID: "protected_entity_changed", Severity: "warning", Message: "Имя карты"},
	)
	got := criticToolFindings(items)
	if len(got) != maxCriticWarningsPerRule+3 {
		t.Fatalf("expected six samples, one summary, error and guard: %d", len(got))
	}
	summary := got[len(got)-1]
	if summary.RuleID != "repeat.word" || !strings.Contains(summary.Message, "Ещё 34") || !strings.Contains(summary.Message, "слово35") || strings.Contains(summary.Message, "слово36") {
		t.Fatalf("summary must keep scale and fragments: %+v", summary)
	}
	full := map[string]bool{}
	for _, item := range got {
		full[item.RuleID] = true
	}
	for _, rule := range []string{"ARITHMETIC_INCONSISTENCY", "protected_entity_changed"} {
		if !full[rule] {
			t.Fatalf("%s must reach the critic in full", rule)
		}
	}
}
