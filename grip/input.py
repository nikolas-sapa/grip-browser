"""Human-shaped pointer geometry.

This is geometry, not a behavioural model. A pointer that travels in a straight
line at constant velocity is the clearest synthetic-input tell available to a
page: real hands overshoot, curve, accelerate and decelerate. The functions here
produce a curved, eased path and a randomized press dwell so the events grip
dispatches through Input.dispatchMouseEvent are not trivially separable from a
mouse.

Nothing here claims to defeat fingerprinting. It only removes the tells that are
free to remove at the CDP layer.
"""

from __future__ import annotations

import math
import random

from grip.cdp.shadow import _RESOLVE_JS

Point = tuple[int, int]

# The coordinates a snapshot recorded describe the page as it was; a reflow moves
# the target and the click lands somewhere else. Reusing discovery's own resolver
# keeps the identity check click() has always made — a stale handle returns the
# same reason string, so it raises ELEMENT_STALE exactly as the JS path does —
# and returns the element's live box instead of the remembered one.
RESOLVE_POINT_JS = """
function(handle, expectedTag, expectedText) {
""" + _RESOLVE_JS + """
  const r = gripResolve(handle, expectedTag, expectedText);
  if (!r.el) return { ok: false, reason: r.reason };
  r.el.scrollIntoView({ block: 'center', inline: 'center' });
  const b = r.el.getBoundingClientRect();
  if (b.width === 0 || b.height === 0) return { ok: false, reason: 'not_visible' };
  return {
    ok: true, reason: '',
    x: Math.round(b.left + b.width / 2),
    y: Math.round(b.top + b.height / 2),
  };
}
"""

# Below this the perpendicular offset would round to zero at every sample and
# the "curve" would be an exactly straight line again.
_MIN_OFFSET_PX = 2.0
_MAX_OFFSET_FRACTION = 0.18


def _ease_in_out(t: float) -> float:
    """Cosine ease: slow at both ends, fastest in the middle.

    Sampling the Bezier at these t values (rather than uniform t) is what makes
    the step spacing non-constant, which is the property test_path_velocity_is_
    not_constant checks.
    """
    return 0.5 - 0.5 * math.cos(math.pi * t)


def bezier_path(
    start: Point,
    end: Point,
    steps: int = 24,
    *,
    rng: random.Random | None = None,
) -> list[Point]:
    """A quadratic Bezier from start to end, sampled on an ease-in-out curve.

    The control point sits at the midpoint pushed perpendicular to the line, by
    a randomized amount, so repeated calls to the same target do not retrace the
    same arc. Pass `rng` to make a path reproducible in tests; production calls
    leave it None and vary per call.
    """
    r = rng or random.Random()
    steps = max(2, steps)

    x0, y0 = start
    x1, y1 = end
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)

    if length == 0:
        return [(int(x0), int(y0))] * steps

    # Perpendicular unit vector, scaled to a fraction of the travel distance so
    # short hops bow slightly and long sweeps bow a lot, as a hand does.
    px, py = -dy / length, dx / length
    magnitude = max(_MIN_OFFSET_PX, length * _MAX_OFFSET_FRACTION * r.uniform(0.35, 1.0))
    magnitude *= r.choice((-1.0, 1.0))

    cx = x0 + dx / 2 + px * magnitude
    cy = y0 + dy / 2 + py * magnitude

    path: list[Point] = []
    for i in range(steps):
        t = _ease_in_out(i / (steps - 1))
        inv = 1 - t
        bx = inv * inv * x0 + 2 * inv * t * cx + t * t * x1
        by = inv * inv * y0 + 2 * inv * t * cy + t * t * y1
        path.append((round(bx), round(by)))

    # Float rounding at t=0/t=1 must never leave the pointer next to the target
    # instead of on it — a click one pixel off the widget is a silent miss.
    path[0] = (int(x0), int(y0))
    path[-1] = (int(x1), int(y1))
    return path


def press_dwell(rng: random.Random | None = None) -> float:
    """Seconds to hold the button down. A zero-length press is not a human one."""
    r = rng or random.Random()
    return round(r.uniform(0.04, 0.16), 4)


def move_delay(rng: random.Random | None = None) -> float:
    """Seconds between two pointer samples along a path."""
    r = rng or random.Random()
    return round(r.uniform(0.006, 0.022), 4)
