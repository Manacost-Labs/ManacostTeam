package pipeline

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzer"
	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

const weakDraft = "Монетка дает одну дополнительную ману. Боевой якорррь входит в колоду. Монетку можно использовать в разные моменты партии."

func writingCallsOf(f *fakeLLM, stage string) int {
	n := 0
	for _, call := range f.writingCalls {
		if writingStageOf(call[0].Content) == stage {
			n++
		}
	}
	return n
}

func TestNoThesisStopsBeforeDraft(t *testing.T) {
	lm := &fakeLLM{replies: []string{analysisJSON, "Черновик не должен появиться."}, writing: map[string][]string{"brief": {`{"stop":"материал только перечисляет карты, нового для игрока нет"}`}}}
	r := run(t, lm, weakDraft, "rewrite")
	if r.Accepted || r.Status != StatusRejected || r.Text != weakDraft || len(r.RejectionReasons) != 1 || r.RejectionReasons[0] != ReasonNoThesis {
		t.Fatalf("missing thesis must stop writing: %+v", r)
	}
	if r.Writing == nil || !strings.Contains(r.Writing.StopReason, "нового для игрока нет") {
		t.Fatalf("stop reason not reported: %+v", r.Writing)
	}
	if len(lm.messages) != 1 || stageOf(lm.messages[0][0].Content) != "analysis" {
		t.Fatalf("draft was written without a thesis: %v", lm.stages)
	}
}

func TestCardListPlanIsRetriedThenStops(t *testing.T) {
	cardList := `{"reader_gain":"Как играть колоду в текущей мете.","non_obvious":"Есть несколько сильных карт в колоде.","sections":[{"decision":"Боевой якорррь, Гайкалибур","why":"сильные карты"}]}`
	lm := &fakeLLM{replies: []string{analysisJSON, "Черновик."}, writing: map[string][]string{"brief": {cardList, cardList}}}
	r := run(t, lm, weakDraft, "rewrite")
	if writingCallsOf(lm, "brief") != 2 {
		t.Fatalf("invalid plan must get exactly one retry, got %d", writingCallsOf(lm, "brief"))
	}
	if r.Writing == nil || !strings.Contains(r.Writing.StopReason, "решение игрока") || r.RejectionReasons[0] != ReasonNoThesis {
		t.Fatalf("card-list plan accepted: %+v", r.Writing)
	}
	retry := lm.writingCalls[1]
	if !strings.Contains(retry[len(retry)-1].Content, "не решение игрока") {
		t.Fatal("retry does not name the plan defect")
	}
}

func TestBriefKeepsOnlyGroundedScenes(t *testing.T) {
	replay := []ReplayFact{
		{ID: "r1", Turn: 2, Fact: "Игрок A сыграл Монетку и Боевой якорррь на втором ходу.", Evidence: ReplayEvidence{Level: "observed", PacketIndices: []int{41}}},
		{ID: "r2", Turn: 3, Fact: "Игрок B, вероятно, держал ответ.", Evidence: ReplayEvidence{Level: "heuristic"}},
	}
	raw := `{"reader_gain":"Монетка на втором ходу ускоряет Боевой якорррь.","non_obvious":"Без Гайкалибура Монетку выгоднее приберечь.","sections":[
		{"decision":"когда играть Монетку на втором ходу","why":"темп","scene":{"turns":["Ход 2: Монетка и Боевой якорррь"],"refs":["replay:r1"]}},
		{"decision":"когда приберечь Монетку до шкипера","why":"запас","scene":{"turns":["Ход 3: ответ"],"refs":["replay:r2"]}},
		{"decision":"как читать руку противника заранее","why":"план","scene":{"turns":["Ход 4"],"refs":["quote:этого нет в материале"]}},
		{"decision":"что делать без второго дропа","why":"план","scene":{"turns":["Ход 1"],"refs":["quote:Боевой якорррь входит в колоду"]}}]}`
	brief, err := parseBrief(raw, weakDraft, nil, replay)
	if err != nil {
		t.Fatal(err)
	}
	if brief.Sections[0].Scene == nil || brief.Sections[3].Scene == nil {
		t.Fatal("grounded replay or quote scene was dropped")
	}
	if brief.Sections[1].Scene != nil || brief.Sections[2].Scene != nil {
		t.Fatal("heuristic or invented scene survived")
	}
	if len(brief.Gaps) != 2 {
		t.Fatalf("unproven scenes must become gaps: %v", brief.Gaps)
	}
}

func TestWriterReceivesBriefReplayAndContrastPairs(t *testing.T) {
	brief := `{"reader_gain":"Монетка на втором ходу ускоряет Боевой якорррь.","non_obvious":"Без Гайкалибура Монетку выгоднее приберечь.","sections":[{"decision":"когда играть Монетку на втором ходу","why":"темп","scene":{"turns":["Ход 2: Монетка и Боевой якорррь"],"refs":["replay:r1"]}}]}`
	lm := &fakeLLM{replies: []string{analysisJSON, "Черновик."}, writing: map[string][]string{"brief": {brief}}}
	s := New(lm, nil, "fake")
	req := Request{Text: weakDraft, Mode: "rewrite", ReplayFacts: []ReplayFact{{ID: "r1", Fact: "Игрок A сыграл Монетку на втором ходу.", Evidence: ReplayEvidence{Level: "observed", PacketIndices: []int{7}}}}}
	bundle := rules.Build(&analyzer.Rules{ContrastPairs: []analyzer.ContrastPair{{Topic: "монетка", Boring: "Монетка дает ману.", Interesting: "Играйте Монетку на второй ход.", Why: "решение"}}}, "GUIDE", "переплавка", "ru-RU", nil)
	got, err := s.writingBrief(context.Background(), req, Analysis{})
	if err != nil || got.Stop != "" {
		t.Fatalf("brief failed: %+v %v", got, err)
	}
	req.brief = got
	if _, err := s.rewrite(context.Background(), req, bundle, Analysis{}, nil); err != nil {
		t.Fatal(err)
	}
	payload := lastUserJSON(t, lm.messages[0])
	for _, key := range []string{"writing_brief", "replay_facts", "contrast_pairs"} {
		if payload[key] == nil {
			t.Fatalf("writer payload lacks %s", key)
		}
	}
	if !strings.Contains(lm.messages[0][0].Content, "writing_brief") {
		t.Fatal("writer core does not explain the brief")
	}
	if strings.Contains(bundle.Prompt(), "Играйте Монетку") {
		t.Fatal("contrast pairs leaked into the shared bundle prompt of review stages")
	}
}

func TestReaderSkipPassRewritesOnlyMarkedSentences(t *testing.T) {
	candidate := "Иглогрив-страж — лучшая карта на стадии муллигана. В этом разделе мы поговорим о муллигане колоды. Оставляйте его всегда."
	rewritten := "Иглогрив-страж — лучшая карта на стадии муллигана. Оставляйте его всегда."
	lm := &fakeLLM{writing: map[string][]string{
		"skip":         {`{"skip":[{"quote":"В этом разделе мы поговорим о муллигане колоды.","why":"обещание без решения"},{"quote":"Иглогрив-страж — лучшая карта на стадии муллигана.","why":"сильная фраза автора"},{"quote":"Этого предложения нет в тексте вовсе.","why":"выдумано"}]}`},
		"skip_rewrite": {rewritten},
	}}
	s := New(lm, nil, "fake")
	report := &WritingReport{}
	keep := []StrongSpan{{Quote: "Иглогрив-страж — лучшая карта на стадии муллигана.", Reason: "точный совет"}}
	got := s.readerSkipPass(context.Background(), rules.RuleBundle{}, nil, keep, candidate, report)
	if got != rewritten || !report.SkipRewritten {
		t.Fatalf("marked sentence not rewritten: %q", got)
	}
	if len(report.SkippedSentences) != 1 || !strings.HasPrefix(report.SkippedSentences[0].Quote, "В этом разделе") {
		t.Fatalf("keep spans or invented quotes reached the rewrite: %+v", report.SkippedSentences)
	}
	payload := lastUserJSON(t, lm.writingCalls[1])
	if len(payload["skip"].([]any)) != 1 {
		t.Fatal("rewrite received unvalidated marks")
	}
}

func TestSkipMarksNeverTargetGuardedSentences(t *testing.T) {
	candidate := "В этом разделе мы поговорим о муллигане. Муллиган Раш Воина простой. Карту не стоит держать. Это обычно помогает."
	marks := validSkipMarks([]SkipMark{
		{Quote: "В этом разделе мы поговорим о муллигане.", Why: "обещание"},
		{Quote: "Муллиган Раш Воина простой.", Why: "вступление"},
		{Quote: "Карту не стоит держать.", Why: "повтор"},
		{Quote: "Это обычно помогает.", Why: "общая фраза"},
	}, candidate, nil)
	if len(marks) != 1 || !strings.HasPrefix(marks[0].Quote, "В этом разделе") {
		t.Fatalf("names, negations or hedges reached the skip rewrite: %+v", marks)
	}
}

func TestReaderSkipPassFailureKeepsDraftAndIsReported(t *testing.T) {
	lm := &fakeLLM{writing: map[string][]string{"skip": {"не JSON"}}}
	report := &WritingReport{}
	got := New(lm, nil, "fake").readerSkipPass(context.Background(), rules.RuleBundle{}, nil, nil, weakDraft, report)
	if got != weakDraft || len(report.Errors) != 1 {
		t.Fatalf("failed skip pass must keep the draft and report the error: %q %v", got, report.Errors)
	}
}

const hardParagraph = "Если на второй ход у вас нет второго дропа и нет третьего дропа, который можно было бы сыграть с Монетки, то не стоит использовать силу героя, потому что тотем, который появится на столе, станет удобной целью для заклинаний Мага и ускорит прогресс его квеста, а особой пользы в этом противостоянии он не принесет. Это правило работает почти всегда в 2 из 3 партий."

func TestParagraphVariantsJudgePicksGuardedVariant(t *testing.T) {
	candidate := "Короткое вступление.\n\n" + hardParagraph
	dropsNumber := "Без второго дропа силу героя не используйте: тотем станет целью для заклинаний Мага."
	good := "Нет второго дропа и нет третьего дропа для Монетки? Не используйте силу героя: тотем станет удобной целью для заклинаний Мага и ускорит прогресс его квеста, а пользы не принесет. Правило работает почти всегда в 2 из 3 партий."
	lm := &fakeLLM{writing: map[string][]string{
		"variants":      {`{"variants":[` + jsonQuote(dropsNumber) + `,` + jsonQuote(good) + `]}`},
		"variant_judge": {`{"best":1,"reason":"решение в начале"}`},
	}}
	report := &WritingReport{}
	got := New(lm, nil, "fake").paragraphVariants(context.Background(), candidate, report)
	if got != "Короткое вступление.\n\n"+good {
		t.Fatalf("judge choice not applied: %q", got)
	}
	judged := lastUserJSON(t, lm.writingCalls[1])
	if len(judged["variants"].([]any)) != 1 {
		t.Fatal("variant that lost a number reached the judge")
	}
	if len(report.Variants) != 1 || report.Variants[0].Best != 1 || report.Variants[0].Offered != 1 {
		t.Fatalf("variant choice not reported: %+v", report.Variants)
	}
}

func TestWritingPassesRunBeforeGuardsInEditMode(t *testing.T) {
	lm := &fakeLLM{replies: []string{analysisJSON, hardParagraph, criticJSON("accept")}}
	r := run(t, lm, hardParagraph, "edit")
	if r.Writing == nil || writingCallsOf(lm, "skip") != 1 || writingCallsOf(lm, "variants") != 1 {
		t.Fatalf("writing passes did not run in edit: %+v", r.Writing)
	}
	if writingCallsOf(lm, "brief") != 0 {
		t.Fatal("editing an author's text must not require a new thesis")
	}
	lm = &fakeLLM{replies: []string{analysisJSON, hardParagraph, criticJSON("accept")}}
	run(t, lm, hardParagraph, "proofread")
	if len(lm.writingCalls) != 0 {
		t.Fatal("proofreading ran writing passes")
	}
}

func TestWriterPromptStaysShort(t *testing.T) {
	for _, mode := range []string{"edit", "rewrite"} {
		lm := &fakeLLM{replies: []string{"Текст."}}
		if _, err := New(lm, nil, "fake").rewrite(context.Background(), Request{Text: "Текст.", Mode: mode}, rules.Build(nil, "GUIDE", "обычная", "ru-RU", nil), Analysis{}, nil); err != nil {
			t.Fatal(err)
		}
		// Two pages: rules that a guard or the critic checks do not belong here.
		if words := len(strings.Fields(lm.messages[0][0].Content)); words > 700 {
			t.Fatalf("%s writer prompt grew to %d words", mode, words)
		}
	}
}

func TestReplayFactsValidation(t *testing.T) {
	ok := []ReplayFact{{ID: "a", Fact: "Ход 2.", Evidence: ReplayEvidence{Level: "observed", PacketIndices: []int{1}}}, {ID: "b", Fact: "Вероятно.", Evidence: ReplayEvidence{Level: "heuristic"}}}
	if err := validateReplayFacts(ok); err != nil {
		t.Fatal(err)
	}
	if got := groundedReplayFacts(ok); len(got) != 1 || got[0].ID != "a" {
		t.Fatal("heuristic replay fact treated as observed")
	}
	for _, bad := range [][]ReplayFact{
		{{ID: "", Fact: "x", Evidence: ReplayEvidence{Level: "observed", PacketIndices: []int{1}}}},
		{{ID: "a", Fact: "x", Evidence: ReplayEvidence{Level: "observed"}}},
		{{ID: "a", Fact: "x", Evidence: ReplayEvidence{Level: "guess"}}},
		{ok[0], ok[0]},
	} {
		_, err := New(&fakeLLM{replies: []string{"x"}}, nil, "fake").Run(context.Background(), Request{Text: "Текст.", Mode: "edit", ReplayFacts: bad})
		var reqErr *RequestError
		if !errors.As(err, &reqErr) {
			t.Fatalf("invalid replay facts accepted: %+v", bad)
		}
	}
}

func TestIsDecision(t *testing.T) {
	for text, want := range map[string]bool{
		"муллиган против агро колод":          true,
		"когда сбросить темп и уйти в защиту": true,
		"Боевой якорррь, Гайкалибур":          false,
		"Оставлять ли дорогие карты кривой (Укротитель Уотли, Верховный друид Наралекс) под конкретного оппонента": true,
		"Боевой якорррь, Гайкалибур, Рисковый шкипер":                                                              false,
		"Иглогрив-страж": false,
		"лучшие карты":   false,
	} {
		if isDecision(text) != want {
			t.Errorf("isDecision(%q) = %v, want %v", text, !want, want)
		}
	}
}

func jsonQuote(s string) string { return `"` + jsonEscape(s) + `"` }
