package guards

import "testing"

func TestLiteralFootnoteMustNotBecomeList(t *testing.T) {
	source := "Вы получите карты*.\n\n*\u00a0По две копии каждой карты."
	list := "Вы получите карты*.\n\n* По две копии каждой карты."
	if !Compare(source, list).HasHardChanges() {
		t.Fatal("literal footnote silently became a Markdown list")
	}
	if Compare(source, "Вы получите карты*.\n\n\\* По две копии каждой карты.").HasHardChanges() {
		t.Fatal("escaped literal footnote should preserve its meaning")
	}
	if !Compare(source, "Вы получите карты*.\n\nПо две копии каждой карты.").HasHardChanges() {
		t.Fatal("missing footnote marker accepted")
	}
}

func TestFootnotesDoNotProtectListsOrCodeAsNotes(t *testing.T) {
	for _, source := range []string{"* Обычный список", "    *\u00a0пример кода", "```md\n*\u00a0пример кода\n```", "~~~\n\\* пример кода\n~~~"} {
		if got := Values(Extract(source), "literal_footnote"); len(got) != 0 {
			t.Fatalf("not a footnote: %q: %v", source, got)
		}
	}
	if Compare("* Пункт\n* Второй", "* Пункт\n\n* Второй").HasHardChanges() {
		t.Fatal("blank line became part of a protected list marker")
	}
}

func TestLiteralFootnoteCountsAndMultipleStars(t *testing.T) {
	source := "*\u00a0Первое пояснение.\n\n**\u00a0Второе пояснение."
	if Compare(source, "\\* Первое пояснение.\n\n\\*\\* Второе пояснение.").HasHardChanges() {
		t.Fatal("equivalent literal markers rejected")
	}
	if !Compare(source, "\\* Первое пояснение.\n\n\\* Второе пояснение.").HasHardChanges() {
		t.Fatal("different footnote identifier accepted")
	}
}

func TestMarkdownFootnoteReferenceCannotDisappear(t *testing.T) {
	source := "Описание[^note].\n\n[^note]: Пояснение."
	if !Compare(source, "Описание.\n\n[^note]: Пояснение.").HasHardChanges() {
		t.Fatal("reference removed while definition retained")
	}
}

func TestFootnoteReferenceInsideInlineCodeIsNotAReference(t *testing.T) {
	for _, text := range []string{"`[^note]`", "``code ` [^note]``", "Текст ``code ` [^note]``", "\\[^note]"} {
		if got := Values(Extract(text), "footnote_reference"); len(got) != 0 {
			t.Fatalf("code or escaped text is not a reference: %q: %v", text, got)
		}
	}
	if got := Values(Extract("`code` описание[^real]"), "footnote_reference"); len(got) != 1 {
		t.Fatal("inline code at line start swallowed the real reference", got)
	}
}
