package pipeline

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzer"
	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

func TestEchoIsReviewedInOneRegionWithoutMergingAnotherSentence(t *testing.T) {
	source := "После релиза набора для режима появятся первые изменения. Правила события остаются прежними. Награда будет выдана завтра."
	candidate := "Для режима выйдут первые изменения после выхода набора. Правила события остаются прежними. Награду выдадут завтра."
	edits := localEdits(source, candidate)
	counts := map[string]int{}
	for _, e := range edits {
		for _, echo := range e.Echoes {
			counts[echo.Quote]++
			if strings.Contains(e.After, "Награду") {
				t.Fatal("echo joined an unrelated sentence")
			}
		}
	}
	if len(counts) == 0 {
		t.Fatal("fixture did not exercise an introduced echo")
	}
	for quote, count := range counts {
		if count != 1 {
			t.Fatalf("one echo has %d competing reviews: %s", count, quote)
		}
	}
}

func TestWritingRepairsGroundedFactFeedbackAndRechecksBeforeAccepting(t *testing.T) {
	h := readyHandoff()
	good := "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения. Совет может помочь. [Источник](https://example.org/guide)"
	bad := good + " Это гарантирует победу."
	fact := `{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Сохраняйте ресурс","condition_quote":"при слабой позиции","exception_quote":"кроме угрозы поражения","confidence_quote":"может помочь","evidence_refs":["SRC-1"]}]}`
	invalidFact := strings.Replace(fact, `"unsupported_claims":[]`, `"unsupported_claims":["Это гарантирует победу."]`, 1)
	writer := &fakeLLM{replies: []string{bad, good}}
	reviewer := &fakeLLM{replies: []string{invalidFact, fact, criticJSON("accept")}}
	qa := &scriptedAnalyzer{name: "all-written-prose"}
	s := New(writer, nil, "fake", qa)
	s.Reviewer = reviewer
	r, err := s.Run(context.Background(), Request{Mode: "write", Handoff: h})
	if err != nil || !r.Accepted || !r.ChecksComplete || r.Text != good || r.Attempts != 2 || r.FactReview == nil {
		t.Fatalf("grounded fact correction was not rechecked: %+v %v", r, err)
	}
	if len(qa.inputs) != 2 || qa.inputs[0].Text != bad || qa.inputs[1].Text != good {
		t.Fatal("QA must check each written candidate, never an empty preflight", qa.inputs)
	}
	payload := lastUserJSON(t, writer.messages[1])
	if payload["research_handoff"] == nil || payload["candidate"] != bad || payload["findings"] == nil {
		t.Fatal("repair lost evidence, candidate, or concrete targets", payload)
	}
	// Repeating an unsupported fact must exhaust the SAME global repair budget.
	writer = &fakeLLM{replies: []string{bad}}
	reviewer = &fakeLLM{replies: []string{invalidFact}}
	s = New(writer, nil, "fake")
	s.Reviewer = reviewer
	r, err = s.Run(context.Background(), Request{Mode: "write", Handoff: h})
	if err != nil || r.Accepted || r.Text != "" || r.Attempts != MaxRepairs+1 || r.ChecksComplete || !strings.Contains(strings.Join(r.RejectionReasons, ","), "fact_review_failed") {
		t.Fatalf("unresolved fact passed or budget changed: %+v %v", r, err)
	}
}

func TestCriticRetryIncludesDescriptiveSchemaAndAllLocalErrors(t *testing.T) {
	source := "Начало. Первая фраза. Другая часть. Вторая фраза."
	candidate := "Начало. Первая строчка. Другая часть. Вторая строчка."
	in := criticInput{Source: source, Candidate: candidate, Mode: "edit"}
	edits := localEdits(source, candidate)
	if len(edits) != 2 {
		t.Fatal("expected two independent changes", edits)
	}
	aa := []EditAssessment{}
	for _, e := range edits {
		aa = append(aa, EditAssessment{EditID: e.ID, ReadingQuote: e.CandidateContext, Reading: "natural", ScopeQuote: "Начало.", Scope: "preserved", Decision: "keep", Reason: "Содержание сохранено."})
	}
	var report map[string]any
	_ = json.Unmarshal([]byte(criticJSON("accept")), &report)
	report["edit_assessments"] = aa
	valid, _ := json.Marshal(report)
	aa[0].ReadingQuote = "Несуществующее чтение."
	aa[1].ScopeQuote = "Несуществующая область."
	report["edit_assessments"] = aa
	report["regressions"] = []map[string]string{{"quote": "Первая строчка.", "reason": "наблюдение"}}
	invalid, _ := json.Marshal(report)
	model := &fakeLLM{omitLocalReview: true, replies: []string{string(invalid), string(valid)}}
	s := New(model, nil, "fake")
	_, err := s.critic(context.Background(), rules.RuleBundle{}, in, 1)
	if err != nil || len(model.messages) != 2 {
		t.Fatalf("one schema retry should suffice: %v", err)
	}
	feedback := model.messages[1][len(model.messages[1])-1].Content
	for _, expected := range []string{"regressions", "reading_quote", "scope_quote", "candidate_context"} {
		if !strings.Contains(feedback, expected) {
			t.Fatalf("retry hides %s: %s", expected, feedback)
		}
	}
	// A malformed observation still cannot be accepted without a valid retry.
	model = &fakeLLM{omitLocalReview: true, replies: []string{string(invalid)}}
	if _, err := New(model, nil, "fake").critic(context.Background(), rules.RuleBundle{}, in, 1); err == nil {
		t.Fatal("unresolved schema/evidence errors accepted")
	}
}

func TestWriteStartsWithoutDraftAndKeepsEvidenceAndStyleBoundaries(t *testing.T) {
	h := readyHandoff()
	candidate := "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения. Совет может помочь. [Источник](https://example.org/guide)"
	fact := `{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Сохраняйте ресурс","condition_quote":"при слабой позиции","exception_quote":"кроме угрозы поражения","confidence_quote":"может помочь","evidence_refs":["SRC-1"]}]}`
	writer := &fakeLLM{replies: []string{candidate}}
	s := New(writer, nil, "fake")
	s.Reviewer = &fakeLLM{replies: []string{fact, criticJSON("accept")}}
	r, err := s.Run(context.Background(), Request{Mode: "write", Handoff: h})
	if err != nil || !r.Accepted || r.Text != candidate || r.FactReview == nil {
		t.Fatalf("writing without a draft failed: %+v %v", r, err)
	}
	if len(writer.messages) != 1 || lastUserJSON(t, writer.messages[0])["draft"] != "" {
		t.Fatal("writing required or fabricated a draft")
	}
	for _, req := range []Request{{Mode: "write"}, {Mode: "edit", Handoff: h}} {
		if _, err := s.Run(context.Background(), req); err == nil {
			t.Fatal("missing evidence or empty ordinary source accepted")
		}
	}
	writer = &fakeLLM{replies: []string{candidate}}
	_, err = New(writer, nil, "fake").rewrite(context.Background(), Request{Mode: "reconstruct", Handoff: h}, rules.RuleBundle{}, Analysis{}, corpusExamples)
	if err != nil {
		t.Fatal(err)
	}
	for _, rule := range []string{"копировать предложения дословно", "Пустое обобщение", "риторические вопросы"} {
		if !strings.Contains(strings.ToLower(writer.messages[0][0].Content), strings.ToLower(rule)) {
			t.Fatal("writing prompt lacks", rule)
		}
	}
	for _, mode := range []string{"proofread", "facts_only"} {
		if proseInstruction(mode) != "" {
			t.Fatal("literary rewriting guidance leaked into", mode)
		}
	}
}

func TestWritingRetrievesStyleForVerifiedContentInsteadOfDraft(t *testing.T) {
	h := readyHandoff()
	r := &fakeRetriever{examples: corpusExamples}
	s := New(&fakeLLM{replies: []string{"unused"}}, nil, "fake")
	s.Retriever = r
	_, _ = s.retrieve(context.Background(), Request{Text: "Непроверенный ИИ-черновик.", Handoff: h}, "reconstruct", "on", "guide")
	if len(r.queries) != 1 || r.queries[0].Text != h.VerifiedText() {
		t.Fatal("style query still depends on a draft", r.queries)
	}
}

func TestWritingSeesRequiredSectionsWithoutTreatingThemAsFacts(t *testing.T) {
	model := &fakeLLM{replies: []string{"Готовый текст."}}
	bundle := rules.Build(&analyzer.Rules{SectionsRequired: []string{"Что делать"}}, "GUIDE", "переплавка", "ru-RU", nil)
	_, err := New(model, nil, "fake").rewrite(context.Background(), Request{Mode: "reconstruct", Handoff: readyHandoff()}, bundle, Analysis{}, nil)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(lastUserJSON(t, model.messages[0])["editorial_rules"])
	if !strings.Contains(string(raw), "Что делать") {
		t.Fatal("writer never saw the sections enforced by postflight", string(raw))
	}
}

func TestWritingMalformedFactFeedbackCannotTriggerRepair(t *testing.T) {
	bad := "Совет без условий."
	for _, fact := range []string{
		`{"claims":[]}`,
		`{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":["Цитата, которой нет."],"claims":[{"claim_id":"CLM-1","status":"insufficient","evidence_refs":["SRC-1"]}]}`,
		`{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"insufficient","evidence_refs":["foreign-source"]}]}`,
		`{"candidate_checked":true,"confidence_preserved":false,"unsupported_claims":["Совет без условий."],"claims":[{"claim_id":"CLM-1","status":"insufficient","evidence_refs":["SRC-1"]}]}`,
	} {
		writer := &fakeLLM{replies: []string{bad}}
		s := New(writer, nil, "fake")
		s.Reviewer = &fakeLLM{replies: []string{fact}}
		r, err := s.Run(context.Background(), Request{Mode: "write", Handoff: readyHandoff()})
		if err != nil || r.Accepted || r.Text != "" || r.ChecksComplete || len(writer.messages) != 1 {
			t.Fatalf("unreliable feedback authorized repair or acceptance: %+v %v", r, err)
		}
	}
}

func TestSmallConcreteEditsAndActionArgumentsReachEditorialStages(t *testing.T) {
	model := &fakeLLM{replies: []string{analysisJSON, "Готовый текст.", criticJSON("accept")}}
	s := New(model, nil, "fake")
	bundle := rules.RuleBundle{}
	req := Request{Text: "Исходник.", Mode: "edit"}
	a := s.editorialAnalysis(context.Background(), req, bundle, nil)
	_, _ = s.rewrite(context.Background(), req, bundle, a, nil)
	_, _ = s.critic(context.Background(), bundle, criticInput{Source: req.Text, Candidate: "Готовый текст.", Mode: "edit"}, 1)
	for _, messages := range model.messages {
		for _, rule := range []string{"не повод сохранять доказанный дубль", "в справочник три статьи"} {
			if !strings.Contains(messages[0].Content, rule) {
				t.Fatal("editorial policy did not reach model stage:", rule)
			}
		}
	}
}
