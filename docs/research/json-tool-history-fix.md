# JSON tool-history milestone

## Acceptance tests

1. Six argument fixtures (Unicode, quotes, booleans, null, lists, empty object):
   six exact `json.loads` roundtrips from Runner assistant history, zero Python
   literal strings sent as tool arguments.
2. One native OpenAI SDK intercepted two-request Runner roundtrip: assistant call
   arguments decode to the original object; call/result IDs match; zero paid calls.
3. Non-finite/non-JSON argument fixtures: explicit validation error before any
   browser dispatch, zero side effects.
4. Existing unit suite: zero introduced regressions. Scoped lint/typing and
   independent Python review pass.

## Implementation

Serialize tool arguments with strict `json.dumps` rather than `str(dict)`.
Validate serialization before dispatch, then replay the validated JSON string.
Preserve existing tool ID and assistant-text behavior.

## Non-goals

No provider response-ID changes, new SDKs in project dependencies, removal of
Anthropic/Gemini legacy compatibility parsing, invalid-argument recovery,
termination, billing usage or ambiguous-action behavior. No live paid API calls,
release, merge or production deployment. Intercepted transport verifies client
serialization; live provider acceptance remains unverified.

## Verification

Original native OpenAI SDK interception confirmed replayed `str(dict)` arguments
cannot be decoded with `json.loads`. Before implementation, eight new cases failed;
a dumps-only intermediate fix also failed three coercion fixtures (integer key,
tuple, top-level list), leading to explicit recursive validation.

Six positive roundtrips, six invalid-value fixtures and one native OpenAI SDK
two-request history test pass. Combined Runner/adapter/wire checks: 67 passes.
Full unit suite: 579 passes, zero skips, 88.07% coverage (80% required). One existing
Google SDK Python 3.14 deprecation warning remains. Repository and changed-test
Ruff checks, scoped Runner mypy, Python review and security review pass.

OpenAI provider response-ID retention remains a separate provider milestone;
this test verifies matching replay call/result IDs using the existing fallback.
Full integration/gripsearch suite, live provider compatibility and multi-version
Python matrix are not claimed for this change. No paid API call or production
deployment performed.
