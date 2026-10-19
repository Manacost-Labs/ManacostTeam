package pipeline

import (
	"errors"
	"fmt"
	"strings"

	"github.com/Manacost-Labs/EditorTeam/go/internal/guards"
)

// Exact quotes anchor the review; they never establish editorial quality alone.
func validateStrengthChanges(in criticInput, out criticResult) error {
	if out.Verdict != "accept" {
		return nil
	}
	var invalid []error
	for _, span := range in.KeepSpans {
		if strings.Contains(in.Candidate, span.Quote) || proseSpanPreserved(in.Candidate, span.Quote) {
			continue
		}
		matches := 0
		for _, change := range out.StrengthChanges {
			if change.Quote == span.Quote && strings.TrimSpace(change.Reason) != "" && (change.ReplacementQuote == "" || strings.Contains(in.Candidate, change.ReplacementQuote)) {
				matches++
			}
		}
		if matches != 1 {
			invalid = append(invalid, fmt.Errorf("lost keep_span %q requires one concrete strength_changes explanation with the whole exact quote (got %d)", span.Quote, matches))
		}
	}
	return errors.Join(invalid...)
}

// Paragraph boundaries do not erase a prose strength. Keep exact wording:
// changed words, punctuation, code or markup still need a quoted explanation.
func proseSpanPreserved(candidate, quote string) bool {
	if strings.ContainsAny(quote, "`<>\t") || strings.TrimSpace(quote) == "" {
		return false
	}
	for _, line := range strings.Split(quote, "\n") {
		trimmed := strings.TrimLeft(line, " ")
		if strings.HasPrefix(line, "    ") || (len(trimmed) > 0 && strings.ContainsAny(trimmed[:1], "#>*-+")) {
			return false
		}
	}
	return strings.Contains(guards.NormalizeWhitespace(candidate), guards.NormalizeWhitespace(quote))
}
