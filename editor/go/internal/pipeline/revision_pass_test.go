package pipeline

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

func autoRevisionRequest(t *testing.T, source, candidate, mode string) Request {
	t.Helper()
	data, _ := json.Marshal(map[string]any{"text": source, "candidate_text": candidate, "mode": mode, "revise_candidate": true})
	var req Request
	if err := json.Unmarshal(data, &req); err != nil {
		t.Fatal(err)
	}
	return req
}

func TestAutomaticRevisionEditsCurrentDraftAgainstSourceAndKeepsParagraph(t *testing.T) {
	source := "Первое правило касается всех игроков. Второе правило для новых игроков включает в себя порядок получения награды."
	candidate := "Первое правило касается всех игроков.\n\nВторое правило для новый игроков включает порядок получения награды."
	fixed := "Первое правило касается всех игроков. Второе правило для новых игроков включает порядок получения награды."
	want := strings.Replace(fixed, ". Второе", ".\n\nВторое", 1)
	model := &fakeLLM{replies: []string{analysisJSON, fixed, criticJSON("accept")}}
	r, err := New(model, nil, "fake").Run(context.Background(), autoRevisionRequest(t, source, candidate, "edit"))
	if err != nil || !r.Accepted || r.Text != want || strings.Join(model.stages, ",") != "analysis,rewrite,critic" {
		t.Fatalf("automatic draft revision failed: %+v %v %v", r, err, model.stages)
	}
	analysis := lastUserJSON(t, model.messages[0])
	writer := lastUserJSON(t, model.messages[1])
	critic := lastUserJSON(t, model.messages[2])
	if analysis["text"] != source || analysis["candidate"] != nil || writer["source"] != source || writer["text"] != candidate {
		t.Fatal("source analysis was primed by the prior edit, or writer lost the current draft/source boundary")
	}
	if critic["source"] != source || critic["candidate"] != want || critic["revision_base"] != candidate || critic["analysis"].(map[string]any)["thesis"] != "" {
		t.Fatal("critic lacks factual source, previous form, or independence")
	}
}

func TestAutomaticRevisionRequiresDraftAndDoesNotTrustItsFactsOrDryRun(t *testing.T) {
	for _, tc := range []struct{ mode, candidate string }{{"edit", ""}, {"proofread", "Версия."}, {"rewrite", "Версия."}} {
		lm := &fakeLLM{replies: []string{analysisJSON}}
		_, err := New(lm, nil, "fake").Run(context.Background(), autoRevisionRequest(t, "Исходник.", tc.candidate, tc.mode))
		var bad *RequestError
		if !errors.As(err, &bad) || len(lm.messages) != 0 {
			t.Fatalf("invalid automatic revision reached model: %v", err)
		}
	}
	source, candidate := "Награда — 4 кристалла.", "Награда — 5 кристаллов."
	lm := &fakeLLM{replies: []string{analysisJSON, candidate, criticJSON("accept"), candidate, criticJSON("accept"), candidate, criticJSON("accept")}}
	r, err := New(lm, nil, "fake").Run(context.Background(), autoRevisionRequest(t, source, candidate, "edit"))
	if err != nil || r.Accepted || r.Text != source || !strings.Contains(strings.Join(r.RejectionReasons, ","), ReasonProtectedEntityChanged) {
		t.Fatalf("draft overrode source facts: %+v %v", r, err)
	}
	checks := &scriptedAnalyzer{name: "test"}
	r, err = New(nil, nil, "none", checks).Run(context.Background(), autoRevisionRequest(t, source, candidate, "edit"))
	if err != nil || r.Accepted || r.Text != source {
		t.Fatalf("dry run exposed draft: %+v %v", r, err)
	}
	for _, input := range checks.inputs {
		if input.Text != source {
			t.Fatal("dry run analyzed unverified draft")
		}
	}
}

func TestAutomaticRevisionRepairAlsoReceivesPreviousForm(t *testing.T) {
	source, candidate := "Участие в турнире осуществляется бесплатно.", "Участие в турнире бесплатное."
	lm := &fakeLLM{replies: []string{analysisJSON, candidate, criticJSON("repair", warning("style.local", "Проверь формулировку.")), candidate, criticJSON("accept")}}
	r, err := New(lm, nil, "fake").Run(context.Background(), autoRevisionRequest(t, source, candidate, "edit"))
	if err != nil || !r.Accepted || lastUserJSON(t, lm.messages[3])["revision_base"] != candidate {
		t.Fatalf("repair lost previous useful wording: %+v %v", r, err)
	}
}
