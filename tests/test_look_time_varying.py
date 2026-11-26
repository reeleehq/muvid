"""A moving look declares itself, so the assembler can keep its clock (muvid#73, #376).

The behaviour is real and measured here rather than quoted: a transitioned
boundary renders as a separate two-input invocation whose inputs are
input-side-seeked to the blend window, and input-side ``-ss`` rebases the filter
timeline to 0 — so a part rendered on its own clock starts a moving look's ramp
AGAIN. ``test_the_ramp_really_does_restart_on_a_blended_boundary`` is that
measurement, against decoded pixels.

muvid#73 answered it with a declaration (the EDL says which kind a look is,
because the seam is a bare string and muvid cannot tell a punch from a grade by
looking at it) and a warning. muvid#376 replaced the warning with the fix: every
part of a cut that runs on the clock is fed from the cut's first on-screen frame,
runs the look over that whole run and is trimmed afterwards, so the move carries
on through the blend and the fragment is never rewritten (``looks``' rule 27
still holds). ``test_a_photos_move_carries_on_through_the_fade`` is the
acceptance, with the unfixed render as its positive control;
``test_rewinding_never_moves_the_footage_in_time`` pins that the rewind changes
the look's clock and nothing else.

A static look (and an undeclared moving one) is untouched: its parts render
exactly as before, at no extra decode.
"""

from __future__ import annotations

import subprocess
import warnings

import pytest

from muvid.footage.assemble import _part_filter, _part_plan
from muvid.footage.edl import (
    AssemblyCut,
    CropWindow,
    EdlEntry,
    FootageAlignment,
    Transition,
    derive_cuts,
    validate_edl,
)
from muvid.footage.look import (
    LookFragment,
    chain,
    is_time_varying,
    motion,
    punch_in,
    punch_in_cuts,
    stylize,
)
from tests.ffmpeg_support import needs_ffmpeg

SONG_DUR = 20.0
_A = FootageAlignment("A", 0.0, 0.9, 20.0, (0.0, 20.0))
_GREY = "hue=s=0"
_PUNCH = punch_in(canvas=(640, 360), fps=25, duration_s=3.0)


def _cut(**kw) -> AssemblyCut:
    base = dict(
        song_start=0.0, song_end=4.0, clip_id="A", clip_in=0.0, clip_path="/tmp/a.mp4"
    )
    return AssemblyCut(**{**base, **kw})


def _plan_warnings(cuts, fps=25):
    """Every RuntimeWarning ``_part_plan`` raises for these cuts, as strings."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _part_plan(cuts, fps)
    return [str(w.message) for w in caught]


def _restart_warnings(cuts, fps=25):
    return [m for m in _plan_warnings(cuts, fps) if "time-varying look" in m]


# -- the measurement the warning is about ------------------------------------


@needs_ffmpeg
def test_the_ramp_really_does_restart_on_a_blended_boundary(tmp_path):
    """muvid#73, reproduced against DECODED pixels before anything is claimed.

    A 3.0 s cut at 25 fps, a 0.4 s fade after it, ``punch_in(zoom=1.12)``. Each
    part is rendered twice — with the look and without it — and compared to its
    OWN unlooked twin, because the two parts show different source frames and
    comparing them to each other would measure the footage, not the zoom.

    The solo part's last frame is drawn at zoom 1.109 and differs from its twin
    by tens of levels. The blend part's first frame is drawn at zoom 1.000 and is
    indistinguishable from having no punch at all — which is the bug: the move
    ran to 1.109 and was then redrawn from the start.
    """
    w, h, fps = 320, 180, 25
    src = tmp_path / "a.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={w}x{h}:rate={fps}:d=6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            str(src),
        ],
        check=True,
        capture_output=True,
    )
    look = punch_in(canvas=(w, h), fps=fps, duration_s=3.0)
    a = _cut(song_end=3.0, clip_path=str(src), look=look, look_time_varying=True)
    b = _cut(
        song_start=3.0,
        song_end=6.0,
        clip_id="B",
        clip_path=str(src),
        transition=Transition(0.4, "fade"),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        plan = _part_plan([a, b], fps)
    solo, blend = plan[0], plan[1]
    assert (solo.kind, blend.kind) == ("solo", "xfade")

    def render(name, n_frames, clip_in, look_):
        out = tmp_path / f"{name}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                f"{clip_in:.6f}",
                "-t",
                f"{3.0 + 1.0 / fps:.6f}",
                "-i",
                str(src),
                "-vf",
                _part_filter(
                    _cut(song_end=3.0, clip_path=str(src), look=look_),
                    w=w,
                    h=h,
                    fps=fps,
                ),
                "-frames:v",
                str(n_frames),
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "18",
                "-preset",
                "veryfast",
                str(out),
            ],
            check=True,
            capture_output=True,
        )
        return out

    def pixels(video, index):
        raw = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(video),
                "-vf",
                f"select=eq(n\\,{index})",
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            check=True,
            capture_output=True,
        ).stdout
        return raw

    def mean_abs_diff(x, y):
        assert len(x) == len(y) and len(x) == w * h * 3
        return sum(abs(p - q) for p, q in zip(x, y)) / len(x)

    solo_look = render("solo_look", solo.n_frames, solo.clip_in, look)
    solo_bare = render("solo_bare", solo.n_frames, solo.clip_in, None)
    # The A SIDE of the blend, seeked exactly as `_render_transition` seeks it.
    blend_look = render("blend_look", blend.n_frames, blend.prev_in, look)
    blend_bare = render("blend_bare", blend.n_frames, blend.prev_in, None)

    solo_diff = mean_abs_diff(
        pixels(solo_look, solo.n_frames - 1), pixels(solo_bare, solo.n_frames - 1)
    )
    blend_diff = mean_abs_diff(pixels(blend_look, 0), pixels(blend_bare, 0))
    assert solo_diff > 10, (
        f"the punch barely moved the solo part ({solo_diff:.2f}/255) — this test "
        "cannot show a restart it never measured a move in."
    )
    assert blend_diff < 2, (
        f"the blend's first frame differs from its unlooked twin by "
        f"{blend_diff:.2f}/255, so the ramp did NOT restart on a part rendered on "
        "its own clock, and the rewind (muvid#376) is fixing nothing."
    )


# -- the declaration ---------------------------------------------------------


def test_muvids_own_compilers_declare_what_they_emit():
    assert is_time_varying(punch_in(canvas=(640, 360), fps=25, duration_s=3.0))
    assert is_time_varying(
        motion(
            [(0.0, CropWindow(0, 0, 1, 1)), (2.0, CropWindow(0.2, 0.2, 0.6, 0.6))],
            canvas=(640, 360),
            fps=25,
        )
    )
    # …and the fragment is still a plain string everywhere else.
    assert punch_in(canvas=(640, 360), fps=25, duration_s=3.0).startswith("zoompan=")
    assert isinstance(_PUNCH, str)


@needs_ffmpeg
def test_stylize_answers_from_the_compiled_plan_not_from_an_assumption():
    """A grade is static; a ``motion`` step and a SPANNED step are not.

    The obvious reading — "stylize is the grade door, so it is always static" —
    is wrong twice, and both wrong cases are reachable from ``stylize`` alone.
    """
    import looks

    from muvid.footage.look import stylize

    grade = stylize(
        looks.Look(steps=(looks.Effect(name="saturation", params={"amount": 0.0}),)),
        canvas=(640, 360),
        fps=25,
        duration_s=3.0,
    )
    assert not is_time_varying(grade)

    moving = stylize(
        looks.Look(
            steps=(
                looks.Effect(
                    name="motion",
                    params={
                        "keyframes": [(0.0, (0, 0, 1, 1)), (2.0, (0.2, 0.2, 0.6, 0.6))]
                    },
                ),
            )
        ),
        canvas=(640, 360),
        fps=25,
        duration_s=3.0,
    )
    assert "in_time" in moving, "the premise: the motion effect ramps on the clock"
    assert is_time_varying(moving)

    spanned = stylize(
        looks.Look(steps=(looks.Effect(name="blur", at=looks.Span(0.5, 1.5)),)),
        canvas=(640, 360),
        fps=25,
        duration_s=3.0,
    )
    assert "enable=" in spanned, "the premise: a span compiles to enable='between(t…)'"
    assert is_time_varying(spanned)


@needs_ffmpeg
@pytest.mark.parametrize("name, moving", [("grain", True), ("contrast", False)])
def test_stylize_reads_time_varying_off_the_compiled_plan(name, moving):
    """No effect-name list here: ``grain`` (muvid#180) is moving because its
    implementation declares it, so a new clock-reading ``looks`` effect is picked
    up without anyone editing muvid."""
    looks = pytest.importorskip("looks")
    frag = stylize(
        looks.Look(steps=(looks.Effect(name=name),)),
        canvas=(640, 360),
        fps=25,
        duration_s=3.0,
    )
    assert is_time_varying(frag) is moving


def test_impl_ref_timeline_is_not_this_property():
    """The near-miss worth pinning: ``ImplRef.timeline`` gets every row backwards.

    It says the implementation supports ffmpeg's ``enable=`` option. ``motion``
    — the one moving effect — declares ``False``, and the static grades declare
    ``True``, so a reader reaching for it as "is this time-varying?" would
    produce exactly the inverse classification.
    """
    looks = pytest.importorskip("looks")

    by_effect = {
        e: {
            i.timeline
            for i in looks.REGISTRY.implementations(e)
            if i.backend == "ffmpeg"
        }
        for e in ("motion", "blur", "gamma")
    }
    assert by_effect["motion"] == {False}
    assert by_effect["blur"] == {True} and by_effect["gamma"] == {True}


def test_a_fragment_survives_copy_and_pickle():
    """Not free, and CI runs no doctests — so the guard lives here.

    ``str`` subclasses are reconstructed through ``__new__``, so without
    ``__getnewargs_ex__`` both ``copy.deepcopy`` and ``pickle`` raise
    ``TypeError: __new__() missing 1 required keyword-only argument`` (measured).
    An ``EdlEntry`` carrying one is an ordinary dataclass a caller may well copy.
    """
    import copy
    import pickle

    frag = LookFragment("zoompan=d=1:s=64x48:fps=25", time_varying=True)
    assert copy.deepcopy(frag).time_varying is True
    assert pickle.loads(pickle.dumps(frag)) == frag
    assert pickle.loads(pickle.dumps(frag)).time_varying is True

    entry = EdlEntry(0.0, 4.0, "A", look=frag, look_time_varying=True)
    assert copy.deepcopy(entry) == entry


def test_chain_ors_the_declarations():
    moving = LookFragment("zoompan=d=1:s=64x48:fps=25", time_varying=True)
    assert chain(_GREY, moving).time_varying
    assert chain(moving, _GREY).time_varying  # order must not matter
    assert not chain(_GREY, "unsharp=5:5:1").time_varying
    assert chain(_GREY, moving) == f"{_GREY},{moving}"


def test_punch_in_cuts_sets_the_flag_from_the_fragment():
    entries = [
        EdlEntry(0.0, 4.0, "A"),
        EdlEntry(4.0, 8.0, "B"),
        EdlEntry(8.0, 12.0, ""),
    ]
    out = punch_in_cuts(entries, canvas=(640, 360), fps=25, every=1)
    assert [e.look_time_varying for e in out] == [True, True, False]
    assert out[2].look is None, "a gap is left alone"
    for e in out[:2]:
        assert e.look_time_varying is True and e.look.startswith("zoompan=")


# -- the wire: field, gate, round trips --------------------------------------


def test_the_flag_survives_the_json_round_trip():
    from muvid.mcp.footage_tools import _edl_json

    caller = [
        {"song_start": 0.0, "song_end": 4.0, "clip_id": "A", "look": _GREY},
        {
            "song_start": 4.0,
            "song_end": 9.0,
            "clip_id": "A",
            "look": _PUNCH,
            "look_time_varying": True,
        },
    ]
    first = validate_edl(caller, [_A], SONG_DUR)
    returned = [_edl_json(e) for e in first]
    assert "look_time_varying" not in returned[0], "omit-when-False, so False is absent"
    assert returned[1]["look_time_varying"] is True
    second = validate_edl(returned, [_A], SONG_DUR)
    assert [e.look_time_varying for e in second] == [False, True]
    assert [_edl_json(e) for e in second] == returned


def test_the_flag_survives_the_editor_round_trip():
    pytest.importorskip("lacing")
    from muvid.footage.lacing_bridge import edl_annotations, edl_from_annotations

    entries = validate_edl(
        [
            {
                "song_start": 0.0,
                "song_end": 4.0,
                "clip_id": "A",
                "look": _PUNCH,
                "look_time_varying": True,
            }
        ],
        [_A],
        4.0,
    )
    anns = edl_annotations(entries, song_asset_id="a" * 64, attributed_to="t")
    assert anns[0].body["look_time_varying"] is True
    [back] = edl_from_annotations(anns)
    assert back["look_time_varying"] is True
    assert validate_edl([back], [_A], 4.0)[0].look_time_varying is True


def test_a_static_entry_leaves_the_editor_body_exactly_as_it_was():
    """Omit-when-FALSE, so no existing DECISION body changes shape."""
    pytest.importorskip("lacing")
    from muvid.footage.lacing_bridge import _edl_body

    assert _edl_body(EdlEntry(0.0, 4.0, "A")) == {"clip_id": "A"}
    assert _edl_body(EdlEntry(0.0, 4.0, "A", look=_GREY)) == {
        "clip_id": "A",
        "look": _GREY,
    }


def test_the_editor_read_skips_a_malformed_flag_rather_than_crashing():
    """Untrusted browser output, same posture as the look and crop reads.

    ``bool("false")`` is ``True``, so forwarding a string would arm a warning the
    caller asked to be off — and ``_as_entry`` would then RAISE on it, turning an
    editor bug into a refused export.
    """
    pytest.importorskip("lacing")
    from muvid.footage.lacing_bridge import edl_annotations, edl_from_annotations

    entries = validate_edl(
        [
            {
                "song_start": 0.0,
                "song_end": 4.0,
                "clip_id": "A",
                "look": _PUNCH,
                "look_time_varying": True,
            }
        ],
        [_A],
        4.0,
    )
    anns = edl_annotations(entries, song_asset_id="a" * 64, attributed_to="t")
    anns[0].body["look_time_varying"] = "false"
    [back] = edl_from_annotations(anns)
    assert "look_time_varying" not in back


def test_a_non_bool_flag_raises_rather_than_being_coerced():
    for bad in ("false", 1, 0, {}):
        with pytest.raises(ValueError, match="look_time_varying is malformed"):
            validate_edl(
                [
                    {
                        "song_start": 0.0,
                        "song_end": 4.0,
                        "clip_id": "A",
                        "look": _GREY,
                        "look_time_varying": bad,
                    }
                ],
                [_A],
                4.0,
            )


def test_the_flag_without_a_look_is_refused():
    with pytest.raises(ValueError, match="carries no look"):
        validate_edl(
            [
                {
                    "song_start": 0.0,
                    "song_end": 4.0,
                    "clip_id": "A",
                    "look_time_varying": True,
                }
            ],
            [_A],
            4.0,
        )


def test_the_flag_reaches_the_assembly_cut():
    entries = validate_edl(
        [
            {
                "song_start": 0.0,
                "song_end": 4.0,
                "clip_id": "A",
                "look": _PUNCH,
                "look_time_varying": True,
            }
        ],
        [_A],
        4.0,
    )
    [cut] = derive_cuts(entries, [_A], {"A": "/tmp/a.mp4"})
    assert cut.look_time_varying is True
    assert AssemblyCut(0.0, 1.0, "A", 0.0, "/x").look_time_varying is False


# -- the fix: one clock per cut (muvid#376) ----------------------------------


def _fade(i, start, end, **kw):
    return _cut(
        song_start=start,
        song_end=end,
        clip_id="ABC"[i],
        transition=Transition(0.4, "fade") if i else None,
        **kw,
    )


def _plan(cuts, fps=25):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _part_plan(cuts, fps)


def test_every_part_of_a_moving_cut_counts_from_its_first_on_screen_frame():
    """A -> B -> C, fades of 10 frames (5 + 5) at 25 fps, the move on B.

    B is on screen from its incoming blend's first frame. That blend is B's
    frame 0 (``look_from`` 0), its solo starts 10 frames in, and the outgoing
    blend starts where the solo ends: 5 (head) + 100 (its span) - 5 (what C's
    blend takes) = 100. Those three numbers are the continuity.
    """
    cuts = [
        _fade(0, 0.0, 4.0),
        _fade(1, 4.0, 8.0, look=_PUNCH, look_time_varying=True),
        _fade(2, 8.0, 12.0),
    ]
    plan = _plan(cuts)
    assert [p.kind for p in plan] == ["solo", "xfade", "solo", "xfade", "solo"]
    _, b_in, b_solo, c_in, _ = plan
    assert b_in.look_from == 0 and b_in.prev_look_from == 0  # A does not move
    assert b_solo.look_from == 10
    assert c_in.prev_look_from == b_solo.look_from + b_solo.n_frames == 100
    assert c_in.look_from == 0  # C does not move
    assert all(p.look_from == 0 for p in (plan[0], plan[4]))


def test_the_outgoing_side_counts_from_the_cuts_first_frame_without_a_head():
    cuts = [_fade(0, 0.0, 3.0, look=_PUNCH, look_time_varying=True), _fade(1, 3.0, 6.0)]
    solo, blend, _ = _plan(cuts)
    assert solo.look_from == 0
    assert blend.prev_look_from == solo.n_frames == 70


@pytest.mark.parametrize(
    "kw, why",
    [
        (dict(look=_GREY), "a static look"),
        (dict(look=_PUNCH), "a moving look the caller did not declare"),
        (dict(), "no look at all"),
        (dict(look_time_varying=True), "the flag with no look to describe"),
        (dict(crop=CropWindow(0, 0, 0.5, 0.5)), "a fixed crop"),
    ],
)
def test_what_renders_exactly_as_before(kw, why):
    """``look_from == 0`` everywhere is the historical plan, byte for byte."""
    cuts = [_fade(0, 0.0, 4.0, **kw), _fade(1, 4.0, 8.0, **kw), _fade(2, 8.0, 12.0)]
    plan = _plan(cuts)
    assert all(p.look_from == 0 and p.prev_look_from == 0 for p in plan), why


def test_a_moving_crop_keeps_its_clock_too():
    """``crop_end`` ramps in ``t`` like a look does, so it restarted the same way."""
    pan = dict(crop=CropWindow(0, 0, 0.5, 0.5), crop_end=CropWindow(0.5, 0.5, 0.5, 0.5))
    _, blend, solo = _plan([_fade(0, 0.0, 4.0, **pan), _fade(1, 4.0, 8.0, **pan)])
    assert blend.prev_look_from == 95 and solo.look_from == 10


def test_the_rewind_moves_the_clock_and_nothing_else():
    """Frame counts and in-points are the declaration-free plan's, exactly."""
    moving = [_fade(0, 0.0, 4.0, look=_PUNCH, look_time_varying=True)]
    moving += [_fade(1, 4.0, 8.0, look=_PUNCH, look_time_varying=True)]
    static = [_fade(0, 0.0, 4.0, look=_PUNCH), _fade(1, 4.0, 8.0, look=_PUNCH)]
    key = lambda p: (p.kind, p.n_frames, p.clip_in, p.prev_in)  # noqa: E731
    assert [key(p) for p in _plan(moving)] == [key(p) for p in _plan(static)]
    assert any(p.look_from or p.prev_look_from for p in _plan(moving))


def test_a_transition_that_rounds_away_rewinds_nothing():
    """Zero blended frames is a hard cut: one part per cut, nothing to carry."""
    cuts = [
        _cut(song_end=4.0, look=_PUNCH, look_time_varying=True),
        _cut(
            song_start=4.0,
            song_end=8.0,
            clip_id="B",
            transition=Transition(0.01, "fade"),
            look=_PUNCH,
            look_time_varying=True,
        ),
    ]
    msgs = _plan_warnings(cuts, fps=25)
    assert any("rounds to zero frames" in m for m in msgs)
    assert all(p.look_from == 0 for p in _plan(cuts))


def test_the_plan_hands_its_finding_to_the_reply_sink_as_well():
    """``warnings.warn`` reaches stderr; ``on_note`` reaches the caller.

    Both, never either, and with the SAME text. The zero-frame transition is the
    finding ``_part_plan`` still makes (the moving-look one went with muvid#376),
    so it is what keeps the sink path guarded: forwarding ``None`` instead of
    ``note`` must fail here.
    """
    cuts = [
        _cut(song_end=4.0),
        _cut(
            song_start=4.0,
            song_end=8.0,
            clip_id="B",
            transition=Transition(0.02, "fade"),
        ),
    ]
    notes = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _part_plan(cuts, 25, notes.append)
    assert notes == [str(w.message) for w in caught]
    assert len(notes) == 1 and "rounds to zero frames" in notes[0]


def test_a_path_that_holds_still_is_declared_static():
    """One window compiles to a constant crop, which never reads the clock; a
    moving declaration there would buy a re-decode of every blended video cut."""
    pytest.importorskip("looks")
    w = CropWindow(0.05, 0.05, 0.9, 0.9)
    assert not motion([(0.0, w), (3.0, w)], canvas=(640, 360), fps=25).time_varying
    assert motion(
        [(0.0, CropWindow(0, 0, 1, 1)), (3.0, w)], canvas=(640, 360), fps=25
    ).time_varying


def test_the_trim_comes_after_the_look_and_only_when_asked():
    cut = _cut(look=_PUNCH, look_time_varying=True)
    plain = _part_filter(cut, w=640, h=360, fps=25)
    assert "trim" not in plain, "look_from=0 must leave the chain as it was"
    chain_ = _part_filter(
        cut, w=640, h=360, fps=25, look_from=7, tail=",format=yuv420p"
    )
    trim = ",trim=start_frame=7,setpts=PTS-STARTPTS,"
    assert trim in chain_
    assert chain_.index(_PUNCH) < chain_.index(trim) < chain_.index("setparams")
    assert chain_.endswith(",format=yuv420p")


def test_the_plan_no_longer_warns_about_a_moving_look():
    """The muvid#73 warning described a restart that no longer happens."""
    cuts = [
        _fade(0, 0.0, 4.0, look=_PUNCH, look_time_varying=True),
        _fade(1, 4.0, 8.0, look=_PUNCH, look_time_varying=True),
    ]
    assert _plan_warnings(cuts) == []


def _decode(video, w, h):
    import numpy as np

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-f", "rawvideo"]
        + ["-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
    ).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(float)


def _assemble(tmp_path, name, cuts, w, h, fps):
    from muvid.footage.assemble import assemble_music_video

    song = tmp_path / "song.m4a"
    if not song.exists():
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i"]
            + ["anullsrc=r=48000:cl=stereo", "-t", "6", "-c:a", "aac", str(song)],
            check=True,
        )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = assemble_music_video(
            cuts, str(song), str(tmp_path / f"{name}.mp4"), canvas=(w, h), fps=fps
        )
    return _decode(out, w, h)


def _picture(tmp_path, name, source, w, h):
    out = tmp_path / f"{name}.png"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"{source}=size={w}x{h}:rate=1"]
        + ["-frames:v", "1", str(out)],
        check=True,
    )
    return out


@needs_ffmpeg
def test_a_photos_move_carries_on_through_the_fade(tmp_path):
    """muvid#376's acceptance: no snap at the first frame of a fade over a photo.

    A photo with a 1.12x punch over 3 s, then a 0.4 s fade into a second photo.
    The fade's first frame is still all A (its progress is 0), so it must look
    like the solo's next frame: one step of the push-in. Rendered with the move
    UNDECLARED, the same boundary is the bug — the photo snaps back to 1.0 —
    which is the positive control that this measures a pop and not noise.
    Measured: 3.8/255 with the fix, 24.5/255 without, and ~2.6/255 between two
    ordinary frames of the push.

    The boundary is found from the render's own steps rather than computed,
    so the test does not depend on where the blend sits in the render's frames.
    """
    w, h, fps = 320, 180, 25
    a = _picture(tmp_path, "a", "testsrc2", w, h)
    b = _picture(tmp_path, "b", "smptebars", w, h)
    look = punch_in(canvas=(w, h), fps=fps, duration_s=3.0)

    def steps(declared):
        cuts = [
            AssemblyCut(
                0.0, 3.0, "A", 0.0, str(a), look=look, look_time_varying=declared
            ),
            AssemblyCut(3.0, 6.0, "B", 0.0, str(b), transition=Transition(0.4, "fade")),
        ]
        f = _decode_steps(_assemble(tmp_path, f"photo{declared}", cuts, w, h, fps))
        return f

    fixed, unfixed = steps(True), steps(False)
    # Before the blend begins the two renders are identical frame for frame.
    first_blend = next(i for i, (x, y) in enumerate(zip(fixed, unfixed)) if x != y)
    assert unfixed[first_blend] > 15, (
        f"the unfixed render steps {unfixed[first_blend]:.1f}/255 into the fade — "
        "the snap this test exists for did not happen, so it measures nothing"
    )
    push = max(fixed[first_blend - 10 : first_blend])
    assert fixed[first_blend] < 2 * push + 1, (
        f"the fade's first frame steps {fixed[first_blend]:.1f}/255 from the solo's "
        f"last (an ordinary frame of the push steps at most {push:.1f}): the move "
        "restarted on the blend (muvid#376)"
    )


def _decode_steps(frames):
    """Mean |diff| between each pair of neighbouring frames, rounded for equality."""
    return [
        round(float(abs(frames[i + 1] - frames[i]).mean()), 3)
        for i in range(len(frames) - 1)
    ]


@needs_ffmpeg
def test_rewinding_never_moves_the_footage_in_time(tmp_path):
    """A rewound part shows the SAME source moments as before; only the clock moved.

    A video source (it changes every frame, so a one-frame shift is visible) and a
    look that is declared moving but draws every frame the same way: the rewind
    path runs on both sides of both blends, and the render must match the
    undeclared one frame for frame (to encode noise).

    This holds where source frames sit on the delivery grid (here 25 fps at 25,
    rate 1). Off the grid (24 -> 30, or ``rate != 1``) the review of muvid#376
    measured a rewound solo one output frame AHEAD of the unrewound one, because
    ``fps`` now resamples from the incoming blend's phase; it is the blend's phase
    that the solo continues, so the junction is smoother, not worse.
    """
    w, h, fps = 320, 180, 25
    src = tmp_path / "v.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={w}x{h}:rate={fps}:d=12",
        ]
        + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", str(src)],
        check=True,
    )

    def render(declared):
        kw = dict(look=_GREY, look_time_varying=declared, clip_path=str(src))
        cuts = [
            _cut(song_end=2.0, clip_in=1.0, **kw),
            _cut(
                song_start=2.0,
                song_end=4.0,
                clip_id="B",
                clip_in=5.0,
                transition=Transition(0.4, "fade"),
                **kw,
            ),
            _cut(
                song_start=4.0,
                song_end=6.0,
                clip_id="C",
                clip_in=2.0,
                transition=Transition(0.4, "wipeleft"),
                **kw,
            ),
        ]
        return _assemble(tmp_path, f"video{declared}", cuts, w, h, fps)

    rewound, plain = render(True), render(False)
    assert len(rewound) == len(plain)
    worst = max(float(abs(x - y).mean()) for x, y in zip(rewound, plain))
    assert worst < 1.5, f"a rewound part differs by {worst:.2f}/255: it moved in time"


def test_the_mcp_reply_carries_the_findings_the_render_plan_made(tmp_path, monkeypatch):
    """End to end through the live tool, with the REAL assembler and no encoding.

    muvid#73's stated purpose was to warn. It did -- into the server process's
    stderr, which the caller of a per-caller MCP connector has no access to, and
    ``assemble_music_video``'s reply had no key for it at all. So the finding was
    served on the developer path only: a remote caller got ``ok: true`` and a
    video with the hitch in it.

    ``run_ffmpeg`` is stubbed and nothing else is: ``_part_plan`` is the real one,
    so this asserts the whole path from the plan to the reply rather than the
    plumbing of a fake. The finding carried is an HDR clip this ffmpeg cannot
    tone-map (raised by the real ``_with_source_colour`` off a stubbed probe):
    the moving-look finding is gone since muvid#376 fixed what it warned about,
    and that is asserted too, and a zero-frame transition cannot reach this tool
    because ``validate_edl``'s floor refuses it first. The positive control is the second half -- a clean
    edit returns the key with an EMPTY list, which is what makes "no warnings"
    and "an older build" different readings.
    """
    pytest.importorskip("fastmcp")
    import muvid.mcp.footage_tools as ft
    import muvid.visualize as V
    import muvid.visualize.ffmpeg as F
    from muvid.footage.workspace import FootageWorkspace
    from muvid.mcp.identity import use_email

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(F, "require_ffmpeg", lambda *a, **k: None)
    monkeypatch.setattr(F, "probe", lambda *a, **k: {})
    monkeypatch.setattr(F, "run_ffmpeg", lambda args, **k: None)
    # The edit has a transition, so `assemble_music_video` calls `require_filter`,
    # which shells out to `ffmpeg -filters` — the one subprocess the other three
    # stubs miss. Unstubbed it raised FileNotFoundError on a runner with no
    # ffmpeg, which is a skip-vs-fail question this test has no business asking:
    # it asserts the reply's shape, not the build's capabilities.
    monkeypatch.setattr(F, "require_filter", lambda *a, **k: None)
    monkeypatch.setattr(V, "verify_video", lambda *a, **k: [])
    monkeypatch.setattr(V, "failures", lambda c: [])
    monkeypatch.setattr(V, "report", lambda c: "ok")

    proj = FootageWorkspace.for_email("u@x.com").create_project("warn")
    (proj.root / "song").mkdir()
    (proj.root / "song" / "song.wav").write_bytes(b"x")
    (proj.root / "clips").mkdir()
    for cid in ("A", "B"):
        (proj.root / "clips" / f"{cid}.mp4").write_bytes(b"x")
    m = proj.manifest()
    m.update(
        song="song.wav",
        song_duration=8.0,
        clips=[{"clip_id": c, "file": f"{c}.mp4", "name": c} for c in ("A", "B")],
    )
    proj._write_manifest(m)
    proj.save_alignments(
        [
            FootageAlignment("A", 0.0, 0.9, 20.0, (0.0, 20.0)),
            FootageAlignment("B", 0.0, 0.9, 20.0, (0.0, 20.0)),
        ]
    )

    def _edl(moving):
        return [
            {
                "song_start": 0.0,
                "song_end": 4.0,
                "clip_id": "A",
                "look": _PUNCH,
                "look_time_varying": moving,
            },
            {
                "song_start": 4.0,
                "song_end": 8.0,
                "clip_id": "B",
                "transition": {"duration_s": 0.4, "curve": "fade"},
            },
        ]

    import muvid.footage.assemble as asm
    from muvid.footage.colour import SourceColour

    with use_email("u@x.com"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        moving = ft.assemble_music_video("warn", edl=_edl(True))
        static = ft.assemble_music_video("warn", edl=_edl(False))
        monkeypatch.setattr(
            asm, "read_source_colour", lambda p: SourceColour(hdr_transfer="smpte2084")
        )
        monkeypatch.setattr(asm, "can_tonemap", lambda: False)
        hdr = ft.assemble_music_video("warn", edl=_edl(False))

    assert hdr["ok"] is True, "a warning is not a failure -- the render succeeded"
    assert any("is HDR" in w for w in hdr["warnings"]), hdr["warnings"]
    assert moving["warnings"] == [], "a moving look on a fade is fixed, not warned"
    assert "warnings" in static, (
        "the key must be PRESENT and empty, never absent -- an absent key makes "
        "'nothing to report' and 'an older build' the same reading"
    )
    assert static["warnings"] == [], (
        "the positive control: a clean edit reports nothing, so the key is not "
        "simply always populated"
    )


def test_an_undeclared_plan_reads_as_moving(monkeypatch):
    """``LookPlan.time_varying`` is ``None`` when a step never declared itself;
    the warning that feeds is cheap and a silent clock restart is not."""
    looks = pytest.importorskip("looks")

    class _Plan:
        time_varying = None

    monkeypatch.setattr(looks, "compile_look", lambda *a, **k: _Plan())
    monkeypatch.setattr(looks, "vf", lambda plan: "hue=s=0")
    frag = stylize(
        looks.Look(steps=()),
        canvas=(640, 360),
        fps=25,
        duration_s=3.0,
        env=looks.FfmpegEnv(filters=frozenset()),
    )
    assert is_time_varying(frag)
