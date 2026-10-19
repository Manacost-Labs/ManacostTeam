// Windows adapter for MinGW Hunspell: explicit UTF-8 input and a dictionary
// basename in its directory. The engine rejects drive-letter dictionary paths.
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
	var cfg struct{ Binary string }
	if err == nil {
		err = json.Unmarshal(raw, &cfg)
	}
	if err != nil || !filepath.IsAbs(cfg.Binary) {
		fmt.Fprintln(os.Stderr, "hunspell launcher requires an absolute Binary path:", err)
		return 2
	}
	args := append([]string{"-i", "UTF-8"}, os.Args[1:]...)
	directory := ""
	for index := 2; index+1 < len(args); index++ {
		if args[index] == "-d" && filepath.IsAbs(args[index+1]) {
			directory = filepath.Dir(args[index+1])
			args[index+1] = filepath.Base(args[index+1])
			break
		}
	}
	cmd := exec.Command(cfg.Binary, args...)
	cmd.Dir = directory
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
