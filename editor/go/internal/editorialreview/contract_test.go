package editorialreview

import (
	"crypto/sha256"
	"fmt"
	"strings"
	"testing"
)

func dimensions(candidate, original string) ([]Check, []Check) {
	var logic, preservation []Check
	for _, id := range LogicIDs() {
		logic = append(logic, Check{ID: id, Status: "clear", Quote: candidate, Reason: "Смысл проверен по полному тексту."})
	}
	for _, id := range PreservationIDs() {
		ch := Check{ID: id, Status: "clear", Quote: candidate, OriginalQuote: original, Reason: "Условие, основание и голос сохранены."}
		if original != candidate && original != "" && (id == "author_voice" || id == "strengths") {
			ch.ChangeEvidence = []ChangeEvidence{{OriginalQuote: original, Quote: candidate, Disposition: "justified", Reason: "Исправлено согласование.", Benefit: "Фраза грамматически верна.", MeaningRisk: "Условия и разговорная подача сохранены."}}
		}
		preservation = append(preservation, ch)
	}
	return logic, preservation
}

func TestDimensionsPreserveLegitimateVoiceAndPunctuation(t *testing.T) {
	original := "Не только темп, но и запас ресурсов: чертовски фановая колода. «Спелл» — слово автора."
	candidate := "Не только темп, но и запас ресурсов: чертовски фановая колода. \"Спелл\" — слово автора."
	logic, preservation := dimensions(candidate, original)
	if err := ValidateDimensions(candidate, original, logic, preservation, false); err != nil {
		t.Fatal(err)
	}
	if HasUnresolved(logic, preservation) {
		t.Fatal("grounded accepted punctuation change treated as unresolved")
	}
	// Callers cannot accidentally mutate the canonical IDs.
	LogicIDs()[0] = "unknown"
	PreservationIDs()[0] = "unknown"
	if err := ValidateDimensions(candidate, original, logic, preservation, false); err != nil {
		t.Fatal(err)
	}
}

func TestDimensionsRejectMissingDuplicateUnknownAndUngroundedRows(t *testing.T) {
	text := "Автор сохранил условия и оценку: возможно, колода станет сильнее."
	cases := []struct {
		name   string
		mutate func(*[]Check, *[]Check)
	}{
		{"missing logic", func(l, p *[]Check) { *l = (*l)[1:] }},
		{"missing preservation", func(l, p *[]Check) { *p = (*p)[1:] }},
		{"duplicate logic", func(l, p *[]Check) { (*l)[1].ID = (*l)[0].ID }},
		{"unknown preservation", func(l, p *[]Check) { (*p)[0].ID = "unknown" }},
		{"false candidate quote", func(l, p *[]Check) { (*l)[0].Quote = "Несуществующая цитата." }},
		{"false original quote", func(l, p *[]Check) { (*p)[0].OriginalQuote = "Несуществующая цитата." }},
		{"empty original quote", func(l, p *[]Check) { (*p)[0].OriginalQuote = "" }},
		{"empty reason", func(l, p *[]Check) { (*p)[0].Reason = " " }},
		{"noncanonical status", func(l, p *[]Check) { (*l)[0].Status = " Clear " }},
		{"skip coherence", func(l, p *[]Check) { (*l)[0].Status = "not_applicable" }},
		{"skip author voice", func(l, p *[]Check) { (*p)[4].Status = "not_applicable" }},
		{"issue without action", func(l, p *[]Check) { (*p)[4].Status = "issue" }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			logic, preservation := dimensions(text, text)
			tc.mutate(&logic, &preservation)
			if err := ValidateDimensions(text, text, logic, preservation, false); err == nil {
				t.Fatal("invalid review accepted")
			}
		})
	}
}

func TestDimensionsAllowExplicitUnresolvedStateWithoutAcceptingIt(t *testing.T) {
	text := "Возможно, это улучшит результат."
	logic, preservation := dimensions(text, text)
	logic[0].Status = "issue"
	logic[0].ReaderProblem, logic[0].Benefit = "Неясна причина.", "Объяснение можно проверить."
	logic[0].MeaningRisk, logic[0].Suggestion = "Причину нельзя придумать.", "Запросить источник."
	preservation[0].Status = "unverified"
	if err := ValidateDimensions(text, text, logic, preservation, false); err != nil {
		t.Fatal(err)
	}
	if !HasUnresolved(logic, preservation) {
		t.Fatal("unresolved semantic review treated as acceptance")
	}
}

func TestDimensionsOnlyCausalSupportMayBeInapplicable(t *testing.T) {
	text := "Три карты доступны с 6 октября."
	logic, preservation := dimensions(text, text)
	logic[1].Status, logic[1].Quote, logic[1].Reason = "not_applicable", "", "Причинных утверждений нет."
	if err := ValidateDimensions(text, text, logic, preservation, false); err != nil {
		t.Fatal(err)
	}
	logic, preservation = dimensions(text, "")
	if err := ValidateDimensions(text, "", logic, preservation, true); err != nil {
		t.Fatalf("new article with no invented original rejected: %v", err)
	}
	if err := ValidateDimensions(text, "", logic, preservation, false); err == nil {
		t.Fatal("edit with no original accepted")
	}
}

func TestDimensionsAllowOptionalPreservationEvidenceOnUnchangedText(t *testing.T) {
	text := "Чертовски фановая колода."
	logic, preservation := dimensions(text, text)
	preservation[4].ChangeEvidence = []ChangeEvidence{{OriginalQuote: text, Quote: text, Disposition: "preserved", Reason: "Фрагмент оставлен без правок.", Benefit: "Сохранена авторская оценка.", MeaningRisk: "Изменений нет."}}
	if err := ValidateDimensions(text, text, logic, preservation, false); err != nil {
		t.Fatalf("grounded unchanged evidence must not force a rewrite: %v", err)
	}
}

func TestDimensionsRequireGroundedChangeEvidence(t *testing.T) {
	original, candidate := "Будет пара изменения.", "Будет пара изменений."
	cases := []struct {
		name   string
		mutate func(*Check)
	}{
		{"missing evidence", func(ch *Check) { ch.ChangeEvidence = nil }},
		{"invented original", func(ch *Check) { ch.ChangeEvidence[0].OriginalQuote = "Я этого не писал." }},
		{"invented candidate", func(ch *Check) { ch.ChangeEvidence[0].Quote = "Я этого не писал." }},
		{"unchanged evidence only", func(ch *Check) {
			ch.ChangeEvidence[0].OriginalQuote, ch.ChangeEvidence[0].Quote = "Будет", "Будет"
		}},
		{"no benefit", func(ch *Check) { ch.ChangeEvidence[0].Benefit = "" }},
		{"invalid disposition", func(ch *Check) { ch.ChangeEvidence[0].Disposition = "safe" }},
		{"too many evidence rows", func(ch *Check) { ch.ChangeEvidence = append(ch.ChangeEvidence, make([]ChangeEvidence, 16)...) }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			logic, preservation := dimensions(candidate, original)
			tc.mutate(&preservation[4])
			if err := ValidateDimensions(candidate, original, logic, preservation, false); err == nil {
				t.Fatal("ungrounded change evidence accepted")
			}
		})
	}
	logic, preservation := dimensions(candidate, original)
	preservation[4].ChangeEvidence[0].Disposition = "issue"
	if err := ValidateDimensions(candidate, original, logic, preservation, false); err != nil {
		t.Fatal(err)
	}
	if !HasUnresolved(preservation) {
		t.Fatal("unresolved change evidence ignored")
	}
	// Deletion can be justified without fabricating a surviving quote.
	logic, preservation = dimensions(candidate, original)
	preservation[4].ChangeEvidence[0].Quote = ""
	if err := ValidateDimensions(candidate, original, logic, preservation, false); err != nil {
		t.Fatal(err)
	}
}

func snapshot(id, body string) SourceSnapshot {
	return SourceSnapshot{SourceID: id, URL: "https://example.org/" + id, Title: "Patch notes", PublishedAt: "2026-10-01", RetrievedAt: "2026-10-23T00:00:00Z", Access: "snapshot", Text: body, SHA256: fmt.Sprintf("%x", sha256.Sum256([]byte(body)))}
}

func sourceCheck(source SourceSnapshot) SourceCheck {
	return SourceCheck{SourceID: source.SourceID, Status: "verified", EvidenceQuote: source.Text, Reason: "Сопоставлено с сохранённым текстом.", IdentityCheck: "URL и заголовок сопоставлены; автор не указан.", SupportCheck: "Указанное изменение есть в тексте; весь материал этим не подтверждён.", Access: "snapshot"}
}

func TestSourcesBindFullTextAndExplicitProvenance(t *testing.T) {
	source := snapshot("patch", "Патч меняет стоимость с 3 на 4.")
	if err := ValidateSources([]SourceSnapshot{source}); err != nil {
		t.Fatal(err)
	}
	if err := ValidateSourceChecks([]SourceSnapshot{source}, []SourceCheck{sourceCheck(source)}); err != nil {
		t.Fatal(err)
	}
	if err := ValidateSources(nil); err != nil {
		t.Fatalf("absent evidence must be represented, not fabricated: %v", err)
	}
	if err := ValidateSourceChecks(nil, []SourceCheck{sourceCheck(source)}); err == nil {
		t.Fatal("source verification without a snapshot accepted")
	}
}

func TestSourcesRejectTamperingMissingMetadataAndUnboundedPayloads(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(*SourceSnapshot)
	}{
		{"changed text", func(s *SourceSnapshot) { s.Text += " Теперь 5." }},
		{"missing id", func(s *SourceSnapshot) { s.SourceID = " " }},
		{"missing retrieved date", func(s *SourceSnapshot) { s.RetrievedAt = "" }},
		{"false retrieved date", func(s *SourceSnapshot) { s.RetrievedAt = "yesterday" }},
		{"invalid publication date", func(s *SourceSnapshot) { s.PublishedAt = "not a date" }},
		{"local path", func(s *SourceSnapshot) { s.URL = "C:\\private\\notes.md" }},
		{"file URL", func(s *SourceSnapshot) { s.URL = "file:///C:/private/notes.md" }},
		{"relative URL", func(s *SourceSnapshot) { s.URL = "/patch" }},
		{"credential URL", func(s *SourceSnapshot) { s.URL = "https://user:password@example.org/" }},
		{"unknown access", func(s *SourceSnapshot) { s.Access = "probably_live" }},
		{"empty body", func(s *SourceSnapshot) { *s = snapshot(s.SourceID, " ") }},
		{"oversized body", func(s *SourceSnapshot) { *s = snapshot(s.SourceID, strings.Repeat("я", 100001)) }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			source := snapshot("patch", "Стоимость 4.")
			tc.mutate(&source)
			if err := ValidateSources([]SourceSnapshot{source}); err == nil {
				t.Fatal("invalid snapshot accepted")
			}
		})
	}
	source := snapshot("patch", "Стоимость 4.")
	if err := ValidateSources([]SourceSnapshot{source, source}); err == nil {
		t.Fatal("duplicate source ID accepted")
	}
	var many []SourceSnapshot
	for i := 0; i < 9; i++ {
		many = append(many, snapshot(fmt.Sprint(i), "body"))
	}
	if err := ValidateSources(many); err == nil {
		t.Fatal("too many snapshots accepted")
	}
	if err := ValidateSources([]SourceSnapshot{snapshot("one", strings.Repeat("я", 100000)), snapshot("two", strings.Repeat("я", 50001))}); err == nil {
		t.Fatal("total text limit ignored")
	}
	if err := ValidateSources([]SourceSnapshot{snapshot("one", strings.Repeat("я", 100000)), snapshot("two", strings.Repeat("я", 50000))}); err != nil {
		t.Fatalf("exact boundary rejected: %v", err)
	}
}

func TestSourceChecksRejectInventedSupportAndAccess(t *testing.T) {
	source := snapshot("patch", "Стоимость повышена с 3 до 4.")
	cases := []struct {
		name   string
		mutate func(*SourceCheck)
	}{
		{"unknown id", func(s *SourceCheck) { s.SourceID = "unknown" }},
		{"invented quote", func(s *SourceCheck) { s.EvidenceQuote = "Стоимость 5." }},
		{"empty verified quote", func(s *SourceCheck) { s.EvidenceQuote = "" }},
		{"invented live access", func(s *SourceCheck) { s.Access = "live" }},
		{"empty identity check", func(s *SourceCheck) { s.IdentityCheck = " " }},
		{"empty support check", func(s *SourceCheck) { s.SupportCheck = " " }},
		{"empty reason", func(s *SourceCheck) { s.Reason = "" }},
		{"noncanonical status", func(s *SourceCheck) { s.Status = "Verified" }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			check := sourceCheck(source)
			tc.mutate(&check)
			if err := ValidateSourceChecks([]SourceSnapshot{source}, []SourceCheck{check}); err == nil {
				t.Fatal("false source review accepted")
			}
		})
	}
	if err := ValidateSourceChecks([]SourceSnapshot{source}, nil); err == nil {
		t.Fatal("missing source check accepted")
	}
	check := sourceCheck(source)
	if err := ValidateSourceChecks([]SourceSnapshot{source}, []SourceCheck{check, check}); err == nil {
		t.Fatal("duplicate source check accepted")
	}
	for _, status := range []string{"unavailable", "mismatch"} {
		check := sourceCheck(source)
		check.Status, check.EvidenceQuote = status, ""
		if err := ValidateSourceChecks([]SourceSnapshot{source}, []SourceCheck{check}); err != nil {
			t.Fatalf("unresolved source schema rejected: %v", err)
		}
		if !HasUnresolvedSources([]SourceCheck{check}) {
			t.Fatal("unresolved source treated as verified")
		}
	}
}

func TestSourceReviewCannotClaimUpstreamLiveOrArchiveAccess(t *testing.T) {
	for _, origin := range []string{"live", "archive"} {
		t.Run(origin, func(t *testing.T) {
			source := snapshot("patch", "Стоимость повышена с 3 до 4.")
			source.Access = origin
			check := sourceCheck(source)
			check.Access = origin
			if err := ValidateSourceChecks([]SourceSnapshot{source}, []SourceCheck{check}); err == nil {
				t.Errorf("supplied %s origin must not become a claimed reviewer fetch", origin)
			}
			check.Access = "snapshot"
			if err := ValidateSourceChecks([]SourceSnapshot{source}, []SourceCheck{check}); err != nil {
				t.Errorf("honest snapshot review of %s origin rejected: %v", origin, err)
			}
		})
	}
}
