#!/usr/bin/env python3
"""Audit the deep-research Skill package without external dependencies."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED = {
    "CHANGELOG.md",
    "LICENSE",
    "RELEASE_CHECKLIST.md",
    "VERSION",
    "SKILL.md",
    "README.md",
    "agents/openai.yaml",
    "scripts/audit_skill.py",
    "scripts/community_sources.py",
    "scripts/chinese_hearthstone.py",
    "scripts/hearthstone_names.py",
    "scripts/init_research_run.py",
    "scripts/validate_editor_output.py",
    "scripts/validate_research_run.py",
    "scripts/validate_benchmark.py",
    "scripts/generate_benchmark_results.py",
    "scripts/research_ops.py",
    "scripts/search_support.py",
    "scripts/plan_queries.py",
    "scripts/search_coverage.py",
    "scripts/fetch_source.py",
    "scripts/registry_seed.py",
    "scripts/candidates.py",
    "scripts/validate_recall.py",
    "scripts/model_trial.py",
    "scripts/lineage_suggest.py",
    "scripts/freshness_check.py",
    "references/domains/hearthstone-sources.json",
    "references/domains/hearthstone-patches.json",
    "tests/test_search_tools.py",
    "tests/test_research_run.py",
    "tests/test_editor_output.py",
    "tests/test_benchmark.py",
    "tests/test_research_ops.py",
    "tests/test_community_sources.py",
    "tests/test_chinese_hearthstone.py",
    "tests/test_hearthstone_names.py",
    "references/architecture.md",
    "references/research-protocol.md",
    "references/source-policy.md",
    "references/search-strategy.md",
    "references/evidence-protocol.md",
    "references/editor-output.md",
    "references/verification.md",
    "references/contradiction-search.md",
    "references/community-intelligence.md",
    "references/chinese-hearthstone.md",
    "references/source-providers.md",
    "references/freshness-policy.md",
    "references/confidence-system.md",
    "references/quality-gate.md",
    "references/output-policy.md",
    "references/research-operations.md",
    "references/research-bundle.md",
    "references/web-safety.md",
    "references/domains/general.md",
    "references/domains/gaming.md",
    "references/domains/hearthstone.md",
    "references/domains/world-of-warcraft.md",
    "references/domains/software.md",
    "references/templates/research-plan.md",
    "references/templates/query-plan.md",
    "references/templates/source-record.md",
    "references/templates/evidence-record.md",
    "references/templates/editor-ready.md",
    "references/templates/evidence-appendix.md",
    "references/templates/useful-data.md",
    "references/templates/claim-record.md",
    "references/templates/evidence-matrix.md",
    "references/templates/community-consensus.md",
    "references/templates/contradiction-report.md",
    "references/templates/audit-report.md",
    "references/templates/final-research.md",
    "references/templates/raw-research.md",
    "references/templates/handoff.md",
    "references/examples/gaming-research.md",
    "references/examples/general-research.md",
    "references/examples/chinese-hearthstone-config.json",
    "references/examples/family-map-hearthstone.json",
    "tests/fixtures/chinese/17173_multi_deck.html",
    "tests/fixtures/chinese/bilibili_video.json",
    "tests/fixtures/chinese/gamersky_repost.html",
    "tests/fixtures/chinese/iyingdi_cn_meta.html",
    "validation/acceptance-tests.md",
    "validation/self-audit.md",
}

LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def main() -> int:
    errors: list[str] = []
    markdown_files = set(ROOT.rglob("*.md"))
    link_graph: dict[Path, set[Path]] = {path: set() for path in markdown_files}

    for relative in sorted(REQUIRED):
        if not (ROOT / relative).is_file():
            fail(f"missing required file: {relative}", errors)

    skill_path = ROOT / "SKILL.md"
    if skill_path.is_file():
        skill = skill_path.read_text(encoding="utf-8")
        if not skill.startswith("---\n"):
            fail("SKILL.md has no YAML frontmatter", errors)
        if "name: deep-research" not in skill:
            fail("SKILL.md name does not match folder", errors)
        if not re.search(r"^description:\s+\S", skill, re.MULTILINE):
            fail("SKILL.md has no description", errors)

    version_path = ROOT / "VERSION"
    changelog_path = ROOT / "CHANGELOG.md"
    readme_path = ROOT / "README.md"
    if version_path.is_file():
        version = version_path.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            fail("VERSION is not semantic x.y.z", errors)
        if changelog_path.is_file() and f"## {version} —" not in changelog_path.read_text(encoding="utf-8"):
            fail("CHANGELOG has no entry matching VERSION", errors)
        if readme_path.is_file() and f"Current package version: `{version}`" not in readme_path.read_text(encoding="utf-8"):
            fail("README current version does not match VERSION", errors)

    yaml_path = ROOT / "agents/openai.yaml"
    if yaml_path.is_file():
        ui = yaml_path.read_text(encoding="utf-8")
        if "$deep-research" not in ui:
            fail("default_prompt does not invoke $deep-research", errors)

    for path in sorted(markdown_files):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\b(TODO|TBD|FIXME)\b", text):
            fail(f"unfinished marker in {path.relative_to(ROOT)}", errors)
        for target in LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "#")):
                continue
            clean = target.split("#", 1)[0]
            if not clean:
                continue
            resolved = (path.parent / clean).resolve()
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                fail(f"link escapes package in {path.relative_to(ROOT)}: {target}", errors)
                continue
            if not resolved.exists():
                fail(f"broken link in {path.relative_to(ROOT)}: {target}", errors)
            elif resolved.is_file() and resolved.suffix == ".md":
                link_graph[path].add(resolved)

    reachable: set[Path] = set()
    pending = [ROOT / "SKILL.md", ROOT / "README.md"]
    while pending:
        current = pending.pop()
        if current in reachable or current not in markdown_files:
            continue
        reachable.add(current)
        pending.extend(link_graph[current] - reachable)

    for path in sorted(markdown_files - reachable):
        fail(f"Markdown resource is not discoverable: {path.relative_to(ROOT)}", errors)

    for path in sorted(ROOT.rglob("*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            fail(f"invalid Python in {path.relative_to(ROOT)}: {exc}", errors)

    if errors:
        print("Skill audit: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "Skill audit: PASS "
        f"({len(REQUIRED)} required files; internal links valid; "
        f"{len(markdown_files)} Markdown files discoverable; Python syntax valid)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
