package pipeline

import (
	"crypto/sha256"
	"fmt"
	"strings"
)

// EvidenceSnapshot is supplied by the research reader, never fetched from a
// caller-controlled path or URL. Hashes bind bytes, not factual authority.
type EvidenceSnapshot struct {
	URL    string `json:"url"`
	Text   string `json:"text"`
	SHA256 string `json:"sha256"`
}

func (h *ResearchHandoff) validateEvidenceSnapshots() error {
	if len(h.EvidenceSnapshots) > 8 {
		return fmt.Errorf("too many evidence snapshots")
	}
	known := map[string]bool{}
	for _, source := range h.Sources {
		known[source.URL] = true
	}
	seen := map[string]bool{}
	total := 0
	added := 0
	for _, snapshot := range h.EvidenceSnapshots {
		total += len([]rune(snapshot.Text))
		if !known[snapshot.URL] || seen[snapshot.URL] || strings.TrimSpace(snapshot.Text) == "" || len([]rune(snapshot.Text)) > 100000 || total > 150000 || snapshot.SHA256 != fmt.Sprintf("%x", sha256.Sum256([]byte(snapshot.Text))) {
			return fmt.Errorf("invalid, foreign or duplicate evidence snapshot")
		}
		seen[snapshot.URL] = true
		for _, source := range h.Sources {
			if source.URL == snapshot.URL && strings.Count(snapshot.Text, source.Quote) != 1 {
				return fmt.Errorf("snapshot quote absent or ambiguous: %s", source.ID)
			}
			if source.URL == snapshot.URL {
				added += len([]rune(quoteContext(snapshot.Text, source.Quote))) - len([]rune(source.Quote))
				if added > 100000 {
					return fmt.Errorf("evidence context expansion exceeds budget")
				}
			}
		}
	}
	for _, source := range h.Sources {
		if source.ContextQuote == "" {
			continue
		}
		valid := false
		for _, snapshot := range h.EvidenceSnapshots {
			valid = valid || (source.URL == snapshot.URL && source.ContextQuote == quoteContext(snapshot.Text, source.Quote))
		}
		if !valid {
			return fmt.Errorf("context_quote must equal the server derivation")
		}
	}
	return nil
}

// Expand only around exact unique anchors. Preserve the input, refs, original
// quote, locators and numeric baseline; all evidence still needs fact review.
func (h *ResearchHandoff) withEvidenceContext() *ResearchHandoff {
	out := *h
	out.Sources = append([]ResearchSource(nil), h.Sources...)
	for i, source := range out.Sources {
		for _, snapshot := range h.EvidenceSnapshots {
			if snapshot.URL == source.URL {
				out.Sources[i].ContextQuote = quoteContext(snapshot.Text, source.Quote)
			}
		}
	}
	return &out
}

func quoteContext(text, quote string) string {
	at := strings.Index(text, quote)
	if at < 0 {
		return ""
	}
	start := strings.LastIndex(text[:at], "\n") + 1
	if start > 0 {
		start = strings.LastIndex(text[:start-1], "\n") + 1
	}
	end := at + len(quote)
	for i := 0; i < 3 && end < len(text); i++ {
		next := strings.Index(text[end:], "\n")
		if next < 0 {
			end = len(text)
			break
		}
		end += next + 1
	}
	// At most 200 runes before and 1000 after the unchanged quote, so a long
	// paragraph cannot inflate every source into another full article.
	before := []rune(text[start:at])
	after := []rune(text[at+len(quote) : end])
	if len(before) > 200 {
		before = before[len(before)-200:]
	}
	if len(after) > 1000 {
		after = after[:1000]
	}
	return string(before) + quote + string(after)
}
