from __future__ import annotations
import re
from dataclasses import dataclass, field


_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)\bsystem\s*:"),
    re.compile(r"(?i)\bassistant\s*:"),
    re.compile(r"(?i)\buser\s*:"),
    re.compile(r"(?i)(ignore|disregard)\s+(all\s+)?((previous|prior|your)\s+)?instructions?"),
    re.compile(r"(?i)forget\s+(all\s+)?(previous|your)\s+instructions?"),
    re.compile(r"(?i)\bnew\s+instructions?\s*:"),
    re.compile(r"(?i)<\s*system\s*>"),
    re.compile(r"(?i)\[INST\]"),
    re.compile(r"(?i)###\s*Instruction"),
]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Detection:
    pattern: str
    matched_text: str
    start: int
    end: int


@dataclass
class ScanResult:
    is_clean: bool
    detections: list[Detection] = field(default_factory=list)
    safe_text: str = ""


class InjectionDetector:
    def scan(self, text: str) -> ScanResult:
        detections: list[Detection] = []
        for pattern in _INJECTION_PATTERNS:
            for m in pattern.finditer(text):
                detections.append(
                    Detection(
                        pattern=pattern.pattern,
                        matched_text=m.group(),
                        start=m.start(),
                        end=m.end(),
                    )
                )

        if not detections:
            return ScanResult(is_clean=True, safe_text=text)

        safe_text = self._strip_injections(text, detections)
        return ScanResult(is_clean=False, detections=detections, safe_text=safe_text)

    def _strip_injections(self, text: str, detections: list[Detection]) -> str:
        sentences = _SENTENCE_SPLIT.split(text)
        safe_sentences = []
        for sentence in sentences:
            flagged = any(
                d.matched_text.lower() in sentence.lower() for d in detections
            )
            if not flagged:
                safe_sentences.append(sentence)
        return " ".join(safe_sentences).strip()
