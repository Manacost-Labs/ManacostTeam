package pipeline

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzer"
	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

func TestRequestContextReachesRulesAndPostflight(t *testing.T) {
	var request Request
	_ = json.Unmarshal([]byte(`{"text":"A clear sentence.","mode":"proofread","author":"ivan","meaning":"application","reader_level":"advanced"}`), &request)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var payload map[string]any
		_ = json.NewDecoder(r.Body).Decode(&payload)
		if payload["author"] != "ivan" || payload["meaning"] != "application" || payload["reader_level"] != "advanced" {
			t.Errorf("rules lost request context: %#v", payload)
		}
		_, _ = w.Write([]byte(`{}`))
	}))
	defer server.Close()
	checks := &scriptedAnalyzer{name: "test"}
	model := &fakeLLM{replies: []string{"A clear sentence.", criticJSON("accept")}}
	s := New(model, nil, "test", checks)
	s.RulesClient = analyzer.New(server.URL, time.Second)
	_, _ = s.Run(context.Background(), request)
	if len(checks.inputs) < 2 {
		t.Fatalf("postflight missing: %d", len(checks.inputs))
	}
	for _, input := range checks.inputs {
		if input.Author != "ivan" || input.Meaning != "application" {
			t.Errorf("analyzer context lost: %#v", input)
		}
	}
}

func TestIndependentCriticReceivesKeepSpansAndExplainsLoss(t *testing.T) {
	var in criticInput
	_ = json.Unmarshal([]byte(`{"source":"Keep this phrase. Other text.","candidate":"Other text.","mode":"edit","keep_spans":[{"quote":"Keep this phrase.","reason":"Distinct author voice"}]}`), &in)
	model := &fakeLLM{replies: []string{criticJSON("accept"), criticJSON("accept")}}
	s := New(model, nil, "fake")
	s.Reviewer = model
	_, err := s.critic(context.Background(), rules.Build(nil, "GUIDE", "обычная", "ru-RU", nil), in, 1)
	if err == nil {
		t.Fatal("critic silently accepted lost strong span")
	}
	if !strings.Contains(model.messages[0][1].Content, "Keep this phrase.") || !strings.Contains(model.messages[0][1].Content, "keep_spans") {
		t.Fatal("independent critic lost preservation contract")
	}
	var report map[string]any
	_ = json.Unmarshal([]byte(criticJSON("accept")), &report)
	report["strength_changes"] = []any{map[string]any{"quote": "Keep this phrase.", "reason": "Repeats the previous sentence", "replacement_quote": ""}}
	raw, _ := json.Marshal(report)
	s.Reviewer = &fakeLLM{replies: []string{string(raw)}}
	if _, err = s.critic(context.Background(), rules.Build(nil, "GUIDE", "обычная", "ru-RU", nil), in, 1); err != nil {
		t.Fatal(err)
	}
}

func TestAnalysisPreservesOnlyRealStrongSpans(t *testing.T) {
	model := &fakeLLM{replies: []string{`{"thesis":"t","strengths":[{"quote":"Real text.","reason":"Clear"},{"quote":"Invented","reason":"No"}]}`}}
	s := New(model, nil, "fake")
	analysis := s.editorialAnalysis(context.Background(), Request{Text: "Real text.", Mode: "edit"}, rules.Build(nil, "GUIDE", "обычная", "ru-RU", nil), nil)
	raw, _ := json.Marshal(analysis)
	if !strings.Contains(string(raw), "Real text.") || strings.Contains(string(raw), "Invented") {
		t.Fatal(string(raw))
	}
}

func TestStrengthRetryNamesWholeMissingSpan(t *testing.T) {
	quote := "Всем участникам будут выданы награды после завершения турнира."
	candidate := "Всем участникам выдадут награды после завершения турнира."
	in := criticInput{Source: quote, Candidate: candidate, Mode: "edit", KeepSpans: []StrongSpan{{Quote: quote, Reason: "Условие выдачи рядом с наградой"}}}
	var report map[string]any
	_ = json.Unmarshal([]byte(criticJSON("accept")), &report)
	report["strength_changes"] = []any{map[string]any{"quote": "будут выданы награды", "reason": "Убрана тяжёлая конструкция", "replacement_quote": "выдадут награды"}}
	partial, _ := json.Marshal(report)
	report["strength_changes"] = []any{map[string]any{"quote": quote, "reason": "Условие и адресат сохранены, сокращён пассив", "replacement_quote": candidate}}
	complete, _ := json.Marshal(report)
	model := &fakeLLM{replies: []string{string(partial), string(complete)}}
	s := New(model, nil, "fake")
	s.Reviewer = model
	_, err := s.critic(context.Background(), rules.Build(nil, "GUIDE", "обычная", "ru-RU", nil), in, 1)
	if err != nil || len(model.messages) != 2 {
		t.Fatalf("partial quote must use the existing retry: %v, calls=%d", err, len(model.messages))
	}
	retry := model.messages[1]
	if !strings.Contains(retry[len(retry)-1].Content, quote) {
		t.Fatal("retry did not name the whole missing keep_span")
	}
}

func TestStrongParagraphMayBeSplitWithoutLosingItsWords(t *testing.T) {
	quote := "Мета остаётся разнообразной. Мы продолжим следить за ситуацией."
	in := criticInput{Source: quote, Candidate: "Мета остаётся разнообразной.\n\nМы продолжим следить за ситуацией.", KeepSpans: []StrongSpan{{Quote: quote, Reason: "Спокойный голос автора"}}}
	if err := validateStrengthChanges(in, criticResult{Verdict: "accept"}); err != nil {
		t.Fatal("paragraph break is not a lost strength:", err)
	}
	in.Candidate = "Мета остаётся разнообразной."
	if err := validateStrengthChanges(in, criticResult{Verdict: "accept"}); err == nil {
		t.Fatal("deleting a strong sentence still requires an explanation")
	}
	in.Candidate = "Мета останется разнообразной.\n\nМы продолжим следить за ситуацией."
	if err := validateStrengthChanges(in, criticResult{Verdict: "accept"}); err == nil {
		t.Fatal("changed certainty must not pass as whitespace normalization")
	}
}

func TestReconstructionWriterReceivesApplicableCorrections(t *testing.T) {
	model := &fakeLLM{replies: []string{"draft"}}
	s := New(model, nil, "test")
	bundle := rules.Build(&analyzer.Rules{Corrections: []map[string]string{{"was": "old", "became": "new", "scope": "author_global", "enforcement": "required", "reason": "scoped-author-rule"}}}, "GUIDE", "переплавка", "ru-RU", nil)
	_, err := s.rewrite(context.Background(), Request{Mode: "reconstruct", Handoff: readyHandoff()}, bundle, Analysis{}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(model.messages[0][1].Content, "scoped-author-rule") {
		t.Fatal("reconstruction writer lost rules used by postflight")
	}
}
