# Remaining browser correctness work

Test plan before implementation:

1. Runner: 2 model calls, exactly 1 dispatched action; second request contains the first response's replay metadata unchanged; trace JSONL contains 0 signature occurrences.
2. Runner compatibility: unsigned response history has 0 replay_metadata keys; existing tool IDs, strict JSON, ambiguity outcomes and usage accounting remain unchanged.
3. Gemini: native intercepted transport preserves every signed Content Part and call ID across 3 turns; malformed replay causes 0 transport requests; 2 independent histories have 0 signature mixing.
4. OpenAI: 2 native tool requests contain parallel_tool_calls=false and execute 1 action; no-tools request omits flag; forced 2-call response executes 0 actions and retains exact usage.
5. Popup: default trusted popup closes within 2 seconds and makes 0 fixture requests; opt-in exposes 1 live popup; 2 openers route independently; unrelated targets resume once; browser.open completes within 3 seconds; teardown leaves 0 tasks.

Implementation: retain opaque Gemini native Content on its response and assistant history; request one OpenAI call; route browser-level Chrome page attachments to the managed opener. Provider, popup and parent Runner files have separate owners.

Non-goals: multiple-call executor, concurrent actions, changed default models/dependencies, paid API calls, child Page API, changed click gestures, unrelated UI changes. Package publication is a separate concrete release step after verification.
