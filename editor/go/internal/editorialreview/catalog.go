// Package editorialreview provides the shared, source-backed practice catalog
// used by writer, critic, and targeted repair prompts.
package editorialreview

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
)

//go:embed practices.json
var catalogBytes []byte

type Practice struct {
	ID            string `json:"id"`
	Section       string `json:"section"`
	Owner         string `json:"owner"`
	Question      string `json:"question"`
	Acceptable    string `json:"acceptable"`
	Action        string `json:"action"`
	DefectExample string `json:"defect_example,omitempty"`
}

type Catalog struct {
	Version    int        `json:"version"`
	SourceURL  string     `json:"source_url"`
	Principles []string   `json:"principles"`
	Practices  []Practice `json:"practices"`
}

func Load() (Catalog, error) {
	var c Catalog
	if err := json.Unmarshal(catalogBytes, &c); err != nil {
		return c, fmt.Errorf("editorial practices: %w", err)
	}
	if c.Version != 1 {
		return c, fmt.Errorf("editorial practices: unsupported version %d", c.Version)
	}
	seen := map[string]bool{}
	for _, p := range c.Practices {
		if strings.TrimSpace(p.ID) == "" || seen[p.ID] {
			return c, fmt.Errorf("editorial practices: duplicate or empty id %q", p.ID)
		}
		if p.Owner != "fact_review" && p.Owner != "literary_review" {
			return c, fmt.Errorf("editorial practices: invalid owner for %s", p.ID)
		}
		seen[p.ID] = true
	}
	return c, nil
}

// Prompt renders the catalog as model guidance. It deliberately describes
// contextual questions and local actions; it never creates a forbidden-word
// list or an authorship/detector score.
func Prompt() string {
	c, err := Load()
	if err != nil {
		return "\nEDITORIAL_PRACTICES unavailable: do not infer missing practices.\n"
	}
	var b strings.Builder
	b.WriteString("\nEDITORIAL_PRACTICES: проверяй каждую практику по контексту, а не по словам или вероятности авторства. ")
	if len(c.Principles) > 0 {
		b.WriteString("Принципы: ")
		b.WriteString(strings.Join(c.Principles, "; "))
		b.WriteString(". ")
	}
	for _, p := range c.Practices {
		fmt.Fprintf(&b, "[%s|%s] вопрос: %s; ясно, если: %s; при проблеме: %s", p.ID, p.Owner, p.Question, p.Acceptable, p.Action)
		if p.DefectExample != "" {
			fmt.Fprintf(&b, "; пример риска: %s", p.DefectExample)
		}
		b.WriteString(". ")
	}
	b.WriteString("Отдельные слова, длина фраз, обращения и неровный ритм сами по себе не являются дефектом. Сохраняй подтвержденные факты, условия, модальность и голос автора.")
	return b.String()
}

type Check struct {
	ID            string `json:"id"`
	Status        string `json:"status"`
	Quote         string `json:"quote"`
	Reason        string `json:"reason"`
	ReaderProblem string `json:"reader_problem,omitempty"`
	Benefit       string `json:"benefit,omitempty"`
	MeaningRisk   string `json:"meaning_risk,omitempty"`
	Suggestion    string `json:"suggestion,omitempty"`
}

// ValidateChecks enforces exact catalog coverage and candidate-grounded quotes.
// factsOnly retains only factual-owner practices; proofread still diagnoses all
// applicable practices, while the caller controls that no style rewrite occurs.
func ValidateChecks(candidate string, checks []Check, factsOnly bool) error {
	c, err := Load()
	if err != nil {
		return err
	}
	want := make(map[string]Practice)
	for _, p := range c.Practices {
		if !factsOnly || p.Owner == "fact_review" {
			want[p.ID] = p
		}
	}
	got := make(map[string]bool)
	for _, ch := range checks {
		p, ok := want[ch.ID]
		if !ok {
			return fmt.Errorf("practice_checks: unknown or inapplicable id %q", ch.ID)
		}
		if got[ch.ID] {
			return fmt.Errorf("practice_checks: duplicate id %q", ch.ID)
		}
		got[ch.ID] = true
		status := strings.ToLower(strings.TrimSpace(ch.Status))
		if status != "clear" && status != "not_applicable" && status != "issue" && status != "unverified" {
			return fmt.Errorf("practice_checks: invalid status for %s", ch.ID)
		}
		if strings.TrimSpace(ch.Reason) == "" {
			return fmt.Errorf("practice_checks: %s %s requires reason", ch.ID, status)
		}
		if status == "clear" || status == "issue" {
			if strings.TrimSpace(ch.Quote) == "" || !strings.Contains(candidate, ch.Quote) {
				return fmt.Errorf("practice_checks: %s quote must be nonempty and occur in candidate", ch.ID)
			}
		}
		if (status == "not_applicable" || status == "unverified") && strings.TrimSpace(ch.Quote) != "" && !strings.Contains(candidate, ch.Quote) {
			return fmt.Errorf("practice_checks: %s optional quote must occur in candidate", ch.ID)
		}
		if status == "issue" && (strings.TrimSpace(ch.ReaderProblem) == "" || strings.TrimSpace(ch.Benefit) == "" || strings.TrimSpace(ch.MeaningRisk) == "" || strings.TrimSpace(ch.Suggestion) == "") {
			return fmt.Errorf("practice_checks: issue %s requires reader_problem, benefit, meaning_risk, suggestion", ch.ID)
		}
		_ = p
	}
	var missing []string
	for id := range want {
		if !got[id] {
			missing = append(missing, id)
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		return fmt.Errorf("practice_checks: missing ids %s", strings.Join(missing, ", "))
	}
	return nil
}
