# Popup routing correction

## Test plan

1. Trusted `window.open` under default policy: exactly one blocked event,
   popup closed within two seconds, zero HTTP requests to local receiver.
2. Opt-in: exactly one PopupInfo within two seconds, live target readable,
   zero blocked events.
3. Two managed openers: exactly one popup routed to each, no cross-talk.
4. Unmanaged/no-opener targets: exactly one resume per attach; managed
   Browser.open completes within three seconds after auto-attach is armed.
5. Repeated arming installs one listener; teardown leaves zero background tasks.
6. Existing worker/OOPIF handling remains passing.
7. Trusted window.open returns within three seconds and the next opener command
   returns within one second. Popup JavaScript marker remains zero.
8. Any guard setup failure sends zero debugger resumes and records one failure.

## Implementation

Page websocket auto-attach does not deliver popup targets in real Chrome.
Browser websocket auto-attach does, paused before execution. Arm page-target
auto-attach on Browser, route managed opener IDs to Page's existing handler,
and use that browser connection for its popup session commands. Resume unrelated
targets immediately. Retain Page websocket handling for workers and OOPIFs.

Closing a debugger-paused popup wedges Chrome's opener execution. Blocking every
URL with Network.setBlockedURLs was falsified by a trusted Input fixture: the
receiver saw two requests. A matched offline guard prototype completed ten
trusted clicks with zero requests and a responsive opener.

Offline was also falsified: an opener writing an iframe into the popup produced
two HTTP requests. Scoped Fetch alone intercepted a frame while the popup stayed
alive but lost protection as Target.closeTarget disposed its session before the
opener WindowProxy closed. These guard-and-resume candidates are rejected.

The verified replacement disables child JavaScript, then calls native window
close while the child is still debugger-paused. Require window.closed === true,
never resume the default-policy child. Six real Chrome variants (blank content,
new named window, noopener, javascript, data, HTTP) acknowledged closure, produced
zero script executions and zero requests, and left later opener commands usable.
Chrome loses the originating command response in this path, so a narrowly marked
mutation receives a typed popup refusal within two seconds rather than waiting
out the CDP timeout. No other pending command is interrupted.

Final acceptance: all six variants, zero requests/child scripts, originating
action refusal within two seconds, later command within one second, zero pending
commands and background tasks. Guard/close failure never resumes the child and
records a sanitized failure.

## Non-goals

No click gesture change, child Page API, opt-in Fetch interception, multiple
tool-call execution, or protocol fallback. Existing allow_private bypass remains.
Named-window reuse does not create a target and is outside auto-attach coverage.

Teardown regression plan: late attach during page close must yield zero detach/resume operations for an unresolved remote child; owned Chrome must terminate before detach. Register unresolved targets synchronously before task scheduling. Cancelling teardown cancels zero security closures, preserves pending target evidence, and permits a later close retry. Final attachment-event barrier precedes the second unresolved-target check.

Before releasing debugger pauses, owned Chrome terminates. Remote teardown requires a valid target inventory proving all managed openers and blocked children absent. Attachments delivered during auto-attach shutdown drain without cancellation; unresolved closure retains the connection and raises. Native closure runs in a fresh isolated world, so page replacements of `window.close` or `window.closed` cannot forge its result.
