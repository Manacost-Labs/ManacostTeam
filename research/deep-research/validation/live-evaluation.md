# Live Evaluation Summary

Date: `2026-08-28`  
Version: `1.0.0`  
Tool: built-in ChatGPT Search/Web

The release oracle contains 20 persistent live runs across five domains plus two controlled adversarial runs:

| Domain | Cases | Coverage |
|---|---:|---|
| general | 4 | factual, current, comparative, community |
| software | 4 | current, comparative, statistical |
| Hearthstone | 4 | factual, strategic, exhaustive |
| World of Warcraft | 4 | current, statistical, factual, community |
| consumer | 4 | comparative and statistical buying decisions |
| adversarial fixtures | 2 | prompt injection and duplicate lineage |

Four expected `not_ready` results are successful safety outcomes: two evidence-incomplete Hearthstone tasks and two adversarial fixtures. Every mutable source in the benchmark has a verified local fingerprint, every critical claim is traceable, snippet evidence is zero, and the release validator recomputes these metrics from linked bundles.

Live failures led directly to protocol changes: overloaded-term disambiguation, evidence-class availability gates, chronological patch overlays, claim-level semantic audit, explicit community sampling limits, source fingerprinting, and false-ready blocking.

The detailed research bundles are shipped as a separate deterministic evaluation archive, not inside the runtime Skill archive.
