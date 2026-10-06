from unittest.mock import AsyncMock

from grip.adapters.base import LLMResponse, ToolCall
from grip.runner import Runner
from grip.trace import Trace
from tests.unit.test_runner import FakePage


async def test_runner_preserves_native_metadata_without_tracing_signature(tmp_path):
    metadata = {"provider": "gemini", "content": {
        "role": "model", "parts": [{"thought_signature": "opaque-signature"}],
    }}
    seen = []

    async def complete(messages, tools):
        seen.append([dict(message) for message in messages])
        if len(seen) == 1:
            return LLMResponse(None, ToolCall("snapshot", {}, "native-call"),
                               replay_metadata=metadata)
        return LLMResponse("finished", None)

    trace = Trace()
    result = await Runner(AsyncMock(complete=complete), FakePage(["page"]), trace).run("answer")
    assert result.model_calls == 2
    assistants = [message for message in seen[1] if message["role"] == "assistant"]
    assert len(assistants) == 1 and assistants[0]["replay_metadata"] == metadata
    assert assistants[0]["tool_calls"][0]["id"] == "native-call"
    assert len([entry for entry in trace.actions if entry.action == "snapshot"]) == 1
    path = tmp_path / "trace.jsonl"
    trace.to_jsonl(str(path))
    assert "opaque-signature" not in path.read_text()


async def test_unsigned_response_keeps_legacy_assistant_history():
    seen = []

    async def complete(messages, tools):
        seen.append([dict(message) for message in messages])
        if len(seen) == 1:
            return LLMResponse(None, ToolCall("snapshot", {}))
        return LLMResponse("finished", None)

    await Runner(AsyncMock(complete=complete), FakePage(["page"]), Trace()).run("answer")
    assert len(seen) == 2
    assert all("replay_metadata" not in message for message in seen[1])
