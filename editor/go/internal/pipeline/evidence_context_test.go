package pipeline

import (
	"crypto/sha256"
	"fmt"
	"strings"
	"testing"
)

func TestEvidenceSnapshotRestoresAdjacentConditionWithoutChangingBaseline(t *testing.T) {
	h := readyHandoff()
	h.Sources[0].Quote = "Контркарта опасна."
	h.EvidenceSnapshots = []EvidenceSnapshot{{URL: h.Sources[0].URL, Text: "Введение.\nКонтркарта опасна.\nЕсли ожидаете ее, ускорьте комбинацию.\nНо учитывайте состояние рук."}}
	h.EvidenceSnapshots[0].SHA256 = fmt.Sprintf("%x", sha256.Sum256([]byte(h.EvidenceSnapshots[0].Text)))
	if err := h.Validate(); err != nil {
		t.Fatal(err)
	}
	got := h.withEvidenceContext()
	if err := got.Validate(); err != nil {
		t.Fatal("derived evidence must survive an internal review round trip", err)
	}
	if !strings.Contains(got.Sources[0].ContextQuote, "Если ожидаете ее, ускорьте комбинацию.") {
		t.Fatal("adjacent advice lost", got.Sources[0].ContextQuote)
	}
	if !strings.Contains(h.EvidenceSnapshots[0].Text, got.Sources[0].ContextQuote) || got.Sources[0].Quote != h.Sources[0].Quote || h.Sources[0].ContextQuote != "" || got.VerifiedText() != h.VerifiedText() {
		t.Fatal("context invented evidence or mutated input")
	}
}

func TestEvidenceSnapshotsRejectForeignConflictingOrFabricatedContext(t *testing.T) {
	for _, kind := range []string{"foreign", "duplicate", "missing_quote", "injected_context", "too_large", "ambiguous", "wrong_hash"} {
		t.Run(kind, func(t *testing.T) {
			h := readyHandoff()
			h.Sources[0].Quote = "Точная цитата."
			h.EvidenceSnapshots = []EvidenceSnapshot{{URL: h.Sources[0].URL, Text: "Точная цитата.\nУсловие."}}
			h.EvidenceSnapshots[0].SHA256 = fmt.Sprintf("%x", sha256.Sum256([]byte(h.EvidenceSnapshots[0].Text)))
			switch kind {
			case "foreign":
				h.EvidenceSnapshots[0].URL = "https://other.example.org"
			case "duplicate":
				h.EvidenceSnapshots = append(h.EvidenceSnapshots, h.EvidenceSnapshots[0])
			case "missing_quote":
				h.EvidenceSnapshots[0].Text = "Иной текст."
			case "ambiguous":
				h.EvidenceSnapshots[0].Text += "Точная цитата."
				h.EvidenceSnapshots[0].SHA256 = fmt.Sprintf("%x", sha256.Sum256([]byte(h.EvidenceSnapshots[0].Text)))
			case "wrong_hash":
				h.EvidenceSnapshots[0].SHA256 = strings.Repeat("0", 64)
			case "injected_context":
				h.Sources[0].ContextQuote = "Придуманный совет."
			case "too_large":
				h.EvidenceSnapshots[0].Text = strings.Repeat("a", 100001)
				h.EvidenceSnapshots[0].SHA256 = fmt.Sprintf("%x", sha256.Sum256([]byte(h.EvidenceSnapshots[0].Text)))
			}
			if h.Validate() == nil {
				t.Fatal("invalid evidence snapshot admitted", kind)
			}
		})
	}
}

func evidenceLimitHandoff(sizes ...int) *ResearchHandoff {
	h := readyHandoff()
	h.Sources = nil
	for i, size := range sizes {
		url := fmt.Sprintf("https://example.org/source-%d", i)
		text := "q" + strings.Repeat("x", size-1)
		h.Sources = append(h.Sources, ResearchSource{ID: fmt.Sprintf("SRC-%d", i+1), URL: url, Quote: "q"})
		h.EvidenceSnapshots = append(h.EvidenceSnapshots, EvidenceSnapshot{URL: url, Text: text, SHA256: fmt.Sprintf("%x", sha256.Sum256([]byte(text)))})
	}
	return h
}

func TestEvidenceSnapshotCountAndAggregateBoundaries(t *testing.T) {
	for _, tc := range []struct {
		name  string
		sizes []int
		valid bool
	}{
		{"eight", []int{1, 1, 1, 1, 1, 1, 1, 1}, true},
		{"nine", []int{1, 1, 1, 1, 1, 1, 1, 1, 1}, false},
		{"single_limit", []int{100000}, true},
		{"aggregate_limit", []int{75000, 75000}, true},
		{"aggregate_exceeded", []int{75000, 75001}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if err := evidenceLimitHandoff(tc.sizes...).Validate(); (err == nil) != tc.valid {
				t.Fatalf("valid=%v got %v", tc.valid, err)
			}
		})
	}
}

func TestEvidenceContextCapsUnicodeWindowAndAggregateExpansion(t *testing.T) {
	text := strings.Repeat("д", 201) + "QUOTE" + strings.Repeat("ж", 1001)
	got := quoteContext(text, "QUOTE")
	want := strings.Repeat("д", 200) + "QUOTE" + strings.Repeat("ж", 1000)
	if got != want || !strings.Contains(text, got) {
		t.Fatal("context crop lost its rune boundary or exact source bytes")
	}
	h := evidenceLimitHandoff(1)
	h.Sources[0].Quote = "QUOTE"
	h.EvidenceSnapshots[0].Text = text
	h.EvidenceSnapshots[0].SHA256 = fmt.Sprintf("%x", sha256.Sum256([]byte(text)))
	for i := 2; i <= 84; i++ {
		h.Sources = append(h.Sources, ResearchSource{ID: fmt.Sprintf("SRC-%d", i), URL: h.Sources[0].URL, Quote: "QUOTE"})
	}
	if err := h.Validate(); err == nil || !strings.Contains(err.Error(), "expansion exceeds budget") {
		t.Fatal("aggregate context expansion must remain bounded", err)
	}
}
