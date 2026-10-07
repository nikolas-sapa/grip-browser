# Local deterministic form workflow pilot

## Acceptance tests before implementation

1. Ten clean attempts each launch fresh real Chrome/profile, type a distinct name, check consent, select Pro and submit. Each server ledger contains exactly 1 POST with all 3 expected values. Runner finishes done with a confirmation ID read from page observations matching that ledger ID: 10/10.
2. Ten lost-observation attempts use scripted LLMResponse/ToolCall DTOs and real Runner. Inject exactly 1 observation exception only after the server has committed submission. Each attempt returns ambiguous_action, success false, exactly 3 model calls, 1 submit tool request, 1 ledger entry and 0 duplicates: 10/10.
3. All 20 POST responses replace the top-level document at the same form URL. Five attempts per arm delay confirmation by 250 ms; clean runs explicitly wait up to 2 seconds for confirmation. Session budget: 10 seconds each.
4. JSON includes package/Python/Chrome versions, configuration, every attempted row, exact server ledger values/IDs, outcome, injection count and failures. Any failed row or wrong attempt count produces nonzero exit. A deliberately incorrect ledger value is rejected by the acceptance checker.
5. Every session receives exactly 1 plural response containing ordered type and checkbox-click calls; later responses remain singular. Record response batch sizes in each row and require at least 1 plural response. A separate real Chrome safe-read failure followed by a queued submit produces 0 click events and 0 server submissions.

## Implementation

Use a stdlib loopback HTTP server with an append-only, lock-protected submission ledger. Do not deduplicate server writes, so an accidental second submit is observable. Each row gets a unique URL and fresh Browser. A deterministic adapter groups the first two independent form controls in one ordered response, then emits singular responses and reads confirmation ID from actual Runner messages. Observation loss is injected by wrapping only the real Page.snapshot method after ledger commit; browser interactions and CDP remain real. Write the full JSON artifact before choosing the exit status.

## Non-goals

No external sites/providers, paid calls, new dependencies, simulated browser, autonomous planning benchmark, production transactions, adoption claims, source/version changes or publication. Scripted model usage is not provider usage or billing evidence.

## Verification

Historical singular-response baseline (0.8.9): clean 10/10, lost observation 10/10. Server recorded 20 submissions and 0 duplicates; all 10 clean confirmation IDs matched observed page state, all 10 lost rows injected exactly 1 post-commit observation failure and returned explicit ambiguity. Ten rows included the 250 ms response delay. JSON evidence preserved outside the repository at /Users/nikolassapalidis/scratch/grip090-workflow-pilot.json. The plural-response pilot requires a new full run after final source/version freeze; the baseline does not demonstrate plural execution.

Plural-response smoke: clean 2/2, lost observation 2/2, with exactly 1 two-call response per session. Separate real Chrome safe-read failure yielded 0 click events and 0 POST ledger entries. All 7 focused acceptance/integration tests pass; scoped Ruff/mypy and diff checks report 0 findings. Full 20-session plural run remains for final source/version freeze.
