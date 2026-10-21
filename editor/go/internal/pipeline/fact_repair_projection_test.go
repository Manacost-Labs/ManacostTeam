package pipeline

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
)

func factWithFaultySupportedQuote() string {
	negative := strings.Replace(publicationFact, `"unsupported_claims":[]`, `"unsupported_claims":["Это гарантирует победу."]`, 1)
	return strings.Replace(negative, `"action_quote":"Сохраняйте ресурс"`, `"action_quote":"Сохраняйте весь ресурс"`, 1)
}

func TestWritingRestoresMissingConditionFromCompleteNegativeReview(t *testing.T) {
	bad := strings.Replace(publicationCandidate, " при слабой позиции", "", 1)
	negative := strings.Replace(publicationFact, `"status":"supported"`, `"status":"insufficient"`, 1)
	negative = strings.Replace(negative, `"condition_quote":"при слабой позиции"`, `"condition_quote":""`, 1)
	writer := &fakeLLM{replies: []string{bad, publicationCandidate}}
	reviewer := &fakeLLM{replies: []string{negative, criticJSON("accept"), publicationFact, criticJSON("accept")}}
	s := New(writer, nil, "fake")
	s.Reviewer = reviewer
	r, err := s.Run(context.Background(), Request{Mode: "write", Handoff: readyHandoff()})
	if err != nil || !r.Accepted || r.Text != publicationCandidate || r.Attempts != 2 || len(writer.messages) != 2 || len(reviewer.messages) != 4 {
		t.Fatalf("missing condition never reached automatic repair and fresh review: %+v %v", r, err)
	}
	if _, err := validateFactReview(negative, readyHandoff(), bad); err == nil {
		t.Fatal("negative omission review cannot authorize acceptance")
	}
}

func TestMissingConditionRepairCannotBypassFreshNegativeReview(t *testing.T) {
	bad := strings.Replace(publicationCandidate, " при слабой позиции", "", 1)
	negative := strings.Replace(publicationFact, `"status":"supported"`, `"status":"insufficient"`, 1)
	negative = strings.Replace(negative, `"condition_quote":"при слабой позиции"`, `"condition_quote":""`, 1)
	writer := &fakeLLM{replies: []string{bad, publicationCandidate, publicationCandidate}}
	reviewer := &fakeLLM{replies: []string{negative, criticJSON("accept"), negative, criticJSON("accept"), negative}}
	s := New(writer, nil, "fake")
	s.Reviewer = reviewer
	r, err := s.Run(context.Background(), Request{Mode: "write", Handoff: readyHandoff()})
	if err != nil || r.Accepted || r.Text != "" || r.FactReview != nil || r.Attempts != MaxRepairs+1 || len(reviewer.messages) != 5 {
		t.Fatalf("repair without a fresh positive factual review was accepted: %+v %v", r, err)
	}
}

func TestWritingRepairsGroundedNegativeDespiteFaultySupportedQuote(t *testing.T) {
	bad := publicationCandidate + " Это гарантирует победу."
	writer := &fakeLLM{replies: []string{bad, publicationCandidate}}
	reviewer := &fakeLLM{replies: []string{factWithFaultySupportedQuote(), criticJSON("accept"), publicationFact, criticJSON("accept")}}
	s := New(writer, nil, "fake")
	s.Reviewer = reviewer
	r, err := s.Run(context.Background(), Request{Mode: "write", Handoff: readyHandoff()})
	if err != nil || !r.Accepted || !r.ChecksComplete || r.Text != publicationCandidate || r.Attempts != 2 || r.FactReview == nil || len(r.FactReview.Claims) != 1 {
		t.Fatalf("grounded negative feedback did not reach a full recheck: %+v %v", r, err)
	}
	if len(reviewer.messages) != 4 || lastUserJSON(t, reviewer.messages[2])["candidate"] != publicationCandidate {
		t.Fatal("acceptance must follow a fresh full fact review of the repaired text")
	}
	if len(writer.messages) != 2 {
		t.Fatal("expected one automatic repair")
	}
	var repairEvidence map[string]any
	for _, raw := range lastUserJSON(t, writer.messages[1])["findings"].([]any) {
		finding := raw.(map[string]any)
		if finding["rule_id"] != "handoff_fact_review" {
			continue
		}
		evidence := finding["evidence"].(string)
		if strings.Contains(evidence, "Сохраняйте весь ресурс") {
			t.Fatal("invented supported quote reached repair")
		}
		if err := json.Unmarshal([]byte(evidence), &repairEvidence); err != nil {
			t.Fatal(err)
		}
	}
	if repairEvidence["repair_only"] != true {
		t.Fatal("partial feedback must be explicitly limited to repair", repairEvidence)
	}
	omitted := repairEvidence["omitted_supported_claim_ids"].([]any)
	if len(omitted) != 1 || omitted[0] != "CLM-1" {
		t.Fatal("faulty bookkeeping row was not identified", omitted)
	}
	clean := repairEvidence["sanitized_review"].(map[string]any)
	quotes := clean["unsupported_claims"].([]any)
	if len(quotes) != 1 || quotes[0] != "Это гарантирует победу." || len(clean["claims"].([]any)) != 0 {
		t.Fatal("repair lost the exact negative quote or retained a faulty attestation", clean)
	}
	// The original negative review is still invalid; sanitizing feedback cannot attest it.
	if _, err := validateFactReview(factWithFaultySupportedQuote(), readyHandoff(), bad); err == nil {
		t.Fatal("partial or negative feedback passed the acceptance validator")
	}
}

func TestWritingFaultySupportedQuoteCannotBypassNewNegativeReview(t *testing.T) {
	bad := publicationCandidate + " Это гарантирует победу."
	writer := &fakeLLM{replies: []string{bad}}
	reviewer := &fakeLLM{replies: []string{factWithFaultySupportedQuote(), criticJSON("accept"), factWithFaultySupportedQuote(), criticJSON("accept"), factWithFaultySupportedQuote()}}
	s := New(writer, nil, "fake")
	s.Reviewer = reviewer
	r, err := s.Run(context.Background(), Request{Mode: "write", Handoff: readyHandoff()})
	if err != nil || r.Accepted || r.Text != "" || r.ChecksComplete || r.FactReview != nil || r.Attempts != MaxRepairs+1 || len(writer.messages) != 3 || len(reviewer.messages) != 5 || !strings.Contains(strings.Join(r.RejectionReasons, ","), "fact_review_failed") {
		t.Fatalf("unresolved negative review was accepted or repair budget changed: %+v %v", r, err)
	}
}

func TestWritingPartialFactFeedbackKeepsUnreliableCasesClosed(t *testing.T) {
	negative := factWithFaultySupportedQuote()
	for _, tc := range []struct{ name, review string }{
		{"no_grounded_negative", strings.Replace(negative, `"unsupported_claims":["Это гарантирует победу."]`, `"unsupported_claims":[]`, 1)},
		{"ungrounded_negative_row", strings.Replace(negative, `"status":"supported"`, `"status":"insufficient"`, 1)},
		{"ungrounded_unsupported_quote", strings.Replace(negative, "Это гарантирует победу.", "Это всегда принесёт победу.", 1)},
		{"foreign_reference", strings.Replace(negative, `"SRC-1"`, `"foreign"`, 1)},
		{"missing_required_quote", strings.Replace(negative, `"condition_quote":"при слабой позиции"`, `"condition_quote":""`, 1)},
		{"missing_claim", `{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":["Это гарантирует победу."],"claims":[]}`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			writer := &fakeLLM{replies: []string{publicationCandidate + " Это гарантирует победу."}}
			replies := []string{tc.review}
			if tc.name == "no_grounded_negative" {
				replies = append(replies, tc.review)
			}
			reviewer := &fakeLLM{replies: replies}
			s := New(writer, nil, "fake")
			s.Reviewer = reviewer
			r, err := s.Run(context.Background(), Request{Mode: "write", Handoff: readyHandoff()})
			if err != nil || r.Accepted || r.Text != "" || r.ChecksComplete || len(writer.messages) != 1 || len(reviewer.messages) != len(replies) {
				t.Fatalf("ungrounded or incomplete review authorized repair/acceptance: %+v %v", r, err)
			}
		})
	}
}
