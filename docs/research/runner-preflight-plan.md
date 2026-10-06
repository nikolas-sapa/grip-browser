# Runner preflight contracts

Test plan (before implementation):

1. Reused native call ID: 2 model calls, exactly 1 mutation, 0 dispatches for the second call, 0 later model requests; retained first native ID unchanged.
2. Invalid native IDs (empty string, integer, list, dictionary): 4 rejected cases, 0 dispatches per case, exactly 1 model call per case. Absent IDs retain unique fallback IDs.
3. Gemini actual SDK response fixtures (NaN, positive infinity, negative infinity, nested non-string key): 4 protocol rejections, 0 dispatches each, exactly 10 measured tokens and 1 model call per Runner result; outcome action_error and success false. Valid native replay retains all signed parts and IDs across 3 requests.
4. wait_for: 6 ordered nonempty/empty condition pairs rejected before dispatch, 0 dispatches each. Each of 3 single nonempty conditions dispatches exactly once.
5. Focused existing Runner/Gemini tests, Ruff and mypy: 0 failures or findings in changed modules.

Implementation plan:

1. Move ID validation and fallback allocation before browser dispatch. Reject present empty, non-string and previously used IDs; preserve provider IDs.
2. Validate Gemini response arguments with existing strict _parse_args before metadata serialization; convert invalid arguments to LLMProtocolError retaining measured usage.
3. Match Page condition counting (non-None), while requiring the single supplied condition to be nonempty.

Non-goals: multiple-call execution (await architecture choice), changed dependencies/models/vendors, paid requests, signature rewriting, retries, unrelated browser/CLI changes.

Verification:

- Before implementation: 15 regression failures, 19 existing/control cases passed.
- After implementation: 121 focused Runner/preflight/Gemini tests passed, including actual SDK transport replay and absent native ID checks.
- Ruff: 0 findings across changed source/tests. Mypy: 0 issues in both source modules.
- No external or paid API requests. Installed SDK emits 1 existing Python 3.14 deprecation warning.
