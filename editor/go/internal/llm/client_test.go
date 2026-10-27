package llm

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestTruncatedCompletionIsAnError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"choices":[{"message":{"role":"assistant","content":"Половина гайда"},"finish_reason":"length"}]}`))
	}))
	defer server.Close()
	client := New("openrouter", "model", "key", "", "", time.Second)
	client.SetEndpointForTest(server.URL)
	if _, err := client.Complete(context.Background(), []Message{{Role: "user", Content: "Напиши гайд"}}, 0); !errors.Is(err, ErrTruncated) {
		t.Fatalf("truncated answer must not look complete: %v", err)
	}
}

func TestStoppedCompletionIsReturned(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"choices":[{"message":{"role":"assistant","content":" Готово "},"finish_reason":"stop"}]}`))
	}))
	defer server.Close()
	client := New("openrouter", "model", "key", "", "", time.Second)
	client.SetEndpointForTest(server.URL)
	text, err := client.Complete(context.Background(), []Message{{Role: "user", Content: "Правь"}}, 0)
	if err != nil || text != "Готово" {
		t.Fatalf("complete answer: %q %v", text, err)
	}
}
