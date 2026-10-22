package pipeline

import (
	"context"
	"fmt"

	"github.com/Manacost-Labs/EditorTeam/go/internal/llm"
	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

// ReviewFactualEdit applies the same source-aware critic and response validator
// to legacy writers without changing their drafting, tools or response format.
func ReviewFactualEdit(ctx context.Context, model llm.Completer, source, candidate string, claims []map[string]any) error {
	if source == candidate {
		return nil // No factual change is possible in byte-identical text.
	}
	if model == nil {
		return fmt.Errorf("проверяющая модель недоступна")
	}
	service := New(model, nil, "")
	verdict, err := service.critic(ctx, rules.RuleBundle{}, criticInput{
		Source: source, Candidate: candidate, Diff: diff(source, candidate),
		Mode: "facts_only", SourceClaims: claims, ReviewScope: "preservation_only", SourceVerification: "not_performed",
	}, 1)
	if err != nil {
		return err
	}
	if verdict.Verdict != "accept" || !verdict.NoNewFacts || len(verdict.UnsupportedAdditions) > 0 {
		return fmt.Errorf("не подтверждено сохранение фактов, смысла и уверенности; добавления: %v", verdict.UnsupportedAdditions)
	}
	return nil
}
