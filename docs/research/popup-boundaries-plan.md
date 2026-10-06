# Remaining popup policy boundaries

## Acceptance tests (before implementation)

1. Private access flag independence: Browser(allow_private=True, allow_popups=False) closes one trusted new-window popup within 2 seconds, records one refusal, receives 0 child HTTP requests, leaves opener usable. With allow_popups=True, one popup remains usable and queue records its opener.
2. Private-access Fetch enforcement: policy permits one localhost Document request while still failing one cloud-metadata Document/XHR/Fetch URL and one disallowed file/scheme URL. Metadata fixture uses intercepted transport only, 0 real metadata requests.
3. Existing guarded popup tests: 0 regressions across paused closure, forged globals, cancellation and remote teardown refusal.
4. Opt-in target interception: 64 flag/URL combinations retain identical policy decisions. Two child sessions using identical Fetch request IDs produce 0 cross-session responses. Forbidden Document, XHR, Fetch, redirect, nested popup and initial iframe URLs produce 0 HTTP receipts; permitted localhost produces >=1 receipt. Setup failure produces 0 debugger resumes. Persistent interception protects named-window reuse.
5. Teardown: all guarded descendants close before browser detach; cancellation produces 0 unguarded children.
5. Full validation: unit coverage >=80%, 0 Ruff findings, 0 strict typing errors, offline real Chrome suite and Python 3.11–3.14 CI pass.

## Implementation

First remove the allow_private early-return gates from popup and Fetch setup. Private address permission does not authorize metadata, file schemes or new windows. Keep existing policy.check decisions unchanged. Add exact-session event subscriptions to CDPEngine. Register child ownership and Fetch handlers before enabling interception and resuming debugger. Recursively auto-attach OOPIF descendants on each exact child session, arming their own Fetch domain before resume; popup-root interception alone missed post-load OOPIF XHR/Fetch in the real Chrome negative control. Security setup is lock-protected and ready only after CDP acknowledgement; failure/cancellation removes provisional listeners and retry re-arms. Keep interception for the child lifetime, including reused named windows. Close every owned child while guard connection remains alive; remote detach requires verified target absence.

## Non-goals

No paid API runs, vendor/dependency changes, DNS pinning, WebSocket egress promises, global JavaScript monkey-patch as a security boundary, or changes to user navigation permissions. Multiple-call execution requires a separate execution-semantics choice.

## Protocol evidence and limits

Real Chrome tests cover initial opener-written iframe, nested popup, Document/XHR/Fetch and named reuse. Initial popup `javascript:` executes after resume without a Fetch event, while Target.attachedToTarget reports an empty URL. Per-session interception cannot prevent that non-network execution. A meaningful initial URL is checked before resume; this is not a guarantee for empty-URL javascript targets. No asynchronous stopLoading race or JavaScript override is used as a security boundary. Direct Page wrappers with known target identity refuse pre-existing related children before mutation, because those children did not receive the wrapper's policy.

## Lifecycle acceptance (before implementation)

1. Managed main target closure and validated target inventory establish absence within 2 seconds before its Page engine disconnects.
2. A closer failure or cancelled closer produces 0 disconnects, preserves guard callbacks and permits retry.
3. A failed main OOPIF guard records its originating Page engine, never sends that session through the browser connection, and teardown either terminates owned Chrome or verifies main target/frame absence on remote Chrome before disconnect.
