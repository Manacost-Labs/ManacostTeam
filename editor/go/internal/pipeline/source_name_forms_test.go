package pipeline

import (
	"context"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/guards"
)

func nameFormHandoff() *ResearchHandoff {
	h := readyHandoff()
	h.Claims[0].Meaning = "Праздник Северной Империи начинается осенью."
	h.Claims[0].Action = h.Claims[0].Meaning
	h.Claims[0].Condition, h.Claims[0].Exception = "", ""
	h.Claims[0].Confidence, h.Claims[0].Status = "high", "supported"
	h.Sources[0].Quote = "Северная Империя отмечает праздник осенью. Южная Республика открывает 99 павильонов. https://unapproved.example.org/"
	h.Sources = append(h.Sources, ResearchSource{ID: "UNUSED", URL: "https://example.org/unused", Quote: "Восточная Федерация"})
	return h
}

func TestWritingAllowsExactReferencedSourceNamesWithoutAuthorizingNumbersOrLinks(t *testing.T) {
	h := nameFormHandoff()
	if err := h.Validate(); err != nil {
		t.Fatal(err)
	}
	before := h.VerifiedText()
	forms := h.sourceNameForms()
	if reconstructionGuard(before, "Северная Империя", forms...).HasHardChanges() {
		t.Fatal("exact name present in cited source was rejected")
	}
	for _, candidate := range []string{"Северной Империей", "Восточная Федерация", "Западная Республика", "99", "[Источник](https://unapproved.example.org/)"} {
		if !reconstructionGuard(before, candidate, forms...).HasHardChanges() {
			t.Fatalf("unapproved form or non-name admitted: %s", candidate)
		}
	}
	if !reconstructionGuard(before, "Северная Империя").HasHardChanges() || !guards.Compare(before, "Северная Империя").HasHardChanges() {
		t.Fatal("ordinary entity protection was weakened")
	}
	if before != h.VerifiedText() {
		t.Fatal("source names changed factual baseline")
	}
}

func TestReferencedSourceNameCannotBypassWritingFactReview(t *testing.T) {
	h := nameFormHandoff()
	candidate := "Южная Республика открывает павильоны. [Источник](https://example.org/guide)"
	if reconstructionGuard(h.VerifiedText(), candidate, h.sourceNameForms()...).HasHardChanges() {
		t.Fatal("test must reach fact review after exact source name allowance")
	}
	negative := `{"candidate_checked":false,"confidence_preserved":true,"unsupported_claims":["Южная Республика открывает павильоны."],"claims":[{"claim_id":"CLM-1","status":"insufficient","action_quote":"Южная Республика открывает павильоны.","condition_quote":"","exception_quote":"","confidence_quote":"","evidence_refs":["SRC-1"]}]}`
	s := New(&fakeLLM{replies: []string{candidate}}, nil, "fake", &scriptedAnalyzer{name: "full-writing-qa"})
	reviewer := &fakeLLM{replies: []string{negative, criticJSON("accept"), negative, criticJSON("accept"), negative}}
	s.Reviewer = reviewer
	result, err := s.Run(context.Background(), Request{Mode: "write", Handoff: h})
	if err != nil {
		t.Fatal(err)
	}
	if result.Accepted || result.Text != "" || (result.FactCheckPassed != nil && *result.FactCheckPassed) || len(reviewer.messages) != 5 || result.Attempts != MaxRepairs+1 || !strings.Contains(strings.Join(result.RejectionReasons, " "), "fact_review_failed") {
		t.Fatalf("source name bypassed complete factual review: %+v", result)
	}
}

func TestWritingUsesSourceNameFormsWithCompleteReviewAndUnchangedBaseline(t *testing.T) {
	h := nameFormHandoff()
	candidate := "Северная Империя отмечает праздник осенью. [Источник](https://example.org/guide)"
	fact := `{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Северная Империя отмечает праздник осенью.","condition_quote":"","exception_quote":"","confidence_quote":"","evidence_refs":["SRC-1"]}]}`
	qa := &scriptedAnalyzer{name: "full-writing-qa"}
	s := New(&fakeLLM{replies: []string{candidate}}, nil, "fake", qa)
	s.Reviewer = &fakeLLM{replies: []string{fact, criticJSON("accept")}}
	result, err := s.Run(context.Background(), Request{Mode: "write", Handoff: h})
	if err != nil || !result.Accepted || !result.ChecksComplete || result.Text != candidate || result.FactCheckPassed == nil || !*result.FactCheckPassed {
		t.Fatalf("source form did not survive the complete writing path: %+v %v", result, err)
	}
	if len(qa.inputs) != 1 || qa.inputs[0].Before != h.VerifiedText() || strings.Contains(qa.inputs[0].Before, "99") {
		t.Fatal("source-only facts leaked into the numeric/semantic QA baseline", qa.inputs)
	}
}
