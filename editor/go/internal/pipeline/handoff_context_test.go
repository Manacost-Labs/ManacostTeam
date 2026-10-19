package pipeline

import (
	"context"
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

func TestCompilerFixtureSurvivesGoAndReachesBothConsumers(t *testing.T) {
	data, err := os.ReadFile("../../../../tests/fixtures/editorial-boundary.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Handoff ResearchHandoff `json:"handoff"`
	}
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	h := &fixture.Handoff
	if err := h.Validate(); err != nil {
		t.Fatal(err)
	}
	serialized, err := json.Marshal(h)
	if err != nil {
		t.Fatal(err)
	}
	var restored ResearchHandoff
	if err := json.Unmarshal(serialized, &restored); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(*h, restored) {
		t.Fatal("metadata lost in save/load")
	}
	writer := &fakeLLM{replies: []string{"draft"}}
	reviewer := &fakeLLM{replies: []string{`{}`}}
	s := New(writer, nil, "fake")
	s.Reviewer = reviewer
	_, _ = s.rewrite(context.Background(), Request{Mode: "reconstruct", Handoff: h}, rules.Build(nil, "GUIDE", "переплавка", "ru-RU", nil), Analysis{}, nil)
	_, _ = s.factReview(context.Background(), h, "draft")
	for _, payload := range []string{writer.messages[0][1].Content, reviewer.messages[0][1].Content} {
		for _, marker := range []string{"synthetic-origin", "confidence_basis", "counterevidence", "EVD-2", "CARD-1", "data_window", "semantic_reviews", "CTR-1"} {
			if !strings.Contains(payload, marker) {
				t.Errorf("compiler fixture lost %s", marker)
			}
		}
	}
}

func TestCounterevidenceMustMatchInspectedReferences(t *testing.T) {
	for _, malformed := range []string{`{"challenging_evidence_ids":["missing"]}`, `{"counterevidence":"bad"}`, `{"counterevidence":[{"evidence_id":"x"}]}`} {
		h := readyHandoff()
		_ = json.Unmarshal([]byte(malformed), &h.Claims[0].ResearchContext)
		if h.Validate() == nil {
			t.Errorf("accepted malformed context %s", malformed)
		}
	}
}

func richHandoffJSON(t *testing.T) []byte {
	t.Helper()
	data, _ := json.Marshal(readyHandoff())
	var raw map[string]any
	_ = json.Unmarshal(data, &raw)
	source := raw["sources"].([]any)[0].(map[string]any)
	source["original_source_id"] = "ORIGINAL"
	source["source_context"] = map[string]any{"lineage_id": "original-lineage", "published_at": "2026-10-01"}
	source["evidence_context"] = map[string]any{"evidence_type": "expert_analysis", "sample": map[string]any{"size": 40}}
	source["content_sha256"] = strings.Repeat("a", 64)
	source["claim_hashes"] = map[string]any{"CLM-1": strings.Repeat("b", 64)}
	raw["claims"].([]any)[0].(map[string]any)["research_context"] = map[string]any{"confidence_basis": "scoped", "inference_steps": []any{"apply condition"}}
	chapter := raw["chapters"].([]any)[0].(map[string]any)
	chapter["decision_cards"] = []any{map[string]any{"card_id": "CARD-1", "kind": "illustrative", "status": "inference", "question": "When?", "gaps": []string{}, "fields": map[string]any{"action": map[string]any{"text": "Keep the resource", "claim_ids": []string{"CLM-1"}, "evidence_refs": []string{"SRC-1"}}}}}
	out, _ := json.Marshal(raw)
	return out
}

func TestRichHandoffReachesWriterAndFactReviewer(t *testing.T) {
	var h ResearchHandoff
	if err := json.Unmarshal(richHandoffJSON(t), &h); err != nil {
		t.Fatal(err)
	}
	if err := h.Validate(); err != nil {
		t.Fatal(err)
	}
	writer := &fakeLLM{replies: []string{"draft"}}
	reviewer := &fakeLLM{replies: []string{`{}`}}
	s := New(writer, nil, "fake")
	s.Reviewer = reviewer
	_, _ = s.rewrite(context.Background(), Request{Mode: "reconstruct", Handoff: &h}, rules.Build(nil, "GUIDE", "переплавка", "ru-RU", nil), Analysis{}, nil)
	_, _ = s.factReview(context.Background(), &h, "draft")
	for _, messages := range []string{writer.messages[0][1].Content, reviewer.messages[0][1].Content} {
		for _, value := range []string{"original-lineage", "expert_analysis", "confidence_basis", "CARD-1", "claim_hashes"} {
			if !strings.Contains(messages, value) {
				t.Errorf("lost %s in consumer payload", value)
			}
		}
	}
}

func TestDecisionCardRejectsUnsupportedField(t *testing.T) {
	var payload map[string]any
	_ = json.Unmarshal(richHandoffJSON(t), &payload)
	payload["chapters"].([]any)[0].(map[string]any)["decision_cards"].([]any)[0].(map[string]any)["fields"].(map[string]any)["action"].(map[string]any)["evidence_refs"] = []string{"unknown"}
	data, _ := json.Marshal(payload)
	var h ResearchHandoff
	_ = json.Unmarshal(data, &h)
	if h.Validate() == nil {
		t.Fatal("unknown card evidence accepted")
	}
}
