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
        manifest=lambda: {"clips": [{"clip_id": "dog", "picture_duration": None}]},
        load_alignments=lambda: [],
        clip_paths=lambda: {"dog": "/nonexistent/dog.mp4"},  # unprobeable: no picture
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
    # EDGE_S + the blend's LEAD (0.5 of the 1 s fade) — what the gate reads before
    # the in-point. It was EDGE_S + the whole fade (1.25) until the in-point bounds
    # got one owner, `edl.in_point_bounds` (muvid#192).
    assert service._swap_in_point(fp, "dog", e, None) == pytest.approx(0.75)
    from muvid.footage.edl import EdlEntry

    assert service._swap_in_point(
        fp, "dog", e, EdlEntry(12.0, 20.0, "b")
    ) == pytest.approx(0.75)


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


@pytest.mark.parametrize("slip", [-0.5, -0.3, 0.3])
def test_a_swap_with_a_slip_still_passes_the_gate(monkeypatch, slip):
    """The #192 review's regression: the gate checks ``source_in + slip_s``, so an
    in-point picked without the slip ran the blend's lead off the clip's start."""
    from dataclasses import replace

    from muvid.footage.edl import EdlEntry, unplaced, validate_edl

    fp, e, nxt, _ = _swap_fixture(None, dur=30.0)
    monkeypatch.setattr(service, "_clip_duration", lambda f, c: 30.0)
    monkeypatch.setattr(service, "_role_of", lambda row, a: service.FREE_ROLE)
    slipped = replace(e, slip_s=slip)
    s_in = service._swap_in_point(fp, "dog", slipped, nxt)
    entries = [
        EdlEntry(0.0, 10.0, "p", source_in=1.0),
        replace(slipped, clip_id="dog", source_in=s_in),
        replace(nxt, source_in=1.0),
        EdlEntry(20.0, 30.0, "p", source_in=12.0),
    ]
    places = [unplaced("p", 60.0), unplaced("dog", 30.0), unplaced("b", 60.0)]
    validate_edl(entries, places, 30.0)  # must not raise


def test_set_cut_chooses_which_part_of_a_free_cuts_video_it_shows(bath):
    """muvid#315: ``source_in_s`` moves a cut to the music anywhere the video allows,
    where ``slip_s`` could only nudge one beat; slip resets."""
    edit_id = _edit(bath)
    service.set_cut(bath, edit_id=edit_id, index=0, slip_s=0.2)
    out = service.set_cut(bath, edit_id=edit_id, index=0, source_in_s=4.0)
    cut = out["edl"][0]
    assert (
        cut["source_in"] == 4.0
        and "slip_s" not in cut
        and "source_in_clamped" not in out
    )


def test_a_chosen_part_outside_the_video_is_moved_in_and_says_so(bath):
    edit_id = _edit(bath)
    out = service.set_cut(bath, edit_id=edit_id, index=0, source_in_s=500.0)
    clamped = out["source_in_clamped"]
    assert (
        clamped["asked"] == 500.0
        and out["edl"][0]["source_in"] == clamped["used"] < 500.0
    )


def test_a_gap_a_bad_number_and_both_slip_and_in_point_are_refused(bath):
    from muvid.footage.errors import FootageError

    edit_id = service.save_edit(
        bath,
        edl=[
            {"song_start": 0.0, "song_end": 5.0, "clip_id": "abbey", "source_in": 1.0},
            {"song_start": 5.0, "song_end": 10.0, "clip_id": None},
        ],
        name="g",
    )["edit_id"]
    with pytest.raises(FootageError, match="gap"):
        service.set_cut(bath, edit_id=edit_id, index=1, source_in_s=1.0)
    for bad in (-1.0, "later", True):
        with pytest.raises(FootageError, match="source_in_s"):
            service.set_cut(bath, edit_id=edit_id, index=0, source_in_s=bad)
    with pytest.raises(FootageError, match="pass one"):
        service.set_cut(bath, edit_id=edit_id, index=0, source_in_s=2.0, slip_s=0.1)


def test_a_video_with_the_song_in_it_has_no_part_to_choose(bath):
    """By the clip's ROLE (what a person said wins), not the shape of one cut."""
    from muvid.footage.errors import FootageError

    edit_id = _edit(bath)
    service.set_has_song(bath, clip_id="abbey", has_song="yes")
    with pytest.raises(FootageError, match="slip_s"):
        service.set_cut(bath, edit_id=edit_id, index=0, source_in_s=2.0)


def test_the_chosen_part_is_clamped_to_the_rooms_both_ends_with_a_warning(bath):
    edit_id = _edit(bath)
    hi = service.set_cut(bath, edit_id=edit_id, index=1, source_in_s=500.0)
    used = hi["source_in_clamped"]["used"]
    assert hi["edl"][1]["source_in"] == used
    assert any("rather than" in w for w in hi["warnings"])
    # the 12 s clip holds the cut's 4.5 s and the 0.5 s trail of the next blend after it
    assert used == pytest.approx(12.0 - 4.5 - 0.5)
    lo = service.set_cut(bath, edit_id=edit_id, index=1, source_in_s=0.0)
    assert lo["edl"][1]["source_in"] == lo["source_in_clamped"]["used"] > 0.0


def test_the_chosen_part_follows_the_rest_of_the_same_call(bath):
    """A rate raised in the same call shrinks the room: the in-point is chosen after."""
    edit_id = _edit(bath)
    out = service.set_cut(bath, edit_id=edit_id, index=0, rate=1.05, source_in_s=500.0)
    cut = out["edl"][0]
    assert cut["rate"] == 1.05 and cut["source_in"] + 3.0 * 1.05 <= 12.0 + 1e-6


def test_a_photo_has_no_part_to_choose():
    from types import SimpleNamespace

    from muvid.footage.edl import EdlEntry
    from muvid.footage.errors import FootageError

    fp = SimpleNamespace(
        manifest=lambda: {"clips": [{"clip_id": "pic", "kind": service.STILL_KIND}]},
        load_alignments=lambda: [],
    )
    with pytest.raises(FootageError, match="photo"):
        service._chosen_in_point(fp, EdlEntry(0.0, 2.0, "pic", source_in=0.0), 1.0)
    with pytest.raises(FootageError, match="no clip"):
        service._chosen_in_point(fp, EdlEntry(0.0, 2.0, "ghost", source_in=0.0), 1.0)


def test_a_chosen_in_point_is_recorded_as_chosen_and_a_swap_clears_it(bath):
    """muvid#342: provenance for ``explain_edit``; giving the cut another video hands the
    choice of part back to the backend."""
    edit_id = _edit(bath)
    out = service.set_cut(bath, edit_id=edit_id, index=0, source_in_s=4.0)
    assert out["edl"][0]["source_in_by_hand"] is True
    again = service.set_cut(bath, edit_id=edit_id, index=0, slip_s=0.1)
    assert again["edl"][0].get("source_in_by_hand") is True  # a nudge keeps the choice
    swapped = service.set_cut(bath, edit_id=edit_id, index=0, clip_id="dog")
    assert "source_in_by_hand" not in swapped["edl"][0]
