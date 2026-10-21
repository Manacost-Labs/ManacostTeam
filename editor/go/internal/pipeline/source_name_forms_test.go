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

func TestReconstructionDoesNotTreatSentenceVerbAsPartOfKnownName(t *testing.T) {
	before := "Эффект Сферы. Найдите Полкелта и Ученицу. Полкелт и Ученица. Скидка Ученицы. Северная Империя."
	for _, after := range []string{"Без Сферы", "После Полкелта", "Выставьте Ученицу", "Перед Северная Империя", "Пока Ученицу", "Если Сферы", "Играть Полкелта", "Текст Сферы", "Отсутствие Полкелта", "Ранний Полкелт", "Разыгрывать Полкелта", "Иногда Ученица", "Скидка Ученицы", "Поздний Полкелт", "Наличие Сферы", "Усиление Ученицы"} {
		if reconstructionGuard(before, after).HasHardChanges() {
			t.Errorf("sentence prefix invented a name: %s", after)
		}
	}
	for _, after := range []string{"Без Неизвестной Сферы", "После Неизвестного Полкелта", "Западная Империя", "Ранний Неизвестный Полкелт", "Текст Неизвестной Сферы", "Сверхсильная Ученицу"} {
		if !reconstructionGuard(before, after).HasHardChanges() {
			t.Errorf("new name admitted: %s", after)
		}
	}
}

func TestNameWrapperCannotPromoteLowercaseCommonPhrase(t *testing.T) {
	for _, before := range []string{"старый ход", "Старый ход", "суперПолкелт"} {
		for _, candidate := range []string{"Текст Старый Ход", "Текст Полкелт"} {
			if !reconstructionGuard(before, candidate).HasHardChanges() {
				t.Fatalf("lowercase phrase or partial word promoted to name: %q => %q", before, candidate)
			}
		}
	}
}

func TestReconstructionScopeAllowsOnlyDeclaredHistoricalFrame(t *testing.T) {
	h := readyHandoff()
	h.Patch = "18.0-2020-08-12"
	baseline := h.VerifiedText() + "\n" + h.scopeText()
	if reconstructionGuard(baseline, "На 12.08.2020, патч 18.0.").HasHardChanges() {
		t.Fatal("declared historical frame treated as invented numeric fact")
	}
	if reconstructionGuard(baseline, "На 12 августа 2020 года, патч 18.0.").HasHardChanges() {
		t.Fatal("same declared calendar date in prose rejected")
	}
	for _, candidate := range []string{"17 урона", "100 урона", "13.08.2020", "13 августа 2020 года", "12 урона"} {
		if !reconstructionGuard(baseline, candidate).HasHardChanges() {
			t.Fatal("scope authorized a different number", candidate)
		}
	}
}

func TestReconstructionRecognizesBoundedKnownRussianNameDeclensions(t *testing.T) {
	before := "Фриз Маг. Звездочет Солариан. Малигос Друид."
	for _, candidate := range []string{"Фриз Маге", "Фриз Магов", "Звездочетом Соларианом", "Малигос Друида"} {
		if reconstructionGuard(before, candidate).HasHardChanges() {
			t.Errorf("ordinary name inflection rejected: %s", candidate)
		}
	}
	for _, candidate := range []string{"Фриз Магистр", "Звездочет Салариан", "Великий Фриз Маг", "Малигос Жрец", "Фриз Маг Солариан"} {
		if !reconstructionGuard(before, candidate).HasHardChanges() {
			t.Errorf("unapproved identity admitted: %s", candidate)
		}
	}
}

func TestReconstructionScopeRejectsUnrecognizedPatchPayload(t *testing.T) {
	for _, patch := range []string{"18.0 17 100", "18.0-2020-08-12 17", "18.0-2020-99-99", "2020-08-12", "arbitrary 100"} {
		h := readyHandoff()
		h.Patch = patch
		if h.scopeText() != "" {
			t.Errorf("malformed patch became numeric authority: %q", patch)
		}
	}
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

func TestSourceAdjacentLowercasePhraseMayStartSentence(t *testing.T) {
	h := nameFormHandoff()
	h.Sources[0].Quote += " Классический пример: классический Фриз Маг. Еще скидка Потока."
	for _, candidate := range []string{"Классический Фриз Маг", "Скидка Потока"} {
		if reconstructionGuard(h.VerifiedText()+" Маг", candidate, h.sourceNameForms()...).HasHardChanges() {
			t.Fatalf("exact adjacent source phrase rejected: %s", candidate)
		}
	}
	if !reconstructionGuard(h.VerifiedText(), "Огромная Потока", h.sourceNameForms()...).HasHardChanges() {
		t.Fatal("arbitrary modifier admitted")
	}
	if !reconstructionGuard(h.VerifiedText()+" Маг", "Риз Маг", h.sourceNameForms()...).HasHardChanges() {
		t.Fatal("suffix of a capitalized source word became a new approved name")
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
