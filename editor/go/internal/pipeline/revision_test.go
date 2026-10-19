package pipeline

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

func revisionRequest(t *testing.T, source, candidate, mode string) Request {
	t.Helper()
	raw, _ := json.Marshal(map[string]string{"text": source, "candidate_text": candidate, "mode": mode})
	var req Request
	if err := json.Unmarshal(raw, &req); err != nil {
		t.Fatal(err)
	}
	return req
}

func TestRevisionUsesCandidateWithoutRegeneratingUsefulEdits(t *testing.T) {
	source := "Участие в турнире осуществляется бесплатно. Награду можно получить завтра."
	candidate := "Участие в турнире бесплатное.\n\nНаграду можно получить завтра."
	model := &fakeLLM{replies: []string{analysisJSON, criticJSON("accept")}}
	checks := &scriptedAnalyzer{name: "test"}
	r, err := New(model, nil, "fake", checks).Run(context.Background(), revisionRequest(t, source, candidate, "edit"))
	if err != nil || !r.Accepted || r.Text != candidate {
		t.Fatalf("revision lost: %+v %v", r, err)
	}
	if strings.Join(model.stages, ",") != "analysis,critic" {
		t.Fatal("candidate was regenerated:", model.stages)
	}
	if !strings.Contains(model.messages[0][1].Content, source) {
		t.Fatal("analysis did not receive source")
	}
	payload := lastUserJSON(t, model.messages[1])
	if payload["source"] != source || payload["candidate"] != candidate {
		t.Fatal("critic lost source/candidate distinction")
	}
	if len(checks.inputs) < 2 || checks.inputs[0].Text != source || checks.inputs[1].Text != candidate {
		t.Fatal("revision bypassed QA")
	}
}

func TestRevisionRejectsInvalidModeBeforeAnyWork(t *testing.T) {
	for _, tc := range []struct{ mode, candidate string }{{"proofread", "Кандидат."}, {"rewrite", "Кандидат."}, {"reconstruct", "Кандидат."}, {"facts_only", "Кандидат."}, {"edit", " \n "}} {
		model := &fakeLLM{replies: []string{analysisJSON}}
		checks := &scriptedAnalyzer{name: "test"}
		_, err := New(model, nil, "fake", checks).Run(context.Background(), revisionRequest(t, "Исходный текст.", tc.candidate, tc.mode))
		var bad *RequestError
		if !errors.As(err, &bad) || len(model.messages) != 0 || len(checks.inputs) != 0 {
			t.Fatalf("invalid revision reached processing: %+v, %v", tc, err)
		}
	}
}

func TestRevisionStillRejectsCandidateFactChangesAndDryRun(t *testing.T) {
	source, candidate := "Награда — 4 кристалла.", "Награда — 5 кристаллов."
	model := &fakeLLM{replies: []string{analysisJSON, criticJSON("accept"), candidate}}
	r, err := New(model, nil, "fake").Run(context.Background(), revisionRequest(t, source, candidate, "edit"))
	if err != nil || r.Accepted || r.Text != source || r.Status != StatusRejected {
		t.Fatalf("candidate was trusted: %+v %v", r, err)
	}
	if !strings.Contains(strings.Join(r.RejectionReasons, ","), ReasonProtectedEntityChanged) || strings.Contains(strings.Join(model.stages, ","), "rewrite") {
		t.Fatal("revision did not reach the source-based fact guard:", r.RejectionReasons, model.stages)
	}
	checks := &scriptedAnalyzer{name: "test"}
	r, err = New(nil, nil, "none", checks).Run(context.Background(), revisionRequest(t, source, candidate, "edit"))
	if err != nil || r.Accepted || r.Text != source {
		t.Fatalf("dry run returned unreviewed candidate: %+v %v", r, err)
	}
	for _, input := range checks.inputs {
		if input.Text != source {
			t.Fatal("dry-run source findings were mixed with unreviewed candidate findings")
		}
	}
}

func TestRevisionRepairPreservesSourceAndCandidateBoundaries(t *testing.T) {
	source := "Первое правило касается всех игроков. Второе правило действует до вечера.\n\nТретье правило включает в себя порядок получения награды завтра."
	candidate := "Первое правило касается всех игроков.\n\nВторое правило действует до вечера. Третье правило включает порядок получения награды завтра."
	want := "Первое правило касается всех игроков.\n\nВторое правило действует до вечера.\n\nТретье правило включает порядок получения награды завтра."
	merged := strings.ReplaceAll(want, "\n\n", " ")
	model := &fakeLLM{replies: []string{analysisJSON, criticJSON("repair", warning("style.local", "Проверь только отмеченную фразу.")), merged, criticJSON("accept")}}
	r, err := New(model, nil, "fake").Run(context.Background(), revisionRequest(t, source, candidate, "edit"))
	if err != nil || !r.Accepted || r.Text != want || r.Attempts != 2 {
		t.Fatalf("revision boundaries lost: %+v %v", r, err)
	}
	if lastUserJSON(t, model.messages[1])["candidate"] != want {
		t.Fatal("source boundary was not restored before critic")
	}
}

func TestEmptyRevisionKeepsNormalDraftAndEditAliasesAcceptRevision(t *testing.T) {
	source, candidate := "Участие в турнире осуществляется бесплатно.", "Участие в турнире бесплатное."
	model := &fakeLLM{replies: []string{analysisJSON, candidate, criticJSON("accept")}}
	r, err := New(model, nil, "fake").Run(context.Background(), revisionRequest(t, source, "", "edit"))
	if err != nil || !r.Accepted || r.Text != candidate || strings.Join(model.stages, ",") != "analysis,rewrite,critic" {
		t.Fatalf("normal edit changed: %+v %v %v", r, err, model.stages)
	}
	for _, mode := range []string{" обычная ", "Глубокая"} {
		model = &fakeLLM{replies: []string{analysisJSON, criticJSON("accept")}}
		r, err = New(model, nil, "fake").Run(context.Background(), revisionRequest(t, source, candidate, mode))
		if err != nil || !r.Accepted || r.Text != candidate || strings.Join(model.stages, ",") != "analysis,critic" {
			t.Fatalf("edit alias changed: %s %+v %v", mode, r, err)
		}
	}
}
