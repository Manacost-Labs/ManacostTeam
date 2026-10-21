package analyzers

import (
	"context"
	"strings"
	"testing"
)

func TestIndeclinableCardNameGrammarUsesExactWordsAndLanguageScope(t *testing.T) {
	for _, word := range []string{"Мозака", "Мозаке", "Мозаку", "Мозаком", "Мозакой", "Мозакам", "Мозаками", "Мозаках", "мозаке"} {
		r, err := (NativeGoAnalyzer{}).Analyze(context.Background(), Input{Game: "hearthstone", Language: "ru-RU", Text: "На собственной " + word + "."})
		if err != nil || len(r.Findings) != 1 || r.Findings[0].RuleID != "grammar.indeclinable-card-name" || r.Findings[0].Evidence != word || !strings.Contains(r.Findings[0].Message, "Мозаки") {
			t.Fatalf("missing exact indeclinable-name finding for %q: %+v %v", word, r, err)
		}
	}
	for _, in := range []Input{
		{Text: "На собственной Мозаки. По Мозаки. У Мозаки. Мозаки, мастер дуэлей."},
		{Text: "Полкелта. Соларианом. Ученице. НеизвестноеИмя. Мозакея. Мозакамышь."},
		{Game: "wow", Language: "ru", Text: "Мозаке"},
		{Game: "hearthstone", Language: "en", Text: "Мозаке"},
	} {
		r, err := (NativeGoAnalyzer{}).Analyze(context.Background(), in)
		if err != nil || len(r.Findings) != 0 {
			t.Fatalf("rule generalized beyond its closed lexical scope: %+v %v", r, err)
		}
	}
}
