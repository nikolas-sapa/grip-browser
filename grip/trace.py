from __future__ import annotations

import json
from dataclasses import dataclass

from grip.errors.types import BrowserError


@dataclass
class TraceEntry:
    timestamp: float
    action: str
    input: dict
    output: dict
    tokens_consumed: int
    duration_ms: int
    error: BrowserError | None = None

    def to_dict(self) -> dict:
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


class Trace:
    def __init__(self) -> None:
        self.actions: list[TraceEntry] = []
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
        with open(path, "w") as f:
            f.writelines(json.dumps(entry.to_dict()) + "\n" for entry in self.actions)
