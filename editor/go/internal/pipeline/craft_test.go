package pipeline

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzers"
	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

func TestAcceptedParagraphEditIsNotRewrittenForWordFrequency(t *testing.T) {
	source := "Вы получите подарки за просмотр. Стримеры разыграют подарки."
	candidate := "Вы получите подарки за просмотр.\n\nСтримеры разыграют подарки."
	lm := &fakeLLM{replies: []string{analysisJSON, candidate, strings.Replace(criticJSON("accept"), `"category":"clarity"`, `"category":"structure"`, 1)}}
	check := &scriptedAnalyzer{name: "vale", perRun: [][]analyzers.Finding{{warning("Repeat", "частый повтор: подарки")}}}
	result := run(t, lm, source, "edit", check)
	if strings.Join(lm.stages, ",") != "analysis,rewrite,critic" || result.Attempts != 1 {
		t.Fatalf("accepted paragraph split triggered another rewrite: %v %+v", lm.stages, result)
	}
	if !result.Accepted || result.Text != candidate || !containsRule(findingsOf(t, lastUserJSON(t, lm.messages[2]), "tool_findings"), "Repeat") {
		t.Fatalf("candidate or diagnostic visibility lost: %+v", result)
	}
	if len(result.QAFindings) == 0 {
		t.Fatal("advisory findings must stay visible to the client")
	}
}

func TestAnalysisFailureKeepsToolObservations(t *testing.T) {
	for _, fail := range []bool{false, true} {
		lm := &fakeLLM{replies: []string{"not json"}}
		if fail {
			lm.fail = map[int]error{0: errors.New("analysis unavailable")}
		}
		svc := New(lm, nil, "fake")
		a := svc.editorialAnalysis(context.Background(), Request{Text: "Текст.", Mode: "edit"}, rules.Build(nil, "GUIDE", "обычная", "ru-RU", nil), nil, warning("Repeat", "повтор"))
		if len(a.ToolObservations) != 1 || a.ToolObservations[0].RuleID != "Repeat" {
			t.Fatalf("analysis failure hid observations: %+v", a)
		}
	}
}

func TestIndependentCriticStillReceivesSoftFindings(t *testing.T) {
	source := "Точная формулировка."
	writer := &fakeLLM{replies: []string{analysisJSON, source}}
	reviewer := &fakeLLM{replies: []string{criticJSONNoImprovement()}}
	check := &scriptedAnalyzer{name: "vale", perRun: [][]analyzers.Finding{{warning("Repeat", "повтор")}}}
	svc := New(writer, nil, "fake", check)
	svc.Reviewer = reviewer
	result, err := svc.Run(context.Background(), Request{Text: source, Mode: "edit"})
	if err != nil || result.Text != source || len(writer.messages) != 2 || len(reviewer.messages) != 1 {
		t.Fatalf("independent review routing: err=%v result=%+v", err, result)
	}
	if !containsRule(findingsOf(t, lastUserJSON(t, reviewer.messages[0]), "tool_findings"), "Repeat") {
		t.Fatal("independent critic lost diagnostic observations")
	}
}

func TestNewProtectedEntityWarningStillTriggersRepair(t *testing.T) {
	source := "Карта стоит 3 маны."
	lm := &fakeLLM{replies: []string{analysisJSON, source + " На 8 ходу.", criticJSON("accept"), source, criticJSONNoImprovement()}}
	result := run(t, lm, source, "edit")
	if strings.Join(lm.stages, ",") != "analysis,rewrite,critic,repair,critic" || result.Text != source {
		t.Fatalf("protected entity warning lost mandatory repair: %v %+v", lm.stages, result)
	}
	if !containsRule(findingsOf(t, lastUserJSON(t, lm.messages[3]), "findings"), "protected_entity_added") {
		t.Fatal("guard warning missing from repair")
	}
}

func TestAnalysisKeepsValidFieldsWhenOptionalDiagnosticHasWrongShape(t *testing.T) {
	lm := &fakeLLM{replies: []string{`{"thesis":"t","paragraphs":[{"n":1,"function":"Условие получения"}],"weak_spots":[{"where":"абзац 1","issue":"смена темы"}],"repetitions":42,"factual_risks":["Проверить срок"],"strengths":[{"quote":"Подарки за просмотр.","reason":"Точное условие"},{"quote":"Несуществующая цитата","reason":"Нет"}]}`}}
	svc := New(lm, nil, "fake")
	a := svc.editorialAnalysis(context.Background(), Request{Text: "Подарки за просмотр.", Mode: "edit"}, rules.Build(nil, "GUIDE", "обычная", "ru-RU", nil), nil)
	if len(a.Strengths) != 1 || a.Strengths[0].Quote != "Подарки за просмотр." || len(a.FactualRisks) != 1 {
		t.Fatalf("valid preservation fields discarded: %+v", a)
	}
	if len(a.Paragraphs) != 1 || a.Paragraphs[0] != "Условие получения" || len(a.WeakSpots) != 1 || !strings.Contains(a.WeakSpots[0], "смена темы") {
		t.Fatalf("known diagnostic object form lost: %+v", a)
	}
}
