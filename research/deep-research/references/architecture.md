# Architecture

## Decision

Use a progressive-disclosure Skill package rather than the requested flat tree. `SKILL.md` remains the orchestration layer; substantial shared rules live in `references/`; domain overlays, reusable records, and examples are nested by purpose. `agents/openai.yaml` supplies ChatGPT Work metadata. This minimizes default context while keeping every module directly discoverable from the entrypoint.

## Runtime flow

```text
User query
  -> Query interpreter
  -> Research planner and recursive tree
  -> optional persistent research-run bundle
  -> source-access layer
       -> built-in ChatGPT Search/Web (default)
       -> optional RedditAPI / GetXAPI / TinyFish adapters
       -> optional Chinese Hearthstone / Scrape.do ingestion
       -> primary sources
       -> statistics
       -> experts
       -> community
  -> Evidence collector
  -> Atomic claim extraction
  -> Evidence matrix
  -> Contradiction search
  -> Freshness/version validation
  -> Research database
  -> working structural and referential-integrity validation
  -> Adversarial Research Auditor
  -> output router
       -> Clarity Editor -> editor-ready document
       -> analytical research report
       -> explicit raw-research dossier
  -> final deterministic integrity/readability validation
  -> delivery and handoff
```

ChatGPT Search/Web is the built-in default discovery and source-access layer. The read-only adapter in `scripts/community_sources.py` optionally normalizes RedditAPI, GetXAPI, and TinyFish results into a provider-neutral envelope. Search snippets and provider results are never promoted directly into the evidence database. The collector relies on inspected source content and records access limitations.

For Chinese Hearthstone sources, `scripts/chinese_hearthstone.py` adds a dependency-free site-profile layer, content-aware Scrape.do escalation, deterministic deckstring/statistics/provenance extraction, Bilibili evidence normalization, and DBF resolution through `api.kolodahearthstone.com`. It produces ingestion records; it does not bypass the normal evidence collector, semantic audit, or final quality gate. Durable scheduling and database migrations remain host-application responsibilities.

## Layers and responsibilities

| Layer | Owns | Does not own |
|---|---|---|
| `SKILL.md` | activation, depth, output-profile routing, phase order, completion | detailed domain/source rules |
| shared protocols | search, provenance, verification, freshness, confidence, audit | domain-specific entities |
| domain adapters | source preferences, version axes, terminology, failure modes | duplicated core methodology |
| templates | working artifact schemas and profile-specific output shapes | one universal prose layout for every request |
| source adapter | optional read-only platform access, local rate gates, normalized provider records | source truth, posting, login, or credential storage |
| Chinese ingestion adapter | public CN source profiles, Scrape.do attempt ledger, deterministic Hearthstone extraction, card DB enrichment | scheduler, private access, final guide writing |
| research-run scripts | reproducible bundle initialization and referential-integrity validation | judging factual truth |
| validation | packaging audit and simulated acceptance evidence | runtime research |

## Artifact flow

1. The research plan fixes meaning and scope.
2. The query plan maps question-tree leaves to search families.
3. Source records preserve provenance and source-level metadata.
4. Evidence records capture exact support or challenge.
5. Claim records create falsifiable units.
6. The matrix tests authority, independence, contradictions, and confidence.
7. Community and contradiction reports preserve disagreement instead of flattening it.
8. The audit controls whether synthesis is allowed.
9. The output router selects an editor-ready, analytical, or explicitly raw template without changing the validated claims.
10. The Clarity Editor makes editorial output easy to understand while the evidence bundle remains the source of truth.
11. The final deterministic gate checks the routed artifact, its profile-specific requirements, hashes, citations, and handoff before delivery.

## Key engineering choices

- Source ranges guide effort but never define completion; branch saturation and quality gates do.
- Confidence is claim-level and categorical, because a single report-level score hides weak subclaims.
- “Research Auditor” is a role contract inside the workflow, not an assumed separate agent. The Skill works in environments without subagent support.
- Domain adapters refine claim authority and freshness without weakening universal evidence rules.
- Templates are Markdown working records so they remain tool-agnostic and can be used in chat or persisted as files.
- The core package has no external runtime dependency. Built-in ChatGPT Search/Web supplies network research; provider support is optional and degrades explicitly when credentials or the TinyFish CLI are unavailable.
- File-backed runs are optional. They are required only when persistence, resumability, raw evidence delivery, or cross-Skill handoff materially improves the task.
- Deterministic validators prove structure and provenance links, not whether a source is true; the Research Auditor retains that semantic responsibility.
- Research depth and output complexity are independent: exhaustive collection can still produce a concise `editor-ready` document.

## Extension rules

- Add a domain adapter only when source authority, version semantics, or validation failure modes genuinely differ.
- Add a protocol only when it has a distinct decision boundary and conditional load value.
- Keep each rule in one authoritative file; link rather than copy.
- Do not encode a one-off research finding as universal methodology.
- Preserve the invariant: validation and audit precede strong synthesis.

## Google Research integration decision

The [`google-research/google-research`](https://github.com/google-research/google-research) repository is a large collection of independent experiments, not a single production dependency. No code from it is vendored into this Skill.

- The [AIS](https://github.com/google-research-datasets/AIS) idea, “Attributable to Identified Sources,” is adopted methodologically through the existing Claim → Evidence → Source chain and semantic audit. Its archived annotation dataset may inform future evaluation cases, but it is not a runtime verifier.
- [BLEURT](https://github.com/google-research/BLEURT) evaluates whether generated text conveys a reference's meaning; it does not establish that a claim is factually supported. Its TensorFlow/model dependency would add weight without replacing the semantic auditor.
- [ScaNN](https://github.com/google-research/google-research/blob/master/scann/README.md) is for large-scale vector nearest-neighbor retrieval. Add it only after a measured evidence-corpus retrieval bottleneck justifies a platform-specific dependency; ordinary research bundles do not need it.

This decision preserves portability and makes factual support an explicit judgment rather than a similarity score.
