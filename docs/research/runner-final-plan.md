# Final Runner correctness fixes

## Acceptance tests

1. Hover dispatch raises a typed or ordinary error after an attempted pointer
   event: exactly 1 hover attempt and 1 model call, outcome `ambiguous_action`,
   success false, and a no-repeat diagnostic.
2. Hover returns successfully but the following snapshot or payload raises:
   exactly 1 hover attempt and 1 model call, outcome `ambiguous_action`, success
   false, and an observation-failure diagnostic.
3. Native OpenAI SDK roundtrip captures exactly 2 requests and 1 click; second
   request preserves exact first-response assistant text (or null), native call
   ID, JSON arguments, and matching result ID. Both requests contain
   `parallel_tool_calls: false`; each response reports 10 tokens, producing
   exactly 20 measured tokens, 2 model calls, and complete usage accounting.
4. Existing Runner, usage, adapter, and OpenAI wire tests all pass; Ruff and
   scoped mypy report 0 errors on modified production files.

## Implementation

Include hover in Runner's existing mutation branch, preserving separate action
and observation uncertainty diagnostics. Preserve native OpenAI assistant text
alongside tool calls instead of replacing it with null. Exercise native SDK
serialization through an intercepted HTTP transport without external requests.

## Non-goals

Multiple-tool DTOs or execution, mutation retries, new provider settings/models,
new dependencies, popup lifecycle changes, SDK publishing, version changes, and
paid provider requests.

## Verification

Before implementation, 5 acceptance cases failed: all 4 hover uncertainty cases
and native mixed-text replay. After implementation, all 145 targeted Runner,
usage, provider, adapter, and native OpenAI wire tests pass. Ruff reports 0 errors
on all modified Python files; mypy reports 0 errors on both modified production
files. Native SDK transport covers text and null assistant content, exact IDs and
JSON arguments, request single-call preferences, and 20 measured tokens. No
external provider requests were made.
