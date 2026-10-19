package guards

import (
	"regexp"
	"strings"
)

var (
	literalNoteRE = regexp.MustCompile(`^ {0,3}((?:\\\*)+|\*+)([ \t\x{00a0}]+)\S`)
	noteRefRE     = regexp.MustCompile(`\[\^[^\]\s]+\]`)
	backtickRE    = regexp.MustCompile("`+")
)

// A star followed by NBSP is literal Markdown text; star-space is a list.
// Escaping the star preserves its identity. Protect markers independently of
// the note's wording so a local language edit need not restore the whole note.
func footnoteEntities(text string) []Entity {
	var out []Entity
	var fence byte
	width, offset := 0, 0
	for _, line := range strings.SplitAfter(text, "\n") {
		trimmed := strings.TrimLeft(line, " ")
		indent := len(line) - len(trimmed)
		if indent <= 3 && len(trimmed) >= 3 && (trimmed[0] == '`' || trimmed[0] == '~') {
			n := 0
			for n < len(trimmed) && trimmed[n] == trimmed[0] {
				n++
			}
			if n >= 3 && fence == 0 {
				fence, width = trimmed[0], n
				offset += len(line)
				continue
			} else if trimmed[0] == fence && n >= width && strings.TrimSpace(trimmed[n:]) == "" {
				fence, width = 0, 0
				offset += len(line)
				continue
			}
		}
		if fence == 0 && indent <= 3 && !strings.HasPrefix(line, "\t") {
			if loc := literalNoteRE.FindStringSubmatchIndex(line); loc != nil {
				marker, space := line[loc[2]:loc[3]], line[loc[4]:loc[5]]
				if strings.HasPrefix(marker, `\`) || strings.HasPrefix(space, "\u00a0") {
					out = append(out, Entity{Kind: "literal_footnote", Value: strings.ReplaceAll(marker, `\`, ""), Start: offset + loc[2], End: offset + loc[3]})
				}
			}
			// Mask inline code without shifting byte offsets.
			plain := maskInlineCode(line)
			for _, loc := range noteRefRE.FindAllStringIndex(plain, -1) {
				if !escapedAt(plain, loc[0]) {
					out = append(out, Entity{Kind: "footnote_reference", Value: line[loc[0]:loc[1]], Start: offset + loc[0], End: offset + loc[1]})
				}
			}
		}
		offset += len(line)
	}
	return out
}

func escapedAt(text string, at int) bool {
	n := 0
	for at > 0 && text[at-1] == '\\' {
		n++
		at--
	}
	return n%2 == 1
}

func maskInlineCode(line string) string {
	runs := backtickRE.FindAllStringIndex(line, -1)
	next := make([]int, len(runs))
	byWidth := map[int]int{}
	for i := len(runs) - 1; i >= 0; i-- {
		width := runs[i][1] - runs[i][0]
		next[i] = -1
		if closing, ok := byWidth[width]; ok {
			next[i] = closing
		}
		byWidth[width] = i
	}
	plain := []byte(line)
	for i := 0; i < len(runs); i++ {
		if next[i] < 0 || escapedAt(line, runs[i][0]) {
			continue
		}
		closing := next[i]
		for at := runs[i][0]; at < runs[closing][1]; at++ {
			plain[at] = ' '
		}
		i = closing
	}
	return string(plain)
}
