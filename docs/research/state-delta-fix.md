# State-delta correctness milestone

## Acceptance tests

1. Thirty bounded state fixtures: 30 correct changed observations, zero false
   `no change` deltas for snapshot-visible state transitions. Cover both directions
   for boolean state, value clearing, selection, expanded comboboxes, options,
   canvas dimensions, visible identity, additions and replacements.
2. Unchanged elements: zero changed entries; coordinate-only changes: zero changed
   entries, because coordinates are not part of the rendered snapshot contract.
3. Real headless Chrome: checkbox, value, disabled, native selection and expanded
   combobox transitions survive DOM discovery, snapshot building and payload
   rendering. Each changed snapshot must set `changed_from_previous`; the next
   unchanged snapshot must clear it. Zero skipped browser acceptance checks.
4. Existing delta/summarizer and unit suites: zero regressions attributable to this
   change. Report failures and skipped checks explicitly.

## Implementation

Compare the information already visible in a full snapshot, rather than only
`Element.text`. Reuse the snapshot state suffix renderer for changed and added
elements. Keep the public `SnapshotDelta.changed` tuple shape and text-only
changes compatible. Preserve navigation, baseline and size fallback guards.

## Non-goals and limits

No provider serialization, tool arguments, termination, usage accounting,
benchmark claims, release or deployment. No new DOM state extraction. Metadata,
hrefs, geometry and state hidden by the existing full-snapshot renderer are outside
this milestone. Existing option preview caps and value formatting remain; this
fix does not claim complete DOM-state equality. Existing ambiguous-document
heuristics may select a full snapshot instead of a delta.

## Verification

Verified against current upstream base `9bf3650` on Python 3.14 with isolated
development tooling and cached Chrome for Testing.

- Original delta module loaded only inside a separate pytest process (checkout
  untouched): 51 failures, 23 passes across the new and existing delta fixtures
  plus six browser cases. All six browser cases failed against original code.
  This independently reproduces text-only detection and state omission from output.
- Fixed implementation: 541 unit tests pass, no skips; coverage 87.59%, above
  repository's 80% gate. The thirty bidirectional visible-state fixtures pass.
- Six real Chrome cases pass: checked, input value, disabled, native select value,
  ARIA selected and combobox expanded. Each checks reversals, actual transmitted
  delta payloads, unchanged content and a subsequent unchanged snapshot. Input
  value also changes the existing accessible label; other cases preserve text.
- Combined state, interaction and native-select browser run: 25 tests pass,
  no skips, in 49.40 seconds.
- Label/state collision regression passes: literal label `Control (checked)` is
  distinct from checked label `Control`. Additions and replacement tests preserve
  state, while unchanged and non-rendered transitions stay empty.
- Repository lint and changed-test lint pass; changed production module passes
  strict mypy with dependency diagnostics suppressed. Full repository mypy reports
  three pre-existing errors in `grip/adapters/anthropic.py`, independently observed
  before this fix (optional import typing and native provider request shape).
- Python specialist review completed; no remaining behavior findings.

Full integration/gripsearch suite and multi-version Python matrix are not run
locally. No paid API calls, release, merge or production deployment performed.
Next separate milestone: provider-specific serialization, starting with Anthropic.
