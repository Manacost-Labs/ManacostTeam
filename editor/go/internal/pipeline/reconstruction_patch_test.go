package pipeline

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzers"
	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

func TestLongReconstructionRepairPreservesUntargetedConditionsAndParagraphs(t *testing.T) {
	intro := "Если стол безопасен, можно сохранить заморозку.\n\n" + strings.Repeat("Полезное объяснение остается на месте. ", 100)
	before := intro + "\n\nСрок отсчитывается от вашего следующего хода.\n\nДругой абзац с условием.\n"
	after := strings.Replace(before, "от вашего следующего хода", "от следующего хода разыгравшего карту", 1)
	m := &fakeLLM{replies: []string{`{"edits":[{"finding_index":0,"before":"от вашего следующего хода","after":"от следующего хода разыгравшего карту"}]}`}}
	s := New(m, nil, "fake")
	got, err := s.repairReconstruction(context.Background(), rules.RuleBundle{}, readyHandoff(), before, []analyzers.Finding{{RuleID: "actor", Message: "Исправь перспективу", Evidence: "от вашего следующего хода"}}, nil, nil)
	if err != nil || got != after {
		t.Fatalf("local repair changed unrelated conditions or failed to apply: err=%v, equal=%v", err, got == after)
	}
}

func TestReconstructionPatchesRejectInvalidOrUnrelatedEditsAtomically(t *testing.T) {
	before := "Вступление с условием.\n\nПравило для игрока. Другая ошибка. Повтор. Повтор."
	targets := []reconstructionTarget{{FindingIndex: 0, RuleID: "actor", Quotes: []string{"Правило для игрока"}}, {FindingIndex: 1, RuleID: "other", Quotes: []string{"Другая ошибка"}}}
	for name, raw := range map[string]string{
		"truncated":            `{"edits":[`,
		"full prose":           before,
		"unknown key":          `{"edits":[],"extra":true}`,
		"trailing":             `{"edits":[]} explanation`,
		"empty":                `{"edits":[]}`,
		"null":                 `null`,
		"missing index":        `{"edits":[{"before":"Правило","after":"Совет"}]}`,
		"unknown finding":      `{"edits":[{"finding_index":2,"before":"Правило","after":"Совет"}]}`,
		"negative finding":     `{"edits":[{"finding_index":-1,"before":"Правило","after":"Совет"}]}`,
		"wrong finding":        `{"edits":[{"finding_index":1,"before":"Правило","after":"Совет"}]}`,
		"unrelated":            `{"edits":[{"finding_index":0,"before":"Вступление с условием.","after":"Безусловное вступление."}]}`,
		"stale":                `{"edits":[{"finding_index":0,"before":"Старое правило","after":"Совет"}]}`,
		"ambiguous":            `{"edits":[{"finding_index":0,"before":"Повтор.","after":"Совет"}]}`,
		"empty anchor":         `{"edits":[{"finding_index":0,"before":"","after":"Совет"}]}`,
		"noop":                 `{"edits":[{"finding_index":0,"before":"Правило","after":"Правило"}]}`,
		"overlap":              `{"edits":[{"finding_index":0,"before":"Правило для игрока","after":"Совет"},{"finding_index":0,"before":"для игрока","after":"читателю"}]}`,
		"duplicate":            `{"edits":[{"finding_index":0,"before":"Правило","after":"Совет"},{"finding_index":0,"before":"Правило","after":"Совет"}]}`,
		"partial then invalid": `{"edits":[{"finding_index":0,"before":"Правило","after":"Совет"},{"finding_index":1,"before":"Нет якоря","after":"Новая фраза"}]}`,
	} {
		t.Run(name, func(t *testing.T) {
			got, err := applyReconstructionPatches(before, raw, targets)
			if err == nil || got != before {
				t.Fatalf("invalid patch changed candidate: %v %q", err, got)
			}
		})
	}
}

func TestReconstructionPatchesUseOriginalUnicodeRangesAndBudgets(t *testing.T) {
	index := 0
	encode := func(edits []reconstructionPatch) string {
		b, _ := json.Marshal(map[string]any{"edits": edits})
		return string(b)
	}
	before := "абв\n\nПервое условие. Второе условие.\n\n" + strings.Repeat("текст ", 1200)
	targets := []reconstructionTarget{{FindingIndex: 0, RuleID: "scope"}}
	edits := []reconstructionPatch{{&index, "Второе условие", "Вторая оговорка"}, {&index, "Первое условие", "Второе условие"}}
	got, err := applyReconstructionPatches(before, encode(edits), targets)
	want := strings.Replace(strings.Replace(before, "Второе условие", "Вторая оговорка", 1), "Первое условие", "Второе условие", 1)
	if err != nil || got != want {
		t.Fatal("edits were applied sequentially to mutated text or broke UTF-8", err)
	}
	for _, edit := range []reconstructionPatch{{&index, strings.Repeat("текст ", 334), "x"}, {&index, "абв", strings.Repeat("д", 2501)}} {
		if got, err := applyReconstructionPatches(before, encode([]reconstructionPatch{edit}), targets); err == nil || got != before {
			t.Fatal("oversize repair accepted", err)
		}
	}
	// An exact 2000-rune Unicode anchor is within the bound, unlike 2001.
	for _, n := range []int{2000, 2001} {
		candidate := strings.Repeat("д", n) + "unique tail" + strings.Repeat("ж", 8000)
		got, err := applyReconstructionPatches(candidate, encode([]reconstructionPatch{{&index, strings.Repeat("д", n), "Исправлено"}}), targets)
		if (err == nil) != (n == 2000) || (err != nil && got != candidate) {
			t.Fatal("rune boundary wrong", n, err)
		}
	}
	// Unique anchors may not collectively replace the whole long article.
	candidate := strings.Repeat("а", 1500) + strings.Repeat("б", 1500) + strings.Repeat("в", 1500)
	var large []reconstructionPatch
	for _, letter := range []string{"а", "б", "в"} {
		large = append(large, reconstructionPatch{&index, strings.Repeat(letter, 1500), "сокращено"})
	}
	if got, err := applyReconstructionPatches(candidate, encode(large), targets); err == nil || got != candidate {
		t.Fatal("whole long article rewrite accepted")
	}
	near := strings.Repeat("д", 2000) + "я"
	if got, err := applyReconstructionPatches(near, encode([]reconstructionPatch{{&index, strings.Repeat("д", 2000), "новый текст"}}), targets); err == nil || got != near {
		t.Fatal("near-threshold rewrite must preserve two-thirds too")
	}
}

func TestLongReconstructionPatchStillNeedsFreshCompleteFactReview(t *testing.T) {
	padding := "\n\n" + strings.Repeat("пояснение с условием сохраняется. ", 100)
	bad := strings.Replace(publicationCandidate, " при слабой позиции", "", 1) + padding
	good := publicationCandidate + padding
	negative := strings.Replace(publicationFact, `"status":"supported"`, `"status":"insufficient"`, 1)
	negative = strings.Replace(negative, `"condition_quote":"при слабой позиции"`, `"condition_quote":""`, 1)
	patch := `{"edits":[{"finding_index":0,"before":"Сохраняйте ресурс","after":"Сохраняйте ресурс при слабой позиции"}]}`
	critic := strings.Replace(criticJSON("accept"), improvementJSON, `[{"category":"usefulness","before":"кроме угрозы поражения.","after":"кроме угрозы поражения. Совет может помочь.","reason":"совет связан с ограничением применения"}]`, 1)
	for _, positive := range []bool{true, false} {
		fresh := publicationFact
		if !positive {
			fresh = negative
		}
		writer := &fakeLLM{replies: []string{bad, patch}}
		reviewer := &fakeLLM{replies: []string{negative, critic, fresh, critic, fresh}}
		s := New(writer, nil, "fake")
		s.Reviewer = reviewer
		r, err := s.Run(context.Background(), Request{Mode: "write", Handoff: readyHandoff()})
		if err != nil || (r.FactReview != nil) != positive || (!positive && r.Accepted) {
			t.Fatalf("patch bypassed fresh factual decision: %+v %v", r, err)
		}
		if positive && (r.FactCheckPassed == nil || !*r.FactCheckPassed || !r.ChecksComplete) {
			t.Fatal("fresh complete factual success was not recorded")
		}
		if len(reviewer.messages) < 3 || lastUserJSON(t, reviewer.messages[2])["candidate"] != good {
			t.Fatal("missing fresh whole-candidate factual review")
		}
	}
}
