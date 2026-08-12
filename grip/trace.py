from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grip.errors.types import BrowserError


@dataclass
class TraceEntry:
    timestamp: float
    action: str
    input: dict[str, Any]
    output: dict[str, Any]
    tokens_consumed: int
    duration_ms: int
    error: BrowserError | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "timestamp": self.timestamp,
            "action": self.action,
            "input": self.input,
            "output": self.output,
            "tokens_consumed": self.tokens_consumed,
            "duration_ms": self.duration_ms,
        }
        if self.error:
            d["error"] = {
                "type": self.error.type.value,
                "message": self.error.message,
                "confidence": self.error.confidence,
                "recovery": [r.value for r in self.error.recovery],
            }
        return d


_REDACTED_TEXT = "[REDACTED — typed text is never persisted]"


# A Browser's Trace outlives any single Page and every action on every page
# appends to it, so an MCP server left running for hours/days would otherwise
# grow this list without bound. Cap it at a rolling window; total_tokens and
# total_duration_ms are separate running counters and stay exact regardless of
# what has aged out of `actions`.
DEFAULT_MAX_ACTIONS = 1000


class Trace:
    def __init__(self, max_actions: int = DEFAULT_MAX_ACTIONS) -> None:
        self.actions: deque[TraceEntry] = deque(maxlen=max_actions)
        self.total_tokens: int = 0
        self.total_duration_ms: int = 0
        self.errors: list[BrowserError] = []

    def add(self, entry: TraceEntry) -> None:
        # An agent types passwords. The trace is a debugging artifact that gets
        # committed, pasted into issues and shipped to logs — the one place a
        # credential must not be. Redact at entry, not at serialization, so the
        # secret never lands in memory for a caller to read off `trace.actions`.
        if entry.action == "type" and "text" in entry.input:
            entry.input = {**entry.input, "text": _REDACTED_TEXT}
        self.actions.append(entry)
        self.total_tokens += entry.tokens_consumed
        self.total_duration_ms += entry.duration_ms
        if entry.error:
            self.errors.append(entry.error)

    def to_jsonl(self, path: str) -> None:
        with Path(path).open("w") as f:
            f.writelines(json.dumps(entry.to_dict()) + "\n" for entry in self.actions)
