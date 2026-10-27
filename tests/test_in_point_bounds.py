"""``edl.in_point_bounds`` is pinned to the gate it summarises (muvid#192).

Every in-point it returns must pass ``validate_edl`` with the blends either side, and
an in-point just outside its strict bounds (no edge margin) must be refused — so the
helper cannot drift from ``_validate_transition`` and the containment rule.
"""

from __future__ import annotations

import itertools

import pytest

from muvid.footage.edl import (
    EDGE_S,
    TRANSITION_SPLIT,
    EdlEntry,
    Transition,
    in_point_bounds,
    unplaced,
    validate_edl,
)

_STEP = 5e-3  # well past the gate's 1 ms tolerance


def _edit(source_in, *, span, rate, fade, next_fade):
    """A long clip, then the cut under test on clip `c`, then a long clip again."""
    t = Transition(duration_s=fade, curve="fade") if fade else None
    nt = Transition(duration_s=next_fade, curve="fade") if next_fade else None
    entries = [
        EdlEntry(0.0, 10.0, "p", source_in=2.0),
        EdlEntry(10.0, 10.0 + span, "c", transition=t, source_in=source_in, rate=rate),
        EdlEntry(10.0 + span, 30.0, "p", transition=nt, source_in=20.0),
    ]
    return entries, t, nt


def _fits_in_song_time(span, fade, next_fade) -> bool:
    """The gate's song-time rule, which no in-point can satisfy or break: the cut's
    span must hold its own blend's trail plus the next blend's lead."""
    return fade * (1 - TRANSITION_SPLIT) + next_fade * TRANSITION_SPLIT <= span


_CASES = [
    c
    for c in itertools.product(
        (0.5, 2.0, 4.5),  # span
        (1.0, 0.94, 1.08),  # rate
        (0.0, 0.4, 1.0),  # its own fade
        (0.0, 0.6, 1.0),  # the next cut's fade
        (2.6, 3.4, 6.0, 30.0),  # the clip's length
    )
    if _fits_in_song_time(c[0], c[2], c[3])
]


@pytest.mark.parametrize("span,rate,fade,next_fade,dur", _CASES)
def test_every_bound_passes_the_gate_and_one_step_outside_does_not(
    span, rate, fade, next_fade, dur
):
    places = [unplaced("p", 60.0), unplaced("c", dur)]

    def ok(source_in) -> bool:
        entries, *_ = _edit(
            source_in, span=span, rate=rate, fade=fade, next_fade=next_fade
        )
        try:
            validate_edl(entries, places, 30.0)
        except ValueError:
            return False
        return True

    _, t, nt = _edit(0.0, span=span, rate=rate, fade=fade, next_fade=next_fade)
    kw = dict(
        span_s=span, clip_duration_s=dur, rate=rate, transition=t, next_transition=nt
    )
    strict = in_point_bounds(**kw)
    if strict is None:
        # nothing fits: no in-point on a fine grid passes either
        assert not any(ok(x * _STEP) for x in range(int(dur / _STEP) + 1))
        return
    preferred = in_point_bounds(**kw, edge_s=EDGE_S)
    for bound in (*strict, *preferred):
        assert ok(round(bound, 4)), f"{bound} is inside the bounds but refused"
    assert strict[0] <= preferred[0] <= preferred[1] <= strict[1]
    assert not ok(strict[0] - _STEP) and not ok(strict[1] + _STEP)
