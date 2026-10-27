package pipeline

import (
	"fmt"
	"strings"
	"unicode"
)

// Повтор условного совета в другой главе раньше проверялся одной цитатой:
// «Ученица — только при пустом столе» в одной главе подтверждало claim,
// а безусловное «играйте Ученицу» в выводе проходило незамеченным. Здесь
// детерминированно находятся все предложения кандидата с картой claim;
// проверяющий обязан оценить каждое, а не выбрать удобную цитату.

// RepeatAttestation — оценка одного повтора: тот ли это совет и сохранено
// ли в нём условие или исключение claim.
type RepeatAttestation struct {
	Quote         string `json:"quote"`
	SameAdvice    bool   `json:"same_advice"`
	ConditionKept bool   `json:"condition_kept"`
}

// maxConditionRepeats ограничивает объём обязательной оценки на один claim.
const maxConditionRepeats = 12

// conditionRepeats возвращает для claims с условием или исключением все
// предложения кандидата, где упомянута их карта, если таких предложений
// больше одного. Claim без карты из источников не получает требования:
// без якоря повтор нельзя найти детерминированно.
func conditionRepeats(h *ResearchHandoff, candidate string) map[string][]string {
	if h == nil || candidate == "" {
		return nil
	}
	names := sourceCardNames(h)
	sentences := candidateSentences(candidate)
	out := map[string][]string{}
	for _, claim := range h.requiredClaims() {
		if strings.TrimSpace(claim.Condition) == "" && strings.TrimSpace(claim.Exception) == "" {
			continue
		}
		var anchors [][]string
		for _, name := range names {
			words := stemWords(name.Name)
			if len(words) > 0 && containsStems(textWords(claim.Action+" "+claim.Meaning), words) {
				anchors = append(anchors, words)
			}
		}
		if len(anchors) == 0 {
			continue
		}
		var found []string
		for _, sentence := range sentences {
			words := textWords(sentence)
			for _, anchor := range anchors {
				if containsStems(words, anchor) {
					found = append(found, sentence)
					break
				}
			}
			if len(found) == maxConditionRepeats {
				break
			}
		}
		if len(found) > 1 {
			out[claim.ID] = found
		}
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

// validateConditionRepeats: каждый найденный повтор оценён дословно, и ни в
// одном повторе того же совета условие не потеряно. Пропуск оценки —
// ошибка учёта (factQuoteError, допускает одну корректировку); потерянное
// условие — содержательный отрицательный результат для repair.
func validateConditionRepeats(review FactReview, h *ResearchHandoff, candidate string) error {
	required := conditionRepeats(h, candidate)
	if len(required) == 0 {
		return nil
	}
	byClaim := map[string]FactAttestation{}
	for _, item := range review.Claims {
		byClaim[item.ClaimID] = item
	}
	var lost []string
	for _, claim := range h.requiredClaims() {
		sentences, ok := required[claim.ID]
		if !ok {
			continue
		}
		item := byClaim[claim.ID]
		for _, sentence := range sentences {
			var match *RepeatAttestation
			for i := range item.Repeats {
				quote := strings.TrimSpace(item.Repeats[i].Quote)
				if quote != "" && strings.Contains(sentence, quote) {
					match = &item.Repeats[i]
					break
				}
			}
			if match == nil {
				return &factQuoteError{fmt.Sprintf("не оценён повтор %s: %q", claim.ID, sentence)}
			}
			if match.SameAdvice && !match.ConditionKept {
				lost = append(lost, fmt.Sprintf("%s: %q", claim.ID, sentence))
			}
		}
	}
	if len(lost) > 0 {
		return fmt.Errorf("в повторе совета потеряно условие или исключение: %s", strings.Join(lost, "; "))
	}
	return nil
}

const conditionRepeatInstruction = "condition_repeats перечисляет для claim все предложения candidate с его картой. Для каждого такого claim верни в его объекте repeats: [{\"quote\":\"дословный фрагмент предложения\",\"same_advice\":true|false,\"condition_kept\":true|false}] по одной записи на каждое предложение. same_advice=true, если предложение снова советует то же действие; condition_kept=true, только если в этом предложении или прямо связанной с ним фразе сохранены условие и исключение claim. Упоминание карты в списке, описании или другом совете — same_advice=false. "

// candidateSentences режет кандидата на строки и предложения без потерь
// текста внутри предложения.
func candidateSentences(text string) []string {
	var out []string
	for _, line := range strings.Split(text, "\n") {
		start := 0
		runes := []rune(line)
		for i, r := range runes {
			if (r == '.' || r == '!' || r == '?') && (i+1 == len(runes) || unicode.IsSpace(runes[i+1])) {
				if part := strings.TrimSpace(string(runes[start : i+1])); part != "" {
					out = append(out, part)
				}
				start = i + 1
			}
		}
		if part := strings.TrimSpace(string(runes[start:])); part != "" {
			out = append(out, part)
		}
	}
	return out
}

// textWords — слова в нижнем регистре, ё как е.
func textWords(text string) []string {
	return strings.FieldsFunc(strings.ReplaceAll(strings.ToLower(text), "ё", "е"), func(r rune) bool { return !unicode.IsLetter(r) && !unicode.IsDigit(r) })
}

// stemWords даёт основы слов названия: русские названия карт склоняются
// («Ученица», «Ученицу», «Ученицей»), поэтому окончание отбрасывается,
// а слово текста сравнивается с основой по префиксу.
func stemWords(name string) []string {
	words := textWords(name)
	for i, word := range words {
		if runes := []rune(word); len(runes) > 4 {
			words[i] = string(runes[:len(runes)-2])
		}
	}
	return words
}

// containsStems: слова words подряд начинаются с основ anchor.
func containsStems(words, anchor []string) bool {
	if len(anchor) == 0 || len(anchor) > len(words) {
		return false
	}
	for i := 0; i+len(anchor) <= len(words); i++ {
		match := true
		for j, stem := range anchor {
			if !strings.HasPrefix(words[i+j], stem) {
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
