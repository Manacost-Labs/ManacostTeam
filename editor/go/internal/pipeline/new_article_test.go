package pipeline

import (
	"context"
	"strings"
	"testing"
)

func TestNewArticleDoesNotRequireEditingProofAgainstFactLedger(t *testing.T) {
	h := nameFormHandoff()
	candidate := "Северная Империя отмечает праздник осенью. https://example.org/guide"
	fact := `{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Северная Империя отмечает праздник осенью.","condition_quote":"","exception_quote":"","confidence_quote":"","evidence_refs":["SRC-1"]}]}`
	for _, input := range []struct{ draft, previous string }{{}, {draft: "Исходная статья."}, {previous: candidate}} {
		s := New(&fakeLLM{replies: []string{candidate}}, nil, "fake", &scriptedAnalyzer{name: "full-writing-qa"})
		reviewer := &fakeLLM{replies: []string{fact, criticJSONNoImprovement()}}
		s.Reviewer = reviewer
		result, err := s.Run(context.Background(), Request{Mode: "write", Text: input.draft, CandidateText: input.previous, Handoff: h})
		if input.previous != "" {
			if err == nil {
				t.Fatal("writing accepted a prepared candidate through the authoring path")
			}
			continue
		}
		if err != nil {
			t.Fatal(err)
		}
		if input.draft == "" && input.previous == "" {
			if !result.Accepted || result.Text != candidate || !result.ChecksComplete || result.FactCheckPassed == nil || !*result.FactCheckPassed {
				t.Fatalf("new article compared as editing a ledger: %+v", result)
			}
			if lastUserJSON(t, reviewer.messages[1])["new_article"] != true {
				t.Fatal("critic not told there is no draft")
			}
		} else if result.Accepted || !strings.Contains(strings.Join(result.RejectionReasons, " "), ReasonNoImprovement) {
			t.Fatalf("existing draft lost improvement requirement: %+v", result)
		}
	}
}

func TestNewArticleWithoutEditingProofStillNeedsPositiveCritic(t *testing.T) {
	h := nameFormHandoff()
	candidate := "Северная Империя отмечает праздник осенью. https://example.org/guide"
	fact := `{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Северная Империя отмечает праздник осенью.","condition_quote":"","exception_quote":"","confidence_quote":"","evidence_refs":["SRC-1"]}]}`
	s := New(&fakeLLM{replies: []string{candidate}}, nil, "fake", &scriptedAnalyzer{name: "full-writing-qa"})
	s.Reviewer = &fakeLLM{replies: []string{fact, criticJSON("reject")}}
	result, err := s.Run(context.Background(), Request{Mode: "write", Handoff: h})
	if err != nil {
		t.Fatal(err)
	}
	if result.Accepted || result.Text != "" || result.FactCheckPassed == nil || !*result.FactCheckPassed || !strings.Contains(strings.Join(result.RejectionReasons, " "), ReasonCriticRejected) {
		t.Fatalf("new article bypassed critic veto: %+v", result)
	}
}

func TestNewArticleCriticContractKeepsBlockingFindingsAndFactGates(t *testing.T) {
	for _, fragment := range []string{"new_article=true", "необязательные улучшения", "существенная", "все восемь"} {
		if !strings.Contains(criticInstruction, fragment) {
			t.Fatalf("missing critic decision contract: %s", fragment)
		}
	}
}
