# Provider usage and typing

Test plan (before implementation): 10 provider transcripts assert every reported count exactly, including zero and unavailable values; 3 SDK transport checks parse actual SDK responses without network requests; trace sums remain exact after 3 entries evict from a 2-entry window; installed and absent optional SDK mypy runs have 0 errors.

Implementation: additive LLMUsage DTO, optional response and trace metadata; retain native tool IDs; optional imports use importlib with explicit Any; each count means its provider-reported category. Cache and thought counters stay distinct; no estimated billing total.

Non-goals: model changes, dependency changes, paid requests, multi-provider replay architecture, page token estimate changes. Gemini responses requiring thought signature replay fail explicitly because current history cannot preserve signatures.


API: `LLMResponse.usage`, `TraceEntry.model_usage`, and `Trace.model_usage_totals` are additive. `Trace.model_calls` counts all model-call entries; `model_calls_with_usage` counts entries with a usage object (individual fields may still be unknown). Unknown measurements serialize as null and do not enter sums; reported zero is retained.

Native OpenAI/Gemini total_tokens is copied exactly, never recomputed by summing subdivisions. Anthropic lacks a native total; its raw input/output/cache read/cache creation fields are disjoint. An application may derive their sum when counts are known; no billing estimate is emitted. Page token estimates remain in the existing total_tokens counter.

Primary semantics references: https://platform.claude.com/docs/en/build-with-claude/prompt-caching and https://ai.google.dev/gemini-api/docs/generate-content/tokens . Current installed SDK models and intercepted transports verify response field names.

Validation: 10 transcript fixtures, 3 native SDK intercepted transports, native Gemini call/result ID replay, explicit signed-response failure, native total and unknown counters after deque eviction. No paid provider requests. Strict mypy succeeds against installed and absent optional SDK environments (follow-imports=silent isolates target modules from concurrent Runner edits).

Final contract audit tests before edits: reject 2 returned calls from each of 3 providers (0 silently executed), retain exact reported usage on all 3 failures; malformed OpenAI arguments and Gemini signature failure retain usage and sanitize error text. Pre-request Anthropic history rejection remains plain ValueError with no claimed response usage.

Runner integration: RunResult.tokens is measured per-run usage (null if any call has incomplete counts). estimated_tokens remains a separate page estimate. model_calls counts attempts, including timeout/cancellation; usage contains known raw category sums. Anthropic derived totals require all four disjoint counts, including explicit zero cache counts. Protocol rejection retains reported counters.

Trace privacy: typed output strings and copied error messages are redacted, including page-transformed inputs. A real Chrome input listener reproduces value mismatch; JSONL retains zero typed-secret occurrences. No automatic mutation retry follows ambiguous errors.
