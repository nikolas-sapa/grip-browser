import pytest
from grip.security.sanitizer import HiddenElementFilter, RawElement


def make_element(
    tag="button",
    text="Click me",
    display="block",
    visibility="visible",
    opacity="1",
    aria_hidden=False,
    width=100,
    height=30,
):
    return RawElement(
        tag=tag,
        role="button",
        text=text,
        placeholder=None,
        in_shadow_dom=False,
        cx=50,
        cy=50,
        computed_display=display,
        computed_visibility=visibility,
        computed_opacity=opacity,
        aria_hidden=aria_hidden,
        width=width,
        height=height,
    )


def test_visible_element_passes():
    f = HiddenElementFilter()
    el = make_element()
    assert f.is_visible(el)


def test_display_none_filtered():
    f = HiddenElementFilter()
    el = make_element(display="none")
    assert not f.is_visible(el)


def test_visibility_hidden_filtered():
    f = HiddenElementFilter()
    el = make_element(visibility="hidden")
    assert not f.is_visible(el)


def test_opacity_zero_filtered():
    f = HiddenElementFilter()
    el = make_element(opacity="0")
    assert not f.is_visible(el)


def test_aria_hidden_filtered():
    f = HiddenElementFilter()
    el = make_element(aria_hidden=True)
    assert not f.is_visible(el)


def test_zero_width_filtered():
    f = HiddenElementFilter()
    el = make_element(width=0)
    assert not f.is_visible(el)


def test_zero_height_filtered():
    f = HiddenElementFilter()
    el = make_element(height=0)
    assert not f.is_visible(el)


def test_filter_list_removes_hidden():
    f = HiddenElementFilter()
    elements = [make_element(), make_element(display="none"), make_element()]
    visible = f.filter(elements)
    assert len(visible) == 2
