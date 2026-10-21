package pipeline

import (
	"context"
	"strings"
	"testing"
)

func TestActionTimingIsExplicitAndStillRequiresFreshPositiveReview(t *testing.T) {
	h := readyHandoff()
	h.Claims[0].Meaning = "Добор может помочь."
	h.Claims[0].Action = "Планируйте добор до начала хода."
	bad := "Добор может помочь. Планируйте добор до начала комбинации при слабой позиции, кроме угрозы поражения. https://example.org/guide"
	good := strings.Replace(bad, "до начала комбинации", "до начала хода", 1)
	negative := strings.Replace(publicationFact, "Сохраняйте ресурс", "Планируйте добор до начала комбинации", 1)
	negative = strings.Replace(negative, `"status":"supported"`, `"status":"insufficient"`, 1)
	positive := strings.Replace(publicationFact, "Сохраняйте ресурс", "Планируйте добор до начала хода", 1)
	for _, last := range []string{positive, negative} {
		writer := &fakeLLM{replies: []string{bad, good}}
		reviewer := &fakeLLM{replies: []string{negative, criticJSON("accept"), last, criticJSON("accept"), last}}
		s := New(writer, nil, "fake")
		s.Reviewer = reviewer
		r, err := s.Run(context.Background(), Request{Mode: "write", Handoff: h})
		if err != nil {
			t.Fatal(err)
		}
		if last == positive && (!r.Accepted || r.Text != good || r.Attempts != 2) {
			t.Fatalf("temporal action not repaired and reviewed: %+v", r)
		}
		if last == negative && (r.Accepted || r.Text != "") {
			t.Fatal("negative review was ignored")
		}
		payload := lastUserJSON(t, reviewer.messages[0])
		row := payload["required_attestations"].([]any)[0].(map[string]any)
		if row["required_action"] != h.Claims[0].Action || row["required_meaning"] != h.Claims[0].Meaning {
			t.Fatal("independent Action details not explicit in proof requirements", row)
		}
	}
}
