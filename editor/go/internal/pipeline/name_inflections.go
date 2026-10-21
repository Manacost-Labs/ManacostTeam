package pipeline

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
)

var consonantName = regexp.MustCompile(`^[А-ЯЁа-яё]{2,}[бвгджзклмнпрстфхцчшщ]$`)

// Only ordinary suffixes on a complete already known name; no fuzzy spelling,
// root replacement, added words or recombination of separate proper names.
// This lexical allowance never replaces the full claim/evidence review.
func knownNameInflection(name string, known []string) bool {
	words := strings.Fields(name)
	for _, form := range known {
		base := strings.Fields(form)
		if len(base) != len(words) {
			continue
		}
		match := true
		for i, word := range words {
			if word == base[i] {
				continue
			}
			if !consonantName.MatchString(base[i]) {
				match = false
				break
			}
			suffix, ok := strings.CutPrefix(word, base[i])
			if !ok || !strings.Contains("|а|у|ом|е|ы|ов|ам|ами|ах|", "|"+suffix+"|") {
				match = false
				break
			}
		}
		if match {
			return true
		}
	}
	return false
}

// Normalize only the exact approved calendar date for lexical comparison.
// A day number elsewhere, a different day/month/year and article bytes remain
// unchanged. Numbers from prose sources do not enter the approval baseline.
func normalizeDeclaredDate(before, after string) string {
	months := []string{"января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"}
	re := regexp.MustCompile(`\b(\d{1,2}) (января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря) (\d{4})`)
	return re.ReplaceAllStringFunc(after, func(date string) string {
		parts := re.FindStringSubmatch(date)
		day, _ := strconv.Atoi(parts[1])
		year, _ := strconv.Atoi(parts[3])
		for i, month := range months {
			if parts[2] != month {
				continue
			}
			canonical := fmt.Sprintf("%02d.%02d.%04d", day, i+1, year)
			if _, err := time.Parse("02.01.2006", canonical); err == nil && strings.Contains(before, canonical) {
				return canonical
			}
		}
		return date
	})
}
