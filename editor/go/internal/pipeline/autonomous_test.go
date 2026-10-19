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
	for _, checked := range []string{"true", "false"} {
		h := readyHandoff()
		good := "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения. Совет может помочь. [Источник](https://example.org/guide)"
		bad := good + " Это гарантирует победу."
		fact := `{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Сохраняйте ресурс","condition_quote":"при слабой позиции","exception_quote":"кроме угрозы поражения","confidence_quote":"может помочь","evidence_refs":["SRC-1"]}]}`
		invalidFact := strings.Replace(fact, `"unsupported_claims":[]`, `"unsupported_claims":["Это гарантирует победу."]`, 1)
		invalidFact = strings.Replace(invalidFact, `"candidate_checked":true`, `"candidate_checked":`+checked, 1)
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
		if checked == "false" {
			writer = &fakeLLM{replies: []string{good}}
			s = New(writer, nil, "fake")
			s.Reviewer = &fakeLLM{replies: []string{strings.Replace(fact, `"candidate_checked":true`, `"candidate_checked":false`, 1)}}
			r, err = s.Run(context.Background(), Request{Mode: "write", Handoff: h})
			if err != nil || r.Accepted || r.ChecksComplete || r.Text != "" || len(writer.messages) != 1 {
				t.Fatalf("uncertainty without a concrete target triggered repair: %+v %v", r, err)
			}
		}
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
	model = &fakeLLM{replies: []string{criticJSON("accept")}}
	s := New(model, nil, "fake")
	_, _ = s.critic(context.Background(), bundle, criticInput{Source: "Действие.", Candidate: "Действие.", Mode: "reconstruct"}, 1)
	if lastUserJSON(t, model.messages[0])["sections_required"] == nil {
		t.Fatal("critic can contradict a required section it never received")
	}
	model = &fakeLLM{replies: []string{"Действие."}}
	_, _ = New(model, nil, "fake").repairReconstruction(context.Background(), bundle, readyHandoff(), "Действие.", nil, nil, nil)
	if lastUserJSON(t, model.messages[0])["sections_required"] == nil {
		t.Fatal("repair can delete a required section it never received")
	}
	for _, mode := range []string{"edit", "rewrite", "proofread"} {
		model = &fakeLLM{replies: []string{criticJSON("accept")}}
		_, _ = New(model, nil, "fake").critic(context.Background(), bundle, criticInput{Source: "Действие.", Candidate: "Действие.", Mode: mode}, 1)
		if lastUserJSON(t, model.messages[0])["sections_required"] != nil || reconstructionReviewInstruction(mode) != "" {
			t.Fatal("writing-only structure leaked into", mode)
		}
	}
}

func TestWritingQuestionAndNonRedundantExplanationReachAllWritingStages(t *testing.T) {
	bundle := rules.Build(nil, "GUIDE", "переплавка", "ru-RU", nil)
	h := readyHandoff()
	h.Sources = append(h.Sources, ResearchSource{ID: "SRC-2", URL: "https://example.org/timing", Quote: "Откладывайте покупку до следующего хода."})
	h.Claims = append(h.Claims, ResearchClaim{ID: "CLM-2", Meaning: "Откладывайте покупку до следующего хода.", Action: "Откладывайте покупку", Condition: "до следующего хода", Confidence: "high", Patch: h.Patch, Status: "supported_with_conditions", EvidenceRefs: []string{"SRC-2"}})
	h.Chapters[0].RequiredClaimIDs = append(h.Chapters[0].RequiredClaimIDs, "CLM-2")
	h.Decisions = append(h.Decisions, DecisionQuestion{ID: "Q-2", ChapterID: "CH-1", Question: "Как долго откладывать покупку?", Required: true, Status: "answered", ClaimIDs: []string{"CLM-2"}})
	if err := h.Validate(); err != nil {
		t.Fatal(err)
	}
	for _, stage := range []string{"writer", "critic", "repair"} {
		t.Run(stage, func(t *testing.T) {
			model := &fakeLLM{replies: []string{criticJSON("accept")}}
			s := New(model, nil, "fake")
			switch stage {
			case "writer":
				_, _ = s.rewrite(context.Background(), Request{Mode: "reconstruct", Handoff: h}, bundle, Analysis{}, nil)
			case "critic":
				_, _ = s.critic(context.Background(), bundle, criticInput{Source: h.VerifiedText(), Candidate: "Действие.", Mode: "reconstruct", Handoff: h}, 1)
			case "repair":
				_, _ = s.repairReconstruction(context.Background(), bundle, h, "Действие.", nil, nil, nil)
			}
			if len(model.messages) != 1 {
				t.Fatal("missing writing stage", model.messages)
			}
			var got ResearchHandoff
			raw, _ := json.Marshal(lastUserJSON(t, model.messages[0])["research_handoff"])
			if err := json.Unmarshal(raw, &got); err != nil {
				t.Fatal("writing stage lost the question-bearing handoff", err)
			}
			actual, _ := json.Marshal(got)
			expected, _ := json.Marshal(h)
			if string(actual) != string(expected) {
				t.Fatal("writing stage lost brief, questions, required claims or conditions", stage, string(actual))
			}
			instruction := model.messages[0][0].Content
			if !strings.Contains(instruction, "сквозной вопрос") || !strings.Contains(instruction, "одно и то же действие или оговорку") || !strings.Contains(instruction, "дополняющие условия") {
				t.Fatal("writing stage lacks the question, repetition and condition boundaries", stage)
			}
		})
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

func TestFactReviewRetriesOnlyMalformedJSONOnce(t *testing.T) {
	candidate := "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения. Совет может помочь. https://example.org/guide"
	fact := `{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Сохраняйте ресурс","condition_quote":"при слабой позиции","exception_quote":"кроме угрозы поражения","confidence_quote":"может помочь","evidence_refs":["SRC-1"]}]}`
	model := &fakeLLM{replies: []string{fact + "\nКомментарий вне JSON.", fact}}
	s := New(model, nil, "fake")
	_, err := s.factReview(context.Background(), readyHandoff(), candidate)
	if err != nil || len(model.messages) != 2 || len(model.messages[1]) != 4 || model.messages[0][1] != model.messages[1][1] {
		t.Fatalf("format retry changed facts or failed: %v %+v", err, model.messages)
	}
	negative := strings.Replace(fact, `"candidate_checked":true`, `"candidate_checked":false`, 1)
	for _, raw := range []string{negative, fact + "\nКомментарий вне JSON."} {
		model = &fakeLLM{replies: []string{raw}}
		_, err = New(model, nil, "fake").factReview(context.Background(), readyHandoff(), candidate)
		want := 1
		if raw != negative {
			want = 2
		}
		if err == nil || len(model.messages) != want {
			t.Fatalf("semantic failure retried or malformed reply accepted: %v %d", err, len(model.messages))
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
