package pipeline

import (
	"context"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzers"
)

func TestWritingRepairsNameGrammarEvenWhenHandoffContainsIt(t *testing.T) {
	h := readyHandoff()
	h.Claims[0].Meaning = "Проверьте здоровье Мозаки при слабой позиции, кроме угрозы поражения."
	h.Claims[0].Action = "Проверьте здоровье Мозаке"
	h.Sources[0].Quote = `{"id":"SCH_400","name":"Великая дуэлянтка Мозаки"}`
	bad := h.Claims[0].Action + " при слабой позиции, кроме угрозы поражения. Это может помочь. https://example.org/guide"
	good := strings.ReplaceAll(bad, "Мозаке", "Мозаки")
	badFact := strings.Replace(publicationFact, "Сохраняйте ресурс", "Проверьте здоровье Мозаке", 1)
	goodFact := strings.ReplaceAll(badFact, "Мозаке", "Мозаки")
	writer := &fakeLLM{replies: []string{bad, good}}
	reviewer := &fakeLLM{replies: []string{badFact, criticJSON("accept"), goodFact, criticJSON("accept")}}
	s := New(writer, nil, "fake", analyzers.NativeGoAnalyzer{})
	s.Reviewer = reviewer
	r, err := s.Run(context.Background(), Request{Mode: "write", Handoff: h})
	if err != nil || !r.Accepted || r.Text != good || r.Attempts != 2 || len(reviewer.messages) != 4 {
		t.Fatalf("source grammar was copied or repair skipped full fact review: %+v %v", r, err)
	}
	if h.Claims[0].Action != "Проверьте здоровье Мозаке" || !strings.Contains(strings.ToLower(writer.messages[0][0].Content), "несклоняем") {
		t.Fatal("source handoff changed, or author lacks the grammatical-class instruction")
	}
}
