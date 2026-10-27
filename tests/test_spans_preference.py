"""Measured spans steer selection (muvid#16 slice 2): a clip's stretch its spans say
does not match the song is a PREFERENCE against it, like an unvouched clip — never a
refusal, never a dropped source, and nothing changes for a clip without spans."""

from __future__ import annotations

import numpy as np
import pytest

from muvid.footage import strategy as S
from muvid.footage.edl import FootageAlignment, MeasuredSpan, unverified_song_stretches


def _clip(cid, conf, *, spans=None, duration=40.0):
    return FootageAlignment(cid, 0.0, conf, duration, (0.0, duration), spans=spans)


# the stretches must be at least SELECTION_MIN_UNVERIFIED_S (10 s) long to steer selection
A_CONFIRMED_TO_15 = (MeasuredSpan(0.0, 15.0, 0.0, 0.9),)  # unverified 15-40: 25 s


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
    edl = S.select_edl(name, [a, b], 40.0)
    # B over the unverified stretch, and nothing of A past 15 s
    assert _cuts(edl)[-1] == (15.0, 40.0, "B")
    assert all(e <= 15.0 for s, e, cid in _cuts(edl) if cid == "A")


def test_an_unverified_stretch_only_one_clip_covers_is_still_chosen():
    """A preference, not a filter: dropping the only footage would make the strategy a
    second gate (the rule `_prefer_vouched` is written to)."""
    a = _clip("A", 0.9, spans=A_CONFIRMED_TO_15)
    assert _cuts(S.select_edl("best_confidence", [a], 40.0)) == [(0.0, 40.0, "A")]


def test_nothing_changes_for_clips_without_spans():
    a, b = _clip("A", 0.9), _clip("B", 0.5)
    assert _cuts(S.select_edl("best_confidence", [a, b], 40.0)) == [(0.0, 40.0, "A")]


def test_the_weighted_cut_avoids_an_unverified_stretch():
    from muvid.footage.select_score import (
        SelectionContext,
        WeightedSelectionConfig,
        run_weighted,
    )
    from tests.test_scoring_select import make_tensor

    hop, song = 0.1, 40.0
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
        config=WeightedSelectionConfig(weights={"m": 1.0}, l_max_s=50.0),
    )
    entries, meta = run_weighted([a, b], song, ctx)
    assert meta["cause"] == "optimal"
    assert [(e.clip_id, e.song_start, e.song_end) for e in entries] == [
        ("A", 0.0, 15.0),
        ("B", 15.0, 40.0),
    ]
    plain, _ = run_weighted([_clip("A", 0.9), b], song, ctx)
    assert [e.clip_id for e in plain] == ["A"]  # without spans: A throughout


def test_the_trust_tiers_are_ordered():
    """unvouched > unverified + the composite's range [0, 1], and unverified > that
    range: the DP must rank the tiers as the built-ins do (#16 slice-2 review)."""
    from muvid.footage.select_score import (
        UNVERIFIED_REWARD_PENALTY,
        UNVOUCHED_REWARD_PENALTY,
    )

    assert UNVERIFIED_REWARD_PENALTY > 1.0
    assert UNVOUCHED_REWARD_PENALTY > UNVERIFIED_REWARD_PENALTY + 1.0


def test_an_unverified_vouched_clip_beats_a_confirmed_unvouched_one():
    """The review's black hole: with equal penalties the weighted cut took the
    unvouched clip and the recovery blacked it out. Vouched first, then confirmed."""
    from muvid.footage.select_score import (
        SelectionContext,
        WeightedSelectionConfig,
        run_weighted,
    )
    from tests.test_scoring_select import make_tensor

    hop, song = 0.1, 40.0
    n = int(np.ceil(song / hop)) + 1
    t = np.arange(n) * hop
    c = FootageAlignment("C", 0.0, 0.9, 15.0, (0.0, 15.0))
    b = FootageAlignment(
        "B", 0.0, 0.9, 40.0, (0.0, 40.0), spans=(MeasuredSpan(0.0, 15.0, 0.0, 0.9),)
    )
    a = FootageAlignment("A", 15.0, 0.05, 25.0, (15.0, 40.0), reliable=False)
    lanes = {
        "C": np.where(t < 15.0, 0.9, np.nan),
        "B": np.full(n, 0.5),
        "A": np.where(t >= 15.0, 0.9, np.nan),
    }
    tensor = make_tensor([c, b, a], lanes, hop=hop, n=n)
    ctx = SelectionContext(
        tensor=tensor,
        beat_times=list(np.arange(0.5, song, 0.5)),
        config=WeightedSelectionConfig(weights={"m": 1.0}, l_max_s=50.0),
    )
    entries, _ = run_weighted([c, b, a], song, ctx)
    assert all(e.clip_id != "A" for e in entries)
    for name in ("best_confidence", "longest_take", "fewest_cuts"):
        assert all(e.clip_id != "A" for e in S.select_edl(name, [c, b, a], song))


def test_a_short_or_declared_unverified_stretch_does_not_steer():
    """Below the span edge accuracy a stretch is noise (a 0.6 s gap cut a flash into a
    confirmed take); a declared offset was vouched by a person."""
    from muvid.footage.edl import selection_unverified_stretches

    gap = (MeasuredSpan(0.0, 50.0, 0.0, 0.9), MeasuredSpan(50.6, 100.0, 0.0, 0.9))
    a = FootageAlignment("A", 0.0, 0.9, 100.0, (0.0, 100.0), spans=gap)
    assert unverified_song_stretches(a) == [(50.0, 50.6)]  # still reported
    assert selection_unverified_stretches(a) == []
    b = FootageAlignment("B", 0.0, 0.5, 100.0, (0.0, 100.0))
    assert _cuts(S.select_edl("best_confidence", [a, b], 100.0)) == [(0.0, 100.0, "A")]
    declared = FootageAlignment(
        "D", 0.0, 1.0, 40.0, (0.0, 40.0), spans=A_CONFIRMED_TO_15, source="declared"
    )
    assert selection_unverified_stretches(declared) == []


def test_the_span_edge_accuracy_is_mixings_window():
    pytest.importorskip("mixing.audio")
    from mixing.audio.audio_ops import SPAN_WINDOW_S

    from muvid.footage.edl import SPAN_EDGE_ACCURACY_S

    assert SPAN_EDGE_ACCURACY_S == SPAN_WINDOW_S


# -- muvid#241: a finer threshold, and a warning where the auto edit keeps a stretch ----


def test_the_18_s_end_of_a_take_that_stopped_matching_now_steers():
    """#16's own example, which the 20 s threshold dropped."""
    a = FootageAlignment(
        "A", 0.0, 0.9, 78.0, (0.0, 78.0), spans=(MeasuredSpan(0.0, 60.0, 0.0, 0.9),)
    )
    b = FootageAlignment("B", 0.0, 0.5, 78.0, (0.0, 78.0))
    assert _cuts(S.select_edl("best_confidence", [a, b], 78.0)) == [
        (0.0, 60.0, "A"),
        (60.0, 78.0, "B"),
    ]


def test_close_short_stretches_merge_and_a_lone_short_one_does_not_steer():
    from muvid.footage.edl import SELECTION_MIN_UNVERIFIED_S, selection_unverified_stretches

    h = SELECTION_MIN_UNVERIFIED_S
    # two stretches of 0.6h, h/4 apart: one stretch of 1.45h
    spans = (
        MeasuredSpan(0.0, 30.0, 0.0, 0.9),
        MeasuredSpan(30.0 + 0.6 * h, 30.0 + 0.85 * h, 0.0, 0.9),
        MeasuredSpan(30.0 + 1.45 * h, 100.0, 0.0, 0.9),
    )
    a = FootageAlignment("A", 0.0, 0.9, 100.0, (0.0, 100.0), spans=spans)
    assert selection_unverified_stretches(a) == [(30.0, 30.0 + 1.45 * h)]
    lone = (MeasuredSpan(0.0, 30.0, 0.0, 0.9), MeasuredSpan(30.0 + 0.9 * h, 100.0, 0.0, 0.9))
    b = FootageAlignment("B", 0.0, 0.9, 100.0, (0.0, 100.0), spans=lone)
    assert selection_unverified_stretches(b) == []


def test_the_auto_edit_warns_where_it_still_uses_an_unverified_stretch():
    from muvid.footage.edl import EdlEntry
    from muvid.footage.service import _unverified_notes

    a = _clip("A", 0.9, spans=A_CONFIRMED_TO_15)  # unverified 15-40
    [note] = _unverified_notes([EdlEntry(0.0, 40.0, "A")], [a])
    assert "25.0 s of clip 'A' at 15.0-40.0 s" in note
    # a cut that avoids it, a gap, and a cut to the music (its own source moment) do not
    assert _unverified_notes([EdlEntry(0.0, 15.0, "A"), EdlEntry(15.0, 40.0, "")], [a]) == []
    assert _unverified_notes([EdlEntry(15.0, 40.0, "A", source_in=0.0)], [a]) == []
    # the edit the strategy builds over A alone carries it
    entries = S.select_edl("best_confidence", [a], 40.0)
    assert len(_unverified_notes(entries, [a])) == 1


def test_propose_edit_reports_the_unverified_stretch_it_kept(tmp_path, monkeypatch):
    pytest.importorskip("nw")
    from muvid.footage import service
    from muvid.footage.workspace import FootageWorkspace

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data"))
    fp = FootageWorkspace.for_email("u@x.com").create_project("p")
    song = tmp_path / "song.wav"
    song.write_bytes(b"RIFF-song")
    service.set_song(fp, path=str(song), duration_s=40.0)
    clip = tmp_path / "A.mp4"
    clip.write_bytes(b"A")
    service.add_clip(fp, path=str(clip), clip_id="A", duration_s=40.0)
    fp.save_alignments([_clip("A", 0.9, spans=A_CONFIRMED_TO_15)])
    out = service.propose_edit(fp)
    assert any("of clip 'A' at 15.0-40.0 s" in w for w in out["warnings"]), out["warnings"]
