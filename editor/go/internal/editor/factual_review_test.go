package editor

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzer"
	"github.com/Manacost-Labs/EditorTeam/go/internal/llm"
	"github.com/Manacost-Labs/EditorTeam/go/internal/reviewfixture"
)

const goodFactualReview = `{"no_new_facts":true,"unsupported_additions":[],"verdict":"accept","scores":{"factual_preservation":8,"meaning_preservation":8,"clarity":8,"structure":8,"usefulness":8,"natural_russian":8,"author_voice":8,"terminology":8},"improvements":[],"regressions":[],"findings":[],"repair_required":false}`

type factualModel struct {
	draft, review string
	reviews       int
	last          []llm.Message
}

func (m *factualModel) Model() string { return "factual-test" }
func (m *factualModel) Complete(_ context.Context, messages []llm.Message, _ int) (string, error) {
	m.last = append([]llm.Message(nil), messages...)
	if strings.Contains(messages[0].Content, "Ты critic") {
		m.reviews++
		if m.review == goodFactualReview && len(messages) > 1 {
			return reviewfixture.Complete(m.review, messages[1].Content), nil
		}
		return m.review, nil
	}
	return m.draft, nil
}

func TestLegacyModesRequireFactualReview(t *testing.T) {
	for _, mode := range Depths {
		for _, review := range []string{
			strings.Replace(goodFactualReview, `"no_new_facts":true`, `"no_new_facts":false`, 1),
			strings.Replace(goodFactualReview, `"unsupported_additions":[]`, `"unsupported_additions":["замораживает цель"]`, 1),
			`{"verdict":"accept"}`,
			strings.Replace(goodFactualReview, `"factual_preservation":8`, `"factual_preservation":0`, 1),
			strings.Replace(goodFactualReview, `"findings":[]`, `"findings":[{"rule_id":"fact","severity":"critical","message":"Факт потерян"}]`, 1),
		} {
			t.Run(fmt.Sprintf("%s/%s", mode, review[:20]), func(t *testing.T) {
				an := fakeAnalyzer(t, []analyzer.Verdict{{Accepted: true}})
				defer an.Close()
				model := &factualModel{draft: "Способность наносит урон и замораживает цель.", review: review}
				service := New(model, analyzer.New(an.URL, time.Second), 1)
				result, err := service.Edit(context.Background(), Request{Text: "Способность наносит урон.", Game: "hearthstone", Mode: mode})
				if err != nil {
					t.Fatal(err)
				}
				if result.Accepted || result.Text != "Способность наносит урон." || model.reviews == 0 {
					t.Fatalf("unsafe legacy result=%+v review_calls=%d", result, model.reviews)
				}
			})
		}
	}
}

func TestLegacyPreservesValidAndUnchangedResults(t *testing.T) {
	for _, candidate := range []string{"Способность наносит урон.", "Способность причиняет урон."} {
		an := fakeAnalyzer(t, []analyzer.Verdict{{Accepted: true}})
		model := &factualModel{draft: candidate, review: goodFactualReview}
		result, err := New(model, analyzer.New(an.URL, time.Second), 1).Edit(context.Background(), Request{Text: "Способность наносит урон.", Game: "hearthstone"})
		an.Close()
		if err != nil || !result.Accepted || result.Text != candidate {
			t.Fatalf("valid legacy edit failed: result=%+v error=%v", result, err)
		}
		if result.ReviewScope != "source_and_candidate" || result.SourceVerification != "not_performed" {
			t.Fatalf("legacy result must expose truthful review scope: %+v", result)
		}
		if candidate != "Способность наносит урон." && model.reviews != 1 {
			t.Fatal("changed text must be reviewed")
		}
	}
}

func TestLegacyFactualReviewDeclaresSourceAndCandidateScope(t *testing.T) {
	an := fakeAnalyzer(t, []analyzer.Verdict{{Accepted: true}})
	defer an.Close()
	model := &factualModel{draft: "Способность причиняет урон.", review: goodFactualReview}
	result, err := New(model, analyzer.New(an.URL, time.Second), 1).Edit(context.Background(), Request{Text: "Способность наносит урон.", Game: "hearthstone"})
	if err != nil || !result.Accepted {
		t.Fatalf("valid legacy edit failed: result=%+v error=%v", result, err)
	}
	var payload map[string]any
	if len(model.last) < 2 || json.Unmarshal([]byte(model.last[1].Content), &payload) != nil {
		t.Fatal("factual reviewer payload was not captured")
	}
	if payload["review_scope"] != "source_and_candidate" || payload["source_verification"] != "not_performed" {
		t.Fatalf("legacy review scope was not explicit: %#v", payload)
	}
}

func TestLegacyUsesSeparateReviewer(t *testing.T) {
	an := fakeAnalyzer(t, []analyzer.Verdict{{Accepted: true}})
	defer an.Close()
	writer := &factualModel{draft: "Способность причиняет урон.", review: `{"verdict":"reject"}`}
	reviewer := &factualModel{review: goodFactualReview}
	service := New(writer, analyzer.New(an.URL, time.Second), 1)
	service.Reviewer = reviewer
	result, err := service.Edit(context.Background(), Request{Text: "Способность наносит урон.", Game: "hearthstone"})
	if err != nil || !result.Accepted || writer.reviews != 0 || reviewer.reviews != 1 {
		t.Fatalf("reviewer was not isolated: result=%+v error=%v writer_reviews=%d reviewer_reviews=%d", result, err, writer.reviews, reviewer.reviews)
	}
}
