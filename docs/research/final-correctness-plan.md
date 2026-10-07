# Final correctness pass

## Acceptance tests before implementation

1. Each new code defect has at least one failing regression on 0.8.8 and zero failures after its fix. No speculative fixes.
2. All unit tests pass with coverage >=80%; all offline integration/gripsearch tests pass. Ruff and strict mypy produce zero findings. Python 3.11–3.14 CI passes before merge.
3. Independent Python and security review report zero blockers for code changes. Real Chrome checks cover affected browser paths.
4. README token claims explicitly identify historical observation estimates and distinguish Trace.total_tokens from measured provider usage. Historical measurement artifacts remain preserved, with no claim of current comparative superiority.
5. One repeatable form workflow and a matched comparison protocol name independent success checks, pinned versions, total model usage and failure accounting. Zero paid calls or invented external adoption results.
6. Merged tree matches reviewed head; production Ready on exact merge SHA and live URL HTTP 200. SDK publication, if source changes, matches the merged source and installed version.

## Implementation sequence

Run bounded independent audits of Runner/provider, browser lifecycle and CLI/config seams. Reproduce reported defects and fix by dependency, assigning disjoint ownership. Correct misleading documentation in parallel. Prepare workflow/comparison protocol. Freeze source, verify and review, then commit/push via PR and verify release.

## Architecture gate

Multiple tool calls require an explicit execution-policy choice, requested separately. Do not change Runner/provider replay architecture until that answer arrives. Keep current single-call behavior otherwise.

## Non-goals

No arbitrary feature parity, cloud/vendor/dependency migration, paid provider calls, external outreach, external user-adoption claims, concurrent batch execution, retries of uncertain mutations or weakened guards.
