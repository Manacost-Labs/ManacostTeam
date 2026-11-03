package pipeline

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"strings"
)

// CalibrationPacket deliberately projects only blind inputs, never expected decisions.
type CalibrationPacket struct {
	Items []CalibrationItem `json:"items"`
}
type CalibrationItem struct {
	ID        string `json:"id"`
	Task      string `json:"task"`
	Source    string `json:"source"`
	Candidate string `json:"candidate"`
	Brief     string `json:"brief,omitempty"`
	Reference string `json:"reference,omitempty"`
}
type CalibrationReport struct {
	PacketSHA256  string           `json:"packet_sha256,omitempty"`
	Reviewer      string           `json:"reviewer"`
	ReviewerType  string           `json:"reviewer_type"`
	PromptVersion string           `json:"prompt_version"`
	PromptVariant string           `json:"prompt_variant,omitempty"`
	Rows          []CalibrationRow `json:"rows"`
}
type CalibrationRow struct {
	ID               string   `json:"id"`
	Task             string   `json:"task"`
	SourceSHA256     string   `json:"source_sha256"`
	CandidateSHA256  string   `json:"candidate_sha256"`
	Decision         string   `json:"decision"`
	Reason           string   `json:"reason"`
	SourceQuote      string   `json:"source_quote,omitempty"`
	CandidateQuote   string   `json:"candidate_quote,omitempty"`
	Scores           *Scores  `json:"scores,omitempty"`
	Regressions      []string `json:"regressions,omitempty"`
	ChecksComplete   *bool    `json:"checks_complete,omitempty"`
	SkippedAnalyzers []string `json:"skipped_analyzers,omitempty"`
}

// CalibrateCritic runs the same independent critic and reply validation as Run.
// reviewOnly keeps the supplied candidate byte-exact and suppresses all writer,
// salvage and repair calls. An infrastructure failure never becomes a verdict.
func CalibrateCritic(ctx context.Context, s *Service, packet CalibrationPacket) (CalibrationReport, error) {
	r := CalibrationReport{Reviewer: "production-critic:unconfigured", ReviewerType: "production-critic", PromptVersion: PromptVersion, Rows: []CalibrationRow{}}
	if len(packet.Items) == 0 {
		return r, fmt.Errorf("blind packet requires nonempty items")
	}
	seen := map[string]bool{}
	for _, item := range packet.Items {
		if strings.TrimSpace(item.ID) == "" || seen[item.ID] {
			return r, fmt.Errorf("empty or duplicate calibration item id %q", item.ID)
		}
		if item.Task != "meaning" && item.Task != "compound" && item.Task != "voice" {
			return r, fmt.Errorf("%s: unknown task %q", item.ID, item.Task)
		}
		if strings.TrimSpace(item.Source) == "" || strings.TrimSpace(item.Candidate) == "" {
			return r, fmt.Errorf("%s: source and candidate required", item.ID)
		}
		if item.Task == "compound" && strings.TrimSpace(item.Reference) == "" {
			return r, fmt.Errorf("%s: compound task requires original intent in reference", item.ID)
		}
		seen[item.ID] = true
	}
	if s != nil {
		r.PromptVariant = s.PromptVariant
		model := s.Reviewer
		if model == nil {
			model = s.LLM
		}
		r.Reviewer = "production-critic:" + s.Provider
		if model != nil {
			r.Reviewer += ":" + model.Model()
		}
	}
	for _, item := range packet.Items {
		row := CalibrationRow{ID: item.ID, Task: item.Task, SourceSHA256: fmt.Sprintf("%x", sha256.Sum256([]byte(item.Source))), CandidateSHA256: fmt.Sprintf("%x", sha256.Sum256([]byte(item.Candidate))), Decision: "unavailable"}
		switch {
		case item.Task == "voice":
			row.Reason = "task_not_assigned"
		case s == nil:
			row.Reason = "provider_configuration_unavailable"
		case s.LLM == nil:
			row.Reason = "critic_provider_disabled"
		case ctx.Err() != nil:
			row.Reason = "run_cancelled"
		default:
			// The ordinary revision_brief field carries the editorial task as data;
			// reference describes original intent, not a verified factual source.
			criterion := "Проверь сохранение смысла: сопоставь допустимые ситуации в обоих направлениях, включая ход событий и дополнительные свойства. Если формулировки расходятся хотя бы в одном направлении, укажи эту разницу, даже когда их обычный результат совпадает. Стилистическая доводка и типографика сами по себе не меняют смысл. Это проверка пары, не допуск к публикации."
			if item.Task == "compound" {
				criterion = "Проверь вместе грамматику, синтаксис и сохранение замысла. Reference поясняет роль участников и связи в испорченном исходнике, но не задаёт обязательную формулировку и не разрешает добавлять новые сведения. Требуй исправить реальный оставшийся дефект, даже если остальные исправлены."
			}
			brief, _ := json.Marshal(struct {
				Criterion string `json:"criterion"`
				Task      string `json:"task"`
				Brief     string `json:"brief,omitempty"`
				Reference string `json:"reference,omitempty"`
			}{criterion, item.Task, item.Brief, item.Reference})
			result, err := s.Run(ctx, Request{Text: item.Source, CandidateText: item.Candidate, Mode: "edit", RevisionBrief: string(brief), reviewOnly: true})
			switch {
			case err != nil:
				row.Reason = "review_pipeline_unavailable"
			case !result.ScoresValid || result.CriticVerdict == "":
				row.Reason = "no_valid_critic_verdict"
				for _, reason := range result.RejectionReasons {
					if reason == ReasonCriticInvalid || reason == ReasonCriticTimeout || reason == ReasonCriticUnavailable {
						row.Reason = reason
						break
					}
				}
			default:
				row.Decision = result.CriticVerdict
				row.Reason = "validated_critic_verdict"
				row.Scores = &result.Scores
				row.Regressions = result.Regressions
				row.ChecksComplete = &result.ChecksComplete
				row.SkippedAnalyzers = result.SkippedAnalyzers
				for _, finding := range result.QAFindings {
					if finding.Analyzer == "critic" && finding.Message != "" {
						row.Reason = finding.Message
						if strings.TrimSpace(finding.Evidence) != "" && strings.Contains(item.Candidate, finding.Evidence) {
							row.CandidateQuote = finding.Evidence
						}
						break
					}
				}
				if row.Reason == "validated_critic_verdict" {
					for _, regression := range result.Regressions {
						if strings.TrimSpace(regression) != "" {
							row.Reason = regression
							break
						}
					}
				}
				if row.Reason == "validated_critic_verdict" && row.Decision == "accept" && len(result.Improvements) > 0 {
					improvement := result.Improvements[0]
					row.Reason = improvement.Reason
					if improvement.Before != "" && strings.Contains(item.Source, improvement.Before) {
						row.SourceQuote = improvement.Before
					}
					if improvement.After != "" && strings.Contains(item.Candidate, improvement.After) {
						row.CandidateQuote = improvement.After
					}
				}
			}
		}
		r.Rows = append(r.Rows, row)
	}
	return r, nil
}
