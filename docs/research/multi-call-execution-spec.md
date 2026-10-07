# Sequential model-call batches

Status: frozen contract for implementation. User delegated feature decisions on 2026-10-07. Extends existing Runner and installed providers, with sequential execution and bounded recovery.

## Acceptance tests (before implementation plan)

1. **Provider batch replay:** three installed SDK fixtures (OpenAI, Anthropic, Gemini), each with three response turns and five calls: exactly five dispatches, three model-call usage records, five matching tool results, and zero dropped or reordered calls. Include text between native tool blocks. Gemini signature bytes and absent native IDs survive both outgoing replays unchanged.
2. **DTO compatibility:** old two-, three-, and four-positional-argument constructors retain field meanings in three tests. Singular-only, plural-only, and consistent dual forms each produce one canonical tuple in three tests. Conflicting dual forms fail before zero dispatches. Empty calls plus text retain model_text; empty calls without text retain action_error in two tests.
3. **Whole-batch preflight:** at least twelve fixtures cover invalid later arguments, unknown tool, non-JSON/cyclic arguments, empty/non-string ID, duplicate native ID within batch, reused earlier ID, malformed replay metadata, multiple done, and done before another call. Every rejected fixture has zero dispatches and one recorded model request. Schema/ID/metadata failures return action_error; strict non-JSON arguments preserve the existing raised ValueError contract. Malformed later provider calls retain reported usage in all three provider fixtures.
4. **ID allocation:** two absent-ID calls plus one native ID matching a proposed generated ID produce three distinct history IDs. Native ID bytes remain unchanged. One later response reusing any prior history ID is rejected with zero additional dispatches.
5. **Error stop and recovery:** a three-call batch with a safe read error at position one or two executes respectively one or two calls, emits exactly three matching results (one or two NOT_EXECUTED), and makes zero remaining batch dispatches. A subsequent snapshot/done response succeeds in two recovery fixtures.
6. **Uncertain mutation:** eighteen fixtures (click/type/select, three failure timings, two batch positions) attempt exactly one failing mutation, execute zero later batch actions, issue zero later model requests, and end ambiguous_action. Add two hover uncertainty fixtures with the same bounds. All returned calls have exactly one result in final history; skipped calls state NOT_EXECUTED.
7. **Budget:** max_steps=3 fixtures never exceed three model requests or three dispatches (done counts). A batch larger than remaining dispatch budget executes zero calls and ends step_limit with its request usage counted once. A successful done as dispatch three succeeds. Three nonterminal dispatches permit zero fourth model requests.
8. **Native history validation:** for Anthropic and Gemini, missing, duplicate, unrelated, or out-of-order results produce eight rejecting fixtures. Valid two-call batches convert to one native assistant/model turn and one user turn containing exactly two ordered result blocks. OpenAI outgoing messages contain zero internal replay_metadata keys.
9. **Real Chrome pilot:** a local form plus scripted adapter executes type, click, snapshot, done across at least one two-call response. Exactly one submit event, expected input value, success=True and outcome=done. No provider network requests. A local safe-read failure batch proves zero click/submit events after the failure.
10. **Regression:** full existing unit suite and offline browser suite pass with zero new failures. Ruff and strict existing mypy targets report zero errors. Single-call cancellation, usage accounting, trace redaction, pruning, reference version checks and popup lifecycle remain covered.

## Data contract

Append `tool_calls: tuple[ToolCall, ...] = ()` as the fifth LLMResponse dataclass field, after replay_metadata. Preserve the first four fields and positional meanings. Constructor normalizes supplied call sequence to tuple. Singular-only fills the tuple; plural-only sets legacy tool_call to the first call. When both are present, singular must equal the first plural call; disagreement raises ValueError. Runner revalidates the canonical representation because the DTO remains mutable for compatibility. Built-in providers populate the full tuple and legacy first call. Text-only responses have empty tuple and tool_call=None.

Preserve every returned call's name, JSON arguments and native ID. IDs must be nonempty strings when present. Allocate absent IDs deterministically using the existing grip_call prefix; choose against all native IDs in the current batch and all previously reserved history IDs. Never rewrite a native ID. Validation and allocation complete before any action, then reserve every batch history ID, including calls later skipped.

Provider parsers validate every call before returning any response. Protocol failures retain reported usage once. Add a shared internal validate_replay_metadata(response) helper in adapters/base.py for Runner preflight, without importing optional SDKs.

## Replay contract

One shared assistant history message contains response text, the complete ordered OpenAI-shaped tool_calls list, and optional replay_metadata. Follow it with exactly one role=tool message per call, in returned order, with matching history ID. Never split one returned batch across assistant messages. Append the assistant envelope before dispatch and complete matching results even when an executed action causes terminal failure. Preserve legacy singular successful done behavior: it returns immediately without adding terminal assistant/tool history. Plural batches include the done result because the entire batch has one assistant envelope. On cancellation, add runner-authored ERROR CANCELLED for the interrupted call and NOT_EXECUTED results for remaining calls, then propagate cancellation without another provider request.

Successful results retain existing untrusted-page fences. Runner-authored failures remain outside fences. Every skipped result uses the stable prefix `ERROR NOT_EXECUTED:` and explicitly says an earlier batch action failed or was cancelled. This is not a successful result and never runs _dispatch. No trace entry may imply a skipped browser action ran. Actual dispatches retain existing action trace semantics.

Gemini replay_metadata retains the entire native model Content, including interleaved text, thought signatures and all function_call parts. Shared preflight checks native call count/order/name/arguments/IDs against the DTO; signatures remain opaque. Native absent IDs remain absent on outgoing function calls and responses, even when shared history uses a generated ID. Provider conversion groups the consecutive matching tool results into one user Content with all ordered FunctionResponse parts. SDK Content validation remains in the Gemini adapter.

Anthropic replay_metadata uses `{provider: "anthropic", content: <native block JSON list>}`. Preserve original text/tool_use block order. Shared preflight validates every native tool_use against DTO name/arguments/ID/order. Provider conversion replays that assistant block sequence and groups all consecutive matching tool_result blocks into one user message. Custom adapters without metadata use shared text followed by ordered tool_use blocks. Native tool IDs must be present; malformed provider responses fail closed.

OpenAI conversion preserves shared batch calls and individual consecutive tool messages, stripping internal replay_metadata from outgoing wire messages. No internal metadata is sent as an unsupported request field.

Both native grouped converters reject missing, duplicate, unrelated and out-of-order results, including an unfinished final history batch.

## Execution and budgets

Runner counts model requests independently from dispatches; both are capped by max_steps. A request consumes one model-call record regardless of returned batch length. A dispatch, including done, consumes one action slot. Validate the complete batch and ensure its call count fits remaining action slots before executing its first call. An oversized batch ends step_limit with zero actions from that batch; do not partially execute or request a replacement after this rejection.

At most one done is allowed, and it must be last. Execute returned order only. Existing post-mutation snapshot/version checks remain authoritative; later references are not rewritten or automatically retargeted. Batches using references invalidated by earlier actions fail or stop using existing semantics.

Stop the batch after any error. A recoverable safe read GripError may permit the next model response, only after all skipped results have been added to history and only within both budgets. Uncertain mutation ends ambiguous_action immediately after completing matching batch history. Other terminal errors retain action_error. Never execute queued done after an earlier error. Preserve last_error semantics when recovery exhausts the budget. Cancellation propagates without retry.

Remove request-time options that force a single provider call. This permits returned batches; it does not permit concurrent browser execution.

## Non-goals

No concurrent dispatch, rollback, automatic mutation retries, reference rewriting, dependency inference, additional tools, vendor/model/dependency changes, database changes, paid provider calls, external participants, or comparative superiority claims. The deterministic workflow pilot proves local execution/replay correctness only. This change does not claim a network firewall or expand existing popup policy guarantees.

## Implementation plan

1. Land acceptance fixtures for additive DTO, replay, preflight, errors and budgets; confirm old multiple-call rejection fails the new positive cases.
2. Implement additive DTO and metadata preflight, then whole-response provider parsing and grouped native replay, preserving signatures and IDs.
3. Implement Runner whole-batch preflight, independent bounded counters, sequential dispatch and complete result history on stop.
4. Add deterministic local Chrome workflow pilot and documentation showing safe batch behavior and budget semantics.
5. Run focused tests, then full regression/static checks; independent Python/security review precedes merge. Publish only after exact-head CI and live deployment verification.
