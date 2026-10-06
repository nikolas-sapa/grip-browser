# Multiple-call execution decision

Current behavior: providers request one call; multiple returned calls fail explicitly. Choice requested before changing Runner/provider replay architecture.

## Acceptance tests for sequential execution (before implementation)

1. Three installed provider wire fixtures, each with three model turns and five calls: exactly five dispatches, three usage records and five matching results. Gemini native signature bytes and absent native IDs unchanged.
2. Eighteen uncertainty fixtures (click/type/select, three failure timings, two batch positions): one attempted mutation, zero remaining actions, zero later model requests, ambiguous_action result.
3. Eight preflight fixtures (malformed arguments, duplicate IDs, invalid done placement): zero dispatches for every rejected batch.
4. Budget fixtures with max_steps=3: never more than three dispatches or three model requests; oversized batch executes zero calls.
5. Real Chrome type/click/done fixture: exactly one form submission, expected typed value and truthful terminal result.
6. Existing single-call, cancellation, usage, trace redaction and popup tests: zero regressions.

## Options

- Sequential returned order: additive tool_calls representation, whole-batch validation before dispatch, one done only last, stop batch after any error, end run after uncertain mutation. Count usage once per response. Each provider receives complete matching results, including explicit not-executed results for skipped calls. Preserve singular tool_call compatibility. Snapshots after mutations preserve current reference checks; no automatic retargeting.
- Retain single-call contract: keep existing request constraints and explicit multiple-call rejection; no API/replay change.

## Non-goals

No concurrent dispatch, rollback, automatic mutation retries, dependency inference, reference rewriting, new tools, model/dependency changes or paid provider calls. Implementation awaits execution-policy choice.
