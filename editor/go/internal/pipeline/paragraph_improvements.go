package pipeline

import (
	"regexp"
	"strings"
	"unicode"
)

var paragraphBreak = regexp.MustCompile(`\n[ \t]*\n(?:[ \t]*\n)*`)
var nonProseLine = regexp.MustCompile(`(?m)^(?: {4}|[ \t]*(?:[#>*+\-]|[0-9]+[.)][ \t]))`)

// A structural quote proves only a sentence-boundary split in plain prose.
// Require identical words throughout: other edits still use token-diff evidence.
// Reject markup conservatively rather than reinterpret its layout as prose.
func paragraphSplitEvidence(source, candidate, before, after string) bool {
	if normalizeSpace(source) != normalizeSpace(candidate) || strings.ContainsAny(source+candidate, "`<>[]|\\\t*_~") || nonProseLine.MatchString(source) || nonProseLine.MatchString(candidate) {
		return false
	}
	source, candidate = strings.ReplaceAll(source, "\r\n", "\n"), strings.ReplaceAll(candidate, "\r\n", "\n")
	before, after = strings.TrimSpace(strings.ReplaceAll(before, "\r\n", "\n")), strings.TrimSpace(strings.ReplaceAll(after, "\r\n", "\n"))
	if len([]rune(before)) > MaxImprovementFragment || len([]rune(after)) > MaxImprovementFragment {
		return false
	}
	if normalizeSpace(before) != normalizeSpace(after) || paragraphBreak.MatchString(before) || !strings.Contains(source, before) || !strings.Contains(candidate, after) {
		return false
	}
	// A unique quote in the shared word sequence binds both excerpts to the
	// same occurrence. Repeated prose needs less ambiguous evidence.
	normSource, normBefore := normalizeSpace(source), normalizeSpace(before)
	if strings.Index(normSource, normBefore) != strings.LastIndex(normSource, normBefore) {
		return false
	}
	parts := paragraphBreak.Split(after, -1)
	if len(parts) < 2 {
		return false
	}
	// Existing boundaries must survive; moving a break is not adding one.
	oldBreaks, newBreaks := paragraphOffsets(source), paragraphOffsets(candidate)
	if len(newBreaks) <= len(oldBreaks) {
		return false
	}
	for offset := range oldBreaks {
		if !newBreaks[offset] {
			return false
		}
	}
	for _, boundary := range paragraphBreak.FindAllStringIndex(candidate, -1) {
		if oldBreaks[len(normalizeSpace(candidate[:boundary[0]]))] {
			continue
		}
		left := strings.TrimRight(strings.TrimSpace(candidate[:boundary[0]]), `"'»”’)`)
		right := []rune(strings.TrimLeft(strings.TrimSpace(candidate[boundary[1]:]), `"'«“‘(`))
		if left == "" || len(right) == 0 {
			return false
		}
		last := []rune(left)
		if !strings.ContainsRune(".!?…", last[len(last)-1]) || !unicode.IsUpper(right[0]) && !unicode.IsDigit(right[0]) {
			return false
		}
		if last[len(last)-1] == '.' {
			words := strings.FieldsFunc(left, func(r rune) bool { return !unicode.IsLetter(r) })
			// Short dotted forms and common longer titles are ambiguous.
			// A conservative false negative is safer than splitting an initial.
			if len(words) == 0 {
				return false
			}
			word := strings.ToLower(words[len(words)-1])
			if len([]rune(word)) <= 3 || word == "проф" || word == "акад" || word == "прим" {
				return false
			}
		}
	}
	return true
}

// Byte positions in the shared whitespace-normalized text identify boundaries
// without confusing repeated sentences or counting CRLF/extra blank lines.
func paragraphOffsets(text string) map[int]bool {
	out := map[int]bool{}
	for _, boundary := range paragraphBreak.FindAllStringIndex(text, -1) {
		out[len(normalizeSpace(text[:boundary[0]]))] = true
	}
	return out
}
