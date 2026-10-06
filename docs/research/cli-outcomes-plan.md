# CLI run failure propagation

## Acceptance tests (before implementation)

1. Four unsuccessful Runner outcomes (`step_limit`, `llm_timeout`, `action_error`, `ambiguous_action`), each in text and JSON mode: 8/8 CLI invocations return exit code 1, print their outcome on stderr, and close Browser exactly once.
2. Successful `done` and unverified `model_text`, each in text and JSON mode: 4/4 retain exit code 0 and current stdout data shape, with 0 stderr diagnostics. `model_text` remains unverified, not a completion guarantee.
3. All 12 cases use the actual RunResult class. JSON output parses as exactly the existing data payload, with 0 additional envelope fields.
4. Actual Chrome CLI `open about:blank`: exit code 0 and valid JSON snapshot output, with 0 provider requests.
5. Existing CLI tests: 0 regressions; Ruff and strict mypy: 0 findings.

## Implementation

After emitting existing result data, return EXIT_RUNTIME_ERROR and a generic outcome diagnostic when RunResult.success is False. Preserve success and unknown-result behavior. Document failure exit behavior and unverified model text. No raw page error details are added to diagnostics.

## Non-goals

No JSON envelope change, new flags, navigation timeout redesign, new provider requests, credentials changes, retry behavior or multi-call execution.
