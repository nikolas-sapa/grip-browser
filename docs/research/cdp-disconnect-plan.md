# CDP explicit-disconnect completion

## Acceptance tests before implementation

1. Three in-flight root/child-session commands with 30-second defaults fail within 0.25 seconds after explicit disconnect; 0 pending futures remain. No command retries or success results.
2. While socket close is held open, one new command is rejected before websocket send: 0 sends. Disconnect finishes when close is released.
3. Existing actual Chrome owned shutdown with a guarded popup and a disconnected root completes within the existing 8-second bound, with 0 owned processes and 0 connected page sockets. Ten consecutive runs have 0 failures.
4. All engine, popup and cancellation unit regressions pass; Ruff/mypy have 0 findings. Existing clean-disconnect receiver cancellation remains cancellation, not a reported renderer crash.

5. A command cancelled while websocket send is blocked after disconnect leaves 0 unhandled future exceptions; cancellation still propagates.

## Implementation

Mark disconnect in progress before cancelling the receiver. Reject existing command futures with fresh connection-disconnected exceptions and clear pending bookkeeping. Reject new commands during close. Reset the closing marker after a successful new connection. Preserve existing socket-close ordering and browser target/process verification requirements.

## Non-goals

No timeout increases, command retries, weakened guards, implicit reconnect, changed renderer-crash reporting or paid calls.
