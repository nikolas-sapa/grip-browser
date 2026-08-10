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


# HiddenElementFilter lived here and was deleted rather than fixed. It read
# computed_display / computed_visibility / computed_opacity / aria_hidden /
# width / height, and the discovery JS populates none of them — every element
# reached it holding the dataclass defaults, so it could only ever answer
# "visible". Page instantiated it and never called it either way. Visibility is
# decided in the browser by gripIsHidden (grip/cdp/shadow.py), which is the only
# place with the layout information to decide it.
