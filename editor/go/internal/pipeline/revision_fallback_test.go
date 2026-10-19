package pipeline

import (
	"context"
	"strings"
	"testing"
)

func TestFailedRevisionReturnsOnlyIndependentlyReviewedExactPreviousText(t *testing.T) {
	source := "Участие в турнире осуществляется бесплатно. Это правило действует для всех участников."
	previous := "Участие в турнире бесплатное.\n\nЭто правило действует для всех участников."
	bad := previous + " Это правило действует для всех участников."
	negative := criticJSON("repair", warning("repeat.local", "Убери повтор последнего предложения, сохрани две мысли и границу абзаца."))
	lm := &fakeLLM{replies: []string{analysisJSON, bad, negative, bad, negative, bad, negative, criticJSON("accept")}}
	r, err := New(lm, nil, "fake").Run(context.Background(), autoRevisionRequest(t, source, previous, "edit"))
	if err != nil || !r.Accepted || !r.ChecksComplete || r.Text != previous || r.Attempts != MaxRepairs+1 {
		t.Fatalf("prior useful edit/split lost or not independently checked: %+v %v", r, err)
	}
	if r.RevisionFallback == nil || !r.RevisionFallback.KeptPrevious || len(r.RevisionFallback.AttemptReasons) == 0 || len(r.RevisionFallback.CandidateSHA256) != 64 || len(r.RevisionFallback.ReviewReasons) != 0 {
		t.Fatal("fallback hid its provenance", r.RevisionFallback)
	}
	if strings.Join(lm.stages, ",") != "analysis,rewrite,critic,repair,critic,repair,critic,critic" {
		t.Fatal("fallback wrote, repaired or re-analyzed the previous draft", lm.stages)
	}
	last := lastUserJSON(t, lm.messages[len(lm.messages)-1])
	if last["source"] != source || last["candidate"] != previous || last["revision_base"] != previous {
		t.Fatal("fallback review did not receive exact source and prior text", last)
	}
}

func TestPreviousRevisionCannotBypassFactsOrIncompleteTools(t *testing.T) {
	for _, incomplete := range []bool{false, true} {
		source, previous := "Награда — 4 кристалла.", "Награда — 5 кристаллов."
		if incomplete {
			source, previous = "Участие осуществляется бесплатно.", "Участие бесплатное."
		}
		bad := previous + " Повтор."
		negative := criticJSON("repair", warning("style.local", "Убери повтор."))
		lm := &fakeLLM{replies: []string{analysisJSON, bad, negative, bad, negative, bad, negative, criticJSON("accept")}}
		s := New(lm, nil, "fake")
		if incomplete {
			s.Analyzers = append(s.Analyzers, unavailableAnalyzer{})
			s.AllowUnavailable = true
		}
		r, err := s.Run(context.Background(), autoRevisionRequest(t, source, previous, "edit"))
		if err != nil || r.Accepted || r.Text != source || r.RevisionFallback == nil || r.RevisionFallback.KeptPrevious {
			t.Fatalf("unsafe/incomplete prior was accepted: %+v %v", r, err)
		}
		if strings.Join(lm.stages, ",") != "analysis,rewrite,critic,repair,critic,repair,critic,critic" {
			t.Fatal("fallback renewed the repair budget", lm.stages)
		}
	}
}

func TestReviewedSourceEquivalentFallbackIsUnchangedNotAnImprovement(t *testing.T) {
	source := "Каждую неделю будет появляться новая часть истории."
	bad := "Каждую неделю появляется новая часть истории."
	negative := criticJSON("repair", warning("time.local", "Сохрани исходную временную перспективу."))
	lm := &fakeLLM{replies: []string{analysisJSON, bad, negative, bad, negative, bad, negative, criticJSON("accept")}}
	r, err := New(lm, nil, "fake").Run(context.Background(), autoRevisionRequest(t, source, source, "edit"))
	if err != nil || r.Accepted || r.Status != StatusUnchanged || !r.ChecksComplete || r.Text != source || r.RevisionFallback == nil || !r.RevisionFallback.KeptPrevious {
		t.Fatalf("safe no-change was reported as a fresh improvement: %+v %v", r, err)
	}
}
