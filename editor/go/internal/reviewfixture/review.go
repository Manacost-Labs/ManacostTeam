// Package reviewfixture is imported only by tests for unrelated pipeline gates.
// Explicit fields, including invalid ones, are never overwritten. Contract tests
// bypass this helper to exercise missing evidence. It is not a production review.
package reviewfixture

import (
	"encoding/json"

	"github.com/Manacost-Labs/EditorTeam/go/internal/editorialreview"
)

func Complete(raw, payload string) string {
	var fields map[string]json.RawMessage
	var in struct {
		Source, Candidate string
		NewArticle        bool                             `json:"new_article"`
		Snapshots         []editorialreview.SourceSnapshot `json:"source_snapshots"`
	}
	if json.Unmarshal([]byte(raw), &fields) != nil || fields == nil || json.Unmarshal([]byte(payload), &in) != nil {
		return raw
	}
	put := func(key string, value any) {
		if _, present := fields[key]; !present {
			fields[key], _ = json.Marshal(value)
		}
	}
	var practices []editorialreview.Check
	catalog, _ := editorialreview.Load()
	for _, p := range catalog.Practices {
		practices = append(practices, editorialreview.Check{ID: p.ID, Status: "clear", Quote: in.Candidate, Reason: "Fixture: unrelated contextual practice reviewed."})
	}
	put("practice_checks", practices)
	var logic, preservation []editorialreview.Check
	for _, id := range editorialreview.LogicIDs() {
		logic = append(logic, editorialreview.Check{ID: id, Status: "clear", Quote: in.Candidate, Reason: "Fixture: unrelated logic dimension reviewed."})
	}
	for _, id := range editorialreview.PreservationIDs() {
		check := editorialreview.Check{ID: id, Status: "clear", Quote: in.Candidate, OriginalQuote: in.Source, Reason: "Fixture: unrelated preservation dimension reviewed."}
		if !in.NewArticle && in.Source != in.Candidate && (id == "author_voice" || id == "strengths") {
			check.ChangeEvidence = []editorialreview.ChangeEvidence{{OriginalQuote: in.Source, Quote: in.Candidate, Disposition: "justified", Reason: "Fixture: changed passage checked.", Benefit: "Fixture: local readability.", MeaningRisk: "Fixture: no substantive loss in this test."}}
		}
		preservation = append(preservation, check)
	}
	put("logic_checks", logic)
	put("preservation_checks", preservation)
	checks := []editorialreview.SourceCheck{}
	for _, source := range in.Snapshots {
		checks = append(checks, editorialreview.SourceCheck{SourceID: source.SourceID, Status: "verified", EvidenceQuote: source.Text, Reason: "Fixture: supplied source reviewed.", IdentityCheck: "Fixture: source identity matches.", SupportCheck: "Fixture: claim scope matches.", Access: "snapshot"})
	}
	put("source_checks", checks)
	agreement := "not_performed"
	if len(in.Snapshots) > 0 {
		agreement = "supplied_sources_checked"
	}
	put("original_factual_checks", map[string]any{"whole_text_checked": true, "internal_consistency": "clear", "source_agreement": agreement, "issues": []any{}})
	encoded, _ := json.Marshal(fields)
	return string(encoded)
}
