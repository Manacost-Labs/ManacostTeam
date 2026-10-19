package pipeline

import (
	"errors"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzers"
)

func semanticIssue(verdict string) string {
	finding := analyzers.Finding{RuleID: "meaning.quantity", Severity: "error", Message: "В candidate «несколько наград» подменяет исходное «пару наград». Восстанови количество из source."}
	reply := criticJSON(verdict, finding)
	reply = strings.Replace(reply, `"no_new_facts":true`, `"no_new_facts":false`, 1)
	return strings.Replace(reply, `"unsupported_additions":[]`, `"unsupported_additions":["несколько наград"]`, 1)
}

func TestSemanticRepairPreservesUsefulEdit(t *testing.T) {
	source := "Будет выдано пару наград. Игроками была завершена задача."
	draft := "Вы получите несколько наград. Игроки завершили задачу."
	fixed := "Вы получите пару наград. Игроки завершили задачу."
	for _, verdict := range []string{"repair", "reject", "meaning_only_reject"} {
		t.Run(verdict, func(t *testing.T) {
			issue := semanticIssue(verdict)
			if verdict == "meaning_only_reject" {
				issue = criticJSON("reject", analyzers.Finding{RuleID: "meaning.quantity", Severity: "error", Message: "Восстанови исходную точность количества: пару наград."})
			}
			model := &fakeLLM{replies: []string{analysisJSON, draft, issue, fixed, criticJSON("accept")}}
			check := &scriptedAnalyzer{name: "postflight"}
			result := run(t, model, source, "edit", check)
			if !result.Accepted || result.Text != fixed || result.Attempts != 2 || result.FactCheckPassed == nil || !*result.FactCheckPassed {
				t.Fatalf("localized repair discarded useful edit: %+v", result)
			}
			if len(result.UnsupportedAdditions) != 0 || len(result.RejectionReasons) != 0 || strings.Contains(strings.Join(result.FactualRisks, " "), "несколько наград") {
				t.Fatalf("stale rejected draft diagnostics: %+v", result)
			}
			if got := strings.Join(model.stages, ","); got != "analysis,rewrite,critic,repair,critic" {
				t.Fatal(got)
			}
			if len(check.inputs) != 3 || check.inputs[2].Text != fixed {
				t.Fatalf("repair bypassed postflight: %+v", check.inputs)
			}
			payload := lastUserJSON(t, model.messages[3])
			if payload["source"] != source || payload["candidate"] != draft || len(findingsOf(t, payload, "findings")) == 0 {
				t.Fatalf("repair lacks source, candidate, or local finding: %+v", payload)
			}
		})
	}
}

func TestSemanticRepairRemainsFailClosed(t *testing.T) {
	source := "Будет выдано пару наград. Игроками была завершена задача."
	draft := "Вы получите несколько наград. Игроки завершили задачу."
	issue := semanticIssue("repair")
	for _, tc := range []struct {
		name     string
		replies  []string
		fail     map[int]error
		attempts int
		reason   string
	}{
		{"exhausted", []string{analysisJSON, draft, issue, draft, issue, draft, issue}, nil, 3, ReasonUnsupportedFacts},
		{"repair_error", []string{analysisJSON, draft, issue}, map[int]error{3: errors.New("repair offline")}, 1, ReasonUnsupportedFacts},
		{"critic_error_after_repair", []string{analysisJSON, draft, issue, "Вы получите пару наград. Игроки завершили задачу."}, map[int]error{4: errors.New("critic offline")}, 2, ReasonCriticUnavailable},
		{"no_actionable_finding", []string{analysisJSON, draft, strings.Replace(criticJSON("accept"), `"no_new_facts":true`, `"no_new_facts":false`, 1)}, nil, 1, ReasonUnsupportedFacts},
		{"reject_without_finding", []string{analysisJSON, draft, criticJSON("reject")}, nil, 1, ReasonCriticRejected},
		{"reject_info_only", []string{analysisJSON, draft, criticJSON("reject", analyzers.Finding{RuleID: "review.note", Severity: "info", Message: "Проверь смысл."})}, nil, 1, ReasonCriticRejected},
	} {
		t.Run(tc.name, func(t *testing.T) {
			model := &fakeLLM{replies: tc.replies, fail: tc.fail}
			result := run(t, model, source, "edit")
			if result.Accepted || result.Text != source || result.Attempts != tc.attempts || !strings.Contains(strings.Join(result.RejectionReasons, ","), tc.reason) {
				t.Fatalf("unsafe repair result: %+v", result)
			}
			if tc.name == "exhausted" && strings.Count(strings.Join(model.stages, ","), "repair") != MaxRepairs {
				t.Fatal("repair budget not enforced", model.stages)
			}
		})
	}
}

func TestSemanticRepairDoesNotExpandProofread(t *testing.T) {
	source := "Вы получите пару наград."
	model := &fakeLLM{replies: []string{"Вы получите несколько наград.", semanticIssue("repair")}}
	result := run(t, model, source, "proofread")
	if result.Accepted || result.Text != source || result.Attempts != 1 || strings.Contains(strings.Join(model.stages, ","), "repair") {
		t.Fatalf("proofread unexpectedly repaired: %+v %v", result, model.stages)
	}
}
