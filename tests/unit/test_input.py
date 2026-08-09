import random
from unittest.mock import AsyncMock, MagicMock

import pytest

from grip.compression.summarizer import Element, PageSnapshot
from grip.errors.types import ErrorType, GripError
from grip.page import Page
from grip.trace import Trace


def test_bezier_path_is_not_a_straight_line():
    from grip.input import bezier_path
    path = bezier_path((0, 0), (100, 0), steps=20)
    ys = [y for _, y in path]
    assert max(abs(y) for y in ys) > 0, "path was perfectly straight"


def test_bezier_path_starts_and_ends_on_target():
    from grip.input import bezier_path
    path = bezier_path((5, 5), (200, 120), steps=16)
    assert path[0] == (5, 5)
    assert path[-1] == (200, 120)


def test_path_velocity_is_not_constant():
    """Constant-velocity motion is the single clearest synthetic-input tell."""
    from grip.input import bezier_path
    path = bezier_path((0, 0), (300, 0), steps=30)
    gaps = [abs(path[i + 1][0] - path[i][0]) for i in range(len(path) - 1)]
    assert len(set(gaps)) > 3, "every step advanced by the same amount"


def test_path_is_reproducible_with_a_seeded_rng():
    from grip.input import bezier_path
    a = bezier_path((0, 0), (50, 50), rng=random.Random(7))
    b = bezier_path((0, 0), (50, 50), rng=random.Random(7))
    assert a == b


def test_unseeded_paths_vary_between_calls():
    """Production paths must not be identical, or the curve is itself a tell."""
    from grip.input import bezier_path
    runs = {tuple(bezier_path((0, 0), (400, 200))) for _ in range(8)}
    assert len(runs) > 1


def test_curve_never_degenerates_to_zero_offset():
    """A rounded-to-zero offset would make the straight-line test flaky, not red."""
    from grip.input import bezier_path
    for seed in range(50):
        path = bezier_path((0, 0), (120, 0), steps=12, rng=random.Random(seed))
        assert max(abs(y) for _, y in path) > 0, f"degenerate curve at seed {seed}"


def test_dwell_delay_stays_in_a_human_band():
    from grip.input import press_dwell
    values = [press_dwell(random.Random(s)) for s in range(40)]
    assert all(0.02 <= v <= 0.25 for v in values)
    assert len(set(values)) > 1


def _make_safe_page():
    engine = MagicMock()
    engine.send = AsyncMock(return_value={})
    return Page(engine=engine, trace=Trace(), safe=True)


@pytest.mark.asyncio
async def test_safe_mode_blocks_click_at():
    page = _make_safe_page()
    with pytest.raises(GripError) as exc:
        await page.click_at(10, 10)
    assert exc.value.error.type == ErrorType.SAFE_MODE_VIOLATION


@pytest.mark.asyncio
async def test_safe_mode_blocks_drag():
    page = _make_safe_page()
    with pytest.raises(GripError) as exc:
        await page.drag((0, 0), (10, 10))
    assert exc.value.error.type == ErrorType.SAFE_MODE_VIOLATION


@pytest.mark.asyncio
async def test_click_at_dispatches_moves_before_press():
    engine = MagicMock()
    engine.send = AsyncMock(return_value={})
    page = Page(engine=engine, trace=Trace())
    await page.click_at(100, 60, human=True)
    types = [
        c.args[1]["type"]
        for c in engine.send.call_args_list
        if c.args[0] == "Input.dispatchMouseEvent"
    ]
    assert types.count("mouseMoved") > 1, "no pointer motion before the click"
    assert types[-2:] == ["mousePressed", "mouseReleased"]


@pytest.mark.asyncio
async def test_click_at_without_human_sends_no_motion():
    engine = MagicMock()
    engine.send = AsyncMock(return_value={})
    page = Page(engine=engine, trace=Trace())
    await page.click_at(100, 60, human=False)
    types = [
        c.args[1]["type"]
        for c in engine.send.call_args_list
        if c.args[0] == "Input.dispatchMouseEvent"
    ]
    assert types == ["mousePressed", "mouseReleased"]


@pytest.mark.asyncio
async def test_click_at_is_traced():
    engine = MagicMock()
    engine.send = AsyncMock(return_value={})
    page = Page(engine=engine, trace=Trace())
    await page.click_at(12, 34)
    actions = [e.action for e in page._trace.actions]
    assert "click_at" in actions


@pytest.mark.asyncio
async def test_drag_holds_the_button_across_the_path():
    engine = MagicMock()
    engine.send = AsyncMock(return_value={})
    page = Page(engine=engine, trace=Trace())
    await page.drag((0, 0), (200, 0))
    events = [
        c.args[1]
        for c in engine.send.call_args_list
        if c.args[0] == "Input.dispatchMouseEvent"
    ]
    assert events[0]["type"] == "mousePressed"
    assert events[-1]["type"] == "mouseReleased"
    middle = events[1:-1]
    assert all(e["type"] == "mouseMoved" for e in middle)
    # A drag with the button released mid-path is not a drag at all.
    assert all(e.get("button") == "left" for e in middle)


def _snapshot_page(engine):
    page = Page(engine=engine, trace=Trace())
    page._current_snapshot = PageSnapshot(
        version=1, url="https://x.test", title="t",
        elements=[Element(
            index=0, tag="button", role="button", text="Buy",
            placeholder=None, in_shadow_dom=False, cx=10, cy=10,
            ref="e1", handle="h1",
        )],
        text_content="", tokens_estimated=0,
    )
    return page


@pytest.mark.asyncio
async def test_human_click_uses_pointer_events_not_the_js_click():
    engine = MagicMock()
    engine.send = AsyncMock(return_value={
        "result": {"value": {"ok": True, "reason": "", "x": 140, "y": 90}}
    })
    page = _snapshot_page(engine)
    await page.click("Buy", human=True)
    pressed = [
        c.args[1]
        for c in engine.send.call_args_list
        if c.args[0] == "Input.dispatchMouseEvent" and c.args[1]["type"] == "mousePressed"
    ]
    assert pressed and (pressed[0]["x"], pressed[0]["y"]) == (140, 90)
    evaluated = " ".join(
        c.args[1].get("expression", "")
        for c in engine.send.call_args_list
        if c.args[0] == "Runtime.evaluate"
    )
    assert "r.el.click()" not in evaluated, "human path fell through to the JS click"


@pytest.mark.asyncio
async def test_human_click_still_raises_on_a_stale_element():
    """The coordinate path must not drop the staleness guarantee click() gives."""
    engine = MagicMock()
    engine.send = AsyncMock(return_value={
        "result": {"value": {"ok": False, "reason": "identity_mismatch"}}
    })
    page = _snapshot_page(engine)
    with pytest.raises(GripError) as exc:
        await page.click("Buy", human=True)
    assert exc.value.error.type == ErrorType.ELEMENT_STALE
    moves = [
        c for c in engine.send.call_args_list if c.args[0] == "Input.dispatchMouseEvent"
    ]
    assert not moves, "clicked a stale element anyway"


@pytest.mark.asyncio
async def test_human_click_traces_as_click():
    engine = MagicMock()
    engine.send = AsyncMock(return_value={
        "result": {"value": {"ok": True, "reason": "", "x": 5, "y": 6}}
    })
    page = _snapshot_page(engine)
    await page.click("Buy", human=True)
    assert "click" in [e.action for e in page._trace.actions]
