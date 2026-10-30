package pipeline

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzers"
)

// ReaderQuestionTarget links a reader's task to the existing condition ledger.
// Research being answered does not attest that the candidate answers it.
type ReaderQuestionTarget struct {
	QuestionID string   `json:"question_id"`
	ChapterID  string   `json:"chapter_id"`
	Question   string   `json:"question"`
	ClaimIDs   []string `json:"claim_ids"`
}

type ReaderQuestionCheck struct {
	QuestionID     string   `json:"question_id"`
	CandidateQuote string   `json:"candidate_quote"`
	Function       string   `json:"function"`
	Status         string   `json:"status"`
	Reason         string   `json:"reason"`
	ClaimIDs       []string `json:"claim_ids"`
}

func requiredReaderQuestions(h *ResearchHandoff) []ReaderQuestionTarget {
	var out []ReaderQuestionTarget
	if h != nil {
		for _, q := range h.Decisions {
			if q.Required {
				out = append(out, ReaderQuestionTarget{q.ID, q.ChapterID, q.Question, q.ClaimIDs})
			}
		}
	}
	return out
}

func hasOpenReaderQuestions(checks []ReaderQuestionCheck) bool {
	for _, check := range checks {
		if check.Status == "missing" || check.Status == "unclear" {
			return true
		}
	}
	return false
}

// Validate evidence/coverage before projecting any repair targets. This cannot
// decide whether a quoted explanation is semantically sufficient: that remains
// the critic's task. Invalid or contradictory reviews use the existing retry.
func applyReaderQuestionReview(in criticInput, out *criticResult) error {
	if in.Mode != "reconstruct" || in.Handoff == nil {
		if len(out.ReaderQuestionChecks) != 0 {
			return fmt.Errorf("reader_question_checks: no reader questions assigned in this mode")
		}
		return nil
	}
	targets := requiredReaderQuestions(in.Handoff)
	if len(out.ReaderQuestionChecks) != len(targets) {
		return fmt.Errorf("reader_question_checks: required one check for each of %d questions", len(targets))
	}
	want := map[string]ReaderQuestionTarget{}
	for _, q := range targets {
		want[q.QuestionID] = q
	}
	seen := map[string]bool{}
	var findings []analyzers.Finding
	for _, check := range out.ReaderQuestionChecks {
		target, ok := want[check.QuestionID]
		if !ok || seen[check.QuestionID] {
			return fmt.Errorf("reader_question_checks: unknown or duplicate question_id %q", check.QuestionID)
		}
		seen[check.QuestionID] = true
		if strings.TrimSpace(check.Function) == "" || strings.TrimSpace(check.Reason) == "" {
			return fmt.Errorf("reader_question_checks/%s: function and reason required", check.QuestionID)
		}
		refs := map[string]bool{}
		for _, id := range target.ClaimIDs {
			refs[id] = true
		}
		for _, id := range check.ClaimIDs {
			if !refs[id] {
				return fmt.Errorf("reader_question_checks/%s: foreign or duplicate claim_id %q", check.QuestionID, id)
			}
			delete(refs, id)
		}
		if len(refs) != 0 {
			return fmt.Errorf("reader_question_checks/%s: all assigned claim_ids required", check.QuestionID)
		}
		switch check.Status {
		case "answered", "unclear":
			if strings.TrimSpace(check.CandidateQuote) == "" || !strings.Contains(in.Candidate, check.CandidateQuote) {
				return fmt.Errorf("reader_question_checks/%s: exact candidate_quote required", check.QuestionID)
			}
		case "missing":
			if check.CandidateQuote != "" {
				return fmt.Errorf("reader_question_checks/%s: missing answer must not borrow a candidate quote", check.QuestionID)
			}
		default:
			return fmt.Errorf("reader_question_checks/%s: invalid status %q", check.QuestionID, check.Status)
		}
		if check.Status == "answered" {
			continue
		}
		if out.Verdict == "accept" {
			return fmt.Errorf("reader_question_checks/%s: accept contradicts %s answer", check.QuestionID, check.Status)
		}
		finding := analyzers.Finding{
			Analyzer: "reader-question", RuleID: "reader_question." + check.QuestionID, Severity: "error",
			Message:  fmt.Sprintf("Не закрыт вопрос читателя %s (%s): %s. Функция ответа: %s. Основания только из claim_ids: %s. Исправь объяснение по handoff; сохрани остальные полезные фрагменты. Повторная проверка обязательна.", check.QuestionID, target.Question, check.Reason, check.Function, strings.Join(target.ClaimIDs, ", ")),
			Evidence: check.CandidateQuote,
		}
		if check.Status == "missing" {
			// Missing prose has no literal anchor. The existing patch executor can
			// insert at a unique nearby anchor, without pretending it is an answer.
			raw, _ := json.Marshal(map[string]any{"repair_only": true, "missing_reader_question": target})
			finding.Evidence = string(raw)
		}
		findings = append(findings, finding)
	}
	out.Findings = append(out.Findings, findings...)
	return nil
}

const readerQuestionAuthorInstruction = "\nrequired_reader_questions — обязательные задачи читателя, а не готовые заголовки. Для каждой дай понятный ответ по ее claim_ids и соответствующим условиям, исключениям и уверенности из condition_ledger/research_handoff. Выбери порядок объяснения по задаче, не копируй реестр. Один фрагмент может закрывать несколько вопросов, отдельный абзац на вопрос не требуется. Не добавляй недостающие факты или причины ради закрытия вопроса. Эта карта служебная: в статью ее не выводи."

func readerQuestionReviewInstruction(mode string) string {
	if mode != "reconstruct" {
		return ""
	}
	return "\nВерни reader_question_checks: ровно по одному объекту на каждый required_reader_questions, без добавления новых вопросов. Поля: question_id, candidate_quote, function, status (answered|missing|unclear), reason, claim_ids (все назначенные вопросу ID, без чужих и повторов). Сверь весь ответ с условиями и исключениями handoff; присутствие отдельных фактов не гарантирует понятного ответа. answered требует дословный фрагмент candidate и объяснение, как он помогает читателю; unclear требует дословный проблемный фрагмент и конкретное препятствие пониманию. При missing candidate_quote должен быть пустой строкой, function описывает недостающую функцию, reason — что именно отсутствует, а не соседнюю цитату. Несколько вопросов могут ссылаться на один фрагмент, ответ может занимать несколько абзацев. Полезные напоминания и авторская композиция допустимы: не требуй отдельного раздела на вопрос. missing/unclear требуют repair или reject; accept допускается только при всех answered. Не выдумывай основание, чтобы получить answered: повторная проверка проводится по новому candidate."
}
