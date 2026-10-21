package analyzers

import (
	"regexp"
	"strconv"
	"unicode"
	"unicode/utf8"
)

var singularCopyNumber = regexp.MustCompile(`(?:^|[^\p{L}\p{N}])(\d+)[ \t]+копию`)

// Report agreement only; the author must distinguish a quantity from an ordinal
// using the source. This analyzer never changes a number or the article.
func copyNumberGrammar(text string) []Finding {
	var out []Finding
	for _, loc := range singularCopyNumber.FindAllStringSubmatchIndex(text, -1) {
		if loc[1] < len(text) {
			next, _ := utf8.DecodeRuneInString(text[loc[1]:])
			if unicode.IsLetter(next) || unicode.IsNumber(next) {
				continue
			}
		}
		n, err := strconv.ParseUint(text[loc[2]:loc[3]], 10, 64)
		if err != nil || (n%10 == 1 && n%100 != 11) {
			continue
		}
		start := loc[2]
		end := loc[3]
		for end < len(text) && (text[end] == ' ' || text[end] == '\t') {
			end++
		}
		end += len("копию")
		out = append(out, Finding{Analyzer: "native-go", RuleID: "grammar.copy-number", Severity: "error", Evidence: text[start:end], Message: "Число не согласовано со словом «копию». Сохрани смысл источника: для порядка нужна форма вроде «2-ю копию», для количества — «2 копии». Не меняй количество или условие совета ради грамматики."})
	}
	return out
}
