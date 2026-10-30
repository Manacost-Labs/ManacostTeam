package pipeline

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

func TestReaderQuestionClosureRejectsMissingChecks(t *testing.T) {
	h := readyHandoff()
	candidate := h.Claims[0].Meaning + " Совет может помочь. https://example.org/guide"
	model := &fakeLLM{omitReaderQuestionReview: true, replies: []string{criticJSONNoImprovement()}}
	s := New(model, nil, "fake")
	_, err := s.critic(context.Background(), rules.Build(nil, "GUIDE", "", "ru-RU", nil), criticInput{
		Mode: "reconstruct", NewArticle: true, Source: h.VerifiedText(), Candidate: candidate, Handoff: h,
	}, 1)
	if err == nil {
		t.Fatal("critic accepted a writing review without checking required reader questions")
	}
}

const readerDraft = "Сохраняйте ресурс. Это может помочь при слабой позиции, кроме угрозы поражения. https://example.org/guide"
const readerFixed = "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения. Совет может помочь. https://example.org/guide"
const readerFactReview = `{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Сохраняйте ресурс","condition_quote":"при слабой позиции","exception_quote":"кроме угрозы поражения","confidence_quote":"может помочь","evidence_refs":["SRC-1"]}]}`

func readerCheck(status, quote string) ReaderQuestionCheck {
	return ReaderQuestionCheck{QuestionID: "Q-1", Status: status, CandidateQuote: quote, Function: "Помочь выбрать действие с учетом исключения", Reason: "Проверена связь действия с условием; при разрыве связь нужно восстановить", ClaimIDs: []string{"CLM-1"}}
}

func readerCritic(verdict string, checks ...ReaderQuestionCheck) string {
	var raw map[string]any
	_ = json.Unmarshal([]byte(criticJSON(verdict)), &raw)
	raw["reader_question_checks"] = checks
	data, _ := json.Marshal(raw)
	return string(data)
}

func TestReaderQuestionsDriveGroundedRepairAndRecheck(t *testing.T) {
	for _, status := range []string{"unclear", "missing"} {
		t.Run(status, func(t *testing.T) {
			quote := "Сохраняйте ресурс. Это может помочь"
			if status == "missing" {
				quote = ""
			}
			writer := &fakeLLM{replies: []string{readerDraft, readerFixed}}
			reviewer := &fakeLLM{omitReaderQuestionReview: true, replies: []string{
				readerFactReview, readerCritic("repair", readerCheck(status, quote)),
				readerFactReview, readerCritic("accept", readerCheck("answered", "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения.")),
			}}
			s := New(writer, nil, "fake", &scriptedAnalyzer{name: "writing-qa"})
			s.Reviewer = reviewer
			result, err := s.Run(context.Background(), Request{Mode: "write", Handoff: readyHandoff()})
			if err != nil || !result.Accepted || result.Text != readerFixed || result.Attempts != 2 || !result.ChecksComplete || result.FactReview == nil {
				t.Fatalf("grounded question repair did not close: %+v %v", result, err)
			}
			if len(writer.messages) != 2 || len(reviewer.messages) != 4 {
				t.Fatalf("new model stages introduced: writer=%d reviewer=%d", len(writer.messages), len(reviewer.messages))
			}
			if len(result.ReaderQuestionChecks) != 1 || result.ReaderQuestionChecks[0].Status != "answered" || len(result.PracticeChecks) != 26 {
				t.Fatal("final closure or existing practice coverage missing", result)
			}
			for _, messages := range writer.messages {
				payload := lastUserJSON(t, messages)
				if payload["required_reader_questions"] == nil || payload["condition_ledger"] == nil {
					t.Fatal("writer/repair lost questions or grounded conditions", payload)
				}
			}
			repair := lastUserJSON(t, writer.messages[1])
			findings := findingsOf(t, repair, "findings")
			if len(findings) != 1 || findings[0]["rule_id"] != "reader_question.Q-1" || repair["candidate"] != readerDraft {
				t.Fatal("question failure was not the exact repair target", repair)
			}
			if status == "missing" && !strings.Contains(findings[0]["evidence"].(string), `"repair_only":true`) {
				t.Fatal("missing answer borrowed a candidate quotation", findings)
			}
			if lastUserJSON(t, reviewer.messages[3])["candidate"] != readerFixed {
				t.Fatal("closure reused the old draft instead of reviewing the repair")
			}
		})
	}
}

func TestReaderQuestionReviewRejectsBadEvidenceAndCoverage(t *testing.T) {
	in := criticInput{Mode: "reconstruct", Handoff: readyHandoff(), Candidate: readerFixed}
	valid := func() criticResult {
		return criticResult{Verdict: "accept", ReaderQuestionChecks: []ReaderQuestionCheck{readerCheck("answered", "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения.")}}
	}
	for name, mutate := range map[string]func(*criticResult){
		"missing row": func(r *criticResult) { r.ReaderQuestionChecks = nil },
		"duplicate row": func(r *criticResult) {
			r.ReaderQuestionChecks = append(r.ReaderQuestionChecks, r.ReaderQuestionChecks[0])
		},
		"unknown question": func(r *criticResult) { r.ReaderQuestionChecks[0].QuestionID = "Q-foreign" },
		"foreign claim":    func(r *criticResult) { r.ReaderQuestionChecks[0].ClaimIDs = []string{"CLM-foreign"} },
		"duplicate claim":  func(r *criticResult) { r.ReaderQuestionChecks[0].ClaimIDs = []string{"CLM-1", "CLM-1"} },
		"missing claim":    func(r *criticResult) { r.ReaderQuestionChecks[0].ClaimIDs = nil },
		"invented quote": func(r *criticResult) {
			r.ReaderQuestionChecks[0].CandidateQuote = "Всегда тратьте ресурс."
		},
		"empty quote":         func(r *criticResult) { r.ReaderQuestionChecks[0].CandidateQuote = "" },
		"empty function":      func(r *criticResult) { r.ReaderQuestionChecks[0].Function = " " },
		"empty reason":        func(r *criticResult) { r.ReaderQuestionChecks[0].Reason = "" },
		"noncanonical status": func(r *criticResult) { r.ReaderQuestionChecks[0].Status = "clear" },
		"accept unclear":      func(r *criticResult) { r.ReaderQuestionChecks[0].Status = "unclear" },
		"accept missing": func(r *criticResult) {
			r.ReaderQuestionChecks[0].Status = "missing"
			r.ReaderQuestionChecks[0].CandidateQuote = ""
		},
		"missing borrowed quote": func(r *criticResult) { r.Verdict = "repair"; r.ReaderQuestionChecks[0].Status = "missing" },
	} {
		t.Run(name, func(t *testing.T) {
			r := valid()
			mutate(&r)
			if err := applyReaderQuestionReview(in, &r); err == nil || len(r.Findings) != 0 {
				t.Fatalf("invalid review became evidence or repair target: %+v %v", r, err)
			}
		})
	}
}

func TestReaderQuestionsAllowSharedAnswerAndRespectQuestionClaims(t *testing.T) {
	h := readyHandoff()
	h.Claims = append(h.Claims, ResearchClaim{ID: "CLM-2", Meaning: "Вторая проверенная мысль"})
	h.Decisions = append(h.Decisions,
		DecisionQuestion{ID: "Q-2", Required: true, ChapterID: "CH-1", Question: "Какое исключение?", ClaimIDs: []string{"CLM-1"}},
		DecisionQuestion{ID: "Q-optional", Required: false, ChapterID: "CH-1", ClaimIDs: []string{"CLM-2"}},
	)
	in := criticInput{Mode: "reconstruct", Handoff: h, Candidate: readerFixed}
	checks := []ReaderQuestionCheck{readerCheck("answered", readerFixed), readerCheck("answered", readerFixed)}
	checks[1].QuestionID = "Q-2"
	out := criticResult{Verdict: "accept", ReaderQuestionChecks: checks}
	if err := applyReaderQuestionReview(in, &out); err != nil {
		t.Fatal("shared answer or optional question rejected", err)
	}
	checks[1].ClaimIDs = []string{"CLM-2"}
	if err := applyReaderQuestionReview(in, &out); err == nil {
		t.Fatal("claim known to handoff but unrelated to question accepted")
	}
}

func TestReaderQuestionRepairRemainsBounded(t *testing.T) {
	negative := readerCritic("repair", readerCheck("unclear", "Сохраняйте ресурс."))
	writer := &fakeLLM{replies: []string{readerDraft}}
	reviewer := &fakeLLM{omitReaderQuestionReview: true, replies: []string{readerFactReview, negative, readerFactReview, negative, readerFactReview, negative}}
	s := New(writer, nil, "fake", &scriptedAnalyzer{name: "writing-qa"})
	s.Reviewer = reviewer
	result, err := s.Run(context.Background(), Request{Mode: "write", Handoff: readyHandoff()})
	if err != nil || result.Accepted || result.Text != "" || result.Attempts != 1+MaxRepairs || len(writer.messages) != 1+MaxRepairs || len(reviewer.messages) != 2*(1+MaxRepairs) || !strings.Contains(strings.Join(result.RejectionReasons, " "), ReasonRepairExhausted) {
		t.Fatalf("unclosed question escaped repair budget: %+v %v", result, err)
	}
}

func TestReaderQuestionInvalidReviewUsesOnlyExistingRetryBudget(t *testing.T) {
	writer := &fakeLLM{replies: []string{readerFixed}}
	bad := readerCritic("accept", readerCheck("answered", "Выдуманная цитата."))
	reviewer := &fakeLLM{omitReaderQuestionReview: true, replies: []string{readerFactReview, bad, bad}}
	s := New(writer, nil, "fake", &scriptedAnalyzer{name: "writing-qa"})
	s.Reviewer = reviewer
	result, err := s.Run(context.Background(), Request{Mode: "write", Handoff: readyHandoff()})
	if err != nil || result.Accepted || result.ChecksComplete || len(writer.messages) != 1 || len(reviewer.messages) != 2+s.criticRetries() || !strings.Contains(strings.Join(result.RejectionReasons, " "), ReasonCriticInvalid) {
		t.Fatalf("invalid evidence authorized repair/acceptance: %+v %v", result, err)
	}
}

func TestReaderQuestionCorrectedJSONIsValidatedBeforeAcceptance(t *testing.T) {
	writer := &fakeLLM{replies: []string{readerFixed}}
	bad := readerCritic("accept", readerCheck("answered", "Выдуманная цитата."))
	good := readerCritic("accept", readerCheck("answered", readerFixed))
	reviewer := &fakeLLM{omitReaderQuestionReview: true, replies: []string{readerFactReview, bad, good}}
	s := New(writer, nil, "fake", &scriptedAnalyzer{name: "writing-qa"})
	s.Reviewer = reviewer
	result, err := s.Run(context.Background(), Request{Mode: "write", Handoff: readyHandoff()})
	if err != nil || !result.Accepted || !result.ChecksComplete || result.Attempts != 1 || len(writer.messages) != 1 || len(reviewer.messages) != 3 {
		t.Fatalf("corrected grounded review did not use the existing JSON retry: %+v %v", result, err)
	}
	if len(result.ReaderQuestionChecks) != 1 || result.ReaderQuestionChecks[0].CandidateQuote != readerFixed {
		t.Fatal("final result retained the invalid first review", result)
	}
}

func TestReaderQuestionLongRepairPreservesUntargetedProse(t *testing.T) {
	untouched := "\n\n" + strings.Repeat("Полезное объяснение с условием остается на месте. ", 100)
	draft, fixed := readerDraft+untouched, readerFixed+untouched
	index := 0
	patch, err := json.Marshal(map[string]any{"edits": []reconstructionPatch{{FindingIndex: &index, Before: readerDraft, After: readerFixed}}})
	if err != nil {
		t.Fatal(err)
	}
	for _, status := range []string{"unclear", "missing"} {
		t.Run(status, func(t *testing.T) {
			quote := readerDraft
			if status == "missing" {
				quote = ""
			}
			writer := &fakeLLM{replies: []string{draft, string(patch)}}
			reviewer := &fakeLLM{omitReaderQuestionReview: true, replies: []string{
				readerFactReview, readerCritic("repair", readerCheck(status, quote)),
				readerFactReview, readerCritic("accept", readerCheck("answered", readerFixed)),
			}}
			s := New(writer, nil, "fake", &scriptedAnalyzer{name: "writing-qa"})
			s.Reviewer = reviewer
			result, err := s.Run(context.Background(), Request{Mode: "write", Handoff: readyHandoff()})
			if err != nil || !result.Accepted || result.Text != fixed || result.Attempts != 2 {
				t.Fatalf("question repair failed to preserve untargeted prose: %+v %v", result, err)
			}
			payload := lastUserJSON(t, writer.messages[1])
			raw, err := json.Marshal(payload["repair_targets"])
			if err != nil {
				t.Fatal(err)
			}
			var targets []reconstructionTarget
			if err := json.Unmarshal(raw, &targets); err != nil || len(targets) != 1 || targets[0].RuleID != "reader_question.Q-1" {
				t.Fatal("question failure lost local patch target", payload)
			}
			if (status == "missing" && len(targets[0].Quotes) != 0) || (status == "unclear" && (len(targets[0].Quotes) != 1 || targets[0].Quotes[0] != quote)) {
				t.Fatal("patch grounding disagrees with reader evidence", targets)
			}
			if lastUserJSON(t, reviewer.messages[2])["candidate"] != fixed || lastUserJSON(t, reviewer.messages[3])["candidate"] != fixed {
				t.Fatal("patched text skipped fresh factual or reader review")
			}
		})
	}
}

func TestReaderQuestionsAreNotInventedForEditing(t *testing.T) {
	for _, mode := range []string{"edit", "rewrite", "proofread", "facts_only"} {
		out := criticResult{Verdict: "accept"}
		if err := applyReaderQuestionReview(criticInput{Mode: mode}, &out); err != nil || readerQuestionReviewInstruction(mode) != "" {
			t.Fatalf("%s unexpectedly requires a question plan: %v", mode, err)
		}
	}
}

func TestReaderQuestionPatchAnchorsIgnoreQuotedReviewProse(t *testing.T) {
	candidate := "Синий маршрут описан в соседнем разделе.\n\nЗдесь требуется объяснение выбора.\n\n" + strings.Repeat("Остальной текст сохраняется. ", 100)
	h := readyHandoff()
	h.Decisions[0].Question = "Когда выбирать «Синий маршрут»?"
	for _, status := range []string{"missing", "unclear"} {
		t.Run(status, func(t *testing.T) {
			quote := "Здесь требуется объяснение выбора."
			if status == "missing" {
				quote = ""
			}
			check := readerCheck(status, quote)
			check.Reason = "Нужно объяснить выбор, а не повторить «Синий маршрут»."
			check.Function = "Объяснение выбора «Синий маршрут»."
			out := criticResult{Verdict: "repair", ReaderQuestionChecks: []ReaderQuestionCheck{check}}
			if err := applyReaderQuestionReview(criticInput{Mode: "reconstruct", Handoff: h, Candidate: candidate}, &out); err != nil {
				t.Fatal(err)
			}
			targets := reconstructionTargets(candidate, out.Findings)
			if status == "missing" && len(targets[0].Quotes) != 0 {
				t.Fatal("missing answer borrowed an anchor from the review prose", targets)
			}
			if status == "unclear" && (len(targets[0].Quotes) != 1 || targets[0].Quotes[0] != quote) {
				t.Fatal("review prose expanded the validated unclear evidence", targets)
			}
			patch := `{"edits":[{"finding_index":0,"before":"Здесь требуется объяснение выбора.","after":"Здесь уточнено объяснение выбора."}]}`
			if got, err := applyReconstructionPatches(candidate, patch, targets); err != nil || got == candidate {
				t.Fatal("valid local repair was pinned to unrelated review prose", err)
			}
			if status == "unclear" {
				foreign := `{"edits":[{"finding_index":0,"before":"Синий маршрут","after":"Другой маршрут"}]}`
				if got, err := applyReconstructionPatches(candidate, foreign, targets); err == nil || got != candidate {
					t.Fatal("unrelated quoted review prose authorized a patch")
				}
			}
		})
	}
}
