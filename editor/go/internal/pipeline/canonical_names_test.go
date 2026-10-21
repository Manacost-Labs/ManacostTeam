package pipeline

import (
	"context"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

func TestReferencedCanonicalNamesReachWriterRepairAndReviewer(t *testing.T) {
	h := readyHandoff()
	h.Sources[0].Quote = `{"id":"CARD1","name":"Зубрежка"}`
	h.Sources = append(h.Sources, ResearchSource{ID: "UNUSED", Quote: `{"id":"CARD2","name":"Чужая карта"}`})
	for _, stage := range []string{"writer", "repair", "fact"} {
		m := &fakeLLM{replies: []string{publicationFact}}
		s := New(m, nil, "fake")
		switch stage {
		case "writer":
			_, _ = s.rewrite(context.Background(), Request{Mode: "reconstruct", Handoff: h}, rules.RuleBundle{}, Analysis{}, nil)
		case "repair":
			_, _ = s.repairReconstruction(context.Background(), rules.RuleBundle{}, h, publicationCandidate, nil, nil, nil)
		case "fact":
			_, _ = s.factReview(context.Background(), h, publicationCandidate)
		}
		rows := lastUserJSON(t, m.messages[0])["canonical_names"].([]any)
		if len(rows) != 1 || rows[0].(map[string]any)["name"] != "Зубрежка" || rows[0].(map[string]any)["evidence_ref"] != "SRC-1" {
			t.Fatal(stage, "lost verified spelling or used foreign source", rows)
		}
	}
}
