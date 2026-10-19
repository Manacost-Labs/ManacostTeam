package pipeline

import (
	"regexp"
	"sort"
	"strings"
)

var sourceParagraphBreak = regexp.MustCompile(`\r?\n[\t \p{Zs}]*\r?\n`)
var orderedParagraph = regexp.MustCompile(`^[0-9]+[.)]\s`)

// Ordinary edit may split paragraphs, but must not silently join existing
// prose. Restore only unique, unchanged three-word anchors on both sides.
// Ambiguous/rewritten anchors and code/HTML are left for editorial review.
func preserveEditParagraphs(mode, source, candidate string) string {
	if mode != "edit" {
		return candidate
	}
	for _, text := range []string{source, candidate} {
		if strings.Contains(text, "```") || strings.Contains(text, "~~~") || strings.ContainsAny(text, "<>") {
			return candidate
		}
	}
	type boundary struct{ sourceCount, candidateCount, start, end int }
	anchors := map[[6]string]*boundary{}
	paras := sourceParagraphBreak.Split(source, -1)
	for i := 1; i < len(paras); i++ {
		left, right := strings.Fields(paras[i-1]), strings.Fields(paras[i])
		if len(left) < 3 || len(right) < 3 || !plainParagraph(paras[i-1]) || !plainParagraph(paras[i]) {
			continue
		}
		var key [6]string
		copy(key[:3], left[len(left)-3:])
		copy(key[3:], right[:3])
		if anchors[key] == nil {
			anchors[key] = &boundary{}
		}
		anchors[key].sourceCount++
	}
	if len(anchors) == 0 {
		return candidate
	}
	words := strings.Fields(candidate)
	starts := make([]int, len(words))
	cursor := 0
	for i, word := range words {
		starts[i] = cursor + strings.Index(candidate[cursor:], word)
		cursor = starts[i] + len(word)
	}
	for i := 0; i+6 <= len(words); i++ {
		var key [6]string
		copy(key[:], words[i:i+6])
		if b := anchors[key]; b != nil && b.sourceCount == 1 {
			b.candidateCount++
			b.start, b.end = starts[i+2]+len(words[i+2]), starts[i+3]
		}
	}
	var cuts []boundary
	for _, b := range anchors {
		if b.sourceCount == 1 && b.candidateCount == 1 && strings.Count(candidate[b.start:b.end], "\n") < 2 {
			cuts = append(cuts, *b)
		}
	}
	if len(cuts) == 0 {
		return candidate
	}
	sort.Slice(cuts, func(i, j int) bool { return cuts[i].start < cuts[j].start })
	var out strings.Builder
	cursor = 0
	for _, b := range cuts {
		out.WriteString(candidate[cursor:b.start])
		out.WriteString("\n\n")
		cursor = b.end
	}
	out.WriteString(candidate[cursor:])
	return out.String()
}

func plainParagraph(p string) bool {
	t := strings.TrimSpace(p)
	return t != "" && !strings.HasPrefix(p, "    ") && !strings.HasPrefix(p, "\t") && !strings.ContainsAny(t[:1], "#>*+-`|") && !orderedParagraph.MatchString(t)
}
