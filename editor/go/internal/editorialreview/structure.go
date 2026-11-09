package editorialreview

import (
	"crypto/sha256"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"
)

// StructureBlock is an inventory of source spans, not an inferred argument.
type StructureBlock struct {
	ID    string `json:"id"`
	Kind  string `json:"kind"`
	Quote string `json:"quote"`
}

type StructureAssignment struct {
	ArticleSHA256 string           `json:"article_sha256"`
	Blocks        []StructureBlock `json:"blocks"`
	Guidance      string           `json:"guidance"`
}

type StructureBlockCheck struct {
	ID             string   `json:"id"`
	Quote          string   `json:"quote"`
	Function       string   `json:"function"`
	NewInformation string   `json:"new_information"`
	LinkToPrevious string   `json:"link_to_previous"`
	DependsOn      []string `json:"depends_on"`
	RepeatOf       []string `json:"repeat_of"`
	RepeatReason   *string  `json:"repeat_reason"`
	Status         string   `json:"status"`
	Reason         string   `json:"reason"`
}

type StructureReview struct {
	ArticleSHA256  string                `json:"article_sha256"`
	ReaderQuestion string                `json:"reader_question"`
	MainAnswer     string                `json:"main_answer"`
	OrderReason    string                `json:"order_reason"`
	EndingReason   string                `json:"ending_reason"`
	Blocks         []StructureBlockCheck `json:"blocks"`
}

var (
	structureHeading     = regexp.MustCompile(`^ {0,3}#{1,6}(?:[ \t]+|$)`)
	structureList        = regexp.MustCompile(`^ {0,3}(?:[-+*]|[0-9]+[.)])[ \t]+`)
	structureFence       = regexp.MustCompile("^ {0,3}(`{3,}|~{3,})(.*)$")
	structureHTML        = regexp.MustCompile(`(?i)</?(?:p|h[1-6]|li|div|section|blockquote|figure|figcaption|table|tr|td|th|ul|ol)(?:[ \t\r\n][^>]*|/?)>`)
	structureHTMLHeading = regexp.MustCompile(`(?i)^<h[1-6][ \t\r\n/>]`)
	structureHTMLList    = regexp.MustCompile(`(?i)^<li[ \t\r\n/>]`)
)

// PrepareStructure keeps Markdown fences intact and retains every nonblank
// source span. No duplicate text or unconventional sequence is itself an error.
func PrepareStructure(text string) (*StructureAssignment, error) {
	if !nonempty(text) {
		return nil, fmt.Errorf("structure: nonempty article required")
	}
	result := &StructureAssignment{ArticleSHA256: fmt.Sprintf("%x", sha256.Sum256([]byte(text))), Blocks: []StructureBlock{}, Guidance: StructurePrompt()}
	cuts := map[int]bool{0: true, len(text): true}
	offset, fence := 0, ""
	for _, line := range strings.SplitAfter(text, "\n") {
		end := offset + len(line)
		plain := strings.TrimRight(line, "\r\n")
		match := structureFence.FindStringSubmatch(plain)
		if fence != "" {
			if match != nil && match[1][0] == fence[0] && len(match[1]) >= len(fence) && strings.TrimSpace(match[2]) == "" {
				cuts[end] = true
				fence = ""
			}
		} else if match != nil {
			cuts[offset] = true
			fence = match[1]
		} else if strings.TrimSpace(line) == "" {
			cuts[offset], cuts[end] = true, true
		} else {
			if structureHeading.MatchString(plain) {
				cuts[offset], cuts[end] = true, true
			} else if structureList.MatchString(plain) {
				cuts[offset] = true
			}
			for _, span := range structureHTML.FindAllStringIndex(line, -1) {
				cut := span[0]
				if strings.HasPrefix(line[span[0]:span[1]], "</") {
					cut = span[1]
				}
				cuts[offset+cut] = true
			}
		}
		offset = end
	}
	positions := make([]int, 0, len(cuts))
	for at := range cuts {
		positions = append(positions, at)
	}
	sort.Ints(positions)
	for i := 0; i+1 < len(positions); i++ {
		quote := strings.TrimSpace(text[positions[i]:positions[i+1]])
		if quote == "" {
			continue
		}
		kind := "text"
		switch {
		case structureFence.MatchString(strings.TrimRight(strings.SplitN(quote, "\n", 2)[0], "\r")):
			kind = "code"
		case structureHeading.MatchString(quote) || structureHTMLHeading.MatchString(quote):
			kind = "heading"
		case structureList.MatchString(quote) || structureHTMLList.MatchString(quote):
			kind = "list"
		}
		result.Blocks = append(result.Blocks, StructureBlock{ID: fmt.Sprintf("b%03d", len(result.Blocks)+1), Kind: kind, Quote: quote})
	}
	if len(result.Blocks) > 256 {
		return nil, fmt.Errorf("structure: more than 256 blocks; review cannot be truncated")
	}
	return result, nil
}

// ValidateStructure verifies coverage and evidence shape; acceptance must also
// reject HasUnresolvedStructure. Neither check decides whether prose is logical.
func structureText(s string) bool { return nonempty(s) && utf8.RuneCountInString(s) <= 3000 }

func ValidateStructure(text string, review *StructureReview) error {
	assignment, err := PrepareStructure(text)
	if err != nil {
		return err
	}
	if review == nil {
		return fmt.Errorf("structure_review: complete review required")
	}
	if review.ArticleSHA256 != assignment.ArticleSHA256 {
		return fmt.Errorf("structure_review: article_sha256 mismatch")
	}
	if !structureText(review.ReaderQuestion) || !structureText(review.MainAnswer) || !structureText(review.OrderReason) || !structureText(review.EndingReason) {
		return fmt.Errorf("structure_review: reader_question/main_answer/order_reason/ending_reason required")
	}
	if len(review.Blocks) != len(assignment.Blocks) {
		return fmt.Errorf("structure_review: whole article coverage required: expected %d blocks, got %d", len(assignment.Blocks), len(review.Blocks))
	}
	seen := map[string]bool{}
	for i, row := range review.Blocks {
		block := assignment.Blocks[i]
		if row.ID != block.ID {
			return fmt.Errorf("structure_review: block order/coverage mismatch at %s", block.ID)
		}
		if !nonempty(row.Quote) || !strings.Contains(block.Quote, row.Quote) {
			return fmt.Errorf("structure_review/%s: exact quote from this block required", row.ID)
		}
		if !structureText(row.Function) || !structureText(row.NewInformation) || !structureText(row.LinkToPrevious) || !structureText(row.Reason) {
			return fmt.Errorf("structure_review/%s: function/new_information/link_to_previous/reason required", row.ID)
		}
		if row.Status != "clear" && row.Status != "issue" && row.Status != "unverified" {
			return fmt.Errorf("structure_review/%s: invalid status", row.ID)
		}
		for field, refs := range map[string][]string{"depends_on": row.DependsOn, "repeat_of": row.RepeatOf} {
			if refs == nil {
				return fmt.Errorf("structure_review/%s: %s must be an array", row.ID, field)
			}
			unique := map[string]bool{}
			for _, ref := range refs {
				if !seen[ref] || unique[ref] {
					return fmt.Errorf("structure_review/%s: %s must reference unique earlier blocks", row.ID, field)
				}
				unique[ref] = true
			}
		}
		if row.RepeatReason == nil || (len(row.RepeatOf) > 0 && !structureText(*row.RepeatReason)) {
			return fmt.Errorf("structure_review/%s: repeat_reason required", row.ID)
		}
		seen[row.ID] = true
	}
	return nil
}

func HasUnresolvedStructure(review *StructureReview) bool {
	if review == nil {
		return true
	}
	for _, row := range review.Blocks {
		if row.Status != "clear" {
			return true
		}
	}
	return false
}

func StructurePrompt() string {
	return `STRUCTURE_REVIEW_V1: structure_assignment contains source blocks, not a proposed interpretation. Read every block in order and return structure_review: {article_sha256,reader_question,main_answer,order_reason,ending_reason,blocks:[{id,quote,function,new_information,link_to_previous,depends_on:[],repeat_of:[],repeat_reason,status:clear|issue|unverified,reason}]}. Cover each actual block exactly once in its actual order. quote must occur exactly inside that block. Explain what this block adds and how it follows the previous one; for the first explain its opening role. Headings, lists, code and captions also need their actual role, without inventing gameplay content. depends_on and repeat_of contain unique earlier block IDs only. A prerequisite introduced too late is an issue: describe the later block in reason; do not invent an earlier premise. Repetition is not automatically wrong: explain a declared reprise in repeat_reason and distinguish it from an unnecessary repeated argument. Check referents, conditions and exceptions before accepting a conclusion, and whether the ending answers the opening without a new unsupported premise. The four summary fields describe the actual reader question, answer, order and ending; do not impose a fixed genre skeleton or filler transition. issue/unverified is incompatible with accept; preserve a truthful negative review. Fields and quotes establish coverage, not semantic correctness.`
}
