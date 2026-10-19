package markdownlint

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

// A portable child test process observes the exact file sent to the CLI.
func TestSerializedDocumentHelper(t *testing.T) {
	if os.Getenv("EDITOR_MARKDOWN_TEST_HELPER") != "1" {
		return
	}
	data, err := os.ReadFile(os.Args[len(os.Args)-1])
	if err != nil {
		os.Exit(2)
	}
	if os.Getenv("EDITOR_MARKDOWN_EMPTY_EXIT") == "fail" {
		os.Exit(2)
	}
	if os.Getenv("EDITOR_MARKDOWN_EMPTY_EXIT") == "success" {
		os.Exit(0)
	}
	if !strings.HasSuffix(string(data), "\n") {
		os.Stdout.WriteString(`[{"lineNumber":1,"ruleNames":["MD047"],"errorDetail":"missing newline"}]`)
	} else {
		os.Stdout.WriteString(`[]`)
	}
	os.Exit(0)
}

func TestJSONTextIsSerializedAsMarkdownDocument(t *testing.T) {
	// Build a tiny wrapper because Runner owns the CLI arguments.
	dir := t.TempDir()
	source := filepath.Join(dir, "main.go")
	code := `package main
import ("os"; "os/exec")
func main() { args:=append([]string{"-test.run=^TestSerializedDocumentHelper$", "--"},os.Args[1:]...); c:=exec.Command(os.Getenv("EDITOR_TEST_BINARY"),args...); c.Stdout=os.Stdout; c.Stderr=os.Stderr; if c.Run()!=nil {os.Exit(2)} }
`
	if err := os.WriteFile(source, []byte(code), 0600); err != nil {
		t.Fatal(err)
	}
	bin := filepath.Join(dir, "cli.exe")
	if out, err := exec.Command("go", "build", "-o", bin, source).CombinedOutput(); err != nil {
		t.Fatalf("%s: %v", out, err)
	}
	t.Setenv("EDITOR_MARKDOWN_TEST_HELPER", "1")
	t.Setenv("EDITOR_TEST_BINARY", os.Args[0])
	got, err := New(bin, "", 0).Check(context.Background(), "Готовый абзац.")
	if err != nil || len(got) != 0 {
		t.Fatalf("transport newline caused editorial repair: %+v %v", got, err)
	}
	// The real markdownlint CLI is silent when --json finds no violations.
	t.Setenv("EDITOR_MARKDOWN_EMPTY_EXIT", "success")
	got, err = New(bin, "", 0).Check(context.Background(), "Готовый абзац.")
	if err != nil || len(got) != 0 {
		t.Fatalf("successful silent CLI is not unavailable: %+v %v", got, err)
	}
	t.Setenv("EDITOR_MARKDOWN_EMPTY_EXIT", "fail")
	if _, err = New(bin, "", 0).Check(context.Background(), "Готовый абзац."); err == nil {
		t.Fatal("silent failure must remain an error")
	}
}

func TestCheckParsesJSON(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("тест использует POSIX-скрипт")
	}
	dir := t.TempDir()
	bin := filepath.Join(dir, "markdownlint-fake")
	content := "#!/bin/sh\nprintf '%s' '[{\"fileName\":\"input.md\",\"lineNumber\":2,\"ruleNames\":[\"MD022\"],\"errorDetail\":\"нужна пустая строка\",\"errorContext\":\"## Заголовок\",\"errorRange\":[1,3]}]'\n"
	if err := os.WriteFile(bin, []byte(content), 0o700); err != nil {
		t.Fatal(err)
	}
	got, err := New(bin, "", 0).Check(context.Background(), "# Заголовок\n## Заголовок")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].RuleID != "MD022" || got[0].Line != 2 {
		t.Fatalf("unexpected findings: %#v", got)
	}
}

func TestCheckParsesMarkdownlintCLI2Output(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("тест использует POSIX-скрипт")
	}
	dir := t.TempDir()
	bin := filepath.Join(dir, "markdownlint-cli2")
	content := "#!/bin/sh\nprintf '%s\\n' 'markdownlint-cli2 v0.17.2 (markdownlint v0.37.4)' 'Finding: input.md' 'Linting: 1 file(s)' 'Summary: 1 error(s)' 'input.md:2:3 MD022/blanks-around-headings Headings should be surrounded by blank lines [Context: \"## Заголовок\"]'\nexit 1\n"
	if err := os.WriteFile(bin, []byte(content), 0o700); err != nil {
		t.Fatal(err)
	}
	got, err := New(bin, "", 0).Check(context.Background(), "# Заголовок\n## Заголовок")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].RuleID != "MD022" || got[0].Line != 2 || got[0].Column != 3 {
		t.Fatalf("unexpected CLI2 findings: %#v", got)
	}
}

func TestCheckAcceptsCleanMarkdownlintCLI2Output(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("тест использует POSIX-скрипт")
	}
	dir := t.TempDir()
	bin := filepath.Join(dir, "markdownlint-cli2")
	content := "#!/bin/sh\nprintf '%s\\n' 'markdownlint-cli2 v0.17.2 (markdownlint v0.37.4)' 'Finding: input.md' 'Linting: 1 file(s)' 'Summary: 0 error(s)'\n"
	if err := os.WriteFile(bin, []byte(content), 0o700); err != nil {
		t.Fatal(err)
	}
	got, err := New(bin, "", 0).Check(context.Background(), "Чистый текст.")
	if err != nil || len(got) != 0 {
		t.Fatalf("clean CLI2 result: %#v, %v", got, err)
	}
}

func TestParseCLI2RejectsIncompleteOutput(t *testing.T) {
	tests := []struct {
		name   string
		output string
	}{
		{
			name:   "missing summary",
			output: "markdownlint-cli2 v0.17.2 (markdownlint v0.37.4)\nFinding: input.md\nLinting: 1 file(s)\n",
		},
		{
			name: "finding count mismatch",
			output: strings.Join([]string{
				"markdownlint-cli2 v0.17.2 (markdownlint v0.37.4)",
				"Finding: input.md",
				"Linting: 1 file(s)",
				"Summary: 2 error(s)",
				"input.md:2:3 MD022/blanks-around-headings Headings should be surrounded by blank lines",
			}, "\n"),
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if findings, err := parseCLI2(test.output); err == nil {
				t.Fatalf("expected incomplete output error, got findings: %#v", findings)
			}
		})
	}
}

func TestHealthRunsMarkdownlintVersionProbe(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell fixture for Unix")
	}
	dir := t.TempDir()
	bin := filepath.Join(dir, "broken-markdownlint")
	if err := os.WriteFile(bin, []byte("#!/bin/sh\nexit 7\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := New(bin, "", 3*time.Second).Health(context.Background()); err == nil {
		t.Fatal("health must execute markdownlint instead of checking only its path")
	}
}
