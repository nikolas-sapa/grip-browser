from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RawElement:
    tag: str
    role: str
    text: str
    placeholder: str | None
    in_shadow_dom: bool
    cx: int
    cy: int
    computed_display: str
    computed_visibility: str
    computed_opacity: str
    aria_hidden: bool
    width: int
    height: int
    href: str | None = None
    handle: str = ""
    # Interaction state DISCOVER_ELEMENTS_JS's gripElementState now captures
    # (grip/cdp/shadow.py) — an agent deciding whether to click/type needs to
    # know a control is already disabled or filled before it acts, not after
    # the action silently no-ops. Mirrored onto Element in
    # grip/compression/summarizer.py, which reads these via getattr with the
    # same defaults so a RawElement built without them (a test double, an
    # older caller) degrades to "no state known" rather than erroring.
    # value is withheld for password inputs by the JS itself (see
    # _GRIP_NO_VALUE_TYPES_STATE in shadow.py) — that redaction happens
    # upstream of this field and is not duplicated here.
    disabled: bool = False
    required: bool = False
    checked: bool | None = None
    selected: bool | None = None
    value: str | None = None


# HiddenElementFilter lived here and was deleted rather than fixed. It read
# computed_display / computed_visibility / computed_opacity / aria_hidden /
# width / height, and the discovery JS populates none of them — every element
# reached it holding the dataclass defaults, so it could only ever answer
# "visible". Page instantiated it and never called it either way. Visibility is
# decided in the browser by gripIsHidden (grip/cdp/shadow.py), which is the only
# place with the layout information to decide it.
