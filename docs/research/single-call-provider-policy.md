# Single-call provider policy

## Test plan

1. Native OpenAI SDK history roundtrip captures exactly 2 requests, each with
   `parallel_tool_calls: false`, and dispatches exactly 1 browser action.
2. Native OpenAI SDK completion with no tools captures exactly 1 request and
   contains neither `tools` nor `parallel_tool_calls`.
3. A native OpenAI response containing 2 tool calls fails explicitly, with all
   reported usage preserved and no tool call returned for dispatch.
4. Existing provider usage tests retain explicit rejection for all 3 adapters.

## Implementation

Request one tool call at most from OpenAI whenever tools are supplied, matching
Anthropic's existing parallel-use suppression. Retain response validation because
compatible endpoints may ignore request preferences. Gemini remains explicitly
single-call; its native function-calling configuration has no parallel-use flag.

## Non-goals

Plural response DTOs, parallel or sequential execution of multiple calls,
automatic mutation retries, dependency or model changes, paid provider requests,
and package publishing.

## Verification

The native SDK roundtrip test failed before implementation because the flag was
absent. After implementation, all 27 non-Gemini adapter/usage/wire tests pass,
including 3 native OpenAI transport cases. Ruff passes on owned Python files;
scoped OpenAI mypy passes with unrelated imports followed silently. Full-suite
verification remains the integration owner's responsibility after concurrent
Gemini work settles. No network provider requests were made.
