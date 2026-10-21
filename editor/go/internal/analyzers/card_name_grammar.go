package analyzers

import (
	"regexp"
	"strings"
)

var cardNameWord = regexp.MustCompile(`[\p{L}\p{M}]+`)

// Closed grammatical entries, not a suffix rule for arbitrary unknown names.
// The initial entry is SCH_400: "Великая дуэлянтка Мозаки" in verified ruRU
// build 54613. The personal-name component is indeclinable; even an erroneous
// source/handoff spelling must not authorize its inflection in an article.
var indeclinableCardNameForms = map[string]string{
	"мозака": "Мозаки", "мозаке": "Мозаки", "мозаку": "Мозаки", "мозаком": "Мозаки",
	"мозакой": "Мозаки", "мозакам": "Мозаки", "мозаками": "Мозаки", "мозаках": "Мозаки",
}

func cardNameGrammar(text string) []Finding {
	var out []Finding
	for _, loc := range cardNameWord.FindAllStringIndex(text, -1) {
		word := text[loc[0]:loc[1]]
		if canonical, ok := indeclinableCardNameForms[strings.ToLower(word)]; ok {
			out = append(out, Finding{Analyzer: "native-go", RuleID: "grammar.indeclinable-card-name", Severity: "error", Evidence: word,
				Message: "Имя «" + canonical + "» несклоняемое: сохраните эту каноническую форму, даже если в исходнике или handoff ошибочное окончание. Исправьте только грамматику имени; сохраните действие, числа, условие и полезный абзац."})
		}
	}
	return out
}
