package pipeline

import (
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzers"
	"github.com/Manacost-Labs/EditorTeam/go/internal/guards"
)

// ProofreadSalvage — безопасная корректура из отклонённого кандидата.
// Отказ всей правки не должен терять исправленную запятую или окончание:
// из кандидата переносятся только поверхностные изменения, которые
// детерминированно не меняют слова, числа, названия и модальность.
// Это не редакционный допуск: Accepted остаётся false, а Text — исходник.
type ProofreadSalvage struct {
	Text    string   `json:"text"`
	Changes []Change `json:"changes"`
	Applied int      `json:"applied"`
	Skipped int      `json:"skipped"`
	Note    string   `json:"note"`
}

const salvageNote = "Правка отклонена целиком; здесь только безопасная корректура из кандидата " +
	"(пунктуация, кавычки-ёлочки, тире, ё и слова, отмеченные орфографической проверкой). " +
	"Публикационного допуска нет, изменения нужно просмотреть."

// Пределы точного выравнивания: salvage — дешёвая страховка, а не второй
// редактор. Выше них возвращается nil, и исходник остаётся как был.
const (
	maxSalvageLines     = 1200
	maxSalvageHunkWords = 400
)

// salvageSafe chars: знаки, замена которых не меняет границы предложений
// и модальность. Точка, ?, ! и скобки сюда намеренно не входят.
const salvageSafePunct = ",;:—–-«»\"„“”'’…\u00a0 "

// Вставлять можно только типографские знаки: живой кандидат менял «ёлочки»
// на прямые кавычки и оставлял «непарные", а тире на дефис. Удалять такие
// знаки по-прежнему можно, если взамен стоит типографский.
const salvageDowngradePunct = "\"'-"

// SalvageProofreading — то же для legacy /edit, где отказ тоже возвращает
// исходник. Без находок анализаторов слова меняются только в части ё.
func SalvageProofreading(source, candidate string) *ProofreadSalvage {
	return proofreadSalvage(source, candidate, salvageFlags{})
}

// salvageFlags — места исходника, отмеченные анализаторами. Только там
// кандидат может заменить форму слова или знак: модель иногда «исправляет»
// верное («предвестники» → «предвестников», «на отметке» → «на отметки»).
// Опечатка Hunspell ошибочна везде, грамматическая находка LanguageTool —
// только в строке со своим контекстом.
type salvageFlags struct {
	spelling map[string]bool
	grammar  []grammarFlag
}

type grammarFlag struct {
	anchor string
	words  []string
}

func flaggedWords(findings []analyzers.Finding) salvageFlags {
	flags := salvageFlags{spelling: map[string]bool{}}
	for _, item := range findings {
		// Пустой фрагмент заменяется в pipeline контекстом всего предложения;
		// такая «находка» не указывает на слово и ничего не разрешает.
		evidence := strings.TrimSpace(item.Evidence)
		words := textWords(evidence)
		if evidence == "" || evidence == strings.TrimSpace(item.Context) || len(words) > 4 {
			continue
		}
		switch {
		case item.Analyzer == "hunspell" || (item.Analyzer == "languagetool" && strings.HasPrefix(item.RuleID, "MORFOLOGIK")):
			if len(words) == 1 {
				flags.spelling[words[0]] = true
			}
		case item.Analyzer == "languagetool":
			flags.grammar = append(flags.grammar, grammarFlag{anchor: contextAnchor(item.Context, evidence), words: textWords(evidence)})
		}
	}
	return flags
}

// contextAnchor — отмеченный фрагмент с соседними знаками из контекста
// LanguageTool, без многоточий обрезки: по нему находится нужная строка.
func contextAnchor(context, evidence string) string {
	runes, ev := []rune(context), []rune(evidence)
	at := strings.Index(context, evidence)
	if at < 0 {
		return evidence
	}
	start := len([]rune(context[:at]))
	from, to := max(0, start-12), min(len(runes), start+len(ev)+12)
	return strings.Trim(strings.TrimSpace(string(runes[from:to])), ".…")
}

// forLine: слова, которые можно менять в строке, и слова с грамматической
// находкой рядом — только они разрешают правку знаков.
func (f salvageFlags) forLine(line string) (words, grammar map[string]bool) {
	words, grammar = map[string]bool{}, map[string]bool{}
	for word := range f.spelling {
		words[word] = true
	}
	for _, flag := range f.grammar {
		if flag.anchor == "" || !strings.Contains(strings.Join(strings.Fields(line), " "), strings.Join(strings.Fields(flag.anchor), " ")) {
			continue
		}
		for _, word := range flag.words {
			words[word], grammar[word] = true, true
		}
	}
	return words, grammar
}

func proofreadSalvage(source, candidate string, flags salvageFlags) *ProofreadSalvage {
	if source == "" || candidate == "" || source == candidate {
		return nil
	}
	a, b := strings.Split(source, "\n"), strings.Split(candidate, "\n")
	if len(a)+len(b) > maxSalvageLines {
		return nil
	}
	var out strings.Builder
	applied, skipped := 0, 0
	posA := 0
	emit := func(lines []string) {
		for _, line := range lines {
			out.WriteString(line)
			out.WriteByte('\n')
		}
	}
	for _, h := range lineHunks(a, b) {
		emit(a[posA:h.delStart])
		posA = h.delEnd
		del, ins := a[h.delStart:h.delEnd], b[h.insStart:h.insEnd]
		// Склейка и разбиение абзацев — структура, а не корректура.
		if len(del) != len(ins) {
			emit(del)
			skipped++
			continue
		}
		for i := range del {
			words, grammar := flags.forLine(del[i])
			line, ok, rejected := salvageLine(del[i], ins[i], words, grammar)
			applied += ok
			skipped += rejected
			out.WriteString(line)
			out.WriteByte('\n')
		}
	}
	emit(a[posA:])
	text := strings.TrimSuffix(out.String(), "\n")
	if applied == 0 || text == source {
		return nil
	}
	// Последний барьер: ссылки, числа, имена и отрицания исходника на месте.
	if report := guards.Compare(source, text); report.HasHardChanges() || len(report.Added) > 0 {
		return nil
	}
	return &ProofreadSalvage{Text: text, Changes: diff(source, text), Applied: applied, Skipped: skipped, Note: salvageNote}
}

// lineHunks выравнивает строки тем же diff Майерса, что и токены.
func lineHunks(a, b []string) []hunk {
	ops := myers(a, b)
	var out []hunk
	current, open := hunk{}, false
	posA, posB := 0, 0
	for _, op := range ops {
		switch op.kind {
		case opEqual:
			if open {
				out = append(out, current)
				open = false
			}
			posA += op.length
			posB += op.length
		case opDelete, opInsert:
			if !open {
				current = hunk{delStart: posA, delEnd: posA, insStart: posB, insEnd: posB}
				open = true
			}
			if op.kind == opDelete {
				posA += op.length
				current.delEnd = posA
			} else {
				posB += op.length
				current.insEnd = posB
			}
		}
	}
	if open {
		out = append(out, current)
	}
	return out
}

// salvageLine переносит безопасные под-изменения одной строки. Возвращает
// итоговую строку, число перенесённых и число отброшенных изменений.
func salvageLine(source, candidate string, flagged, grammar map[string]bool) (string, int, int) {
	a, b := surfaceTokens(source), surfaceTokens(candidate)
	if wordCount(a) > maxSalvageHunkWords || wordCount(b) > maxSalvageHunkWords {
		return source, 0, 1
	}
	ops := myers(a, b)
	var out strings.Builder
	applied, skipped := 0, 0
	posA, posB := 0, 0
	var del, ins []string
	start := 0
	flush := func() {
		if len(del) == 0 && len(ins) == 0 {
			return
		}
		// Начало строки — место маркеров списков и заголовков.
		near := grammar[nearWord(a, start, -1)] || grammar[nearWord(a, posA, 1)]
		if (start > 0 || allWords(del, ins)) && safeSurfaceChange(del, ins, flagged, near) {
			out.WriteString(strings.Join(ins, ""))
			applied++
		} else {
			out.WriteString(strings.Join(del, ""))
			skipped++
		}
		del, ins = nil, nil
	}
	for _, op := range ops {
		switch op.kind {
		case opEqual:
			flush()
			out.WriteString(strings.Join(a[posA:posA+op.length], ""))
			posA += op.length
			posB += op.length
		case opDelete:
			if len(del) == 0 && len(ins) == 0 {
				start = posA
			}
			del = append(del, a[posA:posA+op.length]...)
			posA += op.length
		case opInsert:
			if len(del) == 0 && len(ins) == 0 {
				start = posA
			}
			ins = append(ins, b[posB:posB+op.length]...)
			posB += op.length
		}
	}
	flush()
	return out.String(), applied, skipped
}

// surfaceTokens режет строку без потерь: слово (буквы, цифры, внутренний
// дефис или апостроф), пробельный промежуток или один прочий символ.
func surfaceTokens(s string) []string {
	var out []string
	runes := []rune(s)
	for i := 0; i < len(runes); {
		j := i + 1
		switch r := runes[i]; {
		case isSalvageWordRune(r):
			for j < len(runes) && (isSalvageWordRune(runes[j]) || (strings.ContainsRune("-'’", runes[j]) && j+1 < len(runes) && isSalvageWordRune(runes[j+1]))) {
				j++
			}
		case unicode.IsSpace(r):
			for j < len(runes) && unicode.IsSpace(runes[j]) {
				j++
			}
		}
		out = append(out, string(runes[i:j]))
		i = j
	}
	return out
}

func allWords(sides ...[]string) bool {
	for _, side := range sides {
		for _, t := range side {
			if !isWordToken(t) {
				return false
			}
		}
	}
	return true
}

func isSalvageWordRune(r rune) bool { return unicode.IsLetter(r) || unicode.IsDigit(r) }

func isWordToken(t string) bool {
	r, _ := utf8.DecodeRuneInString(t)
	return isSalvageWordRune(r)
}

func wordCount(tokens []string) int {
	n := 0
	for _, t := range tokens {
		if isWordToken(t) {
			n++
		}
	}
	return n
}

// nearWord — ближайшее слово исходной строки слева (dir=-1) от позиции или
// справа (dir=1) начиная с неё, в нижнем регистре и с ё как е.
func nearWord(tokens []string, at, dir int) string {
	i := at
	if dir < 0 {
		i = at - 1
	}
	for ; i >= 0 && i < len(tokens); i += dir {
		if isWordToken(tokens[i]) {
			return strings.ReplaceAll(strings.ToLower(tokens[i]), "ё", "е")
		}
	}
	return ""
}

// safeSurfaceChange. Живой прогон показал, что модель ошибается и в знаках:
// убирает нужную запятую, ставит двоеточие вместо запятой, снимает
// неразрывный пробел. Поэтому без находки анализатора рядом проходят только
// однозначные улучшения типографики; запятая, двоеточие и форма слова
// переносятся, лишь если Hunspell или LanguageTool отметили это место.
func safeSurfaceChange(del, ins []string, flagged map[string]bool, near bool) bool {
	var delWords, insWords []string
	var delPunct, insPunct strings.Builder
	nbsp := 0
	for side, tokens := range [][]string{del, ins} {
		for _, t := range tokens {
			if isWordToken(t) {
				if side == 0 {
					delWords = append(delWords, t)
				} else {
					insWords = append(insWords, t)
				}
				continue
			}
			if strings.ContainsAny(t, "\n\r") || strings.Trim(t, salvageSafePunct+"\t") != "" {
				return false
			}
			if side == 1 && strings.ContainsAny(t, salvageDowngradePunct) {
				return false
			}
			for _, r := range t {
				switch {
				case r == '\u00a0':
					nbsp += 2*side - 1
				case unicode.IsSpace(r):
				case side == 0:
					delPunct.WriteRune(r)
				default:
					insPunct.WriteRune(r)
				}
			}
		}
	}
	if nbsp < 0 {
		return false
	}
	punctOK := delPunct.String() == insPunct.String() || typographyUpgrade(delPunct.String(), insPunct.String()) || near
	switch {
	case len(delWords) == 0 && len(insWords) == 0:
		return punctOK
	case len(delWords) == 1 && len(insWords) == 1:
		return punctOK && wordFormFix(delWords[0], insWords[0], flagged)
	default:
		return false
	}
}

// typographyUpgrade: прямые кавычки и дефисы заменены типографскими знаками
// один к одному, без добавления или удаления других знаков.
func typographyUpgrade(before, after string) bool {
	x, y := []rune(before), []rune(after)
	if len(x) == 0 || len(x) != len(y) {
		return false
	}
	for i := range x {
		if !strings.ContainsRune(salvageDowngradePunct, x[i]) || !strings.ContainsRune("«»„“—–", y[i]) {
			return false
		}
	}
	return true
}

// wordFormFix допускает ё/е всегда, а опечатку на одну букву и исправление
// окончания при общей основе — только для слова, отмеченного анализатором.
// Цифры, смена регистра первой буквы, «не»-приставка и короткие слова не
// проходят: там смена буквы часто меняет смысл.
func wordFormFix(before, after string, flagged map[string]bool) bool {
	if strings.ContainsFunc(before+after, unicode.IsDigit) {
		return false
	}
	x, y := []rune(before), []rune(after)
	if len(x) == 0 || len(y) == 0 || unicode.IsUpper(x[0]) != unicode.IsUpper(y[0]) {
		return false
	}
	lx, ly := []rune(strings.ToLower(before)), []rune(strings.ToLower(after))
	if strings.ReplaceAll(string(lx), "ё", "е") == strings.ReplaceAll(string(ly), "ё", "е") {
		return true
	}
	if !flagged[strings.ReplaceAll(string(lx), "ё", "е")] || hasNegationPrefix(lx) != hasNegationPrefix(ly) {
		return false
	}
	shorter := min(len(lx), len(ly))
	if shorter < 6 {
		return false
	}
	if damerauOne(lx, ly) {
		return true
	}
	prefix := 0
	for prefix < shorter && lx[prefix] == ly[prefix] {
		prefix++
	}
	return prefix >= 4 && prefix >= shorter-3 && len(lx)-prefix <= 3 && len(ly)-prefix <= 3
}

func hasNegationPrefix(w []rune) bool {
	s := string(w)
	return strings.HasPrefix(s, "не") || strings.HasPrefix(s, "ни")
}

// damerauOne: ровно одна вставка, удаление, замена или перестановка соседних.
func damerauOne(a, b []rune) bool {
	if len(a) < len(b) {
		a, b = b, a
	}
	switch len(a) - len(b) {
	case 0:
		var diffs []int
		for i := range a {
			if a[i] != b[i] {
				diffs = append(diffs, i)
			}
		}
		if len(diffs) == 1 {
			return true
		}
		return len(diffs) == 2 && diffs[1] == diffs[0]+1 && a[diffs[0]] == b[diffs[1]] && a[diffs[1]] == b[diffs[0]]
	case 1:
		i := 0
		for i < len(b) && a[i] == b[i] {
			i++
		}
		return string(a[i+1:]) == string(b[i:])
	default:
		return false
	}
}
