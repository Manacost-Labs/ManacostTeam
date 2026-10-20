package pipeline

import (
	"context"
	"encoding/json"
	"reflect"
	"strings"
	"testing"

	"github.com/Manacost-Labs/EditorTeam/go/internal/rules"
)

const publicationCandidate = "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения. Совет может помочь. [Источник](https://example.org/guide)"
const publicationFact = `{"candidate_checked":true,"confidence_preserved":true,"unsupported_claims":[],"claims":[{"claim_id":"CLM-1","status":"supported","action_quote":"Сохраняйте ресурс","condition_quote":"при слабой позиции","exception_quote":"кроме угрозы поражения","confidence_quote":"может помочь","evidence_refs":["SRC-1"]}]}`

func TestWritingKeepsSemanticContextButSeparatesAuditFromAuthors(t *testing.T) {
	h := readyHandoff()
	h.Sources[0].ContentSHA256 = strings.Repeat("a", 64)
	h.Sources[0].ClaimSHA256, h.Sources[0].EvidenceSHA256, h.Sources[0].SourceSHA256 = strings.Repeat("b", 64), strings.Repeat("c", 64), strings.Repeat("d", 64)
	h.Sources[0].ClaimHashes = map[string]string{"CLM-1": strings.Repeat("e", 64)}
	h.Sources[0].SourceContext = map[string]any{"published_at": "2026-10-13", "updated_at": "2026-10-14", "fetched_at": "2026-10-19", "source_file_sha256": "source-hash", "article_text_sha256": "text-hash", "article_text_length": 23000, "pagination_complete": true, "metadata_basis": "transport bookkeeping", "custom_rule": map[string]any{"condition": "только при слабой позиции", "fetched_at": "unknown semantic container stays intact"}}
	h.Claims[0].ResearchContext = map[string]any{"confidence_basis": "условный совет", "temporal_limit": "объявленное расписание", "sample": map[string]any{"count": 30}, "inference_steps": []string{"ограниченный вывод"}, "source_limitations": []string{"не обобщать"}, "source_context": h.Sources[0].SourceContext}
	h.EditorialContext = map[string]any{"historical": true, "fetched_at": "2026-10-19", "custom_caveat": "сохранить исключение"}
	original, _ := json.Marshal(h)
	var full any
	_ = json.Unmarshal(original, &full)
	for _, stage := range []string{"writer", "repair", "fact", "critic"} {
		t.Run(stage, func(t *testing.T) {
			model := &fakeLLM{replies: []string{publicationCandidate}}
			s := New(model, nil, "fake")
			switch stage {
			case "writer":
				_, _ = s.rewrite(context.Background(), Request{Mode: "reconstruct", Handoff: h}, rules.RuleBundle{}, Analysis{}, nil)
			case "repair":
				_, _ = s.repairReconstruction(context.Background(), rules.RuleBundle{}, h, publicationCandidate, nil, nil, nil)
			case "fact":
				model.replies = []string{publicationFact}
				_, _ = s.factReview(context.Background(), h, publicationCandidate)
			case "critic":
				model.replies = []string{criticJSON("accept")}
				_, _ = s.critic(context.Background(), rules.RuleBundle{}, criticInput{Mode: "reconstruct", Source: h.VerifiedText(), Candidate: publicationCandidate, Handoff: h}, 1)
			}
			payload := lastUserJSON(t, model.messages[0])["research_handoff"].(map[string]any)
			if stage == "fact" || stage == "critic" {
				if !reflect.DeepEqual(full, payload) {
					t.Fatal("reviewer lost full audit/semantic evidence")
				}
			} else {
				source := payload["sources"].([]any)[0].(map[string]any)
				ctx := source["source_context"].(map[string]any)
				for _, key := range []string{"content_sha256", "claim_sha256", "evidence_sha256", "source_sha256", "claim_hashes"} {
					if source[key] != nil {
						t.Fatal("source audit field reached author", key)
					}
				}
				for _, key := range []string{"fetched_at", "source_file_sha256", "article_text_sha256", "article_text_length", "pagination_complete", "metadata_basis"} {
					if ctx[key] != nil {
						t.Fatal("acquisition metadata reached author", key)
					}
				}
				if ctx["published_at"] != "2026-10-13" || ctx["updated_at"] != "2026-10-14" || ctx["custom_rule"] == nil {
					t.Fatal("substantive dates or unknown context were stripped", ctx)
				}
				if ctx["custom_rule"].(map[string]any)["fetched_at"] == nil {
					t.Fatal("redaction escaped its exact known path")
				}
				claim := payload["claims"].([]any)[0].(map[string]any)
				rc := claim["research_context"].(map[string]any)
				for _, key := range []string{"confidence_basis", "temporal_limit", "sample", "inference_steps", "source_limitations"} {
					if rc[key] == nil {
						t.Fatal("semantic context lost", key)
					}
				}
				if rc["source_context"].(map[string]any)["fetched_at"] != nil {
					t.Fatal("nested audit fields leaked")
				}
				ed := payload["editorial_context"].(map[string]any)
				if ed["fetched_at"] != nil || ed["historical"] != true || ed["custom_caveat"] == nil {
					t.Fatal("editorial context boundary lost", ed)
				}
			}
			unchanged, _ := json.Marshal(h)
			if string(unchanged) != string(original) {
				t.Fatal("projection mutated the original handoff")
			}
		})
	}
}

func TestWritingFactualVetoStillBlocksLiteraryAcceptance(t *testing.T) {
	for _, field := range []string{"condition", "confidence", "unsupported", "schema"} {
		t.Run(field, func(t *testing.T) {
			candidate, fact := publicationCandidate, publicationFact
			switch field {
			case "condition":
				candidate = strings.ReplaceAll(candidate, "при слабой позиции", "")
			case "confidence":
				fact = strings.Replace(fact, `"confidence_preserved":true`, `"confidence_preserved":false`, 1)
			case "unsupported":
				candidate += " Это гарантирует победу."
				fact = strings.Replace(fact, `"unsupported_claims":[]`, `"unsupported_claims":["Это гарантирует победу."]`, 1)
			case "schema":
				fact = `{"claims":[]}`
			}
			writer := &fakeLLM{replies: []string{candidate}}
			s := New(writer, nil, "fake")
			s.Reviewer = &fakeLLM{replies: []string{fact, criticJSON("accept"), fact, criticJSON("accept"), fact}}
			result, err := s.Run(context.Background(), Request{Mode: "write", Handoff: readyHandoff()})
			if err != nil || result.Accepted || result.Text != "" || !strings.Contains(strings.Join(result.RejectionReasons, " "), "fact_review_failed") {
				t.Fatalf("fact veto bypassed: %+v %v", result, err)
			}
			if result.Attempts > MaxRepairs+1 {
				t.Fatal("repair limit increased")
			}
		})
	}
}

func TestPublicationProjectionPreservesExactSemanticNumbers(t *testing.T) {
	h := readyHandoff()
	h.Claims[0].ResearchContext = map[string]any{"sample": map[string]any{"exact_total": json.Number("9007199254740993")}}
	out, err := publicationHandoff(h)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(out)
	if !strings.Contains(string(raw), `"exact_total":9007199254740993`) {
		t.Fatal("semantic number rounded during audit projection", string(raw))
	}
}
