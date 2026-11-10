package pipeline

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzers"
	"github.com/Manacost-Labs/EditorTeam/go/internal/editorialreview"
	"github.com/Manacost-Labs/EditorTeam/go/internal/llm"
	"github.com/Manacost-Labs/EditorTeam/go/internal/reviewfixture"
	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

func TestOwnerIssueRemainsRepairWithQuoteWithoutSchemaRetry(t *testing.T) {
	text := "Синтетический совет."
	in := criticInput{Source: text, Candidate: text, Mode: "edit"}
	payload, _ := json.Marshal(in)
	var fields map[string]json.RawMessage
	_ = json.Unmarshal([]byte(reviewfixture.Complete(criticJSONNoImprovement(), string(payload))), &fields)
	var rows []editorialreview.Check
	_ = json.Unmarshal(fields["owner_checks"], &rows)
	rows[0].Status, rows[0].Reason = "issue", "Не добавляет решения."
	fields["owner_checks"], _ = json.Marshal(rows)
	raw, _ := json.Marshal(fields)
	model := &fakeLLM{replies: []string{string(raw)}}
	out, err := New(model, nil, "fake").critic(context.Background(), rules.RuleBundle{}, in, 1)
	if err != nil || out.Verdict != "repair" || !out.RepairRequired || len(model.messages) != 1 {
		t.Fatalf("negative judgment lost: %+v %v", out, err)
	}
	for _, finding := range out.Findings {
		if finding.RuleID == "owner_review.card_text_retelling" && finding.Evidence == text {
			return
		}
	}
	t.Fatal("repair lost the quoted fragment")
}

func TestOwnerRubricCannotSkipCategoryOrQuote(t *testing.T) {
	for _, defect := range []string{"missing", "quote"} {
		t.Run(defect, func(t *testing.T) {
			in := criticInput{Source: "Совет.", Candidate: "Совет.", Mode: "edit"}
			payload, _ := json.Marshal(in)
			var fields map[string]json.RawMessage
			_ = json.Unmarshal([]byte(reviewfixture.Complete(criticJSONNoImprovement(), string(payload))), &fields)
			var rows []editorialreview.Check
			_ = json.Unmarshal(fields["owner_checks"], &rows)
			if defect == "missing" {
				rows = rows[:len(rows)-1]
			} else {
				rows[0].Quote = ""
			}
			fields["owner_checks"], _ = json.Marshal(rows)
			raw, _ := json.Marshal(fields)
			model := &fakeLLM{replies: []string{string(raw)}}
			_, err := New(model, nil, "fake").critic(context.Background(), rules.RuleBundle{}, in, 1)
			if err == nil || !strings.Contains(err.Error(), "owner_checks") {
				t.Fatalf("incomplete rubric accepted: %v", err)
			}
		})
	}
}

type deletionModel struct{ seen bool }

func (m *deletionModel) Model() string { return "synthetic" }
func (m *deletionModel) Complete(_ context.Context, messages []llm.Message, _ int) (string, error) {
	m.seen = strings.Contains(messages[0].Content, "DELETION_PASS")
	var input struct {
		ArticleSHA256 string              `json:"article_sha256"`
		ToolFindings  []analyzers.Finding `json:"tool_findings"`
	}
	_ = json.Unmarshal([]byte(messages[1].Content), &input)
	if len(input.ToolFindings) != 1 || input.ToolFindings[0].RuleID != "owner.section_repeat" {
		m.seen = false
	}
	raw, _ := json.Marshal(map[string]any{"article_sha256": input.ArticleSHA256, "deletions": []map[string]any{{"start": 6, "quote": " Рамка.", "reason": "Не меняет решение."}}})
	return string(raw), nil
}

func TestDeletionStageReceivesDiagnosticsAndReturnsOnlyRemovals(t *testing.T) {
	model := &deletionModel{}
	text, receipt, err := New(model, nil, "fake").deletionPass(context.Background(), "Совет. Рамка.", []analyzers.Finding{{RuleID: "owner.section_repeat"}})
	if err != nil || !model.seen || text != "Совет." || len(receipt.Deletions) != 1 {
		t.Fatalf("bad cut stage: %q %+v %v", text, receipt, err)
	}
}

func TestClaimSemanticsSurvivePublicationHandoffWithoutClassifyingOldClaims(t *testing.T) {
	for _, kind := range []string{"mechanic", "observation", "opinion"} {
		t.Run(kind, func(t *testing.T) {
			reason := "Verified synthetic rule."
			if kind == "observation" {
				reason = "в источниках не найдено"
			}
			raw, _ := json.Marshal(map[string]any{"claims": []map[string]any{{"claim_id": "new", "claim_kind": kind, "reason": reason, "attribution": map[string]any{"name": "Synthetic player"}}, {"claim_id": "old"}}})
			var handoff ResearchHandoff
			if err := json.Unmarshal(raw, &handoff); err != nil {
				t.Fatal(err)
			}
			output, err := publicationHandoff(&handoff)
			if err != nil || output.Claims[0].ClaimKind != kind || output.Claims[0].Reason != reason || output.Claims[0].Attribution["name"] != "Synthetic player" || output.Claims[1].ClaimKind != "" {
				t.Fatalf("claim semantics lost: %+v %v", output, err)
			}
		})
	}
}
