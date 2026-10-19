package pipeline

import (
	"fmt"
	"strings"
)

// Exact quotes anchor the review; they never establish editorial quality alone.
func validateStrengthChanges(in criticInput, out criticResult) error {
	if out.Verdict != "accept" {
		return nil
	}
	for _, span := range in.KeepSpans {
		if strings.Contains(in.Candidate, span.Quote) {
			continue
		}
		matches := 0
		for _, change := range out.StrengthChanges {
			if change.Quote == span.Quote && strings.TrimSpace(change.Reason) != "" && (change.ReplacementQuote == "" || strings.Contains(in.Candidate, change.ReplacementQuote)) {
				matches++
			}
		}
		if matches != 1 {
			return fmt.Errorf("lost keep_span requires one concrete strength_changes explanation")
		}
	}
	return nil
}
