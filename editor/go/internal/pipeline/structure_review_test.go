package pipeline

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/editorialreview"
	"github.com/Manacost-Labs/EditorTeam/go/internal/reviewfixture"
	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

func TestCriticReceivesStructureInventoryAndExportsItsReview(t *testing.T) {
	text := "# Выбор\n\nОснование.\n\nДействие при этом условии."
	model := &fakeLLM{replies: []string{criticJSONNoImprovement()}}
	report, err := ReviewEdit(context.Background(), model, text, text, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	var input criticInput
	if err := json.Unmarshal([]byte(model.messages[0][1].Content), &input); err != nil {
		t.Fatal(err)
	}
	if input.StructureAssignment == nil || len(input.StructureAssignment.Blocks) != 3 || input.StructureAssignment.Blocks[1].Quote != "Основание." {
		t.Fatalf("critic missed actual text blocks: %+v", input.StructureAssignment)
	}
	if report.StructureReview == nil || report.StructureReview.ArticleSHA256 != input.StructureAssignment.ArticleSHA256 {
		t.Fatal("review hash not propagated")
	}
	encoded, err := json.Marshal(report)
	if err != nil || !strings.Contains(string(encoded), `"structure_review"`) {
		t.Fatalf("Python bridge loses structure review: %s %v", encoded, err)
	}
}

func TestCriticCannotAcceptSkippedBodyOrUnresolvedStructure(t *testing.T) {
	text := "Первое условие.\n\nДругой совет.\n\nПервое условие."
	in := criticInput{Source: text, Candidate: text, Mode: "edit"}
	payload, _ := json.Marshal(in)
	for _, defect := range []string{"missing", "skipped_body", "issue"} {
		t.Run(defect, func(t *testing.T) {
			var fields map[string]json.RawMessage
			if err := json.Unmarshal([]byte(reviewfixture.Complete(criticJSONNoImprovement(), string(payload))), &fields); err != nil {
				t.Fatal(err)
			}
			if defect == "missing" {
				fields["structure_review"] = json.RawMessage(`null`)
			} else {
				var review editorialreview.StructureReview
				if err := json.Unmarshal(fields["structure_review"], &review); err != nil {
					t.Fatal(err)
				}
				if defect == "skipped_body" {
					review.Blocks = review.Blocks[:1]
				} else {
					review.Blocks[1].Status = "issue"
				}
				fields["structure_review"], _ = json.Marshal(review)
			}
			raw, _ := json.Marshal(fields)
			model := &fakeLLM{replies: []string{string(raw)}}
			_, err := New(model, nil, "fake").critic(context.Background(), rules.RuleBundle{}, in, 1)
			if err == nil || err.Kind != ReasonCriticInvalid {
				t.Fatalf("defect accepted: %v", err)
			}
		})
	}
}

func TestStructureIssueRemainsAValidRepairWithActionableFinding(t *testing.T) {
	text := "Первое основание.\n\nВывод без условия."
	in := criticInput{Source: text, Candidate: text, Mode: "edit"}
	payload, _ := json.Marshal(in)
	raw := reviewfixture.Complete(criticJSONNoImprovement(), string(payload))
	var fields map[string]json.RawMessage
	_ = json.Unmarshal([]byte(raw), &fields)
	var review editorialreview.StructureReview
	_ = json.Unmarshal(fields["structure_review"], &review)
	review.Blocks[1].Status, review.Blocks[1].Reason = "issue", "Fixture: conclusion lost the earlier condition."
	fields["structure_review"], _ = json.Marshal(review)
	fields["verdict"], fields["repair_required"] = json.RawMessage(`"repair"`), json.RawMessage(`true`)
	encoded, _ := json.Marshal(fields)
	model := &fakeLLM{replies: []string{string(encoded)}}
	out, err := New(model, nil, "fake").critic(context.Background(), rules.RuleBundle{}, in, 1)
	if err != nil || out.Verdict != "repair" {
		t.Fatalf("truthful structural rejection lost: %+v %v", out, err)
	}
	for _, finding := range out.Findings {
		if finding.RuleID == "article_structure.b002" && finding.Evidence == "Вывод без условия." {
			return
		}
	}
	t.Fatal("repair lacks the affected passage")
}
