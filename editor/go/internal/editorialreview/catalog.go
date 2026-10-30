// Package editorialreview provides the shared, source-backed practice catalog
// used by writer, critic, and targeted repair prompts.
package editorialreview

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"sort"
	"strings"
	"unicode"
)

//go:embed practices.json
var catalogBytes []byte

type Practice struct {
	ID             string          `json:"id"`
	Section        string          `json:"section"`
	Owner          string          `json:"owner"`
	Question       string          `json:"question"`
	Acceptable     string          `json:"acceptable"`
	Action         string          `json:"action"`
	DefectExample  string          `json:"defect_example,omitempty"`
	ResearchChecks []ResearchCheck `json:"research_checks,omitempty"`
}

type ResearchSource struct {
	ID             string `json:"id"`
	URL            string `json:"url"`
	AccessURL      string `json:"access_url,omitempty"`
	Title          string `json:"title"`
	Status         string `json:"status"`
	Scope          string `json:"scope"`
	ReviewCoverage string `json:"review_coverage"`
}

type ResearchCheck struct {
	ID         string   `json:"id"`
	Question   string   `json:"question"`
	Acceptable string   `json:"acceptable"`
	Action     string   `json:"action"`
	Scope      string   `json:"scope"`
	SourceIDs  []string `json:"source_ids"`
}

type Catalog struct {
	Version         int              `json:"version"`
	SourceURL       string           `json:"source_url"`
	Principles      []string         `json:"principles"`
	Practices       []Practice       `json:"practices"`
	ResearchSources []ResearchSource `json:"research_sources,omitempty"`
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
	return c, validateResearch(c)
}

func validateResearch(c Catalog) error {
	sources := map[string]ResearchSource{}
	for _, source := range c.ResearchSources {
		if _, exists := sources[source.ID]; strings.TrimSpace(source.ID) == "" || exists {
			return fmt.Errorf("editorial research: empty or duplicate source %q", source.ID)
		}
		for _, address := range []string{source.URL, source.AccessURL} {
			if address == "" && source.URL != "" {
				continue
			}
			u, err := url.Parse(address)
			if err != nil || u.Hostname() == "" || (u.Scheme != "https" && u.Scheme != "http") || strings.IndexFunc(address, unicode.IsSpace) >= 0 {
				return fmt.Errorf("editorial research: invalid source URL %q", source.ID)
			}
		}
		if source.Status != "read" && source.Status != "partial" && source.Status != "unavailable" {
			return fmt.Errorf("editorial research: invalid source status %q", source.ID)
		}
		if strings.TrimSpace(source.Title) == "" || strings.TrimSpace(source.Scope) == "" || strings.TrimSpace(source.ReviewCoverage) == "" {
			return fmt.Errorf("editorial research: source %s needs title, scope and review coverage", source.ID)
		}
		coverage := source.ReviewCoverage
		if (coverage != "article" && coverage != "selected_sections" && coverage != "indexed_units" && coverage != "unavailable") || ((source.Status == "unavailable") != (coverage == "unavailable")) {
			return fmt.Errorf("editorial research: inconsistent review coverage for %s", source.ID)
		}
		sources[source.ID] = source
	}
	seen := map[string]bool{}
	for _, p := range c.Practices {
		for _, check := range p.ResearchChecks {
			for _, value := range []string{check.ID, check.Question, check.Acceptable, check.Action, check.Scope} {
				if strings.TrimSpace(value) == "" {
					return fmt.Errorf("editorial research: incomplete check %q", check.ID)
				}
			}
			if seen[check.ID] || len(check.SourceIDs) == 0 {
				return fmt.Errorf("editorial research: duplicate check or missing sources %q", check.ID)
			}
			seen[check.ID] = true
			refs := map[string]bool{}
			for _, id := range check.SourceIDs {
				if source, exists := sources[id]; !exists || source.Status != "read" || refs[id] {
					return fmt.Errorf("editorial research: check %s requires unique read sources (%s)", check.ID, id)
				}
				refs[id] = true
			}
		}
	}
	return nil
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
		for _, check := range p.ResearchChecks {
			fmt.Fprintf(&b, "; уточнение [%s]: %s; допустимо: %s; действие: %s; границы: %s; основания: %s", check.ID, check.Question, check.Acceptable, check.Action, check.Scope, strings.Join(check.SourceIDs, ", "))
		}
		b.WriteString(". ")
	}
	b.WriteString("Источники редакционных вопросов (не доказательства фактов статьи): ")
	for _, source := range c.ResearchSources {
		fmt.Fprintf(&b, "[%s|%s] %s %s; объем разбора: %s; границы: %s. ", source.ID, source.Status, source.Title, source.URL, source.ReviewCoverage, source.Scope)
		if source.AccessURL != "" && source.AccessURL != source.URL {
			fmt.Fprintf(&b, "Прочитанная официальная копия: %s. ", source.AccessURL)
		}
	}
	b.WriteString("Отдельные слова, длина фраз, обращения и неровный ритм сами по себе не являются дефектом. Сохраняй подтвержденные факты, условия, модальность и голос автора.")
	return b.String()
}

type Check struct {
	ID             string           `json:"id"`
	Status         string           `json:"status"`
	Quote          string           `json:"quote"`
	OriginalQuote  string           `json:"original_quote,omitempty"`
	Reason         string           `json:"reason"`
	ReaderProblem  string           `json:"reader_problem,omitempty"`
	Benefit        string           `json:"benefit,omitempty"`
	MeaningRisk    string           `json:"meaning_risk,omitempty"`
	Suggestion     string           `json:"suggestion,omitempty"`
	ChangeEvidence []ChangeEvidence `json:"change_evidence,omitempty"`
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
		_, ok := want[ch.ID]
		if !ok {
			return fmt.Errorf("practice_checks: unknown or inapplicable id %q", ch.ID)
		}
		if got[ch.ID] {
			return fmt.Errorf("practice_checks: duplicate id %q", ch.ID)
		}
		got[ch.ID] = true
		if err := validateCheck(candidate, "", ch, false, true); err != nil {
			return fmt.Errorf("practice_checks: %w", err)
		}
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
