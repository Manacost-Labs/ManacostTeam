package pipeline

import (
	"fmt"
	"strings"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzers"
)

// В живом прогоне 136 замечаний анализаторов занимали в пять раз больше
// места, чем сама статья: 63 «повтора слова» и 49 орфографических подсказок
// к игровым названиям. Critic нужен образец и масштаб, а не каждая копия.
// Ошибки, blocker и guards передаются целиком.

// maxCriticWarningsPerRule — сколько предупреждений одного правила critic
// получает полностью; остальные сводятся в одну запись.
const maxCriticWarningsPerRule = 6

const maxSummaryEvidence = 30

func criticToolFindings(items []analyzers.Finding) []analyzers.Finding {
	type rule struct{ analyzer, id string }
	counts := map[rule]int{}
	extra := map[rule][]string{}
	var order []rule
	out := make([]analyzers.Finding, 0, len(items))
	for _, item := range items {
		if item.Severity == "error" || item.Severity == "blocker" || item.Analyzer == "guards" {
			out = append(out, item)
			continue
		}
		key := rule{item.Analyzer, item.RuleID}
		counts[key]++
		if counts[key] <= maxCriticWarningsPerRule {
			out = append(out, item)
			continue
		}
		if counts[key] == maxCriticWarningsPerRule+1 {
			order = append(order, key)
		}
		if evidence := shortEvidence(item); evidence != "" && len(extra[key]) < maxSummaryEvidence {
			extra[key] = append(extra[key], evidence)
		}
	}
	for _, key := range order {
		hidden := counts[key] - maxCriticWarningsPerRule
		message := fmt.Sprintf("Ещё %d похожих предупреждений этого правила.", hidden)
		if len(extra[key]) > 0 {
			message += " Фрагменты: " + strings.Join(extra[key], "; ")
		}
		out = append(out, analyzers.Finding{Analyzer: key.analyzer, RuleID: key.id, Severity: "warning", Message: message, Tags: []string{"summary"}})
	}
	return out
}

func shortEvidence(item analyzers.Finding) string {
	text := strings.TrimSpace(item.Evidence)
	if text == "" {
		text = strings.TrimSpace(item.Context)
	}
	if runes := []rune(text); len(runes) > 40 {
		text = string(runes[:40]) + "…"
	}
	return text
}
