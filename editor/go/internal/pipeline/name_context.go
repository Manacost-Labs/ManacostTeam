package pipeline

import "strings"

// A closed grammatical vocabulary at the start of a sentence/heading is not
// part of the following known name. This permits no new root or compound name:
// the remainder must still consist of verified full name forms. Timing, effects,
// ownership and modality remain in the unchanged candidate for full fact review.
func sentenceStartNamePrefix(word string) bool {
	switch word {
	case "Без", "После", "Перед", "Для", "Против", "При", "До", "Кроме", "Вместо", "Через",
		"На", "По", "Со", "За", "От", "Из", "Про", "Ради", "Между", "Среди", "Под", "Над", "Вокруг", "Внутри", "Вне", "Ко", "Обо":
		return true
	case "Играть", "Играйте", "Разыгрывать", "Разыгрывайте", "Используйте", "Сыграйте", "Выставьте", "Разыграйте", "Найдите", "Оставляйте", "Сохраняйте", "Держите", "Ищите",
		"Найти", "Сыграть", "Оставить", "Сохранить", "Получить", "Потерять", "Разогнать", "Проверить", "Запомните", "Учитывайте", "Пересчитайте", "Считайте":
		return true
	case "Если", "Пока", "Когда", "Это", "Однако", "Сначала", "Так", "Затем", "Иногда", "Обычно", "Здесь", "Как", "Почему", "Зачем", "Эта", "Этот", "Эти", "Сам", "Сама", "Сами", "Саму":
		return true
	case "Текст", "Эффект", "Свойство", "Наличие", "Отсутствие", "Роль", "Стоимость", "Скидка", "Скидку", "Усиление", "Розыгрыш", "Поиск", "Выбор", "Порядок", "Смерть", "Уничтожение",
		"Причина", "Суть", "Оценка", "Возможности", "Задача", "Сила", "Работа", "Подготовка", "План", "Версия", "Сборка", "Ранний", "Поздний", "Классический", "Механика", "Механики":
		return true
	case "Выставленная", "Выставленный", "Выставленные", "Разыгранная", "Разыгранный", "Разыгранные", "Сыгранная", "Сыгранный", "Сыгранные":
		return true
	default:
		return false
	}
}

// A prepositional phrase followed by a subject can contain two separate known
// names ("До Полкелта Сфера ..."). Do not permit the same composition without
// that grammatical boundary, a third name, or any unverified remainder.
func knownNameContext(phrase string, known []string) bool {
	prefix, rest, ok := strings.Cut(phrase, " ")
	if !ok || !sentenceStartNamePrefix(prefix) {
		return false
	}
	if knownNameInflection(rest, known) {
		return true
	}
	switch prefix {
	case "Без", "После", "Перед", "Для", "Против", "При", "До", "Кроме", "Вместо", "Через", "На", "По", "Со", "За", "От", "Из", "Про", "Ради", "Между", "Среди", "Под", "Над", "Вокруг", "Внутри", "Вне", "Ко", "Обо":
	default:
		return false
	}
	words := strings.Fields(rest)
	for i := 1; i < len(words); i++ {
		if knownNameInflection(strings.Join(words[:i], " "), known) && knownNameInflection(strings.Join(words[i:], " "), known) {
			return true
		}
	}
	return false
}
