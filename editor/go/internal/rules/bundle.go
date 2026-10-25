// Package rules формирует небольшой контекст для модели. Нормы и внутренние
// метрики остаются backend-проверкой и намеренно не попадают в prompt.
package rules

import (
	"encoding/json"
	"strings"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzer"
)

type RuleBundle struct {
	// Supplied only to reconstruction; ordinary editing preserves source structure.
	SectionsRequired  []string            `json:"-"`
	Task              string              `json:"task"`
	EditorialGoal     string              `json:"editorial_goal"`
	StyleRules        []string            `json:"style_rules"`
	TerminologyRules  []string            `json:"terminology_rules"`
	Corrections       []map[string]string `json:"corrections,omitempty"`
	ProtectedEntities []string            `json:"protected_entities"`
	SourceClaims      []map[string]any    `json:"source_claims,omitempty"`
	RelevantExamples  []string            `json:"relevant_examples,omitempty"`
	QAFindings        []string            `json:"qa_findings,omitempty"`
	Game              string              `json:"game"`
	Genre             string              `json:"genre"`
	Mode              string              `json:"mode"`
	Depth             string              `json:"depth,omitempty"`
	Language          string              `json:"language"`
	AuthorProfile     string              `json:"author_profile,omitempty"`
	// Writer-only craft context; review stages judge the result, not the recipe.
	ContrastPairs []analyzer.ContrastPair `json:"-"`
}

func Build(r *analyzer.Rules, mode, depth, language string, claims []map[string]any) RuleBundle {
	if mode == "" {
		mode = "GUIDE"
	}
	if language == "" {
		language = "ru-RU"
	}
	genre, profile := "generic", ""
	if r != nil {
		profile, genre = r.Profile, r.Profile
	}
	b := RuleBundle{Game: valueOr(rGame(r), "hearthstone"), Genre: genre, AuthorProfile: profile,
		Mode: mode, Depth: depth, Language: language, SourceClaims: safeClaims(claims),
		ProtectedEntities: []string{"названия карт и персонажей", "классы, архетипы и типы существ", "числа, проценты, стоимость и характеристики", "ссылки, deck codes и Markdown-разметка", "цитаты, отрицания и осторожные условия"},
		StyleRules:        []string{"сохраняй авторский голос и неровный ритм", "один абзац — одна мысль; вывод ставь рядом с объяснением", "для GUIDE скрывай исследовательскую методику и давай читателю прямой совет", "не добавляй факты, карты, цифры или выводы от себя"},
		TerminologyRules:  []string{"используй официальные названия карт", "Темные дары / Темный дар — не «подарки»", "на Полях сражений говори «тип существа», а не «племя»"},
		Task:              taskFor(mode, depth), EditorialGoal: goalFor(mode, depth)}
	if r != nil {
		b.SectionsRequired = append([]string(nil), r.SectionsRequired...)
		b.ContrastPairs = append([]analyzer.ContrastPair(nil), r.ContrastPairs...)
		if len(r.StyleRules) > 0 {
			b.StyleRules = append([]string{}, r.StyleRules...)
		}
		if len(r.TaskContext) > 0 {
			b.AuthorProfile = "manacost"
			if r.Game != "hearthstone" {
				b.ProtectedEntities = []string{"названия способностей, талантов, предметов и персонажей", "числа, проценты, характеристики и длительности", "ссылки и Markdown-разметка", "цитаты, отрицания и осторожные условия"}
				b.TerminologyRules = []string{"используй подтверждённые названия только выбранной игры и сборки", "не придумывай официальную локализацию; неподтверждённое имя оставь на проверку"}
			}
		}
		for _, pair := range r.Replace {
			if pair["from"] != "" && pair["to"] != "" {
				b.TerminologyRules = append(b.TerminologyRules, pair["from"]+" → "+pair["to"])
			}
		}
		for _, keep := range r.Keep {
			b.TerminologyRules = append(b.TerminologyRules, "не заменять: "+keep)
		}
		// The sidecar resolves applicability for both prompt and postflight.
		// Keep advisory context separate from unconditional terminology rules.
		for _, correction := range r.Corrections {
			copy := make(map[string]string, len(correction))
			for key, value := range correction {
				copy[key] = value
			}
			b.Corrections = append(b.Corrections, copy)
		}
		for _, ex := range r.StyleExamples {
			if len(b.RelevantExamples) == 4 {
				break
			}
			if strings.TrimSpace(ex.Text) != "" {
				b.RelevantExamples = append(b.RelevantExamples, strings.TrimSpace(ex.Text))
			}
		}
	}
	return b
}

func (b RuleBundle) WithQA(findings []string) RuleBundle {
	b.QAFindings = append([]string{}, findings...)
	return b
}

func (b RuleBundle) Prompt() string {
	raw, _ := json.Marshal(b)
	return "КОНТЕКСТ РЕДАКТОРА (служебные метрики скрыты). Corrections: required — обязательная применимая норма; advisory — пример только в указанном контексте, не глобальный запрет. Fact corrections и стилевые примеры не доказывают текущие игровые факты:\n" + string(raw)
}

func safeClaims(claims []map[string]any) []map[string]any {
	out := make([]map[string]any, 0, len(claims))
	for _, claim := range claims {
		clean := map[string]any{}
		for _, key := range []string{"claim_id", "meaning", "action", "condition", "exception", "confidence", "patch", "meta_epoch", "evidence_refs", "status", "research_context"} {
			if value, ok := claim[key]; ok {
				clean[key] = value
			}
		}
		out = append(out, clean)
	}
	return out
}

func taskFor(mode, depth string) string {
	if depth == "переплавка" || mode == "rewrite" {
		return "пересобери слабый игровой текст в готовый материал"
	}
	return "отредактируй игровой текст"
}
func goalFor(mode, depth string) string {
	switch {
	case mode == "proofread":
		return "исправь только ошибки, не меняя стиль"
	case depth == "переплавка" || mode == "rewrite":
		return "улучши логику, структуру, ясность и пользу, сохранив все факты"
	default:
		return "сделай текст понятнее и легче для чтения без потери авторского голоса"
	}
}
func rGame(r *analyzer.Rules) string {
	if r != nil {
		return r.Game
	}
	return ""
}
func valueOr(v, fallback string) string {
	if v == "" {
		return fallback
	}
	return v
}
