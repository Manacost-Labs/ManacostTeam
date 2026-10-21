package analyzers

import (
	"context"
	"strings"
	"testing"
)

func TestCardCopyGrammarDistinguishesCountFromOrdinal(t *testing.T) {
	for _, bad := range []string{"2 копию", "11 копию", "22 копию"} {
		r, err := (NativeGoAnalyzer{}).Analyze(context.Background(), Input{Text: "Оставляйте " + bad + " только с Монеткой.", Game: "hearthstone", Language: "ru-RU"})
		if err != nil || len(r.Findings) != 1 || r.Findings[0].RuleID != "grammar.copy-number" || r.Findings[0].Severity != "error" || r.Findings[0].Evidence != bad || !strings.Contains(r.Findings[0].Message, "смысл") {
			t.Fatalf("grammar repair lacks exact evidence and source constraint: %+v %v", r, err)
		}
	}
	for _, good := range []string{"1 копию", "21 копию", "121 копию", "2 копии", "2-ю копию", "11 копий", "вторую копию"} {
		r, err := (NativeGoAnalyzer{}).Analyze(context.Background(), Input{Text: "Оставляйте " + good + ".", Game: "hearthstone", Language: "ru-RU"})
		if err != nil || len(r.Findings) != 0 {
			t.Fatalf("valid number agreement rejected: %s %+v", good, r)
		}
	}
}

func TestCopyGrammarReportsAdjacentErrorsAndKeepsWordBoundaries(t *testing.T) {
	r, _ := (NativeGoAnalyzer{}).Analyze(context.Background(), Input{Text: "2 копию 3 копию", Game: "hearthstone"})
	if len(r.Findings) != 2 || r.Findings[0].Evidence != "2 копию" || r.Findings[1].Evidence != "3 копию" {
		t.Fatal("adjacent agreement errors were consumed", r.Findings)
	}
	for _, text := range []string{"A2 копию", "2 копиюшку", "2 копию2"} {
		r, _ = (NativeGoAnalyzer{}).Analyze(context.Background(), Input{Text: text, Game: "hearthstone"})
		if len(r.Findings) != 0 {
			t.Fatal("partial word became a grammar finding", text, r.Findings)
		}
	}
}
