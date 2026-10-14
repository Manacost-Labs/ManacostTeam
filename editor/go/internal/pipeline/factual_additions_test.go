package pipeline

import (
	"strings"
	"testing"
)

func TestCriticMustExplicitlyCheckNewFacts(t *testing.T) {
	old := strings.Replace(criticJSON("accept"), `"no_new_facts":true,"unsupported_additions":[],`, "", 1)
	for _, response := range []string{old, strings.Replace(old, `"verdict":"accept"`, `"verdict":"accept","no_new_facts":null,"unsupported_additions":[]`, 1)} {
		if _, err := parseCritic(response); err == nil {
			t.Fatal("missing factual audit accepted")
		}
	}
}

func TestUnsupportedDescriptionReturnsOriginalDespiteHighScores(t *testing.T) {
	source := "Способность наносит урон."
	candidate := "Способность наносит урон и замораживает цель."
	for _, response := range []string{
		strings.Replace(criticJSON("accept"), `"no_new_facts":true`, `"no_new_facts":false`, 1),
		strings.Replace(criticJSON("accept"), `"unsupported_additions":[]`, `"unsupported_additions":["замораживает цель"]`, 1),
	} {
		model := &fakeLLM{replies: []string{analysisJSON, candidate, response}}
		result := run(t, model, source, "edit")
		if result.Accepted || result.Text != source || result.FactCheckPassed == nil || *result.FactCheckPassed || !strings.Contains(strings.Join(result.RejectionReasons, ","), "unsupported_factual_addition") {
			t.Fatalf("invented mechanic accepted: %+v", result)
		}
	}
}
