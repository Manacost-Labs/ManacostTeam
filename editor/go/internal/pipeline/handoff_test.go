package pipeline

import (
	"context"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

func readyHandoff() *ResearchHandoff {
	return &ResearchHandoff{SchemaVersion: 1, Brief: "Практический совет", Patch: "test-patch", Status: "research_ready", StyleProfile: "battlegrounds-guide",
		Sources:   []ResearchSource{{ID: "SRC-1", URL: "https://example.org/guide", Quote: "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения."}},
		Claims:    []ResearchClaim{{ID: "CLM-1", Meaning: "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения.", Action: "Сохраняйте ресурс", Condition: "при слабой позиции", Exception: "кроме угрозы поражения", Confidence: "medium", Patch: "test-patch", Status: "supported_with_conditions", EvidenceRefs: []string{"SRC-1"}}},
		Chapters:  []ResearchChapter{{ID: "CH-1", Title: "Решение", RequiredClaimIDs: []string{"CLM-1"}}},
		Decisions: []DecisionQuestion{{ID: "Q-1", ChapterID: "CH-1", Question: "Когда сохранять ресурс?", Required: true, Status: "answered", ClaimIDs: []string{"CLM-1"}}},
	}
}

func TestReconstructRequiresVerifiedHandoff(t *testing.T) {
	for _, h := range []*ResearchHandoff{nil, {SchemaVersion: 1}} {
		_, err := New(nil, nil, "none").Run(context.Background(), Request{Text: "Черновик", Mode: "reconstruct", Handoff: h})
		if err == nil {
			t.Fatal("reconstruct accepted missing or incomplete evidence")
		}
	}
}

func TestHandoffRejectsCriticalGapsAndWrongPatch(t *testing.T) {
	h := readyHandoff()
	if err := h.Validate(); err != nil {
		t.Fatal(err)
	}
	h.Decisions[0].Status = "open"
	if err := h.Validate(); err == nil {
		t.Fatal("critical gap accepted")
	}
	h = readyHandoff()
	h.Claims[0].Patch = "older-patch"
	if err := h.Validate(); err == nil {
		t.Fatal("mixed patches accepted")
	}
	h = readyHandoff()
	h.Claims[0].EvidenceRefs = []string{"unknown"}
	if err := h.Validate(); err == nil {
		t.Fatal("missing evidence accepted")
	}
}

func TestReconstructPromptUsesEvidenceInsteadOfDraftStructure(t *testing.T) {
	model := &fakeLLM{replies: []string{"Готовый текст"}}
	service := New(model, nil, "fake")
	h := readyHandoff()
	_, err := service.rewrite(context.Background(), Request{Text: "Плохой черновик", Mode: "reconstruct", Handoff: h}, rules.Build(nil, "GUIDE", "переплавка", "ru-RU", h.PromptClaims()), Analysis{}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(model.messages[0][0].Content, "Редактируй минимально") {
		t.Fatal("minimal-edit instruction leaked into reconstruction")
	}
	payload := lastUserJSON(t, model.messages[0])
	if payload["research_handoff"] == nil || payload["draft"] != "Плохой черновик" || payload["editorial_rules"] == nil {
		t.Fatalf("evidence/draft boundary lost: %#v", payload)
	}
}

func TestFactReviewRejectsLostConditionAndInventedQuotes(t *testing.T) {
	h := readyHandoff()
	candidate := "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения. https://example.org/guide"
	good := `{"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Сохраняйте ресурс","condition_quote":"при слабой позиции","exception_quote":"кроме угрозы поражения","evidence_refs":["SRC-1"]}]}`
	if _, err := validateFactReview(good, h, candidate); err != nil {
		t.Fatal(err)
	}
	for _, bad := range []string{strings.Replace(good, "при слабой позиции", "несуществующая цитата", 1), strings.Replace(good, `"supported"`, `"insufficient"`, 1), `{"claims":[]}`} {
		if _, err := validateFactReview(bad, h, candidate); err == nil {
			t.Fatal("unverified claim accepted")
		}
	}
	if _, err := validateFactReview(good, h, strings.ReplaceAll(candidate, "https://example.org/guide", "")); err == nil {
		t.Fatal("missing source citation accepted")
	}
}

func TestReconstructCannotIntroduceUnapprovedLinksOrNumbers(t *testing.T) {
	for _, candidate := range []string{"Совет 99", "[Источник](https://example.org)", "[Источник](https://evil.example.org/guide)"} {
		if !reconstructionGuard(readyHandoff().VerifiedText(), candidate).HasHardChanges() {
			t.Fatalf("unapproved entity accepted: %s", candidate)
		}
	}
}

func TestReconstructRunsEvidenceReviewAndAllowsNewComposition(t *testing.T) {
	h := readyHandoff()
	candidate := "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения. [Источник](https://example.org/guide)"
	fact := `{"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Сохраняйте ресурс","condition_quote":"при слабой позиции","exception_quote":"кроме угрозы поражения","evidence_refs":["SRC-1"]}]}`
	writer := &fakeLLM{replies: []string{candidate}}
	reviewer := &fakeLLM{replies: []string{fact, criticJSON("accept")}}
	s := New(writer, nil, "fake")
	s.Reviewer = reviewer
	result, err := s.Run(context.Background(), Request{Text: "Плохой черновик с ненужным повтором.", Mode: "reconstruct", Handoff: h})
	if err != nil {
		t.Fatal(err)
	}
	if !result.Accepted || result.Text != candidate || result.FactReview == nil {
		t.Fatalf("reconstruction failed: %+v", result)
	}
	if len(writer.messages) != 1 || len(reviewer.messages) != 2 {
		t.Fatal("writer and reviewer contexts not separated")
	}
	for _, messages := range reviewer.messages {
		if strings.Contains(messages[1].Content, "Плохой черновик") {
			t.Fatal("unverified draft leaked into reviewer context")
		}
	}
}

func TestReconstructFactFailureReturnsOriginal(t *testing.T) {
	writer := &fakeLLM{replies: []string{"Совет без условия."}}
	s := New(writer, nil, "fake")
	s.Reviewer = &fakeLLM{replies: []string{`{"claims":[]}`}}
	result, err := s.Run(context.Background(), Request{Text: "Исходник", Mode: "reconstruct", Handoff: readyHandoff()})
	if err != nil {
		t.Fatal(err)
	}
	if result.Accepted || result.Text != "Исходник" || result.ChecksComplete {
		t.Fatalf("unsafe result: %+v", result)
	}
}
