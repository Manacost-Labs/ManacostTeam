// A native Windows entry point for the real npm CLI. Go's exec cannot launch
// npm's .cmd shim directly. No shell, argument rewriting, or result emulation.
package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

func run() int {
	exe, err := os.Executable()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	raw, err := os.ReadFile(exe + ".json")
	var cfg struct{ Node, Script string }
	if err == nil {
		err = json.Unmarshal(raw, &cfg)
	}
	if err != nil || !filepath.IsAbs(cfg.Node) || !filepath.IsAbs(cfg.Script) {
		fmt.Fprintln(os.Stderr, "markdownlint launcher requires absolute Node and Script paths:", err)
		return 2
	}
	cmd := exec.Command(cfg.Node, append([]string{cfg.Script}, os.Args[1:]...)...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		var failure *exec.ExitError
		if errors.As(err, &failure) {
			return failure.ExitCode()
		}
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	return 0
}

func main() { os.Exit(run()) }
