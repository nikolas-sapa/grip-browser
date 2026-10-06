from __future__ import annotations

import ast
import json
from typing import Any

try:
    import anthropic  # optional dependency, guarded below
except ImportError:
    anthropic = None  # type: ignore[assignment]

from grip.adapters.base import LLMResponse, ToolCall


def _require_text(value: Any, field: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise ValueError(f"{field} must be {'nonempty ' if nonempty else ''}text")
    return value


def _parse_arguments(raw: Any) -> dict[str, Any]:
    # Transitional support for Runner's Python-dict repr. Reject malformed or
    # non-JSON data instead of silently turning a failed action into empty args.
    parsed = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, RecursionError):
            try:
                parsed = ast.literal_eval(raw)
            except (ValueError, SyntaxError, RecursionError) as exc:
                raise ValueError(
                    "tool arguments must be a JSON object or Python dict repr"
                ) from exc
    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must be an object")

    def validate(value: Any) -> None:
        if isinstance(value, dict):
            if not all(isinstance(key, str) for key in value):
                raise ValueError("tool argument keys must be strings")
            for child in value.values():
                validate(child)
        elif isinstance(value, list):
            for child in value:
                validate(child)
        elif value is not None and not isinstance(value, (str, bool, int, float)):
            raise ValueError("tool arguments must contain JSON values")

    try:
        validate(parsed)
        json.dumps(parsed, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("tool arguments must contain valid JSON values") from exc
    return parsed


def _to_anthropic_messages(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    system: list[str] = []
    converted: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    pending: str | None = None
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            if converted:
                raise ValueError("system messages must precede conversation messages")
            system.append(_require_text(msg.get("content"), "system content"))
            continue
        if pending is not None and role != "tool":
            raise ValueError("tool call must be followed immediately by its result")
        if role == "user":
            converted.append(
                {"role": "user", "content": _require_text(msg.get("content"), "user content")}
            )
        elif role == "assistant":
            text = msg.get("content")
            calls = msg.get("tool_calls")
            if calls is None or calls == []:
                converted.append(
                    {"role": "assistant", "content": _require_text(text, "assistant content")}
                )
                continue
            if not isinstance(calls, list) or len(calls) != 1:
                raise ValueError("only one assistant tool call is supported")
            tc = calls[0]
            if not isinstance(tc, dict) or tc.get("type") != "function":
                raise ValueError("assistant tool call must be a function")
            call_id = _require_text(tc.get("id"), "tool call id", nonempty=True)
            if call_id in seen_ids:
                raise ValueError("duplicate tool call id")
            seen_ids.add(call_id)
            fn = tc.get("function")
            if not isinstance(fn, dict):
                raise ValueError("tool call function must be an object")
            name = _require_text(fn.get("name"), "function name", nonempty=True)
            args = _parse_arguments(fn.get("arguments"))
            parts: list[dict[str, Any]] = []
            if text is not None:
                text = _require_text(text, "assistant content")
                if text:
                    parts.append({"type": "text", "text": text})
            parts.append({"type": "tool_use", "id": call_id, "name": name, "input": args})
            converted.append({"role": "assistant", "content": parts})
            pending = call_id
        elif role == "tool":
            if pending is None or msg.get("tool_call_id") != pending:
                raise ValueError("tool result has no matching tool call id")
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": pending,
                            "content": _require_text(msg.get("content"), "tool result content"),
                        }
                    ],
                }
            )
            pending = None
        else:
            raise ValueError(f"unsupported message role: {role!r}")
    if pending is not None:
        raise ValueError("tool call is missing its result")
    if not converted:
        raise ValueError("at least one conversation message is required")
    return "\n".join(system) if system else None, converted


def _to_anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted = []
    for tool in tools:
        fn = tool.get("function")
        if tool.get("type") != "function" or not isinstance(fn, dict):
            raise ValueError("tools must use the function envelope")
        schema = fn.get("parameters", {"type": "object", "properties": {}})
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ValueError("function parameters must be an object schema")
        native: dict[str, Any] = {
            "name": _require_text(fn.get("name"), "function name", nonempty=True),
            "input_schema": schema,
        }
        if "description" in fn:
            native["description"] = _require_text(fn["description"], "function description")
        converted.append(native)
    return converted


class AnthropicAdapter:
    def __init__(self, api_key: str | None = None, model: str = "claude-opus-4-7") -> None:
        if anthropic is None:
            raise ImportError("pip install grip-browser[anthropic]")
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        system, native_messages = _to_anthropic_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": native_messages,
        }
        if system is not None:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = _to_anthropic_tools(tools)
            kwargs["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
        response = await self._client.messages.create(**kwargs)
        calls = [block for block in response.content if block.type == "tool_use"]
        if len(calls) > 1:
            raise ValueError("multiple tool calls are unsupported by the single-action Runner")
        text = "".join(block.text for block in response.content if block.type == "text")
        if calls:
            call = calls[0]
            return LLMResponse(
                content=text or None,
                tool_call=ToolCall(
                    name=call.name,
                    arguments=_parse_arguments(call.input),
                    id=call.id,
                ),
            )
        return LLMResponse(content=text, tool_call=None)
