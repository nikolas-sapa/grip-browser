from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
import json
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class LLMUsage:
    """Provider-reported categories, never estimates or a billing total.

    Anthropic input excludes cache counts; OpenAI/Gemini input includes cache.
    Thought tokens remain a separate category; do not sum categories blindly.
    """

    provider: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    thought_tokens: int | None = None
    total_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LLMProtocolError(ValueError):
    """Invalid model response with any reported usage retained for accounting."""

    def __init__(self, message: str, usage: LLMUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


def _reported_count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


@dataclass
class LLMResponse:
    content: str | None
    tool_call: ToolCall | None
    usage: LLMUsage | None = None
    replay_metadata: dict[str, Any] | None = None
    tool_calls: tuple[ToolCall, ...] = ()

    def __post_init__(self) -> None:
        self.tool_calls = tuple(self.tool_calls)
        if self.tool_calls:
            if self.tool_call is not None and self.tool_call != self.tool_calls[0]:
                raise ValueError("singular tool call must match the first batch call")
            self.tool_call = self.tool_calls[0]
        elif self.tool_call is not None:
            self.tool_calls = (self.tool_call,)


def _validate_calls(
    calls: tuple[ToolCall, ...], usage: LLMUsage | None, *, require_ids: bool = False,
) -> None:
    seen: set[str] = set()
    for call in calls:
        if not isinstance(call.name, str) or not call.name:
            raise LLMProtocolError("tool name must be nonempty text", usage)
        if call.id is None and require_ids:
            raise LLMProtocolError("tool call ID must be nonempty text", usage)
        if call.id is not None:
            if not isinstance(call.id, str) or not call.id:
                raise LLMProtocolError("tool call ID must be nonempty text", usage)
            if call.id in seen:
                raise LLMProtocolError("duplicate tool call ID", usage)
            seen.add(call.id)


def _validate_fields(
    value: dict[str, Any], required: dict[str, type], optional: dict[str, type],
) -> None:
    if set(value) - (required.keys() | optional.keys()):
        raise ValueError
    for key, expected in required.items():
        if key not in value or type(value[key]) is not expected:
            raise ValueError
    for key, expected in optional.items():
        if key in value and value[key] is not None and type(value[key]) is not expected:
            raise ValueError


def _validate_anthropic_part(part: dict[str, Any]) -> None:
    kind = part.get("type")
    if kind == "text":
        _validate_fields(part, {"type": str, "text": str}, {"citations": list})
        for citation in part.get("citations") or []:
            if not isinstance(citation, dict):
                raise ValueError
            citation_kind = citation.get("type")
            required: dict[str, type] = {"type": str, "cited_text": str}
            optional: dict[str, type] = {"document_title": str, "file_id": str}
            index_fields = {
                "char_location": ("document_index", "start_char_index", "end_char_index"),
                "page_location": ("document_index", "start_page_number", "end_page_number"),
                "content_block_location": (
                    "document_index", "start_block_index", "end_block_index"),
                "search_result_location": (
                    "search_result_index", "start_block_index", "end_block_index"),
            }
            if citation_kind in index_fields:
                required.update(dict.fromkeys(index_fields[citation_kind], int))
                if citation_kind == "search_result_location":
                    required["source"] = str
                    optional = {"title": str}
            elif citation_kind == "web_search_result_location":
                required.update({"encrypted_index": str, "url": str})
                optional = {"title": str}
            else:
                raise ValueError
            _validate_fields(citation, required, optional)
    elif kind == "tool_use":
        _validate_fields(part, {"type": str, "id": str, "name": str, "input": dict},
                         {"caller": dict, "toolset_name": str})
        caller = part.get("caller")
        if caller is not None:
            if caller.get("type") == "direct":
                _validate_fields(caller, {"type": str}, {})
            elif caller.get("type") in {"code_execution_20250825", "code_execution_20260120"}:
                _validate_fields(caller, {"type": str, "tool_id": str}, {})
            else:
                raise ValueError
    elif kind == "thinking":
        _validate_fields(part, {"type": str, "thinking": str, "signature": str}, {})
    elif kind == "redacted_thinking":
        _validate_fields(part, {"type": str, "data": str}, {})
    else:
        raise ValueError


def validate_replay_metadata(response: LLMResponse) -> None:
    """Check opaque native replay against normalized calls before any action."""
    metadata = response.replay_metadata
    if metadata is None:
        return

    def validate_json(value: Any) -> None:
        if isinstance(value, dict):
            if not all(isinstance(key, str) for key in value):
                raise ValueError
            for child in value.values():
                validate_json(child)
        elif isinstance(value, list):
            for child in value:
                validate_json(child)
        elif value is not None and not isinstance(value, (str, bool, int, float)):
            raise ValueError

    try:
        if not isinstance(metadata, dict):
            raise ValueError
        validate_json(metadata)
        json.dumps(metadata, allow_nan=False)
        provider = metadata.get("provider")
        content = metadata.get("content")
        if provider == "gemini":
            if not isinstance(content, dict) or content.get("role") != "model":
                raise ValueError
            _validate_fields(content, {"role": str, "parts": list}, {})
            parts = content.get("parts")
            if not isinstance(parts, list):
                raise ValueError
            native = []
            for part in parts:
                if not isinstance(part, dict):
                    raise ValueError
                _validate_fields(part, {}, {"text": str, "thought": bool,
                    "thought_signature": str, "thoughtSignature": str,
                    "function_call": dict, "functionCall": dict, "part_metadata": dict,
                    "partMetadata": dict})
                if any(snake in part and camel in part for snake, camel in (
                    ("function_call", "functionCall"), ("thought_signature", "thoughtSignature"),
                    ("part_metadata", "partMetadata"),
                )):
                    raise ValueError
                signature = part.get("thought_signature", part.get("thoughtSignature"))
                if signature is not None:
                    base64.b64decode(signature, validate=True)
                call = part.get("function_call", part.get("functionCall"))
                if call is not None:
                    if not isinstance(call, dict):
                        raise ValueError
                    _validate_fields(call, {"name": str}, {"id": str, "args": dict,
                        "partial_args": list, "partialArgs": list,
                        "will_continue": bool, "willContinue": bool})
                    if any(snake in call and camel in call for snake, camel in (
                        ("partial_args", "partialArgs"), ("will_continue", "willContinue"),
                    )):
                        raise ValueError
                    if (call.get("partial_args", call.get("partialArgs"))
                            or call.get("will_continue", call.get("willContinue"))):
                        raise ValueError
                    native.append((call.get("name"), call.get("args") or {}, call.get("id")))
        elif provider == "anthropic":
            if not isinstance(content, list):
                raise ValueError
            native = []
            for part in content:
                if not isinstance(part, dict):
                    raise ValueError
                _validate_anthropic_part(part)
                if part.get("type") == "tool_use":
                    if not isinstance(part.get("id"), str) or not part["id"]:
                        raise ValueError
                    native.append((part.get("name"), part.get("input"), part.get("id")))
        else:
            raise ValueError
        expected = [(call.name, call.arguments, call.id) for call in response.tool_calls]
        if len(native) != len(expected) or any(
            name != wanted_name or call_id != wanted_id
            or json.dumps(arguments, sort_keys=True, allow_nan=False)
            != json.dumps(wanted_arguments, sort_keys=True, allow_nan=False)
            for (name, arguments, call_id), (wanted_name, wanted_arguments, wanted_id)
            in zip(native, expected, strict=True)
        ):
            raise ValueError
    except (TypeError, ValueError, RecursionError):
        raise LLMProtocolError("native replay metadata does not match tool calls", response.usage
                               ) from None


@runtime_checkable
class LLMAdapter(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse: ...
