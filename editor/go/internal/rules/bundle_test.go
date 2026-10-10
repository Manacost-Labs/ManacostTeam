package rules

import (
	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzer"
	"reflect"
	"strings"
	"testing"
)

func TestAdviceConditionsAndEvidenceSurvivePromptFiltering(t *testing.T) {
	claim := map[string]any{"claim_id": "CLM-1", "meaning": "совет", "action": "сохранить ресурс", "condition": "слабая позиция", "exception": "риск поражения", "evidence_refs": []string{"SRC-1"}, "status": "supported_with_conditions", "source": "private-token"}
	got := Build(nil, "GUIDE", "обычная", "ru-RU", []map[string]any{claim}).SourceClaims[0]
	for _, key := range []string{"action", "condition", "exception", "evidence_refs", "status"} {
		if !reflect.DeepEqual(got[key], claim[key]) {
			t.Errorf("lost %s: %#v", key, got)
		}
	}
	if _, ok := got["source"]; ok {
		t.Fatal("private source field leaked")
	}
}

func TestBuildIsCompactAndKeepsClaimContract(t *testing.T) {
	r := &analyzer.Rules{Game: "hearthstone", Profile: "analytics-article", Keep: []string{"винрейт"}, Replace: []map[string]string{{"from": "дека", "to": "колода"}}}
	b := Build(r, "GUIDE", "обычная", "ru-RU", []map[string]any{{"claim_id": "c1", "meaning": "fact", "source": "secret"}})
	if b.Task == "" || len(b.SourceClaims) != 1 || len(b.ProtectedEntities) == 0 {
		t.Fatalf("неполный bundle: %+v", b)
	}
	prompt := b.Prompt()
	if strings.Contains(prompt, "secret") {
		t.Fatalf("backstage-поле попало в prompt: %s", prompt)
	}
	if !strings.Contains(prompt, "винрейт") || !strings.Contains(prompt, "дека → колода") {
		t.Fatalf("термины потеряны: %s", prompt)
	}
}
