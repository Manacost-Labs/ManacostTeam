package pipeline

import (
	"context"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzers"
)

func TestSalvageKeepsSurfaceFixesFromRejectedCandidate(t *testing.T) {
	source := "Патч внесет пару изменения в карты Стандарта.\n\nТаким образом теперь для призыва нужно 4 аберрации вместо 3."
	candidate := "Патч внесёт пару изменений в карты Стандарта.\n\nТаким образом, теперь для призыва нужно 4 аберрации вместо 3."
	flagged := flaggedWords([]analyzers.Finding{
		{Analyzer: "languagetool", RuleID: "AGREEMENT", Evidence: "пару изменения"},
		{Analyzer: "languagetool", RuleID: "COMMA", Evidence: "образом теперь"},
	})
	got := proofreadSalvage(source, candidate, flagged)
	if got == nil || got.Text != candidate || got.Applied != 3 || got.Skipped != 0 {
		t.Fatalf("salvage: %+v", got)
	}
	if len(got.Changes) != 2 || got.Changes[0].Line != 1 || got.Changes[1].Line != 3 {
		t.Fatalf("changes must point at real lines: %+v", got.Changes)
	}
}

func TestSalvageNeedsAnalyzerEvidenceForCommas(t *testing.T) {
	// Живой случай: кандидат убрал нужную запятую и заменил другую двоеточием.
	source := "Чернокнижник нашел решения, которые стоит упомянуть, и внимание игроков ушло."
	candidate := "Чернокнижник нашел решения которые стоит упомянуть: и внимание игроков ушло."
	if got := proofreadSalvage(source, candidate, salvageFlags{}); got != nil {
		t.Fatalf("unflagged punctuation must stay: %+v", got)
	}
}

func TestGrammarFlagWorksOnlyOnItsOwnLine(t *testing.T) {
	// Живой случай: слово с находкой в одном абзаце разрешало «на отметки» в другом.
	source := "Винрейт держится на отметке в 52%.\nКолода держится на отметке в 50%."
	candidate := "Винрейт держится на отметки в 52%.\nКолода держится на отметки в 50%."
	flags := flaggedWords([]analyzers.Finding{{Analyzer: "languagetool", RuleID: "CASE", Evidence: "отметке", Context: "...держится на отметке в 52%."}})
	got := proofreadSalvage(source, candidate, flags)
	if got == nil || got.Applied != 1 || got.Text != "Винрейт держится на отметки в 52%.\nКолода держится на отметке в 50%." {
		t.Fatalf("the flag must stay on its line: %+v", got)
	}
}

func TestSalvageNeedsAnalyzerEvidenceForWordForms(t *testing.T) {
	// Живой случай: модель «исправила» верное приложение в именительном падеже.
	source := "Добавлены 3 новые карты — предвестники дополнения."
	candidate := "Добавлены 3 новые карты — предвестников дополнения."
	if got := proofreadSalvage(source, candidate, salvageFlags{}); got != nil {
		t.Fatalf("an unflagged word must stay: %+v", got)
	}
	flagged := flaggedWords([]analyzers.Finding{{Analyzer: "hunspell", Evidence: "предвестники"}})
	if got := proofreadSalvage(source, candidate, flagged); got == nil || got.Text != candidate {
		t.Fatalf("a flagged word may take the candidate form: %+v", got)
	}
}

func TestSalvageNeverDowngradesTypography(t *testing.T) {
	// Живой случай: «ёлочки» менялись на прямые кавычки, иногда непарно.
	source := "Представляем «Путешествие» — новую сторону игры."
	candidate := "Представляем \"Путешествие\" - новую сторону игры."
	if got := proofreadSalvage(source, candidate, salvageFlags{}); got != nil {
		t.Fatalf("straight quotes and hyphens are not a fix: %+v", got)
	}
	if got := proofreadSalvage(candidate, source, salvageFlags{}); got == nil || got.Text != source {
		t.Fatalf("typographic quotes and dash are a fix: %+v", got)
	}
}

func TestSalvageDropsMeaningChangesAndKeepsSafeOnes(t *testing.T) {
	source := "Колода сильна против Мага но слабее против Жреца.\nРазыгрывайте карту на 5 ходу."
	candidate := "Колода хороша против Мага, но слабее против Жреца!\nРазыгрывайте карту на 6 ходу."
	got := proofreadSalvage(source, candidate, flaggedWords([]analyzers.Finding{{Analyzer: "languagetool", Evidence: "Мага но"}}))
	want := "Колода сильна против Мага, но слабее против Жреца.\nРазыгрывайте карту на 5 ходу."
	if got == nil || got.Text != want || got.Applied != 1 || got.Skipped != 3 {
		t.Fatalf("only the comma is safe: %+v", got)
	}
}

func TestSalvageRejectsUnsafeWordForms(t *testing.T) {
	for _, pair := range [][2]string{
		{"можно", "нужно"}, {"выше", "ниже"}, {"сильный", "несильный"}, {"Маг", "маг"},
		{"больше", "меньше"}, {"5", "6"}, {"карта", "карты"},
	} {
		if wordFormFix(pair[0], pair[1], map[string]bool{pair[0]: true}) {
			t.Fatalf("%q -> %q must not be a surface fix", pair[0], pair[1])
		}
	}
	for _, pair := range [][2]string{
		{"внесет", "внесёт"}, {"изменения", "изменений"}, {"посмотреть", "посмотерть"}, {"стратегия", "стратегии"},
	} {
		if !wordFormFix(pair[0], pair[1], map[string]bool{pair[0]: true}) {
			t.Fatalf("%q -> %q is a surface fix", pair[0], pair[1])
		}
	}
}

func TestSalvageLeavesStructureAndListMarkers(t *testing.T) {
	source := "- Первый пункт\n- Второй пункт\n\nАбзац один. Абзац два."
	candidate := "— Первый пункт\n- Второй пункт\n\nАбзац один.\n\nАбзац два."
	if got := proofreadSalvage(source, candidate, salvageFlags{}); got != nil {
		t.Fatalf("list markers and paragraph splits are not proofreading: %+v", got)
	}
}

func TestRejectedRunExposesSalvageButKeepsSourceText(t *testing.T) {
	source := "Патч внесет пару изменения в карты."
	lm := &fakeLLM{replies: []string{analysisJSON, "Патч внесёт пару изменений в карты.", "мусор", "мусор"}}
	result := run(t, lm, source, "edit")
	if result.Accepted || result.Text != source || len(result.Changes) != 0 {
		t.Fatalf("rejection must still return the source: %+v", result)
	}
	if result.ProofreadSalvage == nil || result.ProofreadSalvage.Text != "Патч внесёт пару изменения в карты." {
		t.Fatalf("safe proofreading must survive the rejection: %+v", result.ProofreadSalvage)
	}
}

func TestCriticRetriesAreConfigurableAndCarryOnlyLastReply(t *testing.T) {
	lm := &fakeLLM{replies: []string{analysisJSON, "Готово.", "мусор один", "мусор два", criticJSON("accept")}}
	s := New(lm, nil, "test")
	s.CriticRetries = 2
	result, err := s.Run(context.Background(), Request{Text: "Текст.", Mode: "edit", Game: "hearthstone", Profile: "constructed-guide"})
	if err != nil {
		t.Fatal(err)
	}
	if !result.Accepted || len(lm.stages) != 5 {
		t.Fatalf("second schema retry must be used: %v %+v", lm.stages, result.RejectionReasons)
	}
	last := lm.messages[4]
	if len(last) != 4 || last[2].Content != "мусор два" {
		t.Fatalf("retry must carry only the last bad reply: %+v", last)
	}
}

func TestPunctuationInsideKeepSpanIsNotLoss(t *testing.T) {
	quote := "Таким образом теперь для призыва божества должны погибнуть 4 аберрации вместо 3."
	in := criticInput{Source: quote, Candidate: "Таким образом, теперь для призыва божества должны погибнуть 4 аберрации вместо 3.", KeepSpans: []StrongSpan{{Quote: quote}}}
	if err := validateStrengthChanges(in, criticResult{Verdict: "accept"}); err != nil {
		t.Fatalf("a comma is not a lost strength: %v", err)
	}
	in.Candidate = "Таким образом теперь для призыва божества должны погибнуть 4 аберрации вместо 3?"
	if err := validateStrengthChanges(in, criticResult{Verdict: "accept"}); err == nil {
		t.Fatal("a changed sentence end still needs an explanation")
	}
}

func TestDiffAlignsLinesAfterInsertion(t *testing.T) {
	before := "Один.\nДва.\nТри.\nЧетыре."
	after := "Ноль.\nОдин.\nДва.\nТри.\nЧетыре."
	got := diff(before, after)
	if len(got) != 1 || got[0].After != "Ноль." || got[0].Before != "" || got[0].Line != 1 {
		t.Fatalf("one inserted line must be one change: %+v", got)
	}
}
