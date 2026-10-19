package pipeline

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestRepairCitationAllowsOnlyBoundaryFullStopDifference(t *testing.T) {
	in := criticInput{Mode: "edit", Source: "Участие в турнире осуществляется бесплатно.", Candidate: "Турнир бесплатный."}
	in.LocalEdits = localEdits(in.Source, in.Candidate)
	for _, tc := range []struct {
		name, message string
		valid         bool
	}{
		{"exact", "Исправь «Турнир бесплатный.» в этом месте.", true},
		{"point_outside_quotes", "Исправь «Турнир бесплатный» в этом месте.", true},
		{"end_of_message", "Исправь: Турнир бесплатный", true},
		{"different_word", "Исправь «Турнир бесплатным» в этом месте.", false},
		{"word_prefix", "Исправь «Турнир бесплатныйполностью» в этом месте.", false},
		{"unrelated", "Исправь другое предложение.", false},
		{"question_substitution", "Исправь «Турнир бесплатный?» здесь.", false},
		{"comma_substitution", "Исправь «Турнир бесплатный, дальше» здесь.", false},
		{"colon_substitution", "Исправь «Турнир бесплатный: дальше» здесь.", false},
		{"semicolon_substitution", "Исправь «Турнир бесплатный; дальше» здесь.", false},
		{"exclamation_substitution", "Исправь «Турнир бесплатный!» здесь.", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			a := EditAssessment{EditID: 1, ReadingQuote: in.Candidate, Reading: "natural", ScopeQuote: in.Candidate, Scope: "preserved", Decision: "repair", Reason: "Нужно восстановить точный предмет действия.", FindingRuleID: "style.local"}
			out := criticResult{Verdict: "repair", EditAssessments: []EditAssessment{a}, Findings: nil}
			out.Findings = append(out.Findings, warning("style.local", tc.message))
			if err := validateEditAssessments(in, out); (err == nil) != tc.valid {
				t.Fatalf("valid=%v error=%v", tc.valid, err)
			}
		})
	}
	// Candidate grounding stays exact; punctuation in the actual text is evidence.
	in.Candidate = "Турнир бесплатный!"
	in.LocalEdits = localEdits(in.Source, in.Candidate)
	a := EditAssessment{EditID: 1, ReadingQuote: "Турнир бесплатный.", Reading: "awkward", ScopeQuote: in.Candidate, Scope: "preserved", Decision: "repair", Reason: "Не тот знак.", FindingRuleID: "style.local"}
	if validateEditAssessments(in, criticResult{Verdict: "repair", EditAssessments: []EditAssessment{a}, Findings: nil}) == nil {
		t.Fatal("invented candidate quotation accepted")
	}
}

func TestBoundaryPunctuationRepairPreservesNeighborAndParagraph(t *testing.T) {
	source := "Участие в турнире осуществляется бесплатно. Награда будет выдана завтра."
	draft := "Турнир бесплатный.\n\nНаграду выдадут завтра."
	fixed := "Участвовать в турнире можно бесплатно.\n\nНаграду выдадут завтра."
	var response map[string]any
	_ = json.Unmarshal([]byte(criticJSON("repair", warning("style.local", "В «Турнир бесплатный» восстанови точный предмет действия; соседнее упрощение оставь."))), &response)
	var assessments []EditAssessment
	for _, e := range localEdits(source, draft) {
		a := EditAssessment{EditID: e.ID, ReadingQuote: e.CandidateContext, Reading: "natural", ScopeQuote: "Награду выдадут завтра.", Scope: "preserved", Decision: "keep", Reason: "Прямой глагол сохраняет срок награды."}
		if strings.Contains(e.After, "Турнир") {
			a.ReadingQuote, a.Decision, a.FindingRuleID = "Турнир бесплатный.", "repair", "style.local"
			a.ScopeQuote = "Турнир бесплатный."
			a.Reason = "Нужно назвать участие, а не стоимость турнира."
		}
		assessments = append(assessments, a)
	}
	response["edit_assessments"] = assessments
	raw, _ := json.Marshal(response)
	model := &fakeLLM{replies: []string{analysisJSON, draft, string(raw), fixed, criticJSON("accept")}}
	result := run(t, model, source, "edit")
	if !result.Accepted || result.Text != fixed || result.Attempts != 2 || len(model.messages) != 5 {
		t.Fatalf("valid local repair never reached or lost neighboring edit: %+v", result)
	}
	if stageOf(model.messages[3][0].Content) != "repair" {
		t.Fatal("finding was mistaken for an invalid critic response")
	}
	// The qualifier example must reach analysis and the writer, not only a
	// critic looking at an already chosen draft (the observed missed route).
	for _, messages := range model.messages {
		stage := stageOf(messages[0].Content)
		if stage != "repair" && !strings.Contains(messages[0].Content, qualifierExampleInstruction) {
			t.Fatalf("qualifier distinction missing from %s request", stage)
		}
	}
}

func TestRepairCitationKeepsInternalAndExpressivePunctuation(t *testing.T) {
	for _, tc := range []struct{ name, quote, message string }{
		{"internal_comma", "Да, можно.", "Исправь «Да можно» здесь."},
		{"question", "Можно?", "Исправь «Можно» здесь."},
		{"exclamation", "Можно!", "Исправь «Можно» здесь."},
		{"ellipsis", "Можно...", "Исправь «Можно» здесь."},
		{"empty", "", "Исправь здесь."},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if findingQuotes(tc.message, tc.quote) {
				t.Fatal("non-boundary evidence mismatch accepted")
			}
		})
	}
}
