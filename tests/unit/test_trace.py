import json
import time
import tempfile
from pathlib import Path
from grip.trace import Trace, TraceEntry
from grip.errors.types import BrowserError, ErrorType, RecoveryAction


def make_entry(action="click", tokens=50, duration=120, error=None):
    return TraceEntry(
        timestamp=time.time(),
        action=action,
        input={"target": "button"},
        output={"success": True},
        tokens_consumed=tokens,
        duration_ms=duration,
        error=error,
    )


def test_trace_starts_empty():
    t = Trace()
    assert t.actions == []
    assert t.total_tokens == 0
    assert t.total_duration_ms == 0


def test_add_entry_updates_totals():
    t = Trace()
    t.add(make_entry(tokens=30, duration=100))
    t.add(make_entry(tokens=20, duration=200))
    assert t.total_tokens == 50
    assert t.total_duration_ms == 300
    assert len(t.actions) == 2


def test_errors_collected():
    t = Trace()
    err = BrowserError(
        type=ErrorType.ELEMENT_STALE,
        message="stale",
        confidence=0.9,
        recovery=[RecoveryAction.RE_SNAPSHOT],
    )
    t.add(make_entry(error=err))
    assert len(t.errors) == 1
    assert t.errors[0].type == ErrorType.ELEMENT_STALE


def test_trace_redacts_typed_text():
    t = Trace()
    t.add(TraceEntry(
        timestamp=1,
        action="type",
        input={"description": "password field", "text": "hunter2-secret"},
        output={"success": True},
        tokens_consumed=0,
        duration_ms=1,
    ))
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    t.to_jsonl(path)
    dumped = Path(path).read_text()
    assert "hunter2-secret" not in dumped
    assert "REDACTED" in dumped
    # Redaction happens at entry, not at serialization: the in-memory trace must
    # not hold the secret either.
    assert "hunter2-secret" not in json.dumps(t.actions[0].to_dict())


def test_trace_keeps_non_secret_type_fields():
    t = Trace()
    t.add(TraceEntry(
        timestamp=1,
        action="type",
        input={"description": "password field", "text": "s3cret", "handle": "h4"},
        output={"success": True},
        tokens_consumed=0,
        duration_ms=1,
    ))
    entry = t.actions[0].input
    assert entry["description"] == "password field"
    assert entry["handle"] == "h4"


def test_trace_leaves_other_actions_alone():
    t = Trace()
    t.add(make_entry(action="click"))
    assert t.actions[0].input == {"target": "button"}


def test_to_jsonl_writes_file():
    t = Trace()
    t.add(make_entry())
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    t.to_jsonl(path)
    lines = Path(path).read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["action"] == "click"
