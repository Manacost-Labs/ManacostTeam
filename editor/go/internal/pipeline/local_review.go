package pipeline

import (
	"fmt"
	"strings"
)

// LocalEdit anchors a lexical change independently of paragraph layout. Context
// uses normalized whitespace; the full source and candidate retain Markdown.
type LocalEdit struct {
	ID               int    `json:"id"`
	Before           string `json:"before"`
	After            string `json:"after"`
	SourceContext    string `json:"source_context"`
	CandidateContext string `json:"candidate_context"`
	Coarse           bool   `json:"coarse,omitempty"`
	span             hunk
}

type EditAssessment struct {
	EditID        int    `json:"edit_id"`
	ReadingQuote  string `json:"reading_quote"`
	Reading       string `json:"reading"`
	ScopeQuote    string `json:"scope_quote"`
	Scope         string `json:"scope"`
	Decision      string `json:"decision"`
	Reason        string `json:"reason"`
	FindingRuleID string `json:"finding_rule_id,omitempty"`
}

func localEdits(source, candidate string) []LocalEdit {
	a, b := strings.Fields(source), strings.Fields(candidate)
	var out []LocalEdit
	hunks := diffHunks(a, b)
	// Bound evidence for long documents and dense rewrites. A coarse region is
	// explicit, never presented as a complete local excerpt; full text remains
	// in criticInput. No second unbounded copy of a 512 KiB article is added.
	const maxRegions = 16
	stride := max(1, (len(hunks)+maxRegions-1)/maxRegions)
	for i := 0; i < len(hunks); i += stride {
		h := hunks[i]
		last := hunks[min(i+stride, len(hunks))-1]
		h.delEnd, h.insEnd = last.delEnd, last.insEnd
		coarse := stride > 1 || len(a) > maxDiffTokens || len(b) > maxDiffTokens
		out = append(out, LocalEdit{
			ID: len(out) + 1, Before: localExcerpt(a[h.delStart:h.delEnd]), After: localExcerpt(b[h.insStart:h.insEnd]),
			SourceContext:    localExcerpt(a[max(0, h.delStart-12):min(len(a), h.delEnd+12)]),
			CandidateContext: localExcerpt(b[max(0, h.insStart-12):min(len(b), h.insEnd+12)]), Coarse: coarse, span: h,
		})
	}
	return out
}

// Prefix only, with no invented ellipsis inside quoted source evidence.
func localExcerpt(tokens []string) string {
	var out strings.Builder
	n := 0
	for _, token := range tokens {
		for _, r := range token {
			if n == 300 {
				return out.String()
			}
			out.WriteRune(r)
			n++
		}
		if n == 300 {
			return out.String()
		}
		out.WriteByte(' ')
		n++
	}
	return strings.TrimSpace(out.String())
}

// This verifies evidence and coverage, not whether a linguistic judgment is
// true. Invalid reviews retry through the existing critic budget; they never
// silently drop a finding or override preservation checks.
func validateEditAssessments(in criticInput, out criticResult) error {
	if in.Mode != "edit" && in.Mode != "rewrite" {
		return nil
	}
	if len(out.EditAssessments) != len(in.LocalEdits) {
		return fmt.Errorf("edit_assessments: required one assessment for each of %d local_edits", len(in.LocalEdits))
	}
	seen := map[int]bool{}
	norm := normalizeSpace(in.Candidate)
	tokens := diffTokenize(norm)
	for _, a := range out.EditAssessments {
		if len([]rune(a.ReadingQuote)) > 300 || len([]rune(a.ScopeQuote)) > 300 {
			return fmt.Errorf("edit_assessments: quotes must not exceed 300 characters")
		}
		if a.EditID < 1 || a.EditID > len(in.LocalEdits) || seen[a.EditID] {
			return fmt.Errorf("edit_assessments: unknown or duplicate edit_id %d", a.EditID)
		}
		seen[a.EditID] = true
		h := in.LocalEdits[a.EditID-1].span
		anchored := false
		for _, r := range tokenRanges(norm, tokens, normalizeSpace(a.ReadingQuote)) {
			if touches(r[0], r[1], h.insStart, h.insEnd) {
				anchored = true
			}
		}
		if !anchored {
			return fmt.Errorf("edit_assessments[%d]: reading_quote must quote candidate at this edit", a.EditID)
		}
		if a.Reading != "natural" && a.Reading != "awkward" {
			return fmt.Errorf("edit_assessments[%d]: reading must be natural or awkward", a.EditID)
		}
		scopeText := in.Candidate
		if a.Scope == "lost" {
			scopeText = in.Source
		} else if a.Scope != "preserved" {
			return fmt.Errorf("edit_assessments[%d]: scope must be preserved or lost", a.EditID)
		}
		if strings.TrimSpace(a.ScopeQuote) == "" || !strings.Contains(normalizeSpace(scopeText), normalizeSpace(a.ScopeQuote)) {
			return fmt.Errorf("edit_assessments[%d]: scope_quote must quote candidate if preserved, source if lost", a.EditID)
		}
		if strings.TrimSpace(a.Reason) == "" {
			return fmt.Errorf("edit_assessments[%d]: concrete reason required", a.EditID)
		}
		switch a.Decision {
		case "keep":
			if a.Reading != "natural" || a.Scope != "preserved" || a.FindingRuleID != "" {
				return fmt.Errorf("edit_assessments[%d]: keep contradicts local defect", a.EditID)
			}
		case "repair":
			linked := false
			for _, f := range repairable(out.Findings) {
				if a.FindingRuleID != "" && f.RuleID == a.FindingRuleID && strings.Contains(normalizeSpace(f.Message), normalizeSpace(a.ReadingQuote)) {
					linked = true
				}
			}
			if out.Verdict == "accept" || !linked {
				return fmt.Errorf("edit_assessments[%d]: repair requires non-accept verdict and actionable finding_rule_id whose message includes reading_quote", a.EditID)
			}
		default:
			return fmt.Errorf("edit_assessments[%d]: decision must be keep or repair", a.EditID)
		}
	}
	return nil
}

func localReviewInstruction(mode string) string {
	if mode != "edit" && mode != "rewrite" {
		return ""
	}
	return `
Обязательный разбор local_edits перед общим verdict: верни edit_assessments по одному на каждый id (если local_edits пуст, массив пуст). Схема элемента: {"edit_id":1,"reading_quote":"","reading":"natural|awkward","scope_quote":"","scope":"preserved|lost","decision":"keep|repair","reason":"","finding_rule_id":""}.
Для каждого изменения сначала прочитай изменённое предложение со словами вокруг него. reading_quote — дословная цитата candidate на месте этой правки, достаточно полная для оценки сочетания слов: субъект, действие и ближайшие повторы. reading=awkward, если сокращение породило однокоренное эхо, сломало управление или звучит хуже исходного сочетания. Оцени реальную фразу, а не длину и не намерение автора.
Затем проверь область действия по целому candidate, включая соседние предложения и заголовок. scope=preserved требует scope_quote из candidate, где предмет или условие уже выражены. Повторять ту же область в каждом пункте не нужно, если она однозначна из общего заголовка или соседнего текста. При scope=lost процитируй в scope_quote именно утраченное условие source и объясни, почему оставшийся контекст его не передаёт. Указание "это keep_span" или "не сказано в том же предложении" само по себе не доказывает потери.
decision=keep сохраняет удачную форму; reason называет её конкретный эффект. Сокращение лишнего придаточного или повторной обвязки может облегчать синтаксис при прежних фактах и голосе. Не откатывай его лишь потому, что смысл не изменился. decision=repair требует точной причины в reason и finding_rule_id существующего исправимого finding. Исправляй локальное сочетание, а не отменяй соседнюю удачную редактуру. При awkward/lost нельзя ставить keep или общий accept. При отсутствии реальной потери не создавай finding ради возврата source.
Цитаты reading_quote и scope_quote не длиннее 300 символов. Сообщение связанного finding должно содержать reading_quote дословно, чтобы repair исправлял именно это место. local_edits нормализуют пробелы только для адресации слов; контексты и before/after ограничены первыми 300 символами. coarse=true обозначает объединённую область нескольких изменений или большого документа: проверь её по полному source/candidate, не считай короткую выдержку всей областью. Полезные границы абзацев оцени отдельно по полному candidate и сохраняй при любом локальном repair. Эта проверка не заменяет no_new_facts, strength_changes и доказательства improvements.`
}
