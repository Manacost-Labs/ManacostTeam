package pipeline

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzers"
)

const wholeFactMissing = `{"candidate_checked":true,"confidence_preserved":false,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"insufficient","action_quote":"","condition_quote":"","exception_quote":"","confidence_quote":"","evidence_refs":["SRC-1"]}]}`

func TestWholeMissingFactReachesRepairButStillNeedsFreshCompleteReview(t *testing.T) {
	bad := "Вводная заметка. https://example.org/guide"
	for _, repairedReview := range []string{publicationFact, wholeFactMissing} {
		writer := &fakeLLM{replies: []string{bad, publicationCandidate}}
		reviewer := &fakeLLM{replies: []string{wholeFactMissing, criticJSON("accept"), repairedReview, criticJSON("accept"), repairedReview}}
		s := New(writer, nil, "fake")
		s.Reviewer = reviewer
		r, err := s.Run(context.Background(), Request{Mode: "write", Handoff: readyHandoff()})
		if err != nil {
			t.Fatal(err)
		}
		if repairedReview == publicationFact {
			if !r.Accepted || r.Text != publicationCandidate || r.Attempts != 2 || len(writer.messages) != 2 {
				t.Fatalf("omitted fact never repaired: %+v", r)
			}
		} else if r.Accepted || r.Text != "" || r.Attempts != MaxRepairs+1 {
			t.Fatalf("missing-fact feedback bypassed fresh positive review: %+v", r)
		}
	}
}

func TestMissingFactAndFaultyPositiveQuoteKeepSeparateRepairTargets(t *testing.T) {
	h := readyHandoff()
	second := h.Claims[0]
	second.ID = "CLM-2"
	h.Claims = append(h.Claims, second)
	h.Chapters[0].RequiredClaimIDs = append(h.Chapters[0].RequiredClaimIDs, second.ID)
	var review FactReview
	_ = json.Unmarshal([]byte(wholeFactMissing), &review)
	var supported FactReview
	_ = json.Unmarshal([]byte(factWithFaultySupportedQuote()), &supported)
	supported.Claims[0].ClaimID = second.ID
	review.Claims = append(review.Claims, supported.Claims[0])
	fs := factRepairFindings(h, "Вводная заметка.", review, context.Canceled)
	if len(fs) != 1 || fs[0].RuleID != "handoff_missing_claim" || strings.Contains(fs[0].Evidence, "Сохраняйте весь ресурс") || !strings.Contains(fs[0].Evidence, `"CLM-2"`) {
		t.Fatal("mixed bookkeeping lost the omission or leaked a faulty quote", fs)
	}
	review.Claims[1].ClaimID = "CLM-1"
	if len(factRepairFindings(h, "Вводная заметка.", review, context.Canceled)) != 0 {
		t.Fatal("duplicate row authorized repair")
	}
}

func TestWritingRepairsCopyGrammarThenRechecksFacts(t *testing.T) {
	h := readyHandoff()
	h.Claims[0].Meaning = "Оставляйте 2-ю копию при слабой позиции, кроме угрозы поражения."
	h.Claims[0].Action = "Оставляйте 2-ю копию"
	good := h.Claims[0].Meaning + " Это может помочь. https://example.org/guide"
	bad := strings.Replace(good, "2-ю", "2", 1)
	goodFact := strings.Replace(publicationFact, "Сохраняйте ресурс", "Оставляйте 2-ю копию", 1)
	badFact := strings.Replace(goodFact, "2-ю", "2", 1)
	writer := &fakeLLM{replies: []string{bad, good}}
	reviewer := &fakeLLM{replies: []string{badFact, criticJSON("accept"), goodFact, criticJSON("accept")}}
	s := New(writer, nil, "fake", analyzers.NativeGoAnalyzer{})
	s.Reviewer = reviewer
	r, err := s.Run(context.Background(), Request{Mode: "write", Handoff: h})
	if err != nil || !r.Accepted || r.Text != good || r.Attempts != 2 || len(writer.messages) != 2 || len(reviewer.messages) != 4 {
		t.Fatalf("grammar not repaired through full factual recheck: %+v %v", r, err)
	}
}

func TestMissingFactProjectionDoesNotInventCandidateAnchor(t *testing.T) {
	h := readyHandoff()
	var review FactReview
	_ = json.Unmarshal([]byte(wholeFactMissing), &review)
	_, cause := validateFactReview(wholeFactMissing, h, "Вводная заметка.")
	fs := factRepairFindings(h, "Вводная заметка.", review, cause)
	if len(fs) == 0 {
		t.Fatal("valid missing-fact feedback was dropped")
	}
	found := false
	for i, f := range fs {
		if f.RuleID != "handoff_missing_claim" {
			continue
		}
		found = true
		if !strings.Contains(f.Evidence, `"repair_only":true`) || !strings.Contains(f.Evidence, `"claim_id":"CLM-1"`) || len(reconstructionTargets("Вводная заметка.", fs)[i].Quotes) != 0 {
			t.Fatal("omission acquired a fabricated candidate anchor", f)
		}
	}
	if !found {
		t.Fatal("omission lacks its own unconstrained insertion target")
	}
}

func TestMissingFactFeedbackRejectsUnreliableNegativeRows(t *testing.T) {
	for _, raw := range []string{
		strings.Replace(wholeFactMissing, `"action_quote":"",`, ``, 1),
		strings.Replace(wholeFactMissing, `"action_quote":""`, `"action_quote":null`, 1),
		strings.Replace(wholeFactMissing, `"insufficient"`, `"contradicted"`, 1),
		strings.Replace(wholeFactMissing, `"SRC-1"`, `"FOREIGN"`, 1),
		strings.Replace(wholeFactMissing, `"candidate_checked":true`, `"candidate_checked":false`, 1),
		strings.Replace(wholeFactMissing, `"action_quote":""`, `"action_quote":"Выдуманная цитата"`, 1),
		`{"candidate_checked":true,"confidence_preserved":false,"unsupported_claims":[],"claims":[]}`,
	} {
		var review FactReview
		_ = json.Unmarshal([]byte(raw), &review)
		_, cause := validateFactReview(raw, readyHandoff(), "Вводная заметка.")
		if cause == nil || len(factRepairFindings(readyHandoff(), "Вводная заметка.", review, cause)) != 0 {
			t.Fatal("unreliable omission authorized repair", raw)
		}
	}
}
