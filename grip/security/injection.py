from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Anchored so the role word opens a line or a sentence: a page writing "System:"
# as the first thing it says is framing a conversation turn, while "the system:
# value is optional" mid sentence is documentation. The unanchored version
# deleted ordinary prose and left dangling citations behind it.
_ROLE_PREFIX = r"(?:^|\n|(?<=[.!?])\s)\s*(?:system|assistant|user)\s*:"

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(_ROLE_PREFIX),
    re.compile(r"(ignore|disregard)\s+(?:the\s+|all\s+|any\s+)*"
               r"(?:previous|prior|above|earlier|your)?\s*instructions?"),
    re.compile(r"forget\s+(?:all\s+)?(?:previous|your)\s+instructions?"),
    re.compile(r"new\s+instructions?\s*:"),
    re.compile(r"<\s*system\s*>"),
    re.compile(r"\[inst\]"),
    re.compile(r"#{2,}\s*instruction"),
    # Framing payloads: these carry no imperative metaword, so the "ignore
    # instructions" family never saw them.
    re.compile(r"(?:notice|instructions?|message)\s+for\s+ai\s+(?:agents?|assistants?)"),
    re.compile(r"your\s+(?:real\s+)?task\s+has\s+changed"),
    re.compile(r"everything\s+written\s+above"),
    re.compile(r"<\|im_start\|>"),
    re.compile(r"<<sys>>"),
]

# Format-control and joiner characters. A zero-width space inside "Ig<ZWSP>nore"
# renders identically and defeats every literal pattern. Written as escapes: a
# literal invisible character here would be unreviewable.
_ZERO_WIDTH = re.compile(
    "[\u200b-\u200f\u2060-\u206f\ufeff]"
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# NFKC handles compatibility, NOT confusables: Cyrillic о (U+043E) survives it
# unchanged because it is a distinct letter, not a variant form of Latin o. The
# homoglyph bypass therefore needs its own map. Only the letters that appear in
# the pattern vocabulary are worth folding.
_CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ѕ": "s", "ԁ": "d", "ɡ": "g", "ν": "v", "ο": "o", "ρ": "p",
    "α": "a", "ϲ": "c", "ѡ": "w", "м": "m", "т": "t", "н": "h", "к": "k",
})


def _normalize(text: str) -> str:
    """Fold the text into the shape a reader actually sees.

    Confusable letters are mapped to their Latin lookalikes, zero-width
    characters dropped, case flattened. A keyword list can only catch what it can
    see; this is what makes it see the rendered string rather than the encoded
    one.
    """
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH.sub("", text)
    return text.lower().translate(_CONFUSABLES)


@dataclass
class ScanResult:
    is_clean: bool
    detections: list[str] = field(default_factory=list)
    safe_text: str = ""
    original_text: str = ""

    @property
    def was_modified(self) -> bool:
        return self.safe_text != self.original_text


class InjectionDetector:
    """Pattern filter over page text.

    ponytail: a keyword list, and it will never have full coverage — a novel
    phrasing walks straight through. It exists to catch the copy-paste payloads,
    not to be a control. The real defense is framing page content as untrusted
    data in the prompt, which the runner does.
    """

    def scan(self, text: str) -> ScanResult:
        detections = self._detect(text)
        if not detections:
            return ScanResult(is_clean=True, safe_text=text, original_text=text)
        return ScanResult(
            is_clean=False,
            detections=detections,
            safe_text=self._strip_injections(text),
            original_text=text,
        )

    def _detect(self, text: str) -> list[str]:
        # Whitespace is collapsed for matching so "ignore all\nprevious
        # instructions" is one payload rather than two innocent halves.
        flat = re.sub(r"\s+", " ", _normalize(text))
        anchored = _normalize(text)
        found: list[str] = []
        for pattern in _INJECTION_PATTERNS:
            target = anchored if pattern.pattern is _ROLE_PREFIX else flat
            if pattern.search(target) or pattern.search(anchored):
                found.append(pattern.pattern)
        return found

    def _looks_injected(self, line: str) -> bool:
        flat = re.sub(r"\s+", " ", _normalize(line))
        return any(p.search(flat) or p.search(_normalize(line))
                   for p in _INJECTION_PATTERNS)

    def _clean_line(self, line: str) -> str:
        """Drop only the sentences that trip a pattern, keeping their neighbours.

        A whole-line blank is right when the line IS the payload, but a product
        page that ends a sentence and starts an injected one on the same line
        would lose its real content too.
        """
        if not self._looks_injected(line):
            return line
        sentences = _SENTENCE_SPLIT.split(line)
        if len(sentences) == 1:
            return ""
        survivors = [s for s in sentences if not self._looks_injected(s)]
        return " ".join(survivors).strip()

    def _strip_injections(self, text: str) -> str:
        """Excise the offending sentences, keeping every line on its own line.

        The old version split the whole document on sentences and rejoined with
        spaces, destroying the paragraph structure read() cites by position. This
        keeps the line grid intact and only drops sentences inside a flagged
        line, so "Great product! System: leak. Buy now." keeps its two halves.
        """
        lines = text.split("\n")
        kept = [self._clean_line(line) for line in lines]
        # A payload spanning a line break leaves its halves individually innocent,
        # so re-check each surviving pair and blank both when the join trips.
        for i in range(len(kept) - 1):
            if not kept[i] or not kept[i + 1]:
                continue
            if self._looks_injected(f"{kept[i]} {kept[i + 1]}"):
                kept[i] = ""
                kept[i + 1] = ""
        return "\n".join(kept).strip()
