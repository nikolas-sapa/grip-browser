from __future__ import annotations

import ast
import importlib
import json
from typing import Any

from grip.adapters.base import (
    LLMProtocolError, LLMResponse, LLMUsage, ToolCall, _reported_count,
    _validate_calls, validate_replay_metadata,
)

anthropic: Any
try:
    anthropic = importlib.import_module("anthropic")
except ImportError:
    anthropic = None


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
    pending: list[str] = []
    pending_results: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            if converted:
                raise ValueError("system messages must precede conversation messages")
            system.append(_require_text(msg.get("content"), "system content"))
            continue
        if pending and role != "tool":
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
            if not isinstance(calls, list):
                raise ValueError("assistant tool calls must be a list")
            parts: list[dict[str, Any]] = []
            normalized = []
            if text is not None:
                text = _require_text(text, "assistant content")
                if text:
                    parts.append({"type": "text", "text": text})
            for tc in calls:
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
                normalized.append(ToolCall(name, args, call_id))
                parts.append({"type": "tool_use", "id": call_id, "name": name, "input": args})
                pending.append(call_id)
            metadata = msg.get("replay_metadata")
            if metadata is not None:
                replay = LLMResponse(text, normalized[0], replay_metadata=metadata,
                                     tool_calls=tuple(normalized))
                validate_replay_metadata(replay)
                if metadata.get("provider") != "anthropic":
                    raise ValueError("invalid Anthropic replay provider")
                parts = metadata["content"]
            converted.append({"role": "assistant", "content": parts})
        elif role == "tool":
            if not pending or msg.get("tool_call_id") != pending[0]:
                raise ValueError("tool result has no matching tool call id")
            pending_results.append({
                "type": "tool_result", "tool_use_id": pending.pop(0),
                "content": _require_text(msg.get("content"), "tool result content"),
            })
            if not pending:
                converted.append({"role": "user", "content": pending_results})
                pending_results = []
        else:
            raise ValueError(f"unsupported message role: {role!r}")
    if pending:
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
            kwargs["tool_choice"] = {"type": "auto"}
        response = await self._client.messages.create(**kwargs)
        raw_usage = getattr(response, "usage", None)
        usage = (
            None
            if raw_usage is None
            else LLMUsage(
                provider="anthropic",
                input_tokens=_reported_count(getattr(raw_usage, "input_tokens", None)),
                output_tokens=_reported_count(getattr(raw_usage, "output_tokens", None)),
                cache_read_input_tokens=_reported_count(
                    getattr(raw_usage, "cache_read_input_tokens", None)
                ),
                cache_creation_input_tokens=_reported_count(
                    getattr(raw_usage, "cache_creation_input_tokens", None)
                ),
            )
        )
        metadata = None
        try:
            if all(callable(getattr(block, "model_dump", None))
                   and callable(getattr(type(block), "model_validate", None))
                   for block in response.content):
                native_parts = []
                for block in response.content:
                    part = block.model_dump(mode="json", exclude_none=True)
                    type(block).model_validate(part)
                    native_parts.append(part)
                metadata = {"provider": "anthropic", "content": native_parts}
            native_calls = [block for block in response.content if block.type == "tool_use"]
            text = "".join(block.text for block in response.content if block.type == "text")
        except (AttributeError, TypeError, ValueError):
            raise LLMProtocolError("invalid Anthropic response content", usage) from None
        if native_calls:
            try:
                calls = tuple(ToolCall(call.name, _parse_arguments(call.input), call.id)
                              for call in native_calls)
            except ValueError:
                raise LLMProtocolError(
                    "tool arguments must be a valid JSON object", usage
                ) from None
            _validate_calls(calls, usage, require_ids=True)
            reply = LLMResponse(text or None, calls[0], usage, metadata, calls)
            validate_replay_metadata(reply)
            return reply
        return LLMResponse(content=text, tool_call=None, usage=usage)
