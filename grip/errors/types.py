from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class ErrorType(Enum):
    ELEMENT_STALE = "element_stale"
    ELEMENT_NOT_FOUND = "element_not_found"
    ANTI_BOT_BLOCK = "anti_bot_block"
    AUTH_REQUIRED = "auth_required"
    NETWORK_TIMEOUT = "network_timeout"
    NAVIGATION_FAILED = "navigation_failed"
    CANVAS_ELEMENT = "canvas_element"


class RecoveryAction(Enum):
    RE_SNAPSHOT = "re_snapshot"
    RETRY = "retry"
    ROTATE_IDENTITY = "rotate_identity"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    VISION_FALLBACK = "vision_fallback"


@dataclass
class BrowserError:
    type: ErrorType
    message: str
    confidence: float
    recovery: list[RecoveryAction] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")


class GripError(Exception):
    def __init__(self, error: BrowserError) -> None:
        self.error = error
        super().__init__(f"{error.type.name}: {error.message}")  # .name = SCREAMING_SNAKE for log readability
