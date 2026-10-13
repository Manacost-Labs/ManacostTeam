package pipeline

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzer"
)

func TestTaskContextSelectsGameAndGenreBeforeAnalysis(t *testing.T) {
	const envelope = `{"schema_version":1,"game":{"id":"world-of-warcraft"},"profile":{"id":"manacost"}}`
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var payload map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Error(err)
		}
		switch r.URL.Path {
		case "/context/resolve":
			if string(payload["task_context"]) != envelope {
				t.Errorf("context lost: %s", payload["task_context"])
			}
			_, _ = w.Write([]byte(`{"game":"wow","profile":"wow-guide","current_patch":"fixture-build","task_context":` + envelope + `}`))
		case "/rules":
			if string(payload["game"]) != `"wow"` || string(payload["profile"]) != `"wow-guide"` || len(payload["task_context"]) == 0 {
				t.Errorf("wrong rules context: %v", payload)
			}
			_, _ = w.Write([]byte(`{"game":"wow","profile":"wow-guide","task_context":` + envelope + `}`))
		default:
			t.Errorf("unexpected request %s", r.URL.Path)
			http.Error(w, "unexpected", http.StatusBadRequest)
		}
	}))
	defer server.Close()
	check := &scriptedAnalyzer{name: "test"}
	service := New(nil, analyzer.New(server.URL, time.Second), "none", check)
	result, err := service.Run(context.Background(), Request{Text: "Урон повышается на 20%.", Mode: "edit", TaskContext: json.RawMessage(envelope)})
	if err != nil {
		t.Fatal(err)
	}
	if string(result.TaskContext) != envelope || len(check.inputs) == 0 || check.inputs[0].Game != "wow" || check.inputs[0].Profile != "wow-guide" || check.inputs[0].CurrentPatch != "fixture-build" {
		t.Fatalf("context not propagated: result=%+v inputs=%+v", result, check.inputs)
	}
}

func TestTaskContextFailurePreventsChecksAndModelCalls(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "conflicting game", http.StatusBadRequest)
	}))
	defer server.Close()
	check := &scriptedAnalyzer{name: "test"}
	model := &fakeLLM{replies: []string{analysisJSON}}
	service := New(model, analyzer.New(server.URL, time.Second), "test", check)
	_, err := service.Run(context.Background(), Request{Text: "Пример.", Mode: "edit", TaskContext: json.RawMessage(`{}`)})
	if _, ok := err.(*RequestError); !ok || len(check.inputs) != 0 || model.i != 0 {
		t.Fatalf("validation did not stop execution: error=%v inputs=%v calls=%d", err, check.inputs, model.i)
	}
}
