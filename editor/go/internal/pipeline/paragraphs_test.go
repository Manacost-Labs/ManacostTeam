package pipeline

import (
	"strings"
	"testing"
)

func TestEditRestoresAnchoredBoundaryWithoutLosingNewSplit(t *testing.T) {
	source := "На сцене выступят три команды. Трансляция начнётся вечером.\n\nИзучите правила и выберите команду заранее."
	draft := "На сцене выступят три команды.\n\nТрансляция начнётся вечером. Изучите правила и выберите команду заблаговременно."
	want := "На сцене выступят три команды.\n\nТрансляция начнётся вечером.\n\nИзучите правила и выберите команду заблаговременно."
	model := &fakeLLM{replies: []string{analysisJSON, draft, criticJSON("accept")}}
	result := run(t, model, source, "edit")
	if !result.Accepted || result.Text != want {
		t.Fatalf("source boundary or new split lost: %+v", result)
	}
	if !strings.Contains(model.messages[2][1].Content, `вечером.\n\nИзучите`) {
		t.Fatal("critic did not receive the actual formatted candidate")
	}
}

func TestBoundaryRestorationIsConservativeAndLexicallyStable(t *testing.T) {
	source := "Одна ясная законченная мысль.\n\nВторая мысль начинается здесь."
	merged := strings.ReplaceAll(source, "\n\n", " ")
	for _, mode := range []string{"rewrite", "reconstruct", "proofread", "facts_only"} {
		if got := preserveEditParagraphs(mode, source, merged); got != merged {
			t.Fatal("boundary policy leaked to", mode)
		}
	}
	for _, tc := range []struct{ name, source, candidate string }{
		{"rewritten_anchor", source, "Одна ясная завершённая мысль. Вторая мысль начинается здесь."},
		{"ambiguous_candidate", source, merged + " " + merged},
		{"ambiguous_source", source + "\n\n" + source, merged},
		{"code", "```\n" + source + "\n```", merged},
		{"html", "<p>" + source + "</p>", merged},
		{"list", "- " + source, merged},
		{"ordered_dot", "1. " + source, "1. " + merged},
		{"ordered_parenthesis", "2) " + source, "2) " + merged},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := preserveEditParagraphs("edit", tc.source, tc.candidate); got != tc.candidate {
				t.Fatal("uncertain anchor changed")
			}
		})
	}
	got := preserveEditParagraphs("edit", source, merged)
	if got != source || strings.Join(strings.Fields(got), " ") != strings.Join(strings.Fields(merged), " ") || preserveEditParagraphs("edit", source, got) != got {
		t.Fatal("word content or idempotence broken")
	}
	if got := preserveEditParagraphs("edit", strings.ReplaceAll(source, "\n", "\r\n"), merged); got != source {
		t.Fatal("CRLF boundary not recognized")
	}
	if got := preserveEditParagraphs("edit", strings.ReplaceAll(source, "\n\n", "\n\u00a0\n"), merged); got != source {
		t.Fatal("Unicode blank line not recognized")
	}
}

func TestEditRestoresBoundaryAfterLocalRepair(t *testing.T) {
	source := "Правило действует для всех игроков.\n\nПолучить награду можно будет завтра после победы."
	draft := "Правило действует для всех игроков.\n\nПолучить награду можно завтра после победы."
	merged := strings.ReplaceAll(draft, "\n\n", " ")
	model := &fakeLLM{replies: []string{analysisJSON, draft, criticJSON("repair", warning("style.local", "Проверь фразу о награде, сохрани остальные полезные правки.")), merged, criticJSON("accept")}}
	result := run(t, model, source, "edit")
	if !result.Accepted || result.Text != draft || result.Attempts != 2 {
		t.Fatalf("repair erased a source boundary: %+v", result)
	}
}
