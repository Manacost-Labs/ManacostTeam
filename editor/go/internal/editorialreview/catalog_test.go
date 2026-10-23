package editorialreview

import "testing"

func validChecks(t *testing.T, candidate string) []Check {
	t.Helper()
	catalog, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	checks := make([]Check, 0, len(catalog.Practices))
	for _, p := range catalog.Practices {
		checks = append(checks, Check{ID: p.ID, Status: "clear", Quote: candidate, Reason: "Контекст проверен."})
	}
	return checks
}

func TestCatalogIsVersionedAndComplete(t *testing.T) {
	catalog, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if catalog.SourceURL == "" || len(catalog.Principles) == 0 || len(catalog.Practices) != 26 {
		t.Fatalf("unexpected catalog: %+v", catalog)
	}
}

func TestValidateChecksRequiresExactGroundedCoverage(t *testing.T) {
	candidate := "Кандидат с проверяемой цитатой."
	checks := validChecks(t, candidate)
	if err := ValidateChecks(candidate, checks, false); err != nil {
		t.Fatal(err)
	}
	checks = checks[:len(checks)-1]
	if err := ValidateChecks(candidate, checks, false); err == nil {
		t.Fatal("missing practice accepted")
	}
}

func TestValidateChecksRejectsUnknownDuplicateAndUngrounded(t *testing.T) {
	candidate := "Кандидат с проверяемой цитатой."
	checks := validChecks(t, candidate)
	checks[0].ID = "unknown"
	if err := ValidateChecks(candidate, checks, false); err == nil {
		t.Fatal("unknown id accepted")
	}
	checks = validChecks(t, candidate)
	checks[1].ID = checks[0].ID
	if err := ValidateChecks(candidate, checks, false); err == nil {
		t.Fatal("duplicate id accepted")
	}
	checks = validChecks(t, candidate)
	checks[0].Quote = "нет в кандидате"
	if err := ValidateChecks(candidate, checks, false); err == nil {
		t.Fatal("ungrounded quote accepted")
	}
}

func TestValidateChecksFactsOnlyUsesFactualSubset(t *testing.T) {
	candidate := "Кандидат с проверяемой цитатой."
	catalog, _ := Load()
	var checks []Check
	for _, p := range catalog.Practices {
		if p.Owner == "fact_review" {
			checks = append(checks, Check{ID: p.ID, Status: "clear", Quote: candidate, Reason: "Факт проверен."})
		}
	}
	if err := ValidateChecks(candidate, checks, true); err != nil {
		t.Fatal(err)
	}
	if err := ValidateChecks(candidate, validChecks(t, candidate), true); err == nil {
		t.Fatal("literary checks accepted in facts_only")
	}
}

func TestValidateChecksRequiresReasonAndIssueFields(t *testing.T) {
	candidate := "Кандидат с проверяемой цитатой."
	checks := validChecks(t, candidate)
	checks[0].Status, checks[0].Quote, checks[0].Reason = "not_applicable", "", ""
	if err := ValidateChecks(candidate, checks, false); err == nil {
		t.Fatal("not_applicable without reason accepted")
	}
	checks = validChecks(t, candidate)
	checks[0].Status = "issue"
	if err := ValidateChecks(candidate, checks, false); err == nil {
		t.Fatal("issue without actionable fields accepted")
	}
	checks = validChecks(t, candidate)
	checks[0].Status = "unverified"
	checks[0].Reason = "Нужна проверка источника."
	if err := ValidateChecks(candidate, checks, false); err != nil {
		t.Fatalf("unverified should be a valid unresolved review state: %v", err)
	}
}

func TestValidateChecksRejectsNoncanonicalStatus(t *testing.T) {
	candidate := "Автор может писать: не только это, но и то."
	for _, status := range []string{"CLEAR", " clear", "clear ", "Issue"} {
		checks := validChecks(t, candidate)
		checks[0].Status = status
		if err := ValidateChecks(candidate, checks, false); err == nil {
			t.Errorf("noncanonical status %q accepted", status)
		}
	}
}
