# Software Domain Adapter

Load for libraries, SDKs, APIs, tools, platforms, architecture comparisons, and implementation guidance.

## Required context

Record exact product/library name, version or commit, runtime/language, operating system, deployment target, date, and whether the question concerns stable, beta, preview, or deprecated behavior.

## Source routing

- API and behavior: current official documentation and versioned reference.
- Changes: release notes, changelog, migration guide, and source control diff or issue when authoritative.
- Bugs: official issue tracker, minimal reproduction, maintainers, and version-specific confirmation.
- Security: vendor advisory, CVE/NVD where relevant, maintainer patch, and primary technical analysis.
- Performance: reproducible benchmark with environment, workload, warm-up, versions, and variance.
- Recommendations: official constraints plus current practitioner evidence and maintenance/ecosystem facts.

Use ChatGPT Search/Web for current documentation discovery when local project or installed code does not establish the version. Prefer official technical sources for technical claims.

## Frequent failure modes

- using latest docs for an older installed version;
- relying on SEO tutorials or generated examples instead of primary documentation;
- confusing deprecated-but-working with supported;
- treating a GitHub issue proposal as released behavior;
- comparing benchmarks with different workloads or hardware;
- citing package popularity as proof of fitness or security;
- presenting an unreleased branch, preview, or roadmap as generally available.

## Freshness

Compare source version with target version. For rapidly changing SDKs and hosted APIs, verify current docs and release notes even when the source is recent. Record deprecations, migration boundaries, and effective rollout state.
