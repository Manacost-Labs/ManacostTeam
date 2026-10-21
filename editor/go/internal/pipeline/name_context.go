package pipeline

// A closed grammatical vocabulary at the start of a sentence/heading is not
// part of the following known name. This permits no new root or compound name:
// the ENTIRE remainder must still match before/sourceNameForms. Timing, effects,
// ownership and modality remain in the unchanged candidate for full fact review.
func sentenceStartNamePrefix(word string) bool {
	switch word {
	case "Без", "После", "Перед", "Для", "Против", "При", "До", "Кроме", "Вместо", "Через",
		"На", "По", "Со", "За", "От", "Из", "Про", "Ради", "Между", "Среди", "Под", "Над", "Вокруг", "Внутри", "Вне", "Ко", "Обо":
		return true
	case "Играть", "Играйте", "Разыгрывать", "Разыгрывайте", "Используйте", "Сыграйте", "Выставьте", "Разыграйте", "Найдите", "Оставляйте", "Сохраняйте", "Держите", "Ищите",
		"Найти", "Сыграть", "Оставить", "Сохранить", "Получить", "Потерять", "Разогнать", "Проверить", "Запомните", "Учитывайте", "Пересчитайте", "Считайте":
		return true
	case "Если", "Пока", "Когда", "Это", "Однако", "Сначала", "Так", "Затем", "Иногда", "Обычно", "Здесь", "Как", "Почему", "Зачем", "Эта", "Этот", "Эти":
		return true
	case "Текст", "Эффект", "Свойство", "Наличие", "Отсутствие", "Роль", "Стоимость", "Скидка", "Скидку", "Усиление", "Розыгрыш", "Поиск", "Выбор", "Порядок", "Смерть", "Уничтожение",
		"Причина", "Суть", "Оценка", "Возможности", "Задача", "Сила", "Работа", "Подготовка", "План", "Версия", "Сборка", "Ранний", "Поздний", "Классический":
		return true
	default:
		return false
	}
}
