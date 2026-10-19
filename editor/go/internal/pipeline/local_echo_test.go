package pipeline

import (
	"strings"
	"testing"
)

// Collect only in small test fixtures; production consumes pairs as a stream.
func introducedEchoes(source, candidate string) []SoundEcho {
	var out []SoundEcho
	walkIntroducedEchoes(source, candidate, func(e SoundEcho) { e.Quote = normalizeSpace(e.Quote); out = append(out, e) })
	return out
}

func TestIntroducedEchoEvidence(t *testing.T) {
	for _, tc := range []struct {
		name, source, candidate string
		want                    int
	}{
		{"new_action_actor", "В матчах участвуют игроки.", "В матчах играют не только игроки.", 1},
		{"existing_repeat", "Игроки играют в шахматы.", "Игроки играют в шахматы.", 0},
		{"different_sentences", "Игроки участвуют. Играют ведущие.", "Игроки выступают. Играют ведущие.", 0},
		{"different_paragraphs", "Игроки участвуют.\n\nИграют ведущие.", "Игроки\n\nиграют", 0},
		{"too_far", "В матчах участвуют все команды и приглашённые игроки.", "В матчах играют все команды и приглашённые игроки.", 0},
		{"advisory_not_linguistic_proof", "На берегу стоит дерево.", "На берегу стоит береза.", 1},
		{"unicode_case_yo", "Дерево зеленое.", "Ёлочка елочная", 1},
		{"identical_word", "Слова рядом.", "Игроки игроки", 0},
		{"source_reversed_pair", "Игроки играют.", "Играют игроки.", 0},
		{"below_length", "Нет пары.", "игр игра", 0},
		{"below_fraction", "Нет пары.", "абвгдежз абвийклмн", 0},
		{"heading_boundary", "Нет пары.", "Игроки\n## Играют", 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := introducedEchoes(tc.source, tc.candidate); len(got) != tc.want {
				t.Fatalf("got %+v, want %d", got, tc.want)
			}
		})
	}
}

func TestEchoEvidenceIsBoundedInCoarseRegion(t *testing.T) {
	source := strings.Repeat("старое текстовое ", 3100)
	candidate := strings.Repeat("новая новинка новизна новички новости ", 1300)
	edits := localEdits(source, candidate)
	if len(edits) != 1 || len(edits[0].Echoes) != 4 || !edits[0].EchoesTruncated {
		t.Fatalf("unbounded or unmarked evidence: %d", len(edits))
	}
}

func TestEchoAssessmentCannotSilentlyIgnorePair(t *testing.T) {
	in := criticInput{Mode: "edit", Source: "В матчах участвуют игроки.", Candidate: "В матчах играют не только игроки."}
	in.LocalEdits = localEdits(in.Source, in.Candidate)
	if len(in.LocalEdits) != 1 || len(in.LocalEdits[0].Echoes) != 1 {
		t.Fatalf("missing local echo %+v", in.LocalEdits)
	}
	a := EditAssessment{EditID: 1, ReadingQuote: in.Candidate, Reading: "natural", ScopeQuote: in.Candidate, Scope: "preserved", Decision: "keep", Reason: "Сохранился предмет."}
	out := criticResult{Verdict: "accept", EditAssessments: []EditAssessment{a}}
	if validateEditAssessments(in, out) == nil {
		t.Fatal("echo ignored")
	}
	a.EchoDecisions = []EchoDecision{{Quote: in.LocalEdits[0].Echoes[0].Quote, Verdict: "accidental", Reason: "Новый глагол повторяет корень названия участника; повтор не уточняет смысл."}}
	out.EditAssessments = []EditAssessment{a}
	if validateEditAssessments(in, out) == nil {
		t.Fatal("accidental echo accepted")
	}
	a.EchoDecisions[0].Verdict = "functional"
	a.EchoDecisions[0].Reason = "Сценарий проверки: повтор выполняет отдельную функцию."
	out.EditAssessments = []EditAssessment{a}
	if err := validateEditAssessments(in, out); err != nil {
		t.Fatal("diagnostic became blanket lexical ban", err)
	}
}
