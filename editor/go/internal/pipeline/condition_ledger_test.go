package pipeline

import (
	"context"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

func TestWritingAndRepairReceiveCompleteConditionLedger(t *testing.T) {
	h := readyHandoff()
	for _, stage := range []string{"writer", "repair"} {
		m := &fakeLLM{replies: []string{publicationCandidate}}
		s := New(m, nil, "fake")
		if stage == "writer" {
			_, _ = s.rewrite(context.Background(), Request{Mode: "reconstruct", Handoff: h}, rules.RuleBundle{}, Analysis{}, nil)
		} else {
			_, _ = s.repairReconstruction(context.Background(), rules.RuleBundle{}, h, publicationCandidate, nil, nil, nil)
		}
		rows, ok := lastUserJSON(t, m.messages[0])["condition_ledger"].([]any)
		if !ok || len(rows) != 1 {
			t.Fatalf("%s lost explicit obligations: %v", stage, rows)
		}
		row := rows[0].(map[string]any)
		if row["claim_id"] != h.Claims[0].ID || row["condition"] != h.Claims[0].Condition || row["exception"] != h.Claims[0].Exception || row["action"] != h.Claims[0].Action || row["meaning"] != h.Claims[0].Meaning {
			t.Fatalf("%s lost fields: %v", stage, row)
		}
		if !strings.Contains(m.messages[0][0].Content, "каждом повторе") {
			t.Fatal("writer did not receive whole-article consistency rule")
		}
	}
}

func TestFactReviewRequestsAllOccurrencesAndActorPerspective(t *testing.T) {
	m := &fakeLLM{replies: []string{publicationFact}}
	s := New(m, nil, "fake")
	_, _ = s.factReview(context.Background(), readyHandoff(), publicationCandidate)
	prompt := m.messages[0][0].Content
	for _, rule := range []string{"каждом повторе", "владелец", "достаточное условие", "короткие дословные цитаты"} {
		if !strings.Contains(prompt, rule) {
			t.Fatalf("missing factual consistency rule %q", rule)
		}
	}
}
