package pipeline

import (
	"regexp"
	"strings"
)

var orderedListMarkerRE = regexp.MustCompile(`^ {0,3}([0-9]{1,9})[.)][ \t]+`)

// Only reconstruction treats list ordinals as composition, not source facts.
// Keep literal code numbers and every body number available to the guard.
func maskReconstructionOrdinals(text string) string {
	plain := []byte(text)
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
			} else if trimmed[0] == fence && n >= width && strings.TrimSpace(trimmed[n:]) == "" {
				fence, width = 0, 0
			}
		} else if fence == 0 {
			if loc := orderedListMarkerRE.FindStringSubmatchIndex(line); loc != nil {
				for at := loc[2]; at < loc[3]; at++ {
					plain[offset+at] = ' '
				}
			}
		}
		offset += len(line)
	}
	return string(plain)
}
