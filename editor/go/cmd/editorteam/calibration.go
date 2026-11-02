package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"unicode/utf8"

	"github.com/Manacost-Labs/EditorTeam/go/internal/pipeline"
)

func calibrateCritic(ctx context.Context, args []string, service *pipeline.Service) error {
	flags := flag.NewFlagSet("calibrate-critic", flag.ContinueOnError)
	packetPath := flags.String("packet", "", "blind packet JSON")
	output := flags.String("output", "", "new local JSON report path")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if *packetPath == "" || *output == "" || flags.NArg() != 0 {
		return fmt.Errorf("usage: editorteam calibrate-critic --packet blind.json --output reviews.json")
	}
	raw, err := os.ReadFile(*packetPath)
	if err != nil {
		return err
	}
	if !utf8.Valid(raw) {
		return fmt.Errorf("packet must be UTF-8")
	}
	var packet pipeline.CalibrationPacket
	if err = json.Unmarshal(bytes.TrimPrefix(raw, []byte{0xef, 0xbb, 0xbf}), &packet); err != nil {
		return fmt.Errorf("blind packet: %w", err)
	}
	if _, err = os.Lstat(*output); err == nil {
		return fmt.Errorf("output already exists: %s", *output)
	} else if !os.IsNotExist(err) {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(*output), ".critic-calibration-*.json")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	defer tmp.Close()
	report, err := pipeline.CalibrateCritic(ctx, service, packet)
	if err != nil {
		return err
	}
	report.PacketSHA256 = fmt.Sprintf("%x", sha256.Sum256(raw))
	enc := json.NewEncoder(tmp)
	enc.SetIndent("", "  ")
	if err = enc.Encode(report); err != nil {
		return err
	}
	if err = tmp.Close(); err != nil {
		return err
	}
	// Publish only complete results, and never replace an existing report.
	return os.Link(tmp.Name(), *output)
}
