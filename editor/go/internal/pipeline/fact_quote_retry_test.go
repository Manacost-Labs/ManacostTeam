package pipeline

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
)

func TestPositiveReviewWithInvalidLiteralQuoteGetsOneGroundingRetry(t *testing.T) {
	h := readyHandoff()
	candidate := "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения. Совет может помочь. https://example.org/guide"
	good := `{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Сохраняйте ресурс","condition_quote":"при слабой позиции","exception_quote":"кроме угрозы поражения","confidence_quote":"может помочь","evidence_refs":["SRC-1"]}]}`
	for _, field := range []string{"action_quote", "condition_quote", "exception_quote", "confidence_quote"} {
		var bad map[string]any
		_ = json.Unmarshal([]byte(good), &bad)
		bad["claims"].([]any)[0].(map[string]any)[field] = "Несуществующая цитата"
		raw, _ := json.Marshal(bad)
		m := &fakeLLM{replies: []string{string(raw), good}}
		s := New(m, nil, "fake")
		review, err := s.factReview(context.Background(), h, candidate)
		if err != nil || len(review.Claims) != 1 || len(m.messages) != 2 {
			t.Fatalf("%s rejected positive review without a grounding retry: %v", field, err)
		}
		retry := m.messages[1]
		if !strings.Contains(retry[len(retry)-1].Content, "insufficient") || lastUserJSON(t, m.messages[0])["candidate"] != candidate {
			t.Fatal("retry may bless a missing fact or rewrite candidate")
		}
		m = &fakeLLM{replies: []string{string(raw), string(raw), good}}
		s = New(m, nil, "fake")
		if _, err = s.factReview(context.Background(), h, candidate); err == nil || len(m.messages) != 2 {
			t.Fatal("invalid literal attestation accepted or retried indefinitely")
		}
	}
}

func TestGroundingRetryNeverRevotesNegativeOrIncompleteReview(t *testing.T) {
	h := readyHandoff()
	candidate := "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения. Совет может помочь. https://example.org/guide"
	for _, raw := range []string{
		`{"candidate_checked":true,"confidence_preserved":false,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Не цитата"}]}`,
		`{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":["Ошибка"],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Не цитата"}]}`,
		`{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"insufficient","action_quote":"Не цитата"}]}`,
		`{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Не цитата"},{"claim_id":"FOREIGN","status":"insufficient"}]}`,
	} {
		m := &fakeLLM{replies: []string{raw}}
		s := New(m, nil, "fake")
		if _, err := s.factReview(context.Background(), h, candidate); err == nil || len(m.messages) != 1 {
			t.Fatal("negative or incomplete review was revoted", raw)
		}
	}
}

func TestGroundingRetryCanDiscoverMissingConditionWithoutAcceptingIt(t *testing.T) {
	h := readyHandoff()
	candidate := "Сохраняйте ресурс. https://example.org/guide"
	positiveWithInventedCondition := `{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Сохраняйте ресурс","condition_quote":"при слабой позиции","exception_quote":"кроме угрозы поражения","confidence_quote":"может помочь","evidence_refs":["SRC-1"]}]}`
	negative := `{"candidate_checked":true,"confidence_preserved":false,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"insufficient","action_quote":"Сохраняйте ресурс","condition_quote":"","exception_quote":"","confidence_quote":"","evidence_refs":["SRC-1"]}]}`
	m := &fakeLLM{replies: []string{positiveWithInventedCondition, negative}}
	s := New(m, nil, "fake")
	review, err := s.factReview(context.Background(), h, candidate)
	if err == nil || len(m.messages) != 2 || review.Claims[0].Status != "insufficient" || review.ConfidencePreserved == nil || *review.ConfidencePreserved {
		t.Fatal("grounding retry hid a missing condition or certainty loss", review, err)
	}
}
