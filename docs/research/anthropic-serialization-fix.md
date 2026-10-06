# Anthropic serialization milestone

## Acceptance tests (refined G03)

Anthropic-only slice of G03; other providers remain separate changes.

1. Twenty explicit serialization/validation fixtures: zero OpenAI tool wrappers,
   system/tool message roles or assistant `tool_calls` in native Anthropic requests.
   Valid nested arguments retain exact strings, Unicode, booleans and nulls.
2. Intercepted native SDK transport: two sequential requests preserve the exact
   provider tool ID through tool use and tool result. Zero paid or live API calls.
3. Malformed/non-object arguments and orphan result IDs: zero HTTP requests;
   explicit validation errors rather than silently replacing arguments with `{}`.
4. Runner replay: one supplied provider ID preserved exactly, two legacy calls
   receive distinct fallback IDs, and assistant text accompanying a call survives.
5. Existing adapter/runner/unit tests: zero introduced regressions; report optional
   SDK omissions and type-check limits explicitly. Request multiple-call responses
   must fail explicitly rather than silently discarding calls.

## Implementation

Translate the existing runner transcript at the Anthropic adapter boundary:
extract system content, map tool definitions to `input_schema`, map assistant calls
to `tool_use`, and map tool replies to user `tool_result` blocks. Add optional
`ToolCall.id` with a backwards-compatible default and replay provider IDs in Runner;
generate unique fallback IDs for existing/custom adapters. Preserve accompanying
assistant text. Request single-call tool behavior, consistent with the current
single-action response contract. Parse legacy Python-dict argument strings strictly
as a temporary compatibility path, alongside proper JSON object strings.

## Non-goals

No runner JSON conversion in this commit (next separate change). No OpenAI/Gemini
serialization changes, new models/vendors, multiple-tool execution, extended
thinking/signatures, outcomes, usage accounting, side-effect retry redesign,
release, merge, deployment or paid API run. Intercepted SDK serialization proves
request shape and history preservation; it does not prove live model compatibility.

## Verification

Initial native Anthropic SDK 0.116.0 interception reproduced system/tool roles,
assistant `tool_calls` and OpenAI-wrapped tool definitions in transmitted requests.
Before implementation, the new wire suite had 20 failures and two passes.

After implementation, 22 native SDK transport/validation tests pass (20 explicit
fixtures, two-request history roundtrip, multiple-response-call rejection).
Combined wire, adapter and Runner suite: 54 passes. Full unit suite: 566 passes,
zero skips, 87.84% coverage (80% required). One Google SDK Python 3.14 deprecation
warning remains. Repository and changed-test Ruff checks pass. Strict mypy passes
all three changed production files with dependency diagnostics suppressed.

Full mypy with all optional provider SDKs installed reports six existing errors in
OpenAI/Gemini optional-import typing. Anthropic request-path typing errors are
resolved; other providers remain outside this change. Python and security reviews
approve. No live provider compatibility, full integration suite or Python version
matrix claimed. No paid API call, merge, release or production deployment.

Contract reference: https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls
