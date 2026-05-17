from __future__ import annotations
import json
from dataclasses import dataclass, field
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


class Trace:
    def __init__(self) -> None:
        self.actions: list[TraceEntry] = []
        self.total_tokens: int = 0
        self.total_duration_ms: int = 0
        self.errors: list[BrowserError] = []

    def add(self, entry: TraceEntry) -> None:
        self.actions.append(entry)
        self.total_tokens += entry.tokens_consumed
        self.total_duration_ms += entry.duration_ms
        if entry.error:
            self.errors.append(entry.error)

    def to_jsonl(self, path: str) -> None:
        with open(path, "w") as f:
            for entry in self.actions:
                f.write(json.dumps(entry.to_dict()) + "\n")
