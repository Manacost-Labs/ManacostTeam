package main

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/pipeline"
)

func TestCalibrateCLIUnavailableIsAttributableAndDoesNotOverwrite(t *testing.T) {
	directory := t.TempDir()
	input := filepath.Join(directory, "packet.json")
	output := filepath.Join(directory, "rows.json")
	raw := []byte(`{"items":[{"id":"i","task":"meaning","source":"До.","candidate":"После.","expected":"SECRET_KEY_LABEL"}]}`)
	if err := os.WriteFile(input, raw, 0600); err != nil {
		t.Fatal(err)
	}
	args := []string{"--packet", input, "--output", output}
	if err := calibrateCritic(context.Background(), args, nil); err != nil {
		t.Fatal(err)
	}
	saved, err := os.ReadFile(output)
	if err != nil {
		t.Fatal(err)
	}
	var report pipeline.CalibrationReport
	if err = json.Unmarshal(saved, &report); err != nil {
		t.Fatal(err)
	}
	if report.PacketSHA256 != fmt.Sprintf("%x", sha256.Sum256(raw)) || report.Rows[0].Decision != "unavailable" || report.Rows[0].Scores != nil || strings.Contains(string(saved), "SECRET_KEY_LABEL") {
		t.Fatalf("bad report: %s", saved)
	}
	if err = calibrateCritic(context.Background(), args, nil); err == nil {
		t.Fatal("existing output could be overwritten")
	}
}
