"""A swapped-in cut leaves room for the NEXT cut's blend (muvid#181)."""

from __future__ import annotations

import pytest

from muvid.footage import service


def _swap_fixture(tmp_path, *, dur, span=2.0, fade=1.0, nxt_fade=1.0):
    """A cut of `span` seconds with a `fade` blend in, followed by a cut with a
    `nxt_fade` blend; and a to-the-music clip of `dur` seconds to swap onto it."""
    from types import SimpleNamespace

    from muvid.footage.edl import EdlEntry, Transition

    e = EdlEntry(
        10.0, 10.0 + span, "a", transition=Transition(duration_s=fade, curve="fade")
    )
    nxt = EdlEntry(
        10.0 + span, 20.0, "b", transition=Transition(duration_s=nxt_fade, curve="fade")
    )
    fp = SimpleNamespace(
        manifest=lambda: {"clips": [{"clip_id": "dog"}]},
        load_alignments=lambda: [],
    )
    return fp, e, nxt, dur


def test_a_swapped_in_point_leaves_room_for_the_next_cuts_blend(monkeypatch, tmp_path):
    """muvid#181: the in-point reserves the TRAIL the next cut's blend reads past this
    cut's end, so the backend's own pick passes its own gate."""
    fp, e, nxt, _ = _swap_fixture(tmp_path, dur=0)
    for dur in (3.0, 3.4, 3.6, 4.0, 6.0, 30.0):
        monkeypatch.setattr(service, "_clip_duration", lambda f, c, d=dur: d)
        monkeypatch.setattr(service, "_role_of", lambda row, a: service.FREE_ROLE)
        try:
            s_in = service._swap_in_point(fp, "dog", e, nxt)
        except service.FootageError:
            assert dur < 2.0 + 0.5 + 0.5  # refused only when the clip cannot hold it
            continue
        assert s_in + 2.0 + 0.5 <= dur + 1e-6, f"{dur}s clip: trail not reserved"
        assert s_in >= 0.5 - 1e-6  # the cut's own lead


def test_without_a_following_blend_nothing_extra_is_reserved(monkeypatch, tmp_path):
    fp, e, _, _ = _swap_fixture(tmp_path, dur=0)
    monkeypatch.setattr(service, "_clip_duration", lambda f, c: 30.0)
    monkeypatch.setattr(service, "_role_of", lambda row, a: service.FREE_ROLE)
    assert service._swap_in_point(fp, "dog", e, None) == pytest.approx(
        1.25
    )  # EDGE_S + fade
    from muvid.footage.edl import EdlEntry

    assert service._swap_in_point(
        fp, "dog", e, EdlEntry(12.0, 20.0, "b")
    ) == pytest.approx(1.25)


def test_a_clip_too_short_for_the_cut_and_its_blends_is_refused_plainly(
    monkeypatch, tmp_path
):
    fp, e, nxt, _ = _swap_fixture(tmp_path, dur=0)
    monkeypatch.setattr(service, "_clip_duration", lambda f, c: 2.2)
    monkeypatch.setattr(service, "_role_of", lambda row, a: service.FREE_ROLE)
    with pytest.raises(service.FootageError, match="too short for this 2.00s cut"):
        service._swap_in_point(fp, "dog", e, nxt)


@pytest.mark.parametrize("dur", [3.0, 3.1, 3.5, 4.0, 5.0, 12.0])
def test_the_pick_passes_the_real_gate_whenever_it_is_not_refused(monkeypatch, dur):
    from dataclasses import replace

    from muvid.footage.edl import EdlEntry, Transition, unplaced, validate_edl

    fp, e, nxt, _ = _swap_fixture(None, dur=dur)
    monkeypatch.setattr(service, "_clip_duration", lambda f, c: dur)
    monkeypatch.setattr(service, "_role_of", lambda row, a: service.FREE_ROLE)
    try:
        s_in = service._swap_in_point(fp, "dog", e, nxt)
    except service.FootageError:
        return  # refused plainly; nothing to validate
    prev = EdlEntry(0.0, 10.0, "p", source_in=1.0)
    swapped = replace(e, clip_id="dog", source_in=s_in)
    after = replace(nxt, source_in=1.0)
    entries = [prev, swapped, after, EdlEntry(20.0, 30.0, "p", source_in=12.0)]
    placements = [unplaced("p", 60.0), unplaced("dog", dur), unplaced("b", 60.0)]
    validate_edl(entries, placements, 30.0)  # must not raise


from tests.test_music_cut import bath  # noqa: E402,F401  (the fixture, not a test)


def _edit(bath, last_in=1.0):
    fade = {"duration_s": 1.0, "curve": "fade"}
    edl = [
        {"song_start": 0.0, "song_end": 3.0, "clip_id": "abbey", "source_in": 1.0},
        {
            "song_start": 3.0,
            "song_end": 7.5,
            "clip_id": "abbey",
            "source_in": 6.0,
            "transition": fade,
        },
        {
            "song_start": 7.5,
            "song_end": 10.0,
            "clip_id": "abbey",
            "source_in": last_in,
            "transition": fade,
        },
    ]
    return service.save_edit(bath, edl=edl, name="t")["edit_id"]


def test_set_cut_swap_passes_its_own_gate_with_a_following_blend(bath):
    """muvid#181 end to end: the 6 s clip swapped onto a 4.5 s cut that the next cut
    blends out of. The old pick (1.25 s in) ran 0.25 s past the clip's end."""
    edit_id = _edit(bath)
    out = service.set_cut(bath, edit_id=edit_id, index=1, clip_id="dog")
    swapped = out["edl"][1]
    assert swapped["clip_id"] == "dog"
    assert swapped["source_in"] + 4.5 + 0.5 <= 6.0 + 1e-6


def test_set_cut_swap_chooses_the_in_point_after_the_rest_of_the_change(bath):
    """The cut as it will finally be decides the in-point: shrinking it in the same
    call must not be refused for the length it had."""
    edit_id = _edit(bath, last_in=4.0)  # room for the next cut to start earlier
    out = service.set_cut(bath, edit_id=edit_id, index=1, clip_id="dog", song_end=5.0)
    assert out["edl"][1]["clip_id"] == "dog" and out["edl"][1]["song_end"] == 5.0
