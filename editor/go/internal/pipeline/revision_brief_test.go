package pipeline

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

func requestWithBrief(t *testing.T, source, candidate, brief string) Request {
	t.Helper()
	raw, _ := json.Marshal(map[string]string{"text": source, "candidate_text": candidate, "revision_brief": brief, "mode": "edit"})
	var req Request
	if err := json.Unmarshal(raw, &req); err != nil {
		t.Fatal(err)
	}
	return req
}

func TestRevisionBriefReachesReviewAndRepairWithoutBecomingFacts(t *testing.T) {
	source, candidate := "Участие в турнире осуществляется бесплатно.", "Участие в турнире бесплатное."
	brief := "Сохрани полезное сокращение и проверь ясность приглашения."
	model := &fakeLLM{replies: []string{analysisJSON, criticJSON("repair", warning("style.local", "Проверь приглашение.")), candidate, criticJSON("accept")}}
	r, err := New(model, nil, "fake").Run(context.Background(), requestWithBrief(t, source, candidate, brief))
	if err != nil || !r.Accepted || r.Text != candidate || strings.Contains(strings.Join(model.stages, ","), "rewrite") {
		t.Fatalf("brief revision failed: %+v %v", r, err)
	}
	for _, index := range []int{0, 1, 2, 3} {
		payload := lastUserJSON(t, model.messages[index])
		if payload["revision_brief"] != brief {
			t.Fatal("revision brief lost at", model.stages[index])
		}
		if index == 0 && payload["text"] != source || index > 0 && payload["source"] != source {
			t.Fatal("brief changed source")
		}
		claims, _ := json.Marshal(payload["source_claims"])
		if strings.Contains(string(claims), brief) {
			t.Fatal("brief became factual evidence")
		}
		if model.stages[index] == "critic" && payload["analysis"].(map[string]any)["thesis"] != "" {
			t.Fatal("writer analysis leaked to critic")
		}
	}
}

func TestRevisionBriefRequiresCandidateAndCannotOverrideSourceGuard(t *testing.T) {
	for _, tc := range []struct{ mode, candidate, brief string }{{"edit", "", "Проверь текст."}, {"proofread", "", "Проверь текст."}, {"edit", " ", "Проверь текст."}, {"edit", "Версия.", " \n "}} {
		model := &fakeLLM{replies: []string{analysisJSON}}
		check := &scriptedAnalyzer{name: "test"}
		req := requestWithBrief(t, "Текст.", tc.candidate, tc.brief)
		req.Mode = tc.mode
		_, err := New(model, nil, "fake", check).Run(context.Background(), req)
		var bad *RequestError
		if !errors.As(err, &bad) || len(model.messages) != 0 || len(check.inputs) != 0 {
			t.Fatalf("invalid brief reached processing: %+v %v", tc, err)
		}
	}
	source, candidate := "Награда — 4 кристалла.", "Награда — 5 кристаллов."
	model := &fakeLLM{replies: []string{analysisJSON, criticJSON("accept"), candidate, criticJSON("accept"), candidate, criticJSON("accept")}}
	r, err := New(model, nil, "fake").Run(context.Background(), requestWithBrief(t, source, candidate, "Укажи награду в 5 кристаллов."))
	if err != nil || r.Accepted || r.Text != source || !strings.Contains(strings.Join(r.RejectionReasons, ","), ReasonProtectedEntityChanged) {
		t.Fatalf("brief overrode source: %+v %v", r, err)
	}
}

func TestAbsentRevisionBriefDoesNotChangePromptsOrPayloads(t *testing.T) {
	source, candidate := "Участие в турнире осуществляется бесплатно.", "Участие в турнире бесплатное."
	model := &fakeLLM{replies: []string{analysisJSON, candidate, criticJSON("repair", warning("style.local", "Проверь фразу.")), candidate, criticJSON("accept")}}
	r, err := New(model, nil, "fake").Run(context.Background(), requestWithBrief(t, source, "", ""))
	if err != nil || !r.Accepted {
		t.Fatalf("default edit failed: %+v %v", r, err)
	}
	for _, messages := range model.messages {
		if strings.Contains(messages[0].Content, "revision_brief") {
			t.Fatal("absent brief changed the system prompt")
		}
		if _, exists := lastUserJSON(t, messages)["revision_brief"]; exists {
			t.Fatal("absent brief changed JSON payload")
		}
	}
}
