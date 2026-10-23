package pipeline

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/editorialreview"
	"github.com/Manacost-Labs/EditorTeam/go/internal/reviewfixture"
	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

func TestAcceptCannotContradictAnyQualitativeAssessment(t *testing.T) {
	for _, key := range scoreKeys {
		for _, score := range []string{"0", "7"} {
			t.Run(key+"/"+score, func(t *testing.T) {
				reply := strings.Replace(criticJSON("accept"), `"`+key+`":8`, `"`+key+`":`+score, 1)
				if _, err := parseCritic(reply); err == nil {
					t.Fatal("accept contradicts the critic's own negative quality judgment")
				}
			})
		}
	}
	if _, err := parseCritic(criticJSON("accept")); err != nil {
		t.Fatalf("coherent boundary judgment must remain valid: %v", err)
	}
}

func TestCorrectionsCannotOverlapOrCascade(t *testing.T) {
	in := criticInput{Source: "A B. C D.", Candidate: "C X. E D.", SourceSnapshots: []editorialreview.SourceSnapshot{{SourceID: "s", Text: "Evidence."}}}
	review := &OriginalFactualChecks{WholeTextChecked: true, InternalConsistency: "clear", SourceAgreement: "issue", Issues: []OriginalIssue{
		{Quote: "A B.", CorrectionQuote: "C X.", Reason: "Supported correction.", Resolution: "corrected", SourceID: "s", EvidenceQuote: "Evidence."},
		{Quote: "C D.", CorrectionQuote: "E D.", Reason: "Supported correction.", Resolution: "corrected", SourceID: "s", EvidenceQuote: "Evidence."},
	}}
	if err := validateOriginalChecks(in, review); err != nil {
		t.Fatal(err)
	}
	if got := correctedBaseline(in.Source, review); got != in.Candidate {
		t.Fatalf("wrong original positions: %q", got)
	}
	review.Issues[1].Quote = "B."
	if err := validateOriginalChecks(in, review); err == nil {
		t.Fatal("overlapping original corrections accepted")
	}
	forged := &EditReview{OriginalFactualChecks: review}
	if forged.PreservationSource(in.Source) != in.Source {
		t.Fatal("unverified public report authorized a correction")
	}
}

func TestReconstructionWritersReceiveSuppliedSnapshots(t *testing.T) {
	sources := []editorialreview.SourceSnapshot{{SourceID: "s", Text: "Evidence."}}
	for _, repair := range []bool{false, true} {
		model := &fakeLLM{replies: []string{"Текст."}}
		service := New(model, nil, "")
		if repair {
			_, _ = service.repairReconstructionWithSources(context.Background(), rules.RuleBundle{}, readyHandoff(), "Текст.", nil, nil, nil, sources)
		} else {
			_, _ = service.rewrite(context.Background(), Request{Mode: "reconstruct", Handoff: readyHandoff(), SourceSnapshots: sources}, rules.RuleBundle{}, Analysis{}, nil)
		}
		if len(model.messages) != 1 || !strings.Contains(model.messages[0][1].Content, `"source_snapshots"`) {
			t.Fatalf("source evidence lost in reconstruction repair=%v", repair)
		}
	}
}

func TestAllEditModesRejectMissingContextualReview(t *testing.T) {
	for _, mode := range []string{"proofread", "edit", "rewrite", "facts_only"} {
		t.Run(mode, func(t *testing.T) {
			model := &fakeLLM{omitContextualReview: true, replies: []string{criticJSON("accept")}}
			service := New(model, nil, "")
			_, err := service.critic(context.Background(), rules.RuleBundle{}, criticInput{Source: "Исходный текст.", Candidate: "Готовый текст.", Mode: mode}, 1)
			if err == nil || err.Kind != ReasonCriticInvalid {
				t.Fatalf("incomplete review accepted: %v", err)
			}
		})
	}
}

func TestUnchangedLegacyInputStillNeedsFullReview(t *testing.T) {
	model := &fakeLLM{omitContextualReview: true, replies: []string{criticJSON("accept")}}
	if err := ReviewFactualEdit(context.Background(), model, "Текст.", "Текст.", nil); err == nil || model.i != 2 {
		t.Fatalf("identical input bypassed review: calls=%d err=%v", model.i, err)
	}
	model = &fakeLLM{replies: []string{criticJSON("accept")}}
	report, err := ReviewEdit(context.Background(), model, "Текст.", "Текст.", nil, nil)
	if err != nil || report == nil || len(report.PracticeChecks) != 26 || len(report.LogicChecks) != 5 || len(report.PreservationChecks) != 7 || report.SourceVerification != "not_performed" {
		t.Fatalf("valid full preservation review: %+v err=%v", report, err)
	}
}

func TestOriginalErrorCannotHideBehindPreservationAccept(t *testing.T) {
	in := criticInput{Source: "Счёт 22-7 (71% побед).", Candidate: "Счёт 22-7 (71% побед).", Mode: "edit"}
	payload, _ := json.Marshal(in)
	reply := reviewfixture.Complete(criticJSON("accept"), string(payload))
	out, err := parseCritic(reply)
	if err != nil {
		t.Fatal(err)
	}
	out.OriginalFactualChecks = &OriginalFactualChecks{WholeTextChecked: true, InternalConsistency: "issue", SourceAgreement: "not_performed", Issues: []OriginalIssue{{Quote: in.Source, Reason: "Счёт и процент несовместимы; неизвестно, какое число неверно.", Resolution: "unresolved"}}}
	if err := validateContextualReview(in, out); err == nil {
		t.Fatal("unresolved original arithmetic passed")
	}
	out.OriginalFactualChecks.Issues[0].Resolution = "corrected"
	out.OriginalFactualChecks.Issues[0].CorrectionQuote = in.Candidate
	if err := validateContextualReview(in, out); err == nil {
		t.Fatal("unsupported guessed correction passed")
	}
}
