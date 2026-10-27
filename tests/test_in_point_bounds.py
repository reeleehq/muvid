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


def _fade(seconds):
    return Transition(duration_s=seconds, curve="fade") if seconds else None


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
        (0.0, -0.3, 0.3),  # its slip
        (2.6, 3.4, 6.0, 30.0),  # the clip's length
    )
    if _fits_in_song_time(c[0], c[2], c[3])
]


@pytest.mark.parametrize("span,rate,fade,next_fade,slip,dur", _CASES)
def test_every_bound_passes_the_gate_and_one_step_outside_does_not(
    span, rate, fade, next_fade, slip, dur
):
    cut = EdlEntry(
        10.0, 10.0 + span, "c", transition=_fade(fade), rate=rate, slip_s=slip
    )
    places = [unplaced("p", 60.0), unplaced("c", dur)]

    def ok(source_in) -> bool:
        if source_in < 0:
            return False  # not a time in the clip: `_as_entry` refuses it
        entries = [
            EdlEntry(0.0, 10.0, "p", source_in=2.0),
            EdlEntry(
                10.0,
                10.0 + span,
                "c",
                transition=_fade(fade),
                source_in=source_in,
                rate=rate,
                slip_s=slip,
            ),
            EdlEntry(
                10.0 + span, 30.0, "p", transition=_fade(next_fade), source_in=20.0
            ),
        ]
        try:
            validate_edl(entries, places, 30.0)
        except ValueError:
            return False
        return True

    kw = dict(clip_duration_s=dur, next_transition=_fade(next_fade))
    strict = in_point_bounds(cut, **kw)
    if strict is None:
        # nothing fits: no in-point on a fine grid passes either
        assert not any(ok(x * _STEP) for x in range(int(dur / _STEP) + 1))
        return
    preferred = in_point_bounds(cut, **kw, edge_s=EDGE_S)
    for bound in (*strict, *preferred):
        assert ok(round(bound, 4)), f"{bound} is inside the bounds but refused"
    assert not ok(strict[0] - _STEP)
    assert not ok(strict[1] + _STEP)
    # the edge margin, exactly: as much of EDGE_S as fits, taken from both ends
    edge = min(EDGE_S, (strict[1] - strict[0]) / 2)
    assert preferred == pytest.approx((strict[0] + edge, strict[1] - edge))


@pytest.mark.parametrize("rate", (1.0, 0.94, 1.08))
@pytest.mark.parametrize("fade,next_fade", [(0.0, 0.0), (1.0, 0.0), (0.4, 1.0)])
@pytest.mark.parametrize("dur", (3.0, 6.0, 30.0))
def test_longest_span_is_where_the_edge_margin_stops_fitting(
    rate, fade, next_fade, dur
):
    """muvid#203: the planner's "can this clip hold the piece" is ``longest_span``, and
    it must be exactly where ``in_point_bounds`` stops keeping the whole edge margin —
    else the planner and the in-point it picks disagree."""
    from muvid.footage.edl import longest_span

    t, nt = _fade(fade), _fade(next_fade)
    span = longest_span(dur, rate=rate, transition=t, next_transition=nt, edge_s=EDGE_S)
    if span <= 0:
        return

    def edge_kept(s):
        cut = EdlEntry(10.0, 10.0 + s, "c", transition=t, rate=rate)
        kw = dict(clip_duration_s=dur, next_transition=nt)
        strict, kept = (
            in_point_bounds(cut, **kw),
            in_point_bounds(cut, **kw, edge_s=EDGE_S),
        )
        return kept[0] - strict[0] >= EDGE_S - 1e-9

    assert edge_kept(span) and not edge_kept(span + 0.01)


def test_a_still_starts_at_the_blends_lead_like_a_video_minus_the_edge():
    from muvid.footage.edl import still_in_point

    cut = EdlEntry(0.0, 2.0, "p", transition=_fade(1.0))
    assert still_in_point(cut) == pytest.approx(1.0 * TRANSITION_SPLIT)
    assert still_in_point(EdlEntry(0.0, 2.0, "p")) == 0.0
