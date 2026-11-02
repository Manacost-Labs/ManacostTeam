package pipeline

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"testing"
)

func calibrationItem(task string) CalibrationItem {
	return CalibrationItem{ID: "blind-1", Task: task, Source: "  Сохраните ресурс, если нет угрозы.\n", Candidate: "Сохраните ресурс.\n\nЕсли нет угрозы, подождите.\n", Brief: "Сохранить условие.", Reference: "Решение относится к спокойному ходу."}
}
func TestCalibrationUsesOnlyProductionCriticOnExactSuppliedPair(t *testing.T) {
	for _, verdict := range []string{"accept", "repair", "reject"} {
		t.Run(verdict, func(t *testing.T) {
			item := calibrationItem("compound")
			writer := &fakeLLM{fail: map[int]error{0: errors.New("writer must not run")}}
			reply := criticJSON(verdict)
			if verdict == "repair" {
				reply = criticJSON("repair", warning("scope", "Уточнить условие совета."))
			}
			reviewer := &fakeLLM{replies: []string{reply}}
			service := New(writer, nil, "fixture")
			service.Reviewer = reviewer
			got, err := CalibrateCritic(context.Background(), service, CalibrationPacket{Items: []CalibrationItem{item}})
			if err != nil {
				t.Fatal(err)
			}
			row := got.Rows[0]
			if row.Decision != verdict || row.Scores == nil || got.ReviewerType != "production-critic" {
				t.Fatalf("wrong judgment: %+v", row)
			}
			if len(writer.messages) != 0 || len(reviewer.messages) != 1 || reviewer.stages[0] != "critic" {
				t.Fatalf("unexpected calls: writer=%v reviewer=%v", writer.stages, reviewer.stages)
			}
			args := lastUserJSON(t, reviewer.messages[0])
			if args["source"] != item.Source || args["candidate"] != item.Candidate || args["revision_base"] != nil {
				t.Fatalf("changed or contaminated pair: %#v", args)
			}
			var guidance map[string]string
			if err = json.Unmarshal([]byte(args["revision_brief"].(string)), &guidance); err != nil || guidance["task"] != "compound" || guidance["reference"] != item.Reference || guidance["brief"] != item.Brief {
				t.Fatalf("wrong task guidance: %#v, %v", guidance, err)
			}
			if row.SourceSHA256 != fmt.Sprintf("%x", sha256.Sum256([]byte(item.Source))) || row.CandidateSHA256 != fmt.Sprintf("%x", sha256.Sum256([]byte(item.Candidate))) {
				t.Fatal("hashes not byte exact")
			}
		})
	}
}
func TestCalibrationCountsOnlyValidatedVerdicts(t *testing.T) {
	item := calibrationItem("meaning")
	cases := []struct {
		name    string
		service *Service
		reason  string
	}{
		{"invalid reply after retry", New(&fakeLLM{replies: []string{"invalid"}}, nil, "fixture"), ReasonCriticInvalid},
		{"timeout", New(&fakeLLM{fail: map[int]error{0: context.DeadlineExceeded}}, nil, "fixture"), ReasonCriticTimeout},
		{"service error", New(&fakeLLM{fail: map[int]error{0: errors.New("SENSITIVE ERROR BODY")}}, nil, "fixture"), ReasonCriticUnavailable},
		{"disabled", New(nil, nil, "none"), "critic_provider_disabled"}, {"unconfigured", nil, "provider_configuration_unavailable"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			report, err := CalibrateCritic(context.Background(), tc.service, CalibrationPacket{Items: []CalibrationItem{item}})
			if err != nil {
				t.Fatal(err)
			}
			row := report.Rows[0]
			if row.Scores != nil || row.Decision != "unavailable" || row.Reason != tc.reason {
				t.Fatalf("wrong unavailable row: %+v", row)
			}
			raw, _ := json.Marshal(report)
			if strings.Contains(string(raw), "SENSITIVE") {
				t.Fatal("provider error leaked")
			}
		})
	}
}
func TestCalibrationUnchangedAcceptAndVoiceSkip(t *testing.T) {
	item := calibrationItem("meaning")
	item.Candidate = item.Source
	voice := calibrationItem("voice")
	voice.ID = "blind-2"
	model := &fakeLLM{replies: []string{criticJSONNoImprovement()}}
	s := New(model, nil, "fixture")
	report, err := CalibrateCritic(context.Background(), s, CalibrationPacket{Items: []CalibrationItem{item, voice}})
	if err != nil {
		t.Fatal(err)
	}
	if report.Rows[0].Decision != "accept" || report.Rows[1].Decision != "unavailable" || report.Rows[1].Reason != "task_not_assigned" || len(model.messages) != 1 {
		t.Fatalf("wrong decisions: %+v", report.Rows)
	}
	_, err = CalibrateCritic(context.Background(), s, CalibrationPacket{Items: []CalibrationItem{item, item}})
	if err == nil || len(model.messages) != 1 {
		t.Fatal("invalid packet produced calls before failing")
	}
}
