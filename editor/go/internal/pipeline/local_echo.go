package pipeline

import (
	"fmt"
	"strings"
	"unicode"
)

type SoundEcho struct {
	Quote        string `json:"quote"`
	First        string `json:"first"`
	Second       string `json:"second"`
	SharedPrefix string `json:"shared_prefix"`
	start, end   int
}
type EchoDecision struct {
	Quote   string `json:"quote"`
	Verdict string `json:"verdict"`
	Reason  string `json:"reason"`
}

// Prefix similarity is only a sound diagnostic, never proof of a shared root.
// Identity is an unordered lowercase word pair, with ё folded to е. Source
// pairs are suppressed globally: repetition already elsewhere may be missed.
func walkIntroducedEchoes(source, candidate string, visit func(SoundEcho)) {
	key := func(e SoundEcho) string {
		a, b := e.First, e.Second
		if a > b {
			a, b = b, a
		}
		return a + "\x00" + b
	}
	seen := map[string]bool{}
	walkNearbyEchoes(source, func(e SoundEcho) {
		seen[key(e)] = true
	})
	walkNearbyEchoes(candidate, func(e SoundEcho) {
		if !seen[key(e)] {
			visit(e)
		}
	})
}

func walkNearbyEchoes(text string, visit func(SoundEcho)) {
	type word struct {
		raw, normalized string
		start, end      int
	}
	var words []word
	start := -1
	flush := func(end int) {
		if start < 0 {
			return
		}
		raw := text[start:end]
		normalized := strings.TrimFunc(raw, func(r rune) bool { return !unicode.IsLetter(r) })
		for _, r := range normalized {
			if !unicode.In(r, unicode.Cyrillic) {
				normalized = ""
				break
			}
		}
		words = append(words, word{raw, strings.ReplaceAll(strings.ToLower(normalized), "ё", "е"), start, end})
		start = -1
	}
	for i, r := range text {
		if unicode.IsSpace(r) {
			flush(i)
		} else if start < 0 {
			start = i
		}
	}
	flush(len(text))
	for i, a := range words {
		ar := []rune(a.normalized)
		if len(ar) < 4 {
			continue
		}
		for j := i + 1; j < len(words) && j <= i+5; j++ {
			// Do not bridge sentences, headings, list lines or paragraphs.
			if strings.ContainsAny(text[words[j-1].start:words[j].start], ".!?;:\r\n") {
				break
			}
			b := words[j]
			br := []rune(b.normalized)
			if len(br) < 4 || a.normalized == b.normalized {
				continue
			}
			n := 0
			for n < len(ar) && n < len(br) && ar[n] == br[n] {
				n++
			}
			strong := n >= 3 && n*2 >= min(len(ar), len(br))
			// A short onset plus a shared nearby consonant may expose root
			// alternation. This is deliberately advisory, not morphological proof.
			weak := n == 2 && min(len(ar), len(br)) >= 5 && sharedInnerConsonant(ar[n:], br[n:])
			if !strong && !weak {
				continue
			}
			// Borrow the source slice; normalize/copy only the retained evidence.
			quote := text[a.start:b.end]
			if len([]rune(quote)) > 300 {
				continue
			}
			visit(SoundEcho{Quote: quote, First: a.normalized, Second: b.normalized, SharedPrefix: string(ar[:n]), start: i, end: j + 1})
		}
	}
}

func sharedInnerConsonant(a, b []rune) bool {
	for _, r := range a[:min(4, len(a))] {
		if strings.ContainsRune("аеёиоуыэюяьъ", r) {
			continue
		}
		for _, s := range b[:min(4, len(b))] {
			if r == s {
				return true
			}
		}
	}
	return false
}

func validateEchoDecisions(e LocalEdit, a EditAssessment) error {
	if len(e.Echoes) != len(a.EchoDecisions) {
		return fmt.Errorf("edit_assessments[%d]: one echo_decisions entry required per emitted sound_echoes quote", e.ID)
	}
	seen := map[string]bool{}
	for _, d := range a.EchoDecisions {
		found := false
		for _, echo := range e.Echoes {
			if normalizeSpace(d.Quote) == echo.Quote {
				found = true
			}
		}
		if !found || seen[normalizeSpace(d.Quote)] || strings.TrimSpace(d.Reason) == "" {
			return fmt.Errorf("edit_assessments[%d]: invalid echo quote or missing contextual reason", e.ID)
		}
		seen[normalizeSpace(d.Quote)] = true
		switch d.Verdict {
		case "functional", "unrelated":
		case "accidental":
			if a.Decision != "repair" || a.Reading != "awkward" || !strings.Contains(normalizeSpace(a.ReadingQuote), normalizeSpace(d.Quote)) {
				return fmt.Errorf("edit_assessments[%d]: accidental echo requires awkward + repair and reading_quote containing the pair", e.ID)
			}
		default:
			return fmt.Errorf("edit_assessments[%d]: echo verdict must be functional, unrelated or accidental", e.ID)
		}
	}
	return nil
}

const soundEchoInstruction = `
sound_echoes — новые близкие слова с общим началом, отсутствовавшие как пара в source. Подсказка охватывает до пяти слов и короткое начало с общей согласной внутри слова: так может проявляться чередование корня. Это наблюдение о звучании, не морфологический разбор и не автоматический запрет. Короткое общее начало часто бывает случайным — unrelated допустим при конкретном объяснении. Для каждой переданной пары добавь в соответствующий edit_assessment echo_decisions:[{quote,verdict,reason}], где quote точно равна её quote, verdict — functional|unrelated|accidental. При echoes_truncated проверь всю область: список наблюдений неполный.
Рассмотри оба слова пары вместе, а не только сочетаемость нового глагола с дополнением. functional — повтор помогает различить понятия, сохраняет точный термин или условие; назови его конкретную задачу. unrelated — одинаковые буквы не создают заметного повтора по звучанию и смыслу; объясни различие. accidental — новая замена без необходимости повторяет корень соседнего слова. Простота или краткость нового глагола сама по себе не оправдывает такого эха. Если для второго слова важен точный термин, сохрани его и исправь только необязательную замену рядом. Не заменяй все повторяющиеся слова синонимами.
При accidental нужны reading=awkward, decision=repair и адресный finding; reading_quote и сообщение finding должны включать цитату пары. Остальные полезные правки, абзацы и условия сохраняются. При functional/unrelated отдельный repair из-за созвучия не нужен.`
