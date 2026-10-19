package analyzer

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestRulesAndValidationForwardSameCorrectionContext(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var data map[string]any
		if err := json.NewDecoder(r.Body).Decode(&data); err != nil {
			t.Error(err)
		}
		if data["author"] != "ivan" || data["meaning"] != "application" {
			t.Errorf("%s lost correction qualification: %#v", r.URL.Path, data)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"accepted":true}`))
	}))
	defer srv.Close()
	c := New(srv.URL, time.Second)
	if _, err := c.RulesWithContext(context.Background(), "hearthstone", "news", RulesContext{Author: "ivan", Meaning: "application"}); err != nil {
		t.Fatal(err)
	}
	if _, err := c.ValidateWithContext(context.Background(), "text", "text", "hearthstone", "news", ValidationContext{Author: "ivan", Meaning: "application"}); err != nil {
		t.Fatal(err)
	}
}
