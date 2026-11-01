"""The post-mortem of an edit, and the cutting fixes it would otherwise apologise for.

- fades START on the beat (a fade centred on its beat reads as "slightly off");
- the beat grid is carried through quiet passages (no 21 s hold at the end);
- ``explain_edit`` says, per cut, where it lands, how it changes, what picture and
  why, with flags for what is worth a look, and every clock time as a link target.
"""

from __future__ import annotations

import numpy as np
import pytest

from muvid.footage import music_cut, service
from muvid.footage.edl import TRANSITION_SPLIT, EdlEntry, Transition
from muvid.footage.explain import explain
from muvid.footage.music_cut import FreeSource, extend_grid, fill_spans
from muvid.montage.analysis import Analysis, Section


def _analysis(duration=40.0, bpm=80.0, *, beats_until=None):
    beat = 60.0 / bpm
    beats = tuple(float(t) for t in np.arange(0.5, beats_until or duration, beat))
    return Analysis(
        duration=duration, tempo_bpm=bpm, beats=beats, downbeats=beats[::4],
        # sections change on a beat, as the real ones (cut on bars) do
        sections=(Section(label="verse", start=0.0, end=beats[len(beats) // 2], energy_db=-20.0),
                  Section(label="chorus", start=beats[len(beats) // 2], end=duration, energy_db=-10.0)),
        beat_source="test", section_source="test",
    )


def _sources():
    return [FreeSource("v1", "/x/v1.mp4", duration_s=30.0), FreeSource("v2", "/x/v2.mp4", duration_s=30.0),
            FreeSource("p1", "/x/p1.jpg", kind="still")]


def _fill(**kw):
    return fill_spans("/x/s.wav", _sources(), envelope_of=lambda s: None, anchor_of=lambda s: (0.5, 0.5),
                      size_of=lambda p: (1080, 1920), canvas=(1080, 1920), **kw)


def test_fades_start_on_the_beat():
    an = _analysis()
    cut = _fill(analysis=an, archetype="ballad_dissolve")
    beats = np.asarray(an.beats)
    fades = [e for e in cut.entries if e.transition is not None]
    assert fades
    for e in fades:
        start = e.song_start - e.transition.duration_s * TRANSITION_SPLIT
        assert np.min(np.abs(beats - start)) < 1e-3, f"fade at {e.song_start} starts off the beat"


def test_the_beat_is_carried_through_a_quiet_ending():
    an = _analysis(duration=40.0, beats_until=30.0)  # the tracker went silent at 30 s
    extended, note = extend_grid(an, 40.0)
    assert extended.beats[-1] > 39.0 and "carried on" in note
    cut = _fill(analysis=an, archetype="beat_cut")
    assert max(e.song_end - e.song_start for e in cut.entries) < 8.0, "no long hold to the end"
    assert cut.report["grid_note"]


def _clips():
    return {"v1": {"name": "The abbey", "kind": "video"}, "p1": {"name": "The dog", "kind": "still"}}


def test_a_fade_centred_on_its_beat_is_said_and_flagged():
    an = _analysis(bpm=60.0)  # beats at 0.5, 1.5, 2.5 ...
    entries = [
        EdlEntry(0.0, 4.5, "v1", source_in=1.0),
        EdlEntry(4.5, 8.5, "v1", source_in=10.0, transition=Transition(0.6, "fade")),  # centred on 4.5
    ]
    out = explain(entries, analysis=an, song_duration=40.0, clips=_clips())
    cut = out["cuts"][1]
    assert "straddles_the_beat" in cut["flags"]
    assert "before the beat" in cut["text"]
    assert cut["transition"]["starts_s"] == pytest.approx(4.2)
    assert {"label": "0:04.2", "s": 4.2} in cut["times"]
    assert "centred on their beat" in out["summary"]


def test_off_the_beat_long_holds_and_photos_are_named():
    an = _analysis(bpm=60.0)
    entries = [
        EdlEntry(0.0, 1.5, "v1", source_in=0.0),
        EdlEntry(1.5, 2.2, "p1", source_in=0.0, look="null", look_spec={"name": "slow_push"}),
        EdlEntry(2.2, 20.0, "v1", source_in=5.0),  # 2.2 is not a beat; 17.8 s hold
    ]
    out = explain(entries, analysis=an, song_duration=40.0, clips=_clips())
    photo, late = out["cuts"][1], out["cuts"][2]
    assert "The dog pushes in slowly" in photo["text"]
    assert "off_the_beat" in late["flags"] and "long_hold" in late["flags"]
    assert out["cuts"][0]["text"].startswith("The video opens at 0:00.0.")


def test_a_window_keeps_the_cuts_it_overlaps_and_the_whole_summary():
    an = _analysis(bpm=60.0)
    entries = [EdlEntry(float(a), float(a + 2), "v1", source_in=float(a)) for a in range(0, 10, 2)]
    out = explain(entries, analysis=an, song_duration=10.0, clips=_clips(), window=(3.0, 5.0))
    assert [c["index"] for c in out["cuts"]] == [1, 2]
    assert out["summary"].startswith("5 shots")


@pytest.fixture
def proj(tmp_path, monkeypatch):
    from muvid.footage.workspace import FootageWorkspace

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(music_cut, "_default_analysis", lambda path: _analysis(bpm=60.0))
    p = FootageWorkspace.for_email("u@x.com").create_project("bath")
    song = tmp_path / "song.wav"
    song.write_bytes(b"RIFF-song")
    service.set_song(p, path=str(song), duration_s=40.0)
    for cid in ("v1", "v2"):
        clip = tmp_path / f"{cid}.mp4"
        clip.write_bytes(cid.encode())
        service.add_clip(p, path=str(clip), clip_id=cid, duration_s=30.0)
        service.set_has_song(p, clip_id=cid, has_song="no")
    return p


def test_explain_edit_and_the_style_choice_through_the_service(proj):
    cuts = service.propose_edit(proj, style="cuts")
    assert not any(e.get("transition") for e in cuts["edl"])
    fades = service.propose_edit(proj, style="fades")
    assert any(e.get("transition") for e in fades["edl"])
    out = service.explain_edit(proj, edit_id=fades["edit_id"])
    assert out["cuts"] and all(c["text"] for c in out["cuts"])
    assert "You chose fades" in out["summary"]
    assert not any("straddles_the_beat" in c["flags"] for c in out["cuts"])
    with pytest.raises(service.FootageError):
        service.propose_edit(proj, style="swirl", save=False)
    assert "explain_edit" in {op.name for op in service.FOOTAGE_OP_SPECS}


def test_synced_cuts_are_described_not_scolded_and_a_span_scopes_the_summary():
    from muvid.footage.edl import FootageAlignment

    an = _analysis(bpm=60.0)
    entries = [
        EdlEntry(0.0, 2.2, "", ),  # black, outside the span
        EdlEntry(2.2, 6.0, "v1"),  # synced, not on a beat
        EdlEntry(6.0, 10.0, "v1", source_in=1.0),
    ]
    a = FootageAlignment("v1", 0.0, 0.9, 30.0, (0.0, 30.0))
    out = explain(entries, analysis=an, song_duration=40.0, clips=_clips(), alignments={"v1": a}, scope=(2.2, 10.0))
    synced = out["cuts"][0]  # the window keeps cuts 1 and 2
    assert "off_the_beat" not in synced["flags"] and "plays where it was filmed" in synced["text"]
    assert out["summary"].startswith("2 shots")
    assert [c["index"] for c in out["cuts"]] == [1, 2]


def test_an_edit_whose_clip_was_removed_is_still_explained(proj):
    made = service.propose_edit(proj, style="cuts")
    service.remove_clip(proj, clip_id="v2")
    out = service.explain_edit(proj, edit_id=made["edit_id"])
    assert out["cuts"]


def test_a_weighted_edit_that_fell_back_says_so():
    """muvid#184 item 5: ``strategy: weighted`` alone would claim a score-driven edit."""
    an = _analysis(bpm=60.0)
    entries = [EdlEntry(0.0, 4.0, "v1", source_in=0.0)]
    fell_back = {"strategy": "weighted", "fallback": "best_confidence", "cause": "coverage_gap"}
    out = explain(entries, analysis=an, song_duration=4.0, clips=_clips(), selection=fell_back)
    # in words, not ids (muvid#207)
    # the title on the strategy registry (muvid#217)
    assert "the simpler rule “Best-aligned video at each moment” chose them" in out["summary"]
    assert "(the videos leave part of the song uncovered)" in out["summary"]
    assert "best_confidence" not in out["summary"] and "coverage_gap" not in out["summary"]
    relaxed = {"strategy": "weighted", "cause": "dwell_relaxed"}
    out = explain(entries, analysis=an, song_duration=4.0, clips=_clips(), selection=relaxed)
    assert "minimum was dropped" in out["summary"]
    plain = explain(
        entries, analysis=an, song_duration=4.0, clips=_clips(), selection={"strategy": "weighted"}
    )
    assert "score-driven" not in plain["summary"]


# -- muvid#20 (b): a cut showing weak footage nothing better covers --------------------


def _synced(cid, offset, dur, *, reliable=True, support=0.9, margin=0.5, spans=None):
    from muvid.footage.edl import FootageAlignment

    return FootageAlignment(
        cid, offset, 0.5, dur, (offset, offset + dur), support=support, margin=margin,
        reliable=reliable, spans=spans,
    )


def _roles(*cids, free=()):
    return {c: {"name": c, "kind": "video", "role": "to_the_music" if c in free else "synced"}
            for c in cids}


def _flag(entries, aligns, clips):
    out = explain(entries, analysis=_analysis(bpm=60.0), song_duration=40.0,
                  clips=clips, alignments=aligns)
    return out, out["cuts"][0]


def test_weak_footage_nothing_better_covers_is_flagged_with_the_failing_number():
    aligns = {"A": _synced("A", 0.0, 40.0, reliable=False, support=0.31)}
    out, cut = _flag([EdlEntry(0.0, 40.0, "A")], aligns, _roles("A"))
    assert "only_weak_footage" in cut["flags"]
    assert "support 0.31" in cut["text"] and "couldn't tell where" in cut["text"]
    assert "(at 0:00.0)" in out["summary"] and "check it first" in out["summary"]


def test_the_number_named_is_the_one_that_failed():
    """support 0.80 is a GOOD support; this clip was refused on its margin (review)."""
    aligns = {"A": _synced("A", 0.0, 40.0, reliable=False, support=0.8, margin=-0.1)}
    _, cut = _flag([EdlEntry(0.0, 40.0, "A")], aligns, _roles("A"))
    assert "margin -0.10" in cut["text"] and "support" not in cut["text"]


def test_unconfirmed_stretches_are_named_with_their_times():
    from muvid.footage.edl import MeasuredSpan

    aligns = {"A": _synced("A", 0.0, 40.0, spans=(MeasuredSpan(0.0, 15.0, 0.0, 0.8),))}
    _, cut = _flag([EdlEntry(0.0, 40.0, "A")], aligns, _roles("A"))
    assert "only_weak_footage" in cut["flags"]
    assert "from 0:15.0 to 0:40.0" in cut["text"]
    assert {"label": "0:15.0", "s": 15.0} in cut["times"]


def test_two_cameras_between_them_are_better_cover():
    weak = _synced("A", 0.0, 40.0, reliable=False)
    aligns = {"A": weak, "B": _synced("B", 0.0, 20.0), "C": _synced("C", 20.0, 20.0)}
    _, cut = _flag([EdlEntry(0.0, 40.0, "A")], aligns, _roles("A", "B", "C"))
    assert "only_weak_footage" not in cut["flags"]
    # with only B, the second half is what nothing better covers — and only that is named
    aligns = {"A": weak, "B": _synced("B", 0.0, 20.0)}
    from muvid.footage.edl import only_weak_footage

    [w] = only_weak_footage(EdlEntry(0.0, 40.0, "A"), weak, [aligns["B"]])
    assert (w.song_start, w.song_end) == (20.0, 40.0)


def test_an_alternative_is_only_better_where_its_own_sync_is_confirmed():
    from muvid.footage.edl import MeasuredSpan

    shaky_b = _synced("B", 0.0, 40.0, spans=(MeasuredSpan(0.0, 5.0, 0.0, 0.8),))
    aligns = {"A": _synced("A", 0.0, 40.0, reliable=False), "B": shaky_b}
    _, cut = _flag([EdlEntry(0.0, 40.0, "A")], aligns, _roles("A", "B"))
    assert "only_weak_footage" in cut["flags"]


def test_a_sliver_below_the_measurement_is_not_named():
    from muvid.footage.edl import MeasuredSpan

    aligns = {"A": _synced("A", 0.0, 40.0, spans=(MeasuredSpan(0.0, 15.0, 0.0, 0.8),))}
    _, cut = _flag([EdlEntry(0.0, 15.05, "A")], aligns, _roles("A"))
    assert "only_weak_footage" not in cut["flags"]


def test_good_replaceable_free_and_declared_footage_is_not_flagged():
    from muvid.footage.edl import DECLARED, FootageAlignment

    # good footage, single camera: not news
    _, cut = _flag([EdlEntry(0.0, 40.0, "A")], {"A": _synced("A", 0.0, 40.0)}, _roles("A"))
    assert "only_weak_footage" not in cut["flags"]
    # weak, but a vouched synced camera covers the same stretch: a choice, not coverage
    aligns = {"A": _synced("A", 0.0, 40.0, reliable=False), "B": _synced("B", 0.0, 40.0)}
    _, cut = _flag([EdlEntry(0.0, 40.0, "A")], aligns, _roles("A", "B"))
    assert "only_weak_footage" not in cut["flags"]
    # ...unless that camera is cut to the music, which offers no sync there
    _, cut = _flag([EdlEntry(0.0, 40.0, "A")], aligns, _roles("A", "B", free=("B",)))
    assert "only_weak_footage" in cut["flags"]
    # an alignment whose clip left the project offers nothing either
    _, cut = _flag([EdlEntry(0.0, 40.0, "A")], aligns, _roles("A"))
    assert "only_weak_footage" in cut["flags"]
    # a free cut claims no sync; a declared offset was vouched for by a person
    _, cut = _flag([EdlEntry(0.0, 10.0, "A", source_in=0.0)], aligns, _roles("A"))
    assert "only_weak_footage" not in cut["flags"]
    declared = FootageAlignment("A", 0.0, 1.0, 40.0, (0.0, 40.0), reliable=True, source=DECLARED)
    _, cut = _flag([EdlEntry(0.0, 40.0, "A")], {"A": declared}, _roles("A"))
    assert "only_weak_footage" not in cut["flags"]


def test_the_coverage_report_lists_the_same_stretches(tmp_path, monkeypatch):
    """The replies an agent reads BEFORE rendering carry it too, from the same helper."""
    aligns = [_synced("A", 0.0, 40.0, reliable=False, support=0.31), _synced("B", 0.0, 10.0)]
    report = service.coverage_report(
        [EdlEntry(0.0, 40.0, "A")], aligns, 40.0, roles={"A": "synced", "B": "synced"}
    )
    assert report["only_weak_footage"] == [
        {"clip_id": "A", "song_start": 10.0, "song_end": 40.0, "why": "unvouched",
         "measure": {"support": 0.31, "threshold": 0.5}},
    ]
    free_b = service.coverage_report(
        [EdlEntry(0.0, 40.0, "A")], aligns, 40.0, roles={"A": "synced", "B": "to_the_music"}
    )
    assert free_b["only_weak_footage"][0]["song_start"] == 0.0
