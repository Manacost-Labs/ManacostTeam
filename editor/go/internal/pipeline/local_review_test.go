package pipeline

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzers"
	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

func TestLocalEditsSeparateWordsFromParagraphs(t *testing.T) {
	source := "Правила турнира. Командами были завершены матчи. Награда доступна всем."
	candidate := "Правила турнира. Команды завершили матчи.\n\nНаграда доступна всем."
	edits := localEdits(source, candidate)
	if len(edits) != 1 || edits[0].Before != "Командами были завершены" || edits[0].After != "Команды завершили" {
		t.Fatalf("unexpected local changes: %+v", edits)
	}
	if got := localEdits(source, strings.ReplaceAll(source, ". ", ".\n\n")); len(got) != 0 {
		t.Fatalf("paragraphs became lexical losses: %+v", got)
	}
}

func TestMissingLocalReviewRetriesThenFailsClosed(t *testing.T) {
	model := &fakeLLM{omitLocalReview: true, replies: []string{criticJSON("accept")}}
	s := New(model, nil, "fake")
	_, err := s.critic(context.Background(), rules.RuleBundle{}, criticInput{Mode: "edit", Source: "Задача была завершена командой.", Candidate: "Команда завершила задачу."}, 1)
	if err == nil || err.Kind != ReasonCriticInvalid || len(model.messages) != 2 {
		t.Fatalf("missing review escaped retry: %v, %d calls", err, len(model.messages))
	}
	var payload criticInput
	if json.Unmarshal([]byte(model.messages[0][1].Content), &payload) != nil || len(payload.LocalEdits) == 0 || payload.Analysis.Thesis != "" {
		t.Fatal("local evidence missing or writer context leaked")
	}
	if !strings.Contains(model.messages[1][len(model.messages[1])-1].Content, "edit_assessments") {
		t.Fatal("retry does not identify missing evidence")
	}
}

func TestCriticRetryReportsBothStrengthAndLocalEvidenceErrors(t *testing.T) {
	source, candidate := "Турнир будет долгим.", "Турнир продлится долго."
	model := &fakeLLM{omitLocalReview: true, replies: []string{criticJSON("accept")}}
	s := New(model, nil, "fake")
	_, err := s.critic(context.Background(), rules.RuleBundle{}, criticInput{Mode: "edit", Source: source, Candidate: candidate, KeepSpans: []StrongSpan{{Quote: source, Reason: "Удачный смысл."}}}, 1)
	if err == nil || len(model.messages) != 2 {
		t.Fatal("invalid evidence escaped bounded retry")
	}
	message := model.messages[1][len(model.messages[1])-1].Content
	if !strings.Contains(message, "strength_changes") || !strings.Contains(message, "edit_assessments") {
		t.Fatalf("retry hides independent error: %s", message)
	}
}

func TestLocalReviewDoesNotExpandOtherModes(t *testing.T) {
	for _, mode := range []string{"proofread", "facts_only", "reconstruct"} {
		if localReviewInstruction(mode) != "" {
			t.Fatal(mode)
		}
		if err := validateEditAssessments(criticInput{Mode: mode, LocalEdits: localEdits("старое", "новое")}, criticResult{}); err != nil {
			t.Fatal(mode, err)
		}
	}
}

func TestLocalReviewRejectsUngroundedOrContradictoryDecisions(t *testing.T) {
	in := criticInput{Mode: "edit", Source: "Правила турнира. Командами были завершены матчи.", Candidate: "Правила турнира. Команды завершили матчи."}
	in.LocalEdits = localEdits(in.Source, in.Candidate)
	valid := EditAssessment{EditID: 1, ReadingQuote: "Команды завершили матчи.", Reading: "natural", ScopeQuote: "Правила турнира.", Scope: "preserved", Decision: "keep", Reason: "Действующее лицо стало подлежащим; соседняя фраза сохраняет тему турнира."}
	for _, tc := range []struct {
		name    string
		change  func(*EditAssessment)
		missing bool
	}{
		{"missing", nil, true},
		{"unknown_id", func(a *EditAssessment) { a.EditID = 99 }, false},
		{"fabricated_quote", func(a *EditAssessment) { a.ReadingQuote = "Несуществующая фраза" }, false},
		{"unrelated_quote", func(a *EditAssessment) { a.ReadingQuote = "Правила турнира." }, false},
		{"fabricated_scope", func(a *EditAssessment) { a.ScopeQuote = "Здесь другой турнир" }, false},
		{"awkward_accepted", func(a *EditAssessment) { a.Reading = "awkward" }, false},
		{"scope_lost_accepted", func(a *EditAssessment) { a.Scope = "lost" }, false},
		{"repair_without_finding", func(a *EditAssessment) { a.Decision = "repair" }, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			a := valid
			out := criticResult{Verdict: "accept"}
			if !tc.missing {
				tc.change(&a)
				out.EditAssessments = []EditAssessment{a}
			}
			if validateEditAssessments(in, out) == nil {
				t.Fatal("invalid local review accepted")
			}
		})
	}
	if err := validateEditAssessments(in, criticResult{Verdict: "accept", EditAssessments: []EditAssessment{valid}}); err != nil {
		t.Fatal(err)
	}
	valid.Decision, valid.Reading, valid.FindingRuleID = "repair", "awkward", "style.local"
	if err := validateEditAssessments(in, criticResult{Verdict: "repair", RepairRequired: true, EditAssessments: []EditAssessment{valid}, Findings: []analyzers.Finding{warning("style.local", "Замечание о другом предложении.")}}); err == nil {
		t.Fatal("matching rule ID without the assessed quote accepted")
	}
	if err := validateEditAssessments(in, criticResult{Verdict: "repair", RepairRequired: true, EditAssessments: []EditAssessment{valid}, Findings: []analyzers.Finding{warning("style.local", "«Команды завершили матчи.»: исправь только сочетание слов; сохрани абзацы.")}}); err != nil {
		t.Fatal(err)
	}
}

func TestLocalReviewEvidenceIsBounded(t *testing.T) {
	for _, texts := range [][2]string{
		{strings.Repeat("Старый текст. ", 4000), strings.Repeat("Новый текст. ", 4000)},
		{strings.Repeat("старый одинаковый ", 80), strings.Repeat("новый одинаковый ", 80)},
	} {
		edits := localEdits(texts[0], texts[1])
		if len(edits) == 0 || len(edits) > 16 || !edits[0].Coarse {
			t.Fatalf("unbounded or hidden coarse review: %+v", edits)
		}
		for _, e := range edits {
			for _, q := range []string{e.Before, e.After, e.SourceContext, e.CandidateContext} {
				if len([]rune(q)) > 300 {
					t.Fatal("unbounded excerpt")
				}
			}
		}
	}
}

func TestLocalTautologyRepairPreservesParagraphAndNeighborEdit(t *testing.T) {
	source := "В раундах принимают участие игроки и ведущие. Награда будет выдана завтра."
	draft := "В раундах играют игроки и ведущие.\n\nНаграду выдадут завтра."
	fixed := "В раундах участвуют игроки и ведущие.\n\nНаграду выдадут завтра."
	issue := warning("style.echo", "«В раундах играют игроки и ведущие.»: убери новый однокоренной повтор, сохрани второй абзац.")
	var response map[string]any
	_ = json.Unmarshal([]byte(criticJSON("repair", issue)), &response)
	var assessments []EditAssessment
	for _, e := range localEdits(source, draft) {
		a := EditAssessment{EditID: e.ID, ReadingQuote: e.CandidateContext, Reading: "natural", ScopeQuote: "игроки и ведущие.", Scope: "preserved", Decision: "keep", Reason: "Сохранены участники и срок награды."}
		if strings.Contains(e.After, "играют") {
			a.ReadingQuote = "В раундах играют игроки и ведущие."
			a.Reading = "awkward"
			a.Decision = "repair"
			a.FindingRuleID = "style.echo"
			for _, echo := range e.Echoes {
				a.EchoDecisions = append(a.EchoDecisions, EchoDecision{Quote: echo.Quote, Verdict: "accidental", Reason: "Необязательная замена породила эхо."})
			}
		}
		assessments = append(assessments, a)
	}
	response["edit_assessments"] = assessments
	raw, _ := json.Marshal(response)
	model := &fakeLLM{replies: []string{analysisJSON, draft, string(raw), fixed, criticJSON("accept")}}
	result := run(t, model, source, "edit")
	if !result.Accepted || result.Text != fixed || result.Attempts != 2 {
		t.Fatalf("local repair lost useful changes: %+v", result)
	}
	if !strings.Contains(model.messages[2][1].Content, "sound_echoes") || !strings.Contains(model.messages[2][1].Content, "играют игроки") {
		t.Fatal("observed pair never reached critic")
	}
	payload := lastUserJSON(t, model.messages[3])
	if payload["candidate"] != draft || !strings.Contains(model.messages[3][1].Content, "style.echo") {
		t.Fatal("wrong repair target")
	}
}

func TestContextualScopeAndUsefulSyntaxCanSurviveKeepSpan(t *testing.T) {
	source := "Правила турнира. Мы расскажем вам о том, как выбрать команду. В этом турнире можно участвовать без приглашения."
	candidate := "Правила турнира. Мы расскажем вам, как выбрать команду.\n\nМожно участвовать без приглашения."
	span := "Мы расскажем вам о том, как выбрать команду."
	analysis := strings.Replace(analysisJSON, "\"factual_risks\":[]", `"factual_risks":[],"strengths":[{"quote":"`+span+`","reason":"Обещание объяснения с обращением к читателю."}]`, 1)
	var response map[string]any
	_ = json.Unmarshal([]byte(criticJSON("accept")), &response)
	response["strength_changes"] = []StrengthChange{{Quote: span, ReplacementQuote: "Мы расскажем вам, как выбрать команду.", Reason: "Сокращена лишняя связь о том, обещание и обращение сохранены."}}
	var assessments []EditAssessment
	for _, e := range localEdits(source, candidate) {
		assessments = append(assessments, EditAssessment{EditID: e.ID, ReadingQuote: e.CandidateContext, Reading: "natural", ScopeQuote: "Правила турнира.", Scope: "preserved", Decision: "keep", Reason: "Тема явно названа в начале; условие приглашения и обращение сохранены, сокращён повтор темы."})
	}
	response["edit_assessments"] = assessments
	raw, _ := json.Marshal(response)
	model := &fakeLLM{replies: []string{analysis, candidate, string(raw)}}
	result := run(t, model, source, "edit")
	if !result.Accepted || result.Text != candidate || result.Attempts != 1 {
		t.Fatalf("contextual scope or keep-span improvement discarded: %+v", result)
	}
}
