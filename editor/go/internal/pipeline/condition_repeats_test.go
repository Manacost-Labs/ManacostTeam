package pipeline

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

func repeatHandoff() *ResearchHandoff {
	h := readyHandoff()
	h.Sources[0].Quote = `{"id":"CARD1","name":"Ученица"}`
	h.Claims[0].Meaning = "Разыгрывайте Ученицу при пустом столе противника, кроме хода с летальным уроном."
	h.Claims[0].Action = "Разыгрывайте Ученицу"
	h.Claims[0].Condition = "при пустом столе противника"
	h.Claims[0].Exception = "кроме хода с летальным уроном"
	return h
}

const repeatCandidate = "Разыгрывайте Ученицу при пустом столе противника, кроме хода с летальным уроном.\n\n## Вывод\n\nВсегда разыгрывайте Ученицей начинать партию. В колоде две Ученицы."

func TestConditionRepeatsFindEveryInflectedMention(t *testing.T) {
	got := conditionRepeats(repeatHandoff(), repeatCandidate)["CLM-1"]
	if len(got) != 3 || !strings.HasPrefix(got[1], "Всегда") || !strings.HasPrefix(got[2], "В колоде") {
		t.Fatalf("all three mentions must be assessed: %q", got)
	}
	if conditionRepeats(repeatHandoff(), "Разыгрывайте Ученицу при пустом столе противника, кроме хода с летальным уроном.") != nil {
		t.Fatal("a single mention is covered by condition_quote")
	}
}

func repeatReview(repeats []RepeatAttestation) FactReview {
	yes := true
	return FactReview{CandidateChecked: &yes, ConfidencePreserved: &yes, UnsupportedClaims: []string{}, Claims: []FactAttestation{{ClaimID: "CLM-1", Status: "supported", Repeats: repeats}}}
}

func TestLostConditionInRepeatIsGroundedNegative(t *testing.T) {
	h := repeatHandoff()
	review := repeatReview([]RepeatAttestation{
		{Quote: "Разыгрывайте Ученицу при пустом столе", SameAdvice: true, ConditionKept: true},
		{Quote: "Всегда разыгрывайте Ученицей", SameAdvice: true, ConditionKept: false},
		{Quote: "В колоде две Ученицы", SameAdvice: false},
	})
	err := validateConditionRepeats(review, h, repeatCandidate)
	var quoteErr *factQuoteError
	if err == nil || errors.As(err, &quoteErr) || !strings.Contains(err.Error(), "Всегда разыгрывайте") {
		t.Fatalf("an unconditional repeat must be a repair target: %v", err)
	}
	item := &review.Claims[0]
	item.ActionQuote, item.ConditionQuote = "Разыгрывайте Ученицу", "при пустом столе противника"
	item.ExceptionQuote, item.ConfidenceQuote = "кроме хода с летальным уроном", "при пустом столе противника"
	item.EvidenceRefs = []string{"SRC-1"}
	findings := factRepairFindings(h, repeatCandidate, review, err)
	if len(findings) != 1 || !strings.Contains(findings[0].Message, "Всегда разыгрывайте") {
		t.Fatalf("the lost repeat must reach repair: %+v", findings)
	}
	review.Claims[0].Repeats[1].ConditionKept = true
	if err := validateConditionRepeats(review, h, repeatCandidate); err != nil {
		t.Fatal(err)
	}
}

func TestUnassessedRepeatNeedsGroundingCorrection(t *testing.T) {
	review := repeatReview([]RepeatAttestation{{Quote: "Разыгрывайте Ученицу при пустом столе", SameAdvice: true, ConditionKept: true}})
	var quoteErr *factQuoteError
	if err := validateConditionRepeats(review, repeatHandoff(), repeatCandidate); !errors.As(err, &quoteErr) {
		t.Fatalf("a skipped repeat is a bookkeeping error: %v", err)
	}
}

func TestFactReviewReceivesConditionRepeats(t *testing.T) {
	m := &fakeLLM{replies: []string{"{}", "{}"}}
	_, _ = New(m, nil, "fake").factReview(context.Background(), repeatHandoff(), repeatCandidate)
	var payload map[string]any
	if err := json.Unmarshal([]byte(m.messages[0][1].Content), &payload); err != nil {
		t.Fatal(err)
	}
	if rows, ok := payload["condition_repeats"].(map[string]any)["CLM-1"].([]any); !ok || len(rows) != 3 {
		t.Fatalf("reviewer must get every repeat: %v", payload["condition_repeats"])
	}
	if !strings.Contains(m.messages[0][0].Content, "same_advice") {
		t.Fatal("reviewer must get the repeats schema")
	}
}
