package editor

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzer"
	"github.com/Manacost-Labs/EditorTeam/go/internal/editorialreview"
	"github.com/Manacost-Labs/EditorTeam/go/internal/reviewfixture"
)

func TestLegacySourceCorrectionRevalidatesAfterIndependentReview(t *testing.T) {
	const before = "Карта стоит 3 маны."
	const after = "Карта стоит 4 маны."
	body := "Стоимость карты повышена с 3 до 4 маны."
	sources := []editorialreview.SourceSnapshot{{SourceID: "patch", URL: "https://example.org/patch", RetrievedAt: "2026-10-23T00:00:00Z", Access: "snapshot", Text: body, SHA256: fmt.Sprintf("%x", sha256.Sum256([]byte(body)))}}
	payload, _ := json.Marshal(map[string]any{"source": before, "candidate": after, "source_snapshots": sources})
	var response map[string]any
	_ = json.Unmarshal([]byte(reviewfixture.Complete(goodFactualReview, string(payload))), &response)
	response["original_factual_checks"] = map[string]any{"whole_text_checked": true, "internal_consistency": "clear", "source_agreement": "issue", "issues": []any{map[string]any{"quote": before, "reason": "Стоимость в исходнике устарела для заданного периода.", "resolution": "corrected", "correction_quote": after, "source_id": "patch", "evidence_quote": body}}}
	review, _ := json.Marshal(response)
	for _, mode := range Depths {
		t.Run(mode, func(t *testing.T) {
			for _, secondAccepted := range []bool{true, false} {
				an := fakeAnalyzer(t, []analyzer.Verdict{{Accepted: false, Violations: []analyzer.Violation{{Kind: "protected_lost", Message: "Число изменено."}}}, {Accepted: true}})
				if !secondAccepted {
					an.Close()
					an = fakeAnalyzer(t, []analyzer.Verdict{{Accepted: false}, {Accepted: false, Violations: []analyzer.Violation{{Kind: "meaning_changed", Message: "Другая ошибка осталась."}}}})
				}
				defer an.Close()
				model := &factualModel{draft: after, review: string(review)}
				result, err := New(model, analyzer.New(an.URL, time.Second), 1).Edit(context.Background(), Request{Text: before, Game: "hearthstone", Mode: mode, SourceSnapshots: sources})
				wantText := before
				if secondAccepted {
					wantText = after
				}
				if err != nil || result.Accepted != secondAccepted || result.Text != wantText || model.reviews != 1 || result.EditorialReview == nil {
					t.Fatalf("verified source correction failed: result=%+v reviews=%d err=%v", result, model.reviews, err)
				}
			}
		})
	}
}
