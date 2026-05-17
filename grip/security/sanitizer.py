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


class HiddenElementFilter:
    def is_visible(self, el: RawElement) -> bool:
        if el.computed_display == "none":
            return False
        if el.computed_visibility == "hidden":
            return False
        try:
            if float(el.computed_opacity) == 0.0:
                return False
        except (ValueError, TypeError):
            pass
        if el.aria_hidden:
            return False
        if el.width == 0 or el.height == 0:
            return False
        return True

    def filter(self, elements: list[RawElement]) -> list[RawElement]:
        return [el for el in elements if self.is_visible(el)]
