package pipeline

import (
	"encoding/json"
	"strings"
	"unicode"
)

type canonicalName struct {
	Name        string `json:"name"`
	EvidenceRef string `json:"evidence_ref"`
}

// Only structured names in referenced evidence are spelling hints. This does
// not authorize card effects, foreign sources, or facts from style examples.
func sourceCardNames(h *ResearchHandoff) []canonicalName {
	var out []canonicalName
	used := map[string]bool{}
	seen := map[string]bool{}
	for _, claim := range h.requiredClaims() {
		for _, ref := range claim.EvidenceRefs {
			used[ref] = true
		}
	}
	for _, source := range h.Sources {
		if !used[source.ID] {
			continue
		}
		var card struct {
			ID   string `json:"id"`
			Name string `json:"name"`
		}
		if json.Unmarshal([]byte(source.Quote), &card) != nil || card.ID == "" || card.Name == "" || seen[card.Name] {
			continue
		}
		if !strings.ContainsFunc(card.Name, func(r rune) bool { return unicode.Is(unicode.Cyrillic, r) }) {
			continue
		}
		seen[card.Name] = true
		out = append(out, canonicalName{Name: card.Name, EvidenceRef: source.ID})
	}
	return out
}

const canonicalNameInstruction = "canonical_names — точные написания из структурированной локализации в разрешенных evidence_refs. Если буквы имени в claims расходятся с этим написанием, исправляй орфографию по canonical_names, сохраняя грамматический падеж. Это не новое игровое сведение и не разрешение менять смысл совета, эффект или патч; не выводи свойства карты из одного имени. "
