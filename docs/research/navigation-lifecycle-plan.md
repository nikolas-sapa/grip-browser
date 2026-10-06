# Navigation and browser lifecycle regression plan

## Test plan (before implementation)

1. Same-URL document replacement: 2 committed documents (CDP navigate/reload) share 0 refs; old ref raises STALE_REF; replacement button receives 0 clicks. Same-document hash navigation retains 1 existing ref.
2. Open failure/cancellation: connect, viewport, geolocation and goto each leave 0 extra Chrome page targets, 0 connected page sockets and 0 tracked pages after verified cleanup. Two cancellation requests during cleanup still complete target verification before disconnecting. Unverified target closure retains 1 tracked guarded page for retry.
3. Dead root transport: owned Chrome process exits and page/root sockets close within 8 seconds; 1 repeated close succeeds. Remote inventory failure keeps 1 root socket connected and preserves retry ownership.
4. After verified owned process death, 0 autoattach-disable requests are sent to the exited browser. Existing owned-popup termination tests must prove exit before disconnect; remote late-attach refusal remains unchanged.

## Implementation plan

1. Add unit failure reproductions and real Chrome lifecycle regressions, run red.
2. Reset ref assignments on main-frame full navigation commits, preserving monotonic ref numbering and same-document identities.
3. Register newly created pages before setup, include all setup stages in failure cleanup, shield cleanup to completion under repeated cancellation.
4. Recover owned inventory failure using existing verified process shutdown; disconnect retained page sockets only after owned process death is verified.
5. Run focused tests, lint and typing checks; hand off diff for review.

## Non-goals

No public APIs, dependencies, model calls, runner behavior changes, navigation policy changes, or unrelated refactors.
