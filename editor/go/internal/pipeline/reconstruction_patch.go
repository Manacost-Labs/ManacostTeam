package pipeline

import (
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzers"
)

const maxRepairAnchorRunes = 2000

type reconstructionPatch struct {
	FindingIndex *int   `json:"finding_index"`
	Before       string `json:"before"`
	After        string `json:"after"`
}

type reconstructionTarget struct {
	FindingIndex int      `json:"finding_index"`
	RuleID       string   `json:"rule_id"`
	Quotes       []string `json:"quotes,omitempty"`
}

var findingQuoteRE = regexp.MustCompile(`«([^»]+)»|"([^"\n]+)"`)

// Targets identify current findings, not past repairs. Literal evidence narrows
// where an edit can apply; findings without quotations still need full review.
func reconstructionTargets(candidate string, findings []analyzers.Finding) []reconstructionTarget {
	out := make([]reconstructionTarget, len(findings))
	for i, f := range findings {
		target := reconstructionTarget{FindingIndex: i, RuleID: f.RuleID}
		add := func(q string) {
			if strings.TrimSpace(q) != "" && strings.Contains(candidate, q) {
				for _, old := range target.Quotes {
					if old == q {
						return
					}
				}
				target.Quotes = append(target.Quotes, q)
			}
		}
		if f.Analyzer == "reader-question" {
			// Reader checks already validate the exact candidate evidence. Quotes
			// in question/reason/function are review prose, never patch anchors.
			var missing struct {
				RepairOnly            bool                  `json:"repair_only"`
				MissingReaderQuestion *ReaderQuestionTarget `json:"missing_reader_question"`
			}
			if json.Unmarshal([]byte(f.Evidence), &missing) != nil || !missing.RepairOnly || missing.MissingReaderQuestion == nil {
				add(f.Evidence)
			}
		} else if f.Analyzer == "fact-review" {
			var envelope struct {
				FactReview
				SanitizedReview *FactReview `json:"sanitized_review"`
			}
			if json.Unmarshal([]byte(f.Evidence), &envelope) == nil {
				review := envelope.FactReview
				if envelope.SanitizedReview != nil {
					review = *envelope.SanitizedReview
				}
				for _, q := range review.UnsupportedClaims {
					add(q)
				}
				for _, claim := range review.Claims {
					if claim.Status != "supported" {
						add(claim.ActionQuote)
						add(claim.ConditionQuote)
						add(claim.ExceptionQuote)
						add(claim.ConfidenceQuote)
					}
				}
			}
		} else {
			add(f.Evidence)
			for _, prefix := range []string{"named_entity: ", "number: ", "url: "} {
				if strings.HasPrefix(f.Evidence, prefix) {
					add(strings.TrimPrefix(f.Evidence, prefix))
				}
			}
			for _, match := range findingQuoteRE.FindAllStringSubmatch(f.Message, -1) {
				add(match[1])
				add(match[2])
			}
		}
		out[i] = target
	}
	return out
}

// Validate everything against the original, then apply nonoverlapping byte
// ranges. On any error nothing is applied; all untouched Markdown stays exact.
func applyReconstructionPatches(candidate, raw string, targets []reconstructionTarget) (string, error) {
	bad := func(reason string) (string, error) {
		return candidate, fmt.Errorf("reconstruction patches: %s", reason)
	}
	if len(raw) > 512000 {
		return bad("response exceeds budget")
	}
	var payload struct {
		Edits []reconstructionPatch `json:"edits"`
	}
	decoder := json.NewDecoder(strings.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&payload); err != nil {
		return bad("invalid JSON: " + err.Error())
	}
	// Unmarshal requires exactly one JSON value and no trailing prose.
	if !json.Valid([]byte(raw)) || len(payload.Edits) == 0 || len(payload.Edits) > 64 {
		return bad("expected one JSON object with 1-64 edits")
	}
	type replacement struct {
		start, end int
		after      string
	}
	var spans []replacement
	changed, inserted := 0, 0
	for _, edit := range payload.Edits {
		if edit.FindingIndex == nil || *edit.FindingIndex < 0 || *edit.FindingIndex >= len(targets) || strings.TrimSpace(edit.Before) == "" || edit.Before == edit.After || utf8.RuneCountInString(edit.Before) > maxRepairAnchorRunes || utf8.RuneCountInString(edit.After) > 2500 || strings.Count(candidate, edit.Before) != 1 {
			return bad("unknown finding, stale/ambiguous anchor or oversized/no-op edit")
		}
		start := strings.Index(candidate, edit.Before)
		end := start + len(edit.Before)
		quotes := targets[*edit.FindingIndex].Quotes
		grounded := len(quotes) == 0
		for _, q := range quotes {
			for offset := 0; offset <= len(candidate)-len(q); {
				at := strings.Index(candidate[offset:], q)
				if at < 0 {
					break
				}
				at += offset
				grounded = grounded || (start < at+len(q) && at < end)
				offset = at + len(q)
			}
		}
		if !grounded {
			return bad("edit does not overlap its current finding evidence")
		}
		changed += utf8.RuneCountInString(edit.Before)
		inserted += utf8.RuneCountInString(edit.After)
		spans = append(spans, replacement{start, end, edit.After})
	}
	budget := utf8.RuneCountInString(candidate) / 3
	if changed > budget || inserted > 2*budget {
		return bad("local repair cannot replace a large part of the article")
	}
	sort.Slice(spans, func(i, j int) bool { return spans[i].start < spans[j].start })
	for i := 1; i < len(spans); i++ {
		if spans[i].start < spans[i-1].end {
			return bad("overlapping edits")
		}
	}
	var out strings.Builder
	at := 0
	for _, span := range spans {
		out.WriteString(candidate[at:span.start])
		out.WriteString(span.after)
		at = span.end
	}
	out.WriteString(candidate[at:])
	return out.String(), nil
}

const reconstructionPatchInstruction = "\nДля длинного candidate верни только JSON {\"edits\":[{\"finding_index\":0,\"before\":\"дословный уникальный фрагмент candidate\",\"after\":\"исправленный фрагмент\"}]}. finding_index — индекс текущего задания в repair_targets (с нуля); quotes привязывают его к месту ошибки. Каждый before должен пересекаться с цитатой своего задания, если quotes непуст. Не меняй соседние предложения вне задания, вступление или вывод ради красоты. Максимум 64 замены, before до 2000 символов, after до 2500; не более трети исходного текста в before суммарно. Якоря уникальны в исходном candidate и не перекрываются, все замены применяются к одному исходному тексту. Для вставки условия включи существующую фразу в before, сохрани ее вместе с добавлением в after. Не возвращай статью целиком, пояснения или Markdown-ограждение; остальные байты текста сохраняет сервер. Патчи не подтверждают факты: после применения все проверки пройдут заново. "
