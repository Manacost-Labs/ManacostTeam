package pipeline

import (
	"context"
	"fmt"

	"github.com/Manacost-Labs/EditorTeam/go/internal/editorialreview"
	"github.com/Manacost-Labs/EditorTeam/go/internal/llm"
	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

// ReviewFactualEdit preserves the old Go entrypoint while performing the full
// contextual review. An unchanged input can still contain a factual error.
func ReviewFactualEdit(ctx context.Context, model llm.Completer, source, candidate string, claims []map[string]any) error {
	_, err := ReviewEdit(ctx, model, source, candidate, claims, nil)
	return err
}

type EditReview struct {
	PracticeChecks        []editorialreview.Check       `json:"practice_checks"`
	LogicChecks           []editorialreview.Check       `json:"logic_checks"`
	PreservationChecks    []editorialreview.Check       `json:"preservation_checks"`
	SourceChecks          []editorialreview.SourceCheck `json:"source_checks"`
	OriginalFactualChecks *OriginalFactualChecks        `json:"original_factual_checks"`
	ReviewScope           string                        `json:"review_scope"`
	SourceVerification    string                        `json:"source_verification"`
	reviewedSource        string
	preservationSource    string
}

// PreservationSource returns an evidence-corrected baseline only after this
// exact original passed independent review. Public report fields cannot grant it.
func (r *EditReview) PreservationSource(original string) string {
	if r == nil || r.reviewedSource != original || r.preservationSource == "" {
		return original
	}
	return r.preservationSource
}

func ReviewEdit(ctx context.Context, model llm.Completer, source, candidate string, claims []map[string]any, snapshots []editorialreview.SourceSnapshot) (*EditReview, error) {
	if err := editorialreview.ValidateSources(snapshots); err != nil {
		return nil, err
	}
	if model == nil {
		return nil, fmt.Errorf("проверяющая модель недоступна")
	}
	service := New(model, nil, "")
	verdict, err := service.critic(ctx, rules.RuleBundle{}, criticInput{
		Source: source, Candidate: candidate, Diff: diff(source, candidate),
		Mode: "facts_only", SourceClaims: claims, SourceSnapshots: snapshots,
	}, 1)
	if err != nil {
		return nil, err
	}
	report := &EditReview{PracticeChecks: verdict.PracticeChecks, LogicChecks: verdict.LogicChecks, PreservationChecks: verdict.PreservationChecks, SourceChecks: verdict.SourceChecks, OriginalFactualChecks: verdict.OriginalFactualChecks, ReviewScope: verdict.ReviewScope, SourceVerification: verdict.SourceVerification}
	if verdict.Verdict != "accept" || !verdict.NoNewFacts || len(verdict.UnsupportedAdditions) > 0 {
		return report, fmt.Errorf("не подтверждены факты, логика, смысл и голос; добавления: %v; замечания: %v", verdict.UnsupportedAdditions, verdict.Findings)
	}
	report.reviewedSource, report.preservationSource = source, correctedBaseline(source, verdict.OriginalFactualChecks)
	return report, nil
}
