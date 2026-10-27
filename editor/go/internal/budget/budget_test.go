package budget

import (
	"strings"
	"testing"
	"time"
)

func TestForTextScalesWithLengthAndIsCapped(t *testing.T) {
	base := 8 * time.Second
	if got := ForText(base, strings.Repeat("я", BaseRunes)); got != base {
		t.Fatalf("short text keeps base: %v", got)
	}
	if got := ForText(base, strings.Repeat("я", 3*BaseRunes)); got != 3*base {
		t.Fatalf("long guide must get proportional time: %v", got)
	}
	if got := ForText(base, strings.Repeat("я", 100*BaseRunes)); got != MaxFactor*base {
		t.Fatalf("growth must be capped: %v", got)
	}
}
