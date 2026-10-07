# Remote lifecycle cancellation completion

## Acceptance tests before implementation

1. Cancel remote connection during socket setup, permission setup and stealth setup after its websocket is live. After Browser.close, 0 owned receiver tasks and 0 open root sockets remain within 1 second. External Chrome remains alive; 1 subsequent connection succeeds.
2. Cancel open twice while a real Target.createTarget result is withheld. Creation completes exactly once; cancellation propagates after cleanup. Within 3 seconds of releasing the result, 0 created targets and 0 tracked pages remain. One independently created foreign target survives remote Browser.close.
3. Existing browser lifecycle, CDP disconnect and popup unit regressions pass. Ruff and mypy report 0 findings for changed files.
4. If the single creation command fails after caller cancellation, cancellation still propagates, 0 pages are registered and 0 cleanup commands guess a target identity.
5. A second concurrent open dispatches 0 target creations while remote permissions are pending. Cancelled __aenter__ cleans 0 remaining root sockets without explicit close. If disconnect fails, 1 incomplete connection remains owned and cannot be reused as ready; explicit close retries cleanup.

## Implementation

Keep remote setup serialized until permission/stealth setup completes. Failed or cancelled setup disconnects its engine to completion; retain failed-cleanup ownership with an incomplete marker so future opens cannot mistake it for readiness. Keep the single target creation command independently owned under caller cancellation, wait for its result under repeated cancellation, then register the exact returned target and use existing verified page cleanup before propagating cancellation.

## Non-goals

No inventory-based guessing of new targets, foreign-tab cleanup, retries, implicit reconnect, timeout increases, weakened guards, externally owned Chrome termination, dependencies, version changes or paid calls.
