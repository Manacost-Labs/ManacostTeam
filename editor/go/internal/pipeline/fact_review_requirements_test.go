package pipeline

import (
	"context"
	"encoding/json"
	"reflect"
	"testing"
)

func TestFactReviewerReceivesEachRequiredQuoteFieldAndItsOwnSources(t *testing.T) {
	h := readyHandoff()
	h.Sources = append(h.Sources, ResearchSource{ID: "SRC-2", URL: "https://example.org/rewards"})
	h.Claims = append(h.Claims,
		ResearchClaim{ID: "CLM-2", Meaning: "Получите награду", Exception: "кроме повторного захода", Confidence: "HIGH", EvidenceRefs: []string{"SRC-2"}},
		ResearchClaim{ID: "CLM-3", Meaning: "Дополнительный ресурс иногда доступен", Condition: "при победе", Confidence: "low", EvidenceRefs: []string{"SRC-1", "SRC-2"}},
		ResearchClaim{ID: "NOT-REQUIRED", Meaning: "Не включать в план", Condition: "условие", Confidence: "medium", EvidenceRefs: []string{"SRC-2"}},
	)
	h.Chapters = append(h.Chapters, ResearchChapter{ID: "CH-2", RequiredClaimIDs: []string{"CLM-2", "CLM-3", "CLM-1"}})
	candidate := "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения. Совет может помочь. Получите награду, кроме повторного захода. Дополнительный ресурс иногда доступен при победе. https://example.org/guide https://example.org/rewards"
	reply := `{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Сохраняйте ресурс","condition_quote":"при слабой позиции","exception_quote":"кроме угрозы поражения","confidence_quote":"может помочь","evidence_refs":["SRC-1"]},{"claim_id":"CLM-2","status":"supported","action_quote":"Получите награду","exception_quote":"кроме повторного захода","evidence_refs":["SRC-2"]},{"claim_id":"CLM-3","status":"supported","action_quote":"Дополнительный ресурс иногда доступен","condition_quote":"при победе","confidence_quote":"иногда","evidence_refs":["SRC-1","SRC-2"]}]}`
	model := &fakeLLM{replies: []string{reply}}
	s := New(model, nil, "fake")
	if _, err := s.factReview(context.Background(), h, candidate); err != nil {
		t.Fatal(err)
	}
	if len(model.messages) != 1 {
		t.Fatalf("unexpected review retry: %d", len(model.messages))
	}
	payload := lastUserJSON(t, model.messages[0])
	before, _ := json.Marshal(h)
	after, _ := json.Marshal(payload["research_handoff"])
	var original any
	if err := json.Unmarshal(before, &original); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(original, payload["research_handoff"]) || payload["candidate"] != candidate {
		t.Fatalf("checklist changed the factual input: %s", after)
	}
	expected := []map[string]any{
		{"claim_id": "CLM-1", "required_quote_fields": []string{"action_quote", "condition_quote", "exception_quote", "confidence_quote"}, "allowed_evidence_refs": []string{"SRC-1"}},
		{"claim_id": "CLM-2", "required_quote_fields": []string{"action_quote", "exception_quote"}, "allowed_evidence_refs": []string{"SRC-2"}},
		{"claim_id": "CLM-3", "required_quote_fields": []string{"action_quote", "condition_quote", "confidence_quote"}, "allowed_evidence_refs": []string{"SRC-1", "SRC-2"}},
	}
	wantJSON, _ := json.Marshal(expected)
	var want any
	if err := json.Unmarshal(wantJSON, &want); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(payload["required_attestations"], want) {
		t.Fatalf("required review fields or source boundaries missing: %#v", payload["required_attestations"])
	}
}
