// Package budget растягивает сроки анализаторов под длину текста.
//
// Фиксированные 8 секунд хватают на новость, но не на гайд в 20 тысяч
// знаков: длинная статья получала checks_complete=false не из-за ошибки,
// а из-за таймаута. Срок растёт линейно и ограничен сверху.
package budget

import (
	"time"
	"unicode/utf8"
)

// BaseRunes — длина, для которой хватает базового срока.
const BaseRunes = 6000

// MaxFactor ограничивает рост: зависший анализатор не держит запрос вечно.
const MaxFactor = 6

// ForText возвращает срок для текста: base до BaseRunes знаков, дальше
// пропорционально длине, но не больше base*MaxFactor.
func ForText(base time.Duration, text string) time.Duration {
	if base <= 0 {
		return base
	}
	runes := utf8.RuneCountInString(text)
	if runes <= BaseRunes {
		return base
	}
	scaled := time.Duration(int64(base) * int64(runes) / BaseRunes)
	if limit := base * MaxFactor; scaled > limit {
		return limit
	}
	return scaled
}
