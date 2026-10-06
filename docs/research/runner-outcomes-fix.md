# Runner outcomes and ambiguous actions

## Test plan (before implementation)

- `test_terminal_outcome_policy`: 12 bounded terminal fixtures, exact outcome/data/success (done True, model text None, failures False); cancellation propagates, timeout <1s, no timeout or exhaustion success.
- `test_invalid_tool_schema_never_dispatches`: at least 12 missing/unknown/type-invalid argument fixtures, zero dispatches and action_error outcome.
- `test_mutation_failure_never_replays`: 20 injected side-effect/observation failures, exactly 1 mutation attempt, exactly 1 model call, ambiguous_action outcome, no retry instruction or second submission.
- Existing strict JSON fixtures: every non-JSON argument still raises ValueError before action, 0 dispatches.
- Read-only semantic recovery may continue; no mutation-method exception alone proves a safe retry.

## Non-goals

Provider adapters, usage accounting, parallel execution, new browser features, releases, and automatic retries of uncertain actions.

## Implementation plan

Add optional RunResult outcome/error/success fields, preserve terminal model text with unverified success (None), validate published tool argument schemas before dispatch, separate mutation and observation failures, terminate conservative ambiguous failures, preserve cancellation propagation.

## Verification

Before implementation: 47 failures, 34 passes (cancellation already propagated).
Fixtures: 12 terminal policies, 16 invalid-schema cases, 20 mutation/observation failures, plus 1 secret-containing exception probe. Existing JSON tests remain fail-before-action.

No model text response alone proves completion: model_text preserves data, success stays None. Only explicit done sets success True.

Transport failures during mutation are conservative ambiguous_action, including failures inside Page settling. Successful mutation followed by snapshot/payload failure records that mutation completed, and terminates without a retry instruction. Mutation-method exceptions always terminate ambiguous; no error-type allowlist proves events were absent. Read-only semantic failures retain recovery.

Security review: custom select may open its dropdown before a semantic stale/ambiguous-option failure. All select errors terminate ambiguous conservatively. Two additional partial-select fixtures prove one dropdown opening and one model request. No click/type/select method exception is considered proven safe to replay.

Scoped verification: 87 Runner tests pass; native OpenAI/Anthropic plus Runner totals 110 tests. Ruff and scoped mypy pass. No paid API calls.

Python review root cause: ELEMENT_STALE conflates pre-event handle failures with post-event value mismatch and missing CDP results. Removed mutation error-type recovery entirely. Three actual Page.type path regressions inject value_mismatch, missingvalue, and exceptionDetails after an input attempt; each must perform exactly one Runtime.evaluate and one model call. Before removing allowlist: all three failed.
