from __future__ import annotations

import ast
import importlib
import json
from typing import Any

from grip.adapters.base import LLMProtocolError, LLMResponse, LLMUsage, ToolCall, _reported_count

genai: Any
genai_types: Any
try:
    genai = importlib.import_module("google.genai")
    genai_types = importlib.import_module("google.genai.types")
except ImportError:
    genai = None
    genai_types = None


def _parse_args(raw: Any) -> dict[str, Any]:
    """Accept JSON objects and transitional Python-repr history, fail closed."""
    parsed = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            try:
                parsed = ast.literal_eval(raw)
            except (ValueError, SyntaxError, RecursionError) as exc:
                raise ValueError("invalid Gemini tool arguments") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Gemini tool arguments must be an object")
    def validate(value: Any) -> None:
        if isinstance(value, dict):
            if not all(isinstance(key, str) for key in value):
                raise ValueError("Gemini tool argument keys must be strings")
            for child in value.values():
                validate(child)
        elif isinstance(value, list):
            for child in value:
                validate(child)
        elif value is not None and not isinstance(value, (str, bool, int, float)):
            raise ValueError("Gemini tool arguments must contain JSON values")

    try:
        validate(parsed)
        json.dumps(parsed, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("invalid Gemini tool arguments") from exc
    return parsed


def _to_contents(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[Any]]:
    """Converts the OpenAI-shaped message list runner.py builds into Gemini
    Content objects, pulling the system message out separately since Gemini
    takes it as system_instruction rather than as a turn in the transcript.
    """
    system_instruction: str | None = None
    contents: list[Any] = []
    # tool_call_id -> function name, so a later "tool" message can be turned
    # into a FunctionResponse naming the function it answers (Gemini has no
    # bare tool_call_id concept).
    call_names: dict[str, str] = {}
    wire_call_ids: dict[str, str | None] = {}

    for msg in messages:
        role = msg.get("role")
        if role == "system":
            system_instruction = msg.get("content")
            continue
        if role == "user":
            contents.append(
                genai_types.Content(
                    role="user", parts=[genai_types.Part.from_text(text=msg.get("content") or "")]
                )
            )
        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            metadata = msg.get("replay_metadata")
            if metadata is not None:
                if not isinstance(metadata, dict) or metadata.get("provider") != "gemini":
                    raise ValueError("invalid Gemini replay metadata")
                try:
                    native = genai_types.Content.model_validate(metadata.get("content"))
                except (ValueError, TypeError):
                    raise ValueError("invalid Gemini replay content") from None
                native_calls = [p.function_call for p in native.parts or [] if p.function_call]
                if native.role != "model" or len(native_calls) != len(tool_calls or []):
                    raise ValueError("Gemini replay content does not match tool history")
                for call, tc in zip(native_calls, tool_calls or [], strict=True):
                    fn = tc["function"]
                    if call.name != fn["name"] or call.args != _parse_args(fn.get("arguments")):
                        raise ValueError("Gemini replay content does not match tool history")
                    if call.id is not None and call.id != tc.get("id"):
                        raise ValueError("Gemini replay call ID does not match tool history")
                    call_names[tc.get("id", "")] = fn["name"]
                    wire_call_ids[tc.get("id", "")] = call.id
                contents.append(native)
                continue
            if tool_calls:
                parts = []
                if msg.get("content"):
                    parts.append(genai_types.Part.from_text(text=msg["content"]))
                for tc in tool_calls:
                    fn = tc["function"]
                    call_names[tc.get("id", "")] = fn["name"]
                    wire_call_ids[tc.get("id", "")] = tc.get("id")
                    part = genai_types.Part.from_function_call(
                        name=fn["name"], args=_parse_args(fn.get("arguments"))
                    )
                    if isinstance(tc.get("id"), str) and tc["id"]:
                        if isinstance(part, dict):
                            part["function_call"]["id"] = tc["id"]
                        else:
                            part.function_call.id = tc["id"]
                    parts.append(part)
                contents.append(genai_types.Content(role="model", parts=parts))
            else:
                content = msg.get("content")
                if content:
                    part = genai_types.Part.from_text(text=content)
                    contents.append(genai_types.Content(role="model", parts=[part]))
        elif role == "tool":
            name = call_names.get(msg.get("tool_call_id", ""), "")
            part = genai_types.Part.from_function_response(
                name=name, response={"result": msg.get("content")}
            )
            history_id = msg.get("tool_call_id", "")
            call_id = wire_call_ids.get(history_id)
            if isinstance(call_id, str) and call_id:
                if isinstance(part, dict):
                    part["function_response"]["id"] = call_id
                else:
                    part.function_response.id = call_id
            contents.append(genai_types.Content(role="user", parts=[part]))

    return system_instruction, contents


def _to_gemini_tools(tools: list[dict[str, Any]]) -> list[Any]:
    declarations = []
    for tool in tools:
        fn = tool["function"]
        params = fn.get("parameters")
        kwargs: dict[str, Any] = {"name": fn["name"], "description": fn.get("description")}
        # "For function with no parameters, this can be left unset" — an empty
        # {"properties": {}} object sent as parameters_json_schema is rejected
        # by some Gemini models, so omit it rather than pass it through empty.
        if params and params.get("properties"):
            kwargs["parameters_json_schema"] = params
        declarations.append(genai_types.FunctionDeclaration(**kwargs))
    return [genai_types.Tool(function_declarations=declarations)]


class GeminiAdapter:
    def __init__(self, api_key: str | None = None, model: str = "gemini-2.0-flash") -> None:
        if genai is None:
            raise ImportError("pip install grip-browser[gemini]")
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        system_instruction, contents = _to_contents(messages)
        config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=_to_gemini_tools(tools) if tools else None,
        )
        response = await self._client.aio.models.generate_content(
            model=self._model, contents=contents, config=config
        )
        raw_usage = getattr(response, "usage_metadata", None)
        usage = (
            None
            if raw_usage is None
            else LLMUsage(
                provider="gemini",
                total_tokens=_reported_count(getattr(raw_usage, "total_token_count", None)),
                input_tokens=_reported_count(getattr(raw_usage, "prompt_token_count", None)),
                output_tokens=_reported_count(getattr(raw_usage, "candidates_token_count", None)),
                cache_read_input_tokens=_reported_count(
                    getattr(raw_usage, "cached_content_token_count", None)
                ),
                thought_tokens=_reported_count(getattr(raw_usage, "thoughts_token_count", None)),
            )
        )
        function_calls = response.function_calls
        if function_calls:
            if len(function_calls) > 1:
                raise LLMProtocolError("multiple tool calls are unsupported", usage)
            fc = function_calls[0]
            candidates = getattr(response, "candidates", None) or []
            candidates = candidates if isinstance(candidates, list) else []
            native = getattr(candidates[0], "content", None) if candidates else None
            metadata = None
            if native is not None:
                metadata = {
                    "provider": "gemini",
                    "content": native.model_dump(mode="json", exclude_none=True),
                }
            return LLMResponse(
                content=None,
                usage=usage,
                tool_call=ToolCall(name=fc.name or "", arguments=fc.args or {}, id=fc.id),
                replay_metadata=metadata,
            )
        return LLMResponse(content=response.text, tool_call=None, usage=usage)
