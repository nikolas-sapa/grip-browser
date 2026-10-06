# Gemini signature replay

Test plan (before implementation): a real Google Gen AI SDK with intercepted transport makes 3 sequential requests, each retaining all earlier model Parts in their original order, exact decoded signature bytes, function arguments and IDs. Two histories sharing one adapter retain 0 signatures from the other history. Signed text and function-call Parts both survive replay. Malformed or mismatched metadata causes 0 HTTP requests. Unsigned histories retain existing behavior. Targeted tests and scoped Ruff/mypy finish with 0 failures/errors.

Implementation scope: additive opaque LLMResponse.replay_metadata, Gemini-native Content serialization and validation, Runner assistant-message handoff. Native metadata stays out of traces. Preserve the entire native model Content because a signature may belong to a text Part rather than the function-call Part.

Non-goals: multiple tool-call execution, provider switching, model or dependency changes, paid API requests, generic provider replay architecture, PyPI release.

Reference: https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures requires signatures returned exactly in their original Parts.

Validation: 25 dedicated replay and existing adapter tests passed. Real SDK intercepted requests preserve signed text/function Parts on requests 2 and 3, with exact base64 wire signatures and native IDs. Two independent histories retain exact decoded signature bytes. Four malformed metadata cases reject before a provider method is called; six invalid argument forms fail closed; native metadata mismatches reject. Scoped Ruff and strict mypy: 0 errors. No paid requests.

Runner acceptance: a real Runner and real Gemini SDK make 3 intercepted requests, execute 2 snapshot actions, preserve both signed native model turns in request 3, retain matching function-response IDs, report exactly 33 total tokens (24 input, 6 candidate output, 3 thoughts), and export 0 signature/replay-metadata fields. Dedicated replay plus Runner handoff tests: 17 passed; Ruff: 0 errors.

Additional test plan (before correction): one signed native function call without an ID must replay the exact original Content, execute one Runner action, and emit a matching function response with 0 invented wire IDs. Runner's fallback ID remains internal for result association. Existing unsigned canonical call IDs remain unchanged.

No-ID correction verified: signed native Content remains exact, function response omits an absent native ID, internal Runner fallback associates the result, unsigned canonical IDs still pass existing replay tests. Gemini replay/provider/adapter suites: 50 passed; Ruff and strict scoped mypy: 0 errors.
