package editorialreview

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"strings"
)

func OwnerIDs() []string {
	return []string{"card_text_retelling", "obvious_or_water", "weak_or_obvious_tips", "duplicated_advice", "source_attribution_in_body", "unsupported_or_false_claim", "illogical_comparison", "unclear_edge_case", "genre_fit", "ai_tells"}
}

const ClaimGuidance = "Правилом с «потому что» подавай только claim_kind=mechanic с проверенным основанием. observation — наблюдение в указанной выборке, не правило и не причина. opinion — мнение с именем игрока, только если нужно читателю. Отсутствующий claim_kind старого handoff не угадывай. Если handoff говорит «блок советов писать не из чего», блок не пишется."

const OwnerPrompt = `
Обязательна рубрика owner_checks: по каждой категории owner_review_assignment верни {id,status:"clear|issue|unverified",quote,reason}.
Каждая строка требует непустую дословную цитату candidate, даже при отсутствии дефекта; reason объясняет проверку.
card_text_retelling: пересказ подсказки карты/силы героя без решения; obvious_or_water: очевидное и страховки;
weak_or_obvious_tips: слабые пункты или ненужный блок целиком; duplicated_advice: повтор между разделами;
source_attribution_in_body: «по данным», Reddit и отчёт об источниках в прозе; unsupported_or_false_claim: правило без проверенной причины, observation вместо mechanic;
illogical_comparison: выбор, которого у игрока на практике нет; unclear_edge_case: необъяснённый частный случай;
genre_fit: манера и объём относительно выбранных образцов. Если переданы только отрывки, бюджет полной статьи неизвестен — не выводи его из длины отрывков;
ai_tells: шаблонные рамки и интонация, не определение авторства. Отрицательный вердикт сохраняй как repair с цитатой, не меняй на clear ради допуска.
Программа проверяет охват и цитаты, смысл и качество оцениваешь ты.
` + ClaimGuidance

const DeletionPrompt = `DELETION_PASS
После черновика и до литературного отзыва выполни проход на вычёркивание. Только удаляй и сокращай; новых фактов, слов, связок и перестановок не добавляй.
Для каждого предложения спроси: «какое решение потеряет игрок, если это убрать?» Нет ответа — вычеркни.
Удали пересказ подсказки карты или силы героя, очевидное, страховочные оговорки без пользы, повтор совета, ссылки на источники в теле («по данным…», «игроки на Reddit…»), наблюдение в форме правила без проверяемой причины, сравнение без доступного игроку выбора. Слабый блок советов убери целиком.
Находки card_paraphrase.retelling, owner.overused_word, owner.section_repeat, owner.forbidden_literal — диагностический вход, не приказ удалить полезное.
«Убрать воду» не означает сократить полезные объяснения: сохрани предпосылки, развилки, числа, условия, исключения и уверенность. Если удаление искажает смысл, оставь для отдельного ремонта.
Верни только JSON {article_sha256,deletions:[{start,quote,reason}],unchanged_reason}. start — индекс Unicode символа (не байт и не UTF-16) в candidate; quote — точная удаляемая подстрока. По возрастанию, без пересечений. deletions=[] требует конкретного unchanged_reason. Список удалений остаётся в рабочих материалах, не в статье.
` + ClaimGuidance

// ValidateOwner validates coverage, not judgment. Negative checks remain valid
// evidence for contextualFindings and cannot authorize acceptance.
func ValidateOwner(candidate string, rows []Check) error {
	ids := OwnerIDs()
	if len(rows) != len(ids) {
		return fmt.Errorf("owner_checks: exactly %d categories required", len(ids))
	}
	expected := map[string]bool{}
	for _, id := range ids {
		expected[id] = true
	}
	for _, row := range rows {
		if !expected[row.ID] {
			return fmt.Errorf("owner_checks: unknown or duplicate category %s", row.ID)
		}
		delete(expected, row.ID)
		if row.Status != "clear" && row.Status != "issue" && row.Status != "unverified" {
			return fmt.Errorf("owner_checks/%s: invalid status", row.ID)
		}
		if !nonempty(row.Quote) || !strings.Contains(candidate, row.Quote) || !nonempty(row.Reason) {
			return fmt.Errorf("owner_checks/%s: exact nonempty quote and reason required", row.ID)
		}
	}
	return nil
}

type Deletion struct {
	Start  *int   `json:"start"`
	Quote  string `json:"quote"`
	Reason string `json:"reason"`
}

type DeletionReceipt struct {
	ArticleSHA256   string     `json:"article_sha256"`
	Deletions       []Deletion `json:"deletions"`
	UnchangedReason string     `json:"unchanged_reason"`
}

func ApplyDeletion(candidate, raw string) (string, *DeletionReceipt, error) {
	var report DeletionReceipt
	decoder := json.NewDecoder(strings.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&report); err != nil {
		return candidate, nil, err
	}
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		return candidate, nil, fmt.Errorf("deletion_pass: trailing JSON")
	}
	if report.ArticleSHA256 != fmt.Sprintf("%x", sha256.Sum256([]byte(candidate))) || report.Deletions == nil || len(report.Deletions) > 1024 {
		return candidate, nil, fmt.Errorf("deletion_pass: hash or deletions invalid")
	}
	if len(report.Deletions) == 0 && !nonempty(report.UnchangedReason) {
		return candidate, nil, fmt.Errorf("deletion_pass: explain unchanged result")
	}
	runes, cursor := []rune(candidate), 0
	var out strings.Builder
	for _, row := range report.Deletions {
		if row.Start == nil || !nonempty(row.Reason) || row.Quote == "" {
			return candidate, nil, fmt.Errorf("deletion_pass: start/quote/reason required")
		}
		start, end := *row.Start, *row.Start+len([]rune(row.Quote))
		if start < cursor || start > len(runes) || end > len(runes) || end < start || string(runes[start:end]) != row.Quote {
			return candidate, nil, fmt.Errorf("deletion_pass: exact ordered nonoverlapping removals required")
		}
		out.WriteString(string(runes[cursor:start]))
		cursor = end
	}
	out.WriteString(string(runes[cursor:]))
	if !nonempty(out.String()) {
		return candidate, nil, fmt.Errorf("deletion_pass: cannot erase article")
	}
	return out.String(), &report, nil
}
