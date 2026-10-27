"""Measured spans steer selection (muvid#16 slice 2): a clip's stretch its spans say
does not match the song is a PREFERENCE against it, like an unvouched clip — never a
refusal, never a dropped source, and nothing changes for a clip without spans."""

from __future__ import annotations

import numpy as np
import pytest

from muvid.footage import strategy as S
from muvid.footage.edl import FootageAlignment, MeasuredSpan, unverified_song_stretches


def _clip(cid, conf, *, spans=None, duration=30.0):
    return FootageAlignment(cid, 0.0, conf, duration, (0.0, duration), spans=spans)


A_CONFIRMED_TO_15 = (MeasuredSpan(0.0, 15.0, 0.0, 0.9),)


def _cuts(edl):
    return [(e.song_start, e.song_end, e.clip_id) for e in edl]


def test_unverified_song_stretches_are_on_the_song_timeline():
    a = FootageAlignment(
        "c", 10.0, 0.9, 30.0, (10.0, 40.0), spans=(MeasuredSpan(0.0, 20.0, 10.0, 0.9),)
    )
    assert unverified_song_stretches(a) == [(30.0, 40.0)]
    assert unverified_song_stretches(_clip("x", 0.9)) == []  # not measured


@pytest.mark.parametrize("name", ["best_confidence", "longest_take", "fewest_cuts"])
def test_every_built_in_prefers_a_confirmed_clip_over_an_unverified_stretch(name):
    a = _clip("A", 0.9, spans=A_CONFIRMED_TO_15)  # better aligned, but unverified 15-30
    b = _clip("B", 0.5)
    edl = S.select_edl(name, [a, b], 30.0)
    # B over the unverified stretch, and nothing of A past 15 s
    assert _cuts(edl)[-1] == (15.0, 30.0, "B")
    assert all(e <= 15.0 for s, e, cid in _cuts(edl) if cid == "A")


def test_an_unverified_stretch_only_one_clip_covers_is_still_chosen():
    """A preference, not a filter: dropping the only footage would make the strategy a
    second gate (the rule `_prefer_vouched` is written to)."""
    a = _clip("A", 0.9, spans=A_CONFIRMED_TO_15)
    assert _cuts(S.select_edl("best_confidence", [a], 30.0)) == [(0.0, 30.0, "A")]


def test_nothing_changes_for_clips_without_spans():
    a, b = _clip("A", 0.9), _clip("B", 0.5)
    assert _cuts(S.select_edl("best_confidence", [a, b], 30.0)) == [(0.0, 30.0, "A")]


def test_the_weighted_cut_avoids_an_unverified_stretch():
    from muvid.footage.select_score import (
        SelectionContext,
        WeightedSelectionConfig,
        run_weighted,
    )
    from tests.test_scoring_select import make_tensor

    hop, song = 0.1, 30.0
    n = int(np.ceil(song / hop)) + 1
    a = _clip("A", 0.9, spans=A_CONFIRMED_TO_15)
    b = _clip("B", 0.9)
    # A scores a little better everywhere: only the unverified stretch moves the cut
    tensor = make_tensor(
        [a, b], {"A": np.full(n, 0.8), "B": np.full(n, 0.6)}, hop=hop, n=n
    )
    ctx = SelectionContext(
        tensor=tensor,
        beat_times=list(np.arange(0.5, song, 0.5)),
        config=WeightedSelectionConfig(weights={"m": 1.0}, l_max_s=40.0),
    )
    entries, meta = run_weighted([a, b], song, ctx)
    assert meta["cause"] == "optimal"
    assert [(e.clip_id, e.song_start, e.song_end) for e in entries] == [
        ("A", 0.0, 15.0),
        ("B", 15.0, 30.0),
    ]
    plain, _ = run_weighted([_clip("A", 0.9), b], song, ctx)
    assert [e.clip_id for e in plain] == ["A"]  # without spans: A throughout
