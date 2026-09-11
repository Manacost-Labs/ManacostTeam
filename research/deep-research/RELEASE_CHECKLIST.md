# Release Checklist

## Required for every local release

- `VERSION` and changelog entry agree.
- `python3 scripts/audit_skill.py` passes.
- `python3 -m unittest discover -s tests -p 'test_*.py' -v` passes.
- A representative `editor-ready` document passes `python3 scripts/validate_editor_output.py FILE` without blocking errors.
- A persistent `editor-ready` bundle records a passing post-edit preservation review for claims, numbers, scope, citations, limitations, and contradictions.
- Any Russian Hearthstone sample uses exact KHS Russian names for resolved entities, leaves missing localization explicit, and resolves avoidable anglicism warnings.
- Official Skill package validation passes.
- At least one representative final research bundle passes validation.
- Semantic gold evaluation passes at 95% or higher with zero P0 failures.
- Benchmark release results are derived from linked bundles and pass tamper-resistant validation.
- README states the built-in ChatGPT Search/Web boundary.
- `LICENSE` records the explicit distribution decision.
- No placeholder, credential, session data, or uninspected citation is packaged.
- Installed copy matches the validated workspace package.
- Release archives are deterministic and the SHA-256 manifest matches their bytes.

## Required before 1.0.0

- Cross-domain live benchmark beyond Hearthstone.
- Source snapshot or content-fingerprint policy validated on mutable pages.
- Larger adversarial citation/semantic-support evaluation.
- Explicit licensing decision.
- Operational `resume`, `compare`, `export`, and `release` commands verified.
