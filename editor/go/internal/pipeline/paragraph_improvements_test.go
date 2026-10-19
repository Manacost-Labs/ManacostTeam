package pipeline

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestParagraphSplitEvidence(t *testing.T) {
	source := "Мы думаем, что мета здорова. В обновлении изменены две колоды. Мы продолжим наблюдать."
	candidate := strings.ReplaceAll(source, ". ", ".\n\n")
	item := Improvement{Category: "structure", Before: "мета здорова. В обновлении изменены две колоды. Мы продолжим", After: "мета здорова.\n\nВ обновлении изменены две колоды.\n\nМы продолжим", Reason: "Разделены оценка меты, действие обновления и дальнейшее наблюдение"}
	got := ValidateImprovements(source, candidate, []Improvement{item, item})
	if len(got) != 1 || got[0].After != item.After {
		t.Fatalf("preserve one proven structural change including its boundaries: %+v", got)
	}
	for name, pair := range map[string][2]string{
		"abbreviation":   {"Др. Иванов подготовил текст. Мы продолжим наблюдать.", "Др.\n\nИванов подготовил текст. Мы продолжим наблюдать."},
		"initial":        {"А. Иванов подготовил текст.", "А.\n\nИванов подготовил текст."},
		"spaces":         {source, strings.ReplaceAll(source, ". ", ".  ")},
		"soft breaks":    {source, strings.ReplaceAll(source, ". ", ".\n")},
		"already split":  {candidate, candidate},
		"mid sentence":   {"Мы думаем, что мета здорова.", "Мы думаем,\n\nчто мета здорова."},
		"moved boundary": {"Мета здорова.\n\nМеняем колоды. Продолжим наблюдать.", "Мета здорова. Меняем колоды.\n\nПродолжим наблюдать."},
		"list":           {"- " + source, "- " + candidate},
		"ordered list":   {"1. " + source, "1. " + candidate},
		"fenced code":    {"```\n" + source + "\n```", "```\n" + candidate + "\n```"},
		"indented code":  {"    " + source, "    " + candidate},
		"inline code":    {"`" + source + "`", "`" + candidate + "`"},
		"heading":        {"# " + source, "# " + candidate},
		"html":           {"<p>" + source + "</p>", "<p>" + candidate + "</p>"},
	} {
		t.Run(name, func(t *testing.T) {
			evidence := Improvement{Category: "structure", Before: pair[0], After: pair[1], Reason: item.Reason}
			if got := ValidateImprovements(pair[0], pair[1], []Improvement{evidence}); len(got) != 0 {
				t.Fatalf("invalid structural evidence accepted: %+v", got)
			}
		})
	}
	// A quoted split cannot establish unrelated lexical edits or reordered prose.
	for _, changed := range []string{strings.Replace(candidate, "Мы думаем, что", "Мы знаем, что", 1), "Мы продолжим наблюдать.\n\nМы думаем, что мета здорова. В обновлении изменены две колоды."} {
		if got := ValidateImprovements(source, changed, []Improvement{item}); len(got) != 0 {
			t.Fatalf("unrelated change proved by paragraph quote: %+v", got)
		}
	}
	if got := ValidateImprovements(source, strings.Replace(candidate, "Мы думаем, что", "Мы думаем,\n\nчто", 1), []Improvement{item}); len(got) != 0 {
		t.Fatalf("valid quote concealed an invalid split elsewhere: %+v", got)
	}
}

func TestPipelineRetainsProvenParagraphSplit(t *testing.T) {
	source := "Мы думаем, что мета здорова. В обновлении изменены две колоды. Мы продолжим наблюдать."
	candidate := strings.ReplaceAll(source, ". ", ".\n\n")
	raw, _ := json.Marshal([]Improvement{{Category: "structure", Before: source, After: candidate, Reason: "Разделены оценка меты, действие обновления и дальнейшее наблюдение"}})
	lm := &fakeLLM{replies: []string{analysisJSON, candidate, criticWithImprovements(string(raw))}}
	r := run(t, lm, source, "edit")
	if !r.Accepted || r.Text != candidate || len(r.Improvements) != 1 {
		t.Fatalf("valid structure lost: %+v", r)
	}
}

func TestParagraphQuoteCannotBorrowAnExistingSplitFromRepeatedProse(t *testing.T) {
	source := "Мета здорова. Обновление готово. Мета здорова.\n\nОбновление готово. Продолжим. Это ожидаемо."
	candidate := strings.Replace(source, "Продолжим. Это", "Продолжим.\n\nЭто", 1)
	item := Improvement{Category: "structure", Before: "Мета здорова. Обновление готово.", After: "Мета здорова.\n\nОбновление готово.", Reason: "Оценка меты отделена от готовности обновления"}
	if got := ValidateImprovements(source, candidate, []Improvement{item}); len(got) != 0 {
		t.Fatalf("quote from a different occurrence counted as improvement: %+v", got)
	}
	source = "Мета здорова. Мета здорова.\n\nМета здорова. Обновление готово. Продолжим. Это ожидаемо."
	candidate = strings.Replace(source, "Продолжим. Это", "Продолжим.\n\nЭто", 1)
	item.Before, item.After = "Мета здорова. Мета здорова.", "Мета здорова.\n\nМета здорова."
	if got := ValidateImprovements(source, candidate, []Improvement{item}); len(got) != 0 {
		t.Fatalf("overlapping occurrences must not count as unique: %+v", got)
	}
}
