package pipeline

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"

	"github.com/Manacost-Labs/EditorTeam/go/internal/analyzers"
	"github.com/Manacost-Labs/EditorTeam/go/internal/editorialreview"
	"github.com/Manacost-Labs/EditorTeam/go/internal/llm"
)

// A grounded negative owner judgment is feedback for repair, never a schema
// retry which asks the reviewer to replace the negative judgment with a pass.
func preserveOwnerRepair(out *criticResult) {
	if editorialreview.HasUnresolved(out.OwnerChecks) && out.Verdict == "accept" {
		out.Verdict, out.RepairRequired = "repair", true
	}
}

func (s *Service) deletionPass(ctx context.Context, candidate string, findings []analyzers.Finding) (string, *editorialreview.DeletionReceipt, error) {
	payload, _ := json.Marshal(map[string]any{"candidate": candidate, "article_sha256": fmt.Sprintf("%x", sha256.Sum256([]byte(candidate))), "tool_findings": findings})
	raw, err := s.complete(ctx, []llm.Message{{Role: "system", Content: editorialreview.DeletionPrompt}, {Role: "user", Content: string(payload)}})
	if err != nil {
		return candidate, nil, fmt.Errorf("deletion_pass: %w", err)
	}
	result, receipt, err := editorialreview.ApplyDeletion(candidate, raw)
	if err != nil {
		return candidate, nil, fmt.Errorf("deletion_pass: %w", err)
	}
	return result, receipt, nil
}
