package pipeline

import (
	"context"
	"testing"
)

func TestRepairKeepsPriorFindingsSeparateFromCurrentTargets(t *testing.T) {
	source := "Участие в турнире осуществляется бесплатно. Награды будут выданы завтра."
	candidate := "Участие в турнире бесплатное. Награды будут выданы завтра."
	repaired := "Участие в турнире бесплатное. Награды выдадут завтра."
	first := warning("first.local", "Упрости пассив, сохрани соседнюю полезную правку.")
	second := warning("second.local", "Прочитай второе предложение рядом с первым.")
	model := &fakeLLM{replies: []string{analysisJSON, criticJSON("repair", first), repaired, criticJSON("repair", second), repaired, criticJSON("accept")}}
	r, err := New(model, nil, "fake").Run(context.Background(), revisionRequest(t, source, candidate, "edit"))
	if err != nil || !r.Accepted || r.Text != repaired || r.Attempts != 3 || len(model.messages) != 6 {
		t.Fatalf("repair/acceptance contract changed: %+v %v", r, err)
	}
	one, two := lastUserJSON(t, model.messages[2]), lastUserJSON(t, model.messages[4])
	if len(findingsOf(t, one, "previous_repair_findings")) != 0 {
		t.Fatal("first repair has invented history")
	}
	prior := findingsOf(t, two, "previous_repair_findings")
	current := findingsOf(t, two, "findings")
	if len(prior) != 1 || prior[0]["rule_id"] != first.RuleID || prior[0]["message"] != first.Message {
		t.Fatal("second repair lost the previous actual targets:", prior)
	}
	if len(current) != 1 || current[0]["rule_id"] != second.RuleID || two["source"] != source || two["candidate"] != repaired {
		t.Fatal("history became active targets or changed the source/current candidate:", two)
	}
}
