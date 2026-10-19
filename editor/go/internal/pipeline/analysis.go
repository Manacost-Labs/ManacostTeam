package pipeline

import (
	"encoding/json"
	"strings"
)

// Ordinary editing includes form work. Keep that intent out of proofreading,
// factual-only review and reconstruction, which have their own contracts.
func formEditingInstruction(mode string) string {
	if mode != "edit" && mode != "rewrite" {
		return ""
	}
	return "\nЗадача edit/rewrite: сохранить содержание и сделать его удобнее читать. Правильная мысль и удачный авторский голос совместимы с улучшением формы. " +
		"Оцени форму отдельно: смена функции внутри плотного абзаца, цепочка придаточных, тяжёлый пассив, избыточная словесная обвязка, повторение уже очевидной темы в соседних пунктах. " +
		"Разделяй самостоятельные смысловые шаги на абзацы, сохраняя связанное объяснение с его условием. Оценка ситуации, действие и отдельный дальнейший план могут образовывать разные абзацы даже в цельном комментарии одного автора. Разделение не требует нового заголовка или переписывания слов. " +
		"Упрощай громоздкую фразу, когда та же мысль читается прямее: убирай дублирующую обвязку, сокращай цепочку придаточных, выбирай естественный глагол без выдуманного действующего лица. Сохраняй точный предмет, условия, степень уверенности и временную точку зрения. " +
		"Для полезной правки достаточно небольшого конкретного выигрыша формы: легче найти отдельную мысль, короче синтаксическая связь, меньше повторной обвязки при ясном предмете. Новый факт, совет или объяснение для этого не нужны. " +
		"Перед добавлением пояснения проверь, что уже явно сказано в соседних предложениях. Если читатель уже получает это же правило, условие или порядок действий, оставь существующее объяснение и не пересказывай его ещё раз в другой фразе. Уточнение должно устранять реальную неоднозначность, а не повторять соседнее предложение. " +
		"Сравни целый абзац после правки: облегчение одной фразы не оправдывает появившийся рядом повтор. Оставь текст без изменений, если после проверки формы конкретной пользы нет."
}

// Analysis is advisory. A malformed optional field must not erase valid
// preservation evidence from another field. Accept the two observed object
// forms explicitly; never stringify arbitrary model objects into instructions.
func parseAnalysis(text string) Analysis {
	var fields map[string]json.RawMessage
	var out Analysis
	if err := json.Unmarshal([]byte(stripJSON(text)), &fields); err != nil || fields == nil {
		out.ParseWarnings = []string{"анализ не разобран: ожидается JSON-объект"}
		return out
	}
	for _, field := range []struct {
		name string
		dest *string
	}{{"thesis", &out.Thesis}, {"audience", &out.Audience}, {"genre", &out.Genre}} {
		if raw, ok := fields[field.name]; ok && json.Unmarshal(raw, field.dest) != nil {
			out.ParseWarnings = append(out.ParseWarnings, "неверный тип: "+field.name)
		}
	}
	for _, field := range []struct {
		name string
		dest *[]string
	}{{"paragraphs", &out.Paragraphs}, {"weak_spots", &out.WeakSpots}, {"repetitions", &out.Repetitions}, {"unclear", &out.Unclear}, {"template_phrases", &out.TemplatePhrases}, {"missing_links", &out.MissingLinks}, {"factual_risks", &out.FactualRisks}} {
		raw, ok := fields[field.name]
		if !ok {
			continue
		}
		var items []json.RawMessage
		if json.Unmarshal(raw, &items) != nil {
			out.ParseWarnings = append(out.ParseWarnings, "неверный тип: "+field.name)
			continue
		}
		for _, item := range items {
			var value string
			if json.Unmarshal(item, &value) != nil {
				var known struct {
					Function string `json:"function"`
					Where    string `json:"where"`
					Issue    string `json:"issue"`
				}
				if json.Unmarshal(item, &known) == nil {
					if field.name == "paragraphs" {
						value = known.Function
					}
					if field.name == "weak_spots" && known.Issue != "" {
						value = strings.TrimSpace(known.Where + ": " + known.Issue)
					}
				}
				if value == "" {
					out.ParseWarnings = append(out.ParseWarnings, "пропущен элемент: "+field.name)
				}
			}
			if strings.TrimSpace(value) != "" {
				*field.dest = append(*field.dest, value)
			}
		}
	}
	if raw, ok := fields["strengths"]; ok {
		var items []json.RawMessage
		if json.Unmarshal(raw, &items) != nil {
			out.ParseWarnings = append(out.ParseWarnings, "неверный тип: strengths")
		} else {
			for _, item := range items {
				var span StrongSpan
				if json.Unmarshal(item, &span) == nil {
					out.Strengths = append(out.Strengths, span)
				}
			}
		}
	}
	return out
}

// Archive examples describe craft, never current game facts or quotas.
const craftInstruction = "\nПриёмы архивных гайдов применяй по задаче читателя, а не по шаблону. " +
	"Глава снимает конкретное препятствие пониманию: сначала нужная предпосылка или механизм, затем выбор и применение. " +
	"Связь условие → действие → причина → исключение полезна только там, где её элементы есть в источнике; недостающую причину или альтернативу не сочиняй. " +
	"Переход продолжает мысль: не добавляй связки ради плавности. Вопрос, обращение и предметный образ нужны только если облегчают понимание, без квот и обязательной разговорности. " +
	"Нейтральный оборот не требует замены только из-за ярлыка «канцелярит». После сокращения или смены залога проверь соседние слова и отсылки: не создавай тавтологию или двусмысленность ради короткого глагола. " +
	"Сохраняй функциональные повторы: точное название, напоминание условия и краткая опора для повторного чтения могут быть полезнее синонима. " +
	"Абзац объединяет одну задачу объяснения. При переходе от общего условия к отдельному способу получения, от основного правила к самостоятельному исключению или от объяснения к следующему действию проверь, нужен ли новый абзац. " +
	"Сначала попробуй только границу абзаца, сохранив слова; не разбивай единое рассуждение по длине и не отделяй условие от совета. Сноска остаётся отдельной сноской, не пунктом списка. " +
	"При локальном repair сохрани уже полезные границы абзацев и соседние удачные правки. Перефразирование равноценной формулировки не считается улучшением. При proofread эти приёмы не разрешают менять композицию или стиль: сохраняй границы абзацев."
