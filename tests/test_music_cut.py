"""Footage that does not contain the song: free cuts, photos, and cutting to the music.

Pins the three layers of the "montage" half of a music video:

- the edit model (:mod:`muvid.footage.edl`): a FREE cut (``source_in`` set) reads its
  clip from its own in-point, needs no alignment and is never refused as unvouched,
  while still being checked for containment;
- the planner bridge (:mod:`muvid.footage.music_cut`): free cuts cover exactly the
  spans asked for, on the beat grid, inside each video, choosing the stretch whose
  picture changes land on the beats;
- the service (:mod:`muvid.footage.service`): photos are accepted, each clip gets a
  role (synced / cut to the music) from listening or from ``set_has_song``, and
  ``propose_edit`` fills every span the synced clips leave — Noel's "Bath" case, where
  nothing could be synced, is a whole song cut to the music instead of mostly black.

The edit-level and service tests need no ffmpeg (the song analysis is injected);
one end-to-end test decodes and renders, marked ``needs_ffmpeg``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from muvid.footage import music_cut, service
from muvid.footage.edl import (
    STILL_DURATION_S,
    EdlEntry,
    UnreliableAlignmentError,
    clip_in_of,
    derive_cuts,
    unplaced,
    validate_edl,
    with_start,
)
from muvid.footage.music_cut import Envelope, FreeSource, fill_spans
from muvid.montage.analysis import Analysis, Section

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg + ffprobe")


def _analysis(duration: float = 40.0, bpm: float = 120.0) -> Analysis:
    beat = 60.0 / bpm
    beats = tuple(float(t) for t in np.arange(0.0, duration, beat))
    return Analysis(
        duration=duration,
        tempo_bpm=bpm,
        beats=beats,
        downbeats=beats[::4],
        sections=(
            Section(label="verse", start=0.0, end=duration / 2, energy_db=-20.0),
            Section(label="chorus", start=duration / 2, end=duration, energy_db=-10.0),
        ),
        beat_source="test",
        section_source="test",
    )


# -- the edit model -------------------------------------------------------------------


def test_free_cut_needs_no_alignment_and_is_not_refused():
    a = unplaced("c", 10.0)  # never placed: unvouched
    e = EdlEntry(song_start=30.0, song_end=34.0, clip_id="c", source_in=2.0)
    [v] = validate_edl([e], [a], 34.0 + 0.0, allow_unreliable=False)[-1:]
    assert v.is_free and clip_in_of(v, a) == 2.0
    [cut] = derive_cuts([v], [a], {"c": "/x/c.mp4"})[-1:]
    assert cut.clip_in == 2.0


def test_anchored_cut_to_the_same_unplaced_clip_is_still_refused():
    a = unplaced("c", 10.0)
    with pytest.raises((UnreliableAlignmentError, ValueError)):
        validate_edl([EdlEntry(0.0, 4.0, "c")], [a], 4.0)


def test_free_cut_past_the_end_of_its_clip_is_refused():
    a = unplaced("c", 10.0)
    with pytest.raises(ValueError, match="does not contain"):
        validate_edl([EdlEntry(0.0, 4.0, "c", source_in=7.0)], [a], 4.0)


def test_free_cut_moves_its_in_point_not_a_slip_when_its_start_moves():
    e = EdlEntry(10.0, 14.0, "c", source_in=2.0)
    moved = with_start(e, 11.0)
    assert moved.source_in == pytest.approx(3.0) and moved.slip_s == 0.0


def test_a_gap_cannot_carry_an_in_point():
    with pytest.raises(ValueError, match="gap"):
        validate_edl(
            [{"song_start": 0.0, "song_end": 4.0, "clip_id": None, "source_in": 1.0}],
            [],
            4.0,
        )


def test_free_cut_round_trips_through_json():
    e = EdlEntry(0.0, 4.0, "c", source_in=2.5)
    wire = service.edl_json(e)
    assert wire["source_in"] == 2.5
    [back] = validate_edl([wire], [unplaced("c", 10.0)], 4.0)
    assert back == e


# -- the planner bridge ----------------------------------------------------------------


def test_choose_source_in_lands_picture_changes_on_the_beats():
    hits = np.zeros(200)
    hits[[63, 73, 83]] = 1.0  # changes at 6.3, 7.3, 8.3 s
    env = Envelope(hop_s=0.1, activity=np.full(200, 0.1), hits=hits)
    s, fit = music_cut.choose_source_in(
        env, clip_duration=20.0, length=3.0, beat_offsets=[0.5, 1.5, 2.5]
    )
    assert s == pytest.approx(5.8) and fit > 1


def test_choose_source_in_avoids_what_was_already_shown():
    env = Envelope(hop_s=0.1, activity=np.full(100, 0.1), hits=np.zeros(100))
    s, _ = music_cut.choose_source_in(
        env, clip_duration=10.0, length=2.0, used=[(0.0, 6.0)]
    )
    assert s >= 6.0 - 1e-9


def _sources():
    return [
        FreeSource("long", "/x/long.mp4", duration_s=30.0),
        FreeSource("short", "/x/short.mp4", duration_s=3.0),
        FreeSource("mid", "/x/mid.mp4", duration_s=8.0),
        FreeSource("pic", "/x/pic.jpg", kind="still"),
    ]


def _fill(spans=None, **kw):
    return fill_spans(
        "/x/song.wav",
        _sources(),
        spans=spans,
        analysis=_analysis(),
        envelope_of=lambda s: None,
        anchor_of=lambda s: (0.5, 0.5),
        size_of=lambda p: (1080, 1920),
        canvas=(1080, 1920),
        **kw,
    )


def test_fill_spans_covers_the_song_with_free_cuts_inside_each_video():
    cut = _fill()
    entries = cut.entries
    assert entries[0].song_start == 0.0 and entries[-1].song_end == pytest.approx(40.0)
    for a, b in zip(entries, entries[1:]):
        assert a.song_end == pytest.approx(b.song_start)
        assert a.clip_id != b.clip_id, "a take-over must not repeat its neighbour"
    by_id = {s.clip_id: s for s in _sources()}
    for e in entries:
        assert e.is_free
        src = by_id[e.clip_id]
        if not src.is_still:
            assert e.source_in + (e.song_end - e.song_start) <= src.duration_s + 1e-6
        else:
            assert e.look and e.look_spec["name"] in music_cut.STILL_MOVES + ("punch_in",)
    placements = [unplaced(s.clip_id, s.duration_s or STILL_DURATION_S) for s in _sources()]
    validate_edl(entries, placements, 40.0, canvas=(1080, 1920))  # the gate agrees
    assert cut.report["style"] == "beat_cut"  # 120 bpm


def test_fill_spans_fills_only_the_spans_it_is_given():
    entries = _fill(spans=[(4.0, 12.0), (20.0, 26.0)]).entries
    covered = sum(e.song_end - e.song_start for e in entries)
    assert covered == pytest.approx(14.0)
    assert all(4.0 - 1e-6 <= e.song_start and e.song_end <= 26.0 + 1e-6 for e in entries)
    assert not any(12.0 < e.song_start < 20.0 for e in entries)


def test_cover_crop_follows_the_shown_shape_not_the_stored_one():
    landscape_on_portrait = music_cut.cover_crop((1920, 1080), (1080, 1920))
    assert landscape_on_portrait.h == 1.0 and landscape_on_portrait.w < 0.35
    assert music_cut.cover_crop((360, 640), (1080, 1920)) is None


# -- the service ----------------------------------------------------------------------


@pytest.fixture
def bath(tmp_path, monkeypatch):
    """Noel's case in miniature: a song, two videos nobody could place, one photo."""
    from muvid.footage.workspace import FootageWorkspace

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(music_cut, "_default_analysis", lambda path: _analysis())
    proj = FootageWorkspace.for_email("u@x.com").create_project("bath")
    song = tmp_path / "song.wav"
    song.write_bytes(b"RIFF-song")
    service.set_song(proj, path=str(song), duration_s=40.0)
    for cid, dur in (("abbey", 12.0), ("dog", 6.0)):
        clip = tmp_path / f"{cid}.mp4"
        clip.write_bytes(cid.encode())
        service.add_clip(proj, path=str(clip), clip_id=cid, duration_s=dur)
    # what listening found on the real shoot: no song in either (support 0.03-0.33)
    proj.save_alignments([_heard(cid, dur, support=0.2) for cid, dur in (("abbey", 12.0), ("dog", 6.0))])
    return proj


def _heard(cid, dur, *, support, reliable=False, offset=3.0, margin=None):
    from muvid.footage.edl import FootageAlignment

    return FootageAlignment(
        clip_id=cid, offset_s=offset, confidence=0.1, duration_s=dur,
        coverage=(offset, offset + dur), overlaps=True, support=support,
        reliable=reliable, window_s=3.0, hop_s=1.5,
        margin=margin if margin is not None else (-0.2 if not reliable else 0.3),
    )


def test_a_project_nothing_could_be_synced_in_is_cut_to_the_music(bath):
    assert service.footage_roles(bath) == {"abbey": "to_the_music", "dog": "to_the_music"}
    out = service.propose_edit(bath)
    edl = out["edl"]
    assert all(e["clip_id"] for e in edl), "no black: the whole song is cut to the music"
    assert all("source_in" in e for e in edl)
    assert out["music"]["n_cuts"] == len(edl)
    assert out["assemble_refusal"] is None
    assert "cut to the music" in service.get_edit(bath, edit_id=out["edit_id"])["how_made"]


def test_a_synced_clip_keeps_its_place_and_the_rest_is_cut_to_the_music(bath):
    service.set_offset(bath, clip_id="abbey", offset_s=10.0)  # declared: synced
    assert service.footage_roles(bath)["abbey"] == "synced"
    edl = service.propose_edit(bath)["edl"]
    synced = [e for e in edl if e["clip_id"] == "abbey" and "source_in" not in e]
    assert synced and synced[0]["song_start"] == pytest.approx(10.0)
    free = [e for e in edl if "source_in" in e]
    assert free and all(e["clip_id"] == "dog" for e in free)
    assert all(e["clip_id"] for e in edl)


def test_set_has_song_overrides_the_listening(bath):
    service.set_offset(bath, clip_id="abbey", offset_s=10.0)
    reply = service.set_has_song(bath, clip_id="abbey", has_song="no")
    assert reply["role"] == "to_the_music"
    assert not any(
        e["clip_id"] == "abbey" and "source_in" not in e
        for e in service.propose_edit(bath, save=False)["edl"]
    )
    assert service.set_has_song(bath, clip_id="abbey", has_song="auto")["role"] == "synced"
    with pytest.raises(service.FootageError):
        service.set_has_song(bath, clip_id="abbey", has_song="maybe")


def test_set_has_song_is_in_the_catalogue():
    assert "set_has_song" in {op.name for op in service.FOOTAGE_OP_SPECS}


def test_pace_changes_how_often_the_music_cuts_come(bath):
    slow = service.propose_edit(bath, pace="slow", save=False)["music"]["n_cuts"]
    driving = service.propose_edit(bath, pace="driving", save=False)["music"]["n_cuts"]
    assert driving > slow


# -- end to end: real media -----------------------------------------------------------


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


@needs_ffmpeg
def test_photos_and_unsynced_videos_render_over_the_song(tmp_path, monkeypatch):
    from muvid.footage.workspace import FootageWorkspace

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data"))
    proj = FootageWorkspace.for_email("u@x.com").create_project("e2e")
    song = tmp_path / "song.wav"
    # a click track at 120 bpm, so there is a beat to cut on
    _ffmpeg("-f", "lavfi", "-i",
            "aevalsrc='0.8*sin(2*PI*880*t)*lt(mod(t,0.5),0.03)':s=22050:d=8", str(song))
    clip = tmp_path / "walk.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=6",
            "-f", "lavfi", "-i", "anoisesrc=d=6:a=0.3:seed=2", "-shortest", "-pix_fmt",
            "yuv420p", str(clip))
    photo = tmp_path / "abbey.png"
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=400x300:duration=1", "-frames:v", "1",
            str(photo))
    service.set_song(proj, path=str(song))
    service.add_clip(proj, path=str(clip), filename="walk.mp4")
    added = service.add_clip(proj, path=str(photo), filename="abbey.png")
    assert added["kind"] == "still" and added["duration"] is None
    assert [c.get("kind") for c in proj.list_clips()] == [None, "still"]
    service.align(proj)  # noise has no song in it: not placed confidently
    assert set(service.footage_roles(proj).values()) == {"to_the_music"}
    out = service.propose_edit(proj)
    assert all(e["clip_id"] for e in out["edl"])
    assert {e["clip_id"] for e in out["edl"]} == set(service.footage_roles(proj))
    meta = service.render(proj, edit_id=out["edit_id"])
    video = proj.root / "renders" / meta["render_id"] / "final.mp4"
    assert video.is_file()
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
         str(video)], capture_output=True, check=True, text=True).stdout)
    assert float(probe["format"]["duration"]) == pytest.approx(8.0, abs=0.3)


def test_a_video_nobody_listened_to_is_not_guessed_about(bath):
    """A concert cut to the music is a desynced concert (muvid#59 by another road)."""
    bath.save_alignments([_heard("abbey", 12.0, support=0.2)])  # dog: never listened to
    assert service.footage_roles(bath)["dog"] == "not_listened"
    with pytest.raises(service.FootageError, match="not been listened to"):
        service.propose_edit(bath, save=False)
    service.set_has_song(bath, clip_id="dog", has_song="no")  # or say what it is
    assert all(e["clip_id"] for e in service.propose_edit(bath, save=False)["edl"])


def test_a_song_heard_but_not_placed_stays_synced_and_is_set_aside(bath):
    """The muvid#59 case: the song is there, its place ambiguous. Not montaged; its
    span is set aside (and filled from the footage that IS cut to the music). A short
    clip's vote (dog: 6 s, three windows) is too coarse to count as heard."""
    bath.save_alignments(
        [_heard("abbey", 12.0, support=0.45, margin=0.1), _heard("dog", 6.0, support=0.5, margin=0.2)]
    )
    assert service.footage_roles(bath) == {"abbey": "synced", "dog": "to_the_music"}
    out = service.propose_edit(bath, save=False)
    assert not any(e["clip_id"] == "abbey" for e in out["edl"])
    assert [x["clip_id"] for x in out["coverage"]["excluded"]] == ["abbey"]
    assert all(e["clip_id"] == "dog" for e in out["edl"])


def test_swapping_a_cut_onto_a_clip_cut_to_the_music_starts_it_at_its_start(bath):
    out = service.propose_edit(bath)
    edl = service.get_edit(bath, edit_id=out["edit_id"])["edl"]
    i, e = next((i, e) for i, e in enumerate(edl) if e["clip_id"] == "abbey" and not e.get("transition"))
    reply = service.set_cut(bath, edit_id=out["edit_id"], index=i, clip_id="dog")
    swapped = reply["edl"][i]
    assert swapped["clip_id"] == "dog" and 0.0 <= swapped["source_in"] <= 1.0


@pytest.mark.parametrize("seed", range(150))
def test_planned_cuts_always_pass_the_edit_gate(seed):
    """Random pools, tempos and spans: what the planner emits is a valid edit (the
    adversarial review's fuzz, kept)."""
    import random

    from muvid.footage.edl import fill_gaps

    r = random.Random(seed)
    d, bpm = r.uniform(2, 120), r.uniform(55, 150)
    srcs = [
        FreeSource(f"v{i}", f"/x/v{i}.mp4", duration_s=r.choice([r.uniform(0.6, 4), r.uniform(3, 40)]))
        for i in range(r.randint(1, 6))
    ]
    if r.random() < 0.4:
        srcs += [FreeSource(f"p{i}", f"/x/p{i}.jpg", kind="still") for i in range(r.randint(1, 3))]
    spans = [(0, d * 0.3), (d * 0.5, d * 0.8)] if r.random() < 0.3 else None
    an = _analysis(d, bpm)
    if r.random() < 0.5:  # the beat tracker went silent before the end (a quiet outro)
        from dataclasses import replace

        keep = tuple(b for b in an.beats if b < d * r.uniform(0.6, 1.0))
        if len(keep) >= 4:
            an = replace(an, beats=keep, downbeats=keep[::4])
    cut = fill_spans(
        "/x/s.wav", srcs, spans=spans, analysis=an,
        archetype=r.choice(["auto", "beat_cut", "ballad_dissolve"]),
        envelope_of=lambda s: None, anchor_of=lambda s: (0.5, 0.5),
        size_of=lambda p: (1080, 1920), canvas=(1080, 1920),
    )
    if not cut.entries:  # only a sub-second video: nothing can be shown, and it says so
        assert all((s.duration_s or 99) < 1.0 for s in srcs)
        return
    places = [unplaced(s.clip_id, s.duration_s or STILL_DURATION_S) for s in srcs]
    validate_edl(fill_gaps(cut.entries, d), places, d, canvas=(1080, 1920))
    # every fade STARTS on a beat of the (carried-on) grid
    from muvid.footage.edl import TRANSITION_SPLIT
    from muvid.footage.music_cut import extend_grid

    # (or a section boundary — the fixture's sections change at half the song)
    beats = np.asarray(list(extend_grid(an, d)[0].beats) + [x.start for x in an.sections])
    for e in cut.entries:
        if e.transition is not None:
            start = e.song_start - e.transition.duration_s * TRANSITION_SPLIT
            assert np.min(np.abs(beats - start)) < 1e-3


def test_a_dissolve_into_a_photo_passes_the_gate():
    srcs = [FreeSource("p1", "/x/p1.jpg", kind="still"), FreeSource("p2", "/x/p2.jpg", kind="still")]
    cut = fill_spans(
        "/x/s.wav", srcs, analysis=_analysis(30.0, 70.0), envelope_of=lambda s: None,
        anchor_of=lambda s: (0.5, 0.5), size_of=lambda p: (1080, 1920), canvas=(1080, 1920),
    )
    assert cut.report["style"] == "ballad_dissolve"
    assert any(e.transition for e in cut.entries), "the slow song keeps its dissolves"
    places = [unplaced(s.clip_id, STILL_DURATION_S) for s in srcs]
    validate_edl(cut.entries, places, 30.0, canvas=(1080, 1920))


def test_a_heic_photo_is_refused_plainly_without_its_decoder(bath, tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_heif(name, *a, **k):
        if name in ("pillow_heif", "pi_heif"):
            raise ImportError("no pillow_heif")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_heif)
    heic = tmp_path / "IMG_0001.HEIC"
    heic.write_bytes(b"not really")
    with pytest.raises(service.FootageError, match="HEIC"):
        service.add_clip(bath, path=str(heic), filename=heic.name)


def test_an_iphone_heic_photo_goes_in_upright_as_jpeg(bath, tmp_path):
    """muvid#140: with a HEIC reader (`pi-heif`, in the `scoring` extra the studio
    installs) a HEIC is read instead of refused. The fixture is a 40x20 picture whose
    `irot` box says "turn a quarter" (what a phone portrait is); the decoder applies it
    and resets the EXIF tag, so the stored JPEG is 20x40 and `exif_transpose` does not
    turn it a second time."""
    pytest.importorskip("pi_heif")
    from PIL import Image

    heic = tmp_path / "IMG_0001.HEIC"
    shutil.copy(Path(__file__).parent / "data" / "portrait_irot.heic", heic)
    added = service.add_clip(bath, path=str(heic), filename=heic.name)
    assert added["kind"] == "still"
    stored = Path(bath.clip_paths()[added["clip_id"]])
    assert stored.suffix == ".jpg"
    with Image.open(stored) as im:
        assert im.format == "JPEG" and im.size == (20, 40)
        r, g, b = im.getpixel((10, 20))
        assert r > 150 and g < 80 and b < 80  # the picture, not a blank


# -- the timeline-editor document carries the cuts to the music (muvid#138) ----------


@pytest.fixture
def bath_with_photo(bath, tmp_path):
    if not HAS_FFMPEG:
        pytest.skip("needs ffmpeg to make a photo")
    photo = tmp_path / "abbey_road.png"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=64x48:duration=1",
        "-frames:v",
        "1",
        str(photo),
    )
    added = service.add_clip(bath, path=str(photo), filename="abbey_road.png")
    assert added["kind"] == "still"
    return bath, added["clip_id"]


def _decision(doc):
    from lacing.model import Annotation

    from muvid.footage.lacing_bridge import DECISION_TIER, edl_from_annotations

    return edl_from_annotations(
        [
            Annotation.model_validate(a)
            for a in doc["annotations"]
            if a["tier"] == DECISION_TIER
        ]
    )


def _key(e):
    return (
        e["clip_id"],
        round(e["song_start"], 3),
        round(e["song_end"], 3),
        e.get("source_in"),
    )


def test_the_editor_decision_tier_is_what_propose_edit_builds(bath_with_photo):
    bath, photo = bath_with_photo
    doc = service.editor_document(bath)
    proposal = service.propose_edit(bath, save=False)["edl"]
    assert doc["decision_error"] is None
    assert [_key(e) for e in _decision(doc)] == [_key(e) for e in proposal]
    assert _decision(doc) == proposal  # the whole cut, not just where and what
    # nothing came back anchored: every free cut keeps its in-point through the editor
    free = [e for e in _decision(doc) if e["clip_id"]]
    assert free and all(e.get("source_in") is not None for e in free)
    assert photo in {e["clip_id"] for e in free}


def test_every_clip_gets_a_lane_and_a_photo_is_not_a_position_on_the_song(
    bath_with_photo,
):
    bath, photo = bath_with_photo
    doc = service.editor_document(bath)
    assert {t["name"] for t in doc["tiers"]} == {
        "DECISION",
        "clip:abbey",
        "clip:dog",
        f"clip:{photo}",
    }
    rec = {
        a["body"]["clip_id"]: a
        for a in doc["annotations"]
        if a["body_schema_uri"].endswith("clip-alignment/v1")
    }
    assert (
        rec[photo]["body"]["still"] is True and rec[photo]["body"]["overlaps"] is False
    )
    assert rec[photo]["body"]["role"] == "to_the_music"
    assert "still" not in rec["abbey"]["body"]
    assert rec["abbey"]["body"]["role"] == "to_the_music"


def test_the_editor_document_can_open_a_saved_edit(bath_with_photo):
    bath, _ = bath_with_photo
    out = service.propose_edit(bath)
    edl = service.get_edit(bath, edit_id=out["edit_id"])["edl"]
    i = next(
        i
        for i, e in enumerate(edl)
        if e["clip_id"] == "abbey" and not e.get("transition")
    )
    service.set_cut(bath, edit_id=out["edit_id"], index=i, clip_id="dog")
    saved = service.get_edit(bath, edit_id=out["edit_id"])["edl"]
    doc = service.editor_document(bath, edit_id=out["edit_id"])
    assert [_key(e) for e in _decision(doc)] == [_key(e) for e in saved]
    assert _decision(doc) == saved
    assert doc["edit_id"] == out["edit_id"]
    assert _decision(doc) != _decision(service.editor_document(bath))


def test_an_unknown_edit_is_refused_not_swapped_for_the_proposal(bath_with_photo):
    bath, _ = bath_with_photo
    with pytest.raises(service.FootageError, match="unknown edit 'nope'"):
        service.editor_document(bath, edit_id="nope")


def _add_unreadable_clip(bath, cid="broken"):
    """A clip whose file ffprobe cannot read and whose length was never recorded."""
    (bath.root / "clips" / f"{cid}.mp4").write_bytes(b"not a video")
    m = bath.manifest()
    m["clips"].append({"clip_id": cid, "file": f"{cid}.mp4", "name": cid})
    bath._write_manifest(m)
    return cid


def test_one_unreadable_clip_does_not_cost_the_others_their_lanes(bath_with_photo):
    bath, photo = bath_with_photo
    saved = service.propose_edit(bath)["edit_id"]
    broken = _add_unreadable_clip(bath)
    doc = service.editor_document(bath)
    assert {t["name"] for t in doc["tiers"]} == {
        "DECISION", "clip:abbey", "clip:dog", f"clip:{photo}", f"clip:{broken}",
    }
    assert repr(broken) in doc["decision_error"]
    # a hosted reply names files, never the server's paths
    assert str(bath.root) not in doc["decision_error"]
    assert not [a for a in doc["annotations"] if a["tier"] == "DECISION"]
    # a named edit that does not use the bad clip still opens
    doc = service.editor_document(bath, edit_id=saved)
    assert doc["decision_error"] is None
    assert _decision(doc) == service.get_edit(bath, edit_id=saved)["edl"]
    assert any(repr(broken) in w for w in doc["warnings"])
    assert not any(str(bath.root) in w for w in doc["warnings"])


def test_an_unlistened_video_degrades_the_decision_tier_not_the_document(bath):
    bath.save_alignments([_heard("abbey", 12.0, support=0.2)])  # dog: never listened to
    doc = service.editor_document(bath)
    assert "not been listened to" in doc["decision_error"]
    assert {t["name"] for t in doc["tiers"]} == {"DECISION", "clip:abbey", "clip:dog"}
    assert not [a for a in doc["annotations"] if a["tier"] == "DECISION"]


def test_a_song_ffprobe_cannot_read_degrades_the_decision_tier_without_a_path(
    bath, monkeypatch
):
    """The music half raises FfmpegError (a RuntimeError): the document still opens."""
    from muvid.visualize.ffmpeg import FfmpegError

    def unreadable(path):
        raise FfmpegError(f"ffprobe could not read {path}: Invalid data")

    monkeypatch.setattr(music_cut, "_default_analysis", unreadable)
    shutil.rmtree(bath.root / "beats", ignore_errors=True)  # warmed at upload
    doc = service.editor_document(bath)
    assert doc["decision_error"] and "ffprobe could not read" in doc["decision_error"]
    assert str(bath.root) not in doc["decision_error"]
    assert {t["name"] for t in doc["tiers"]} == {"DECISION", "clip:abbey", "clip:dog"}


def test_a_saved_edit_is_echoed_by_its_stored_id(bath_with_photo):
    bath, _ = bath_with_photo
    out = service.propose_edit(bath)
    doc = service.editor_document(bath, edit_id=f" {out['edit_id']} ")
    assert doc["edit_id"] == out["edit_id"]


def test_no_video_cut_gives_up_its_edge_margin_to_a_blend_that_did_not_fit():
    """The #203 review's plan: the cap path ended a piece ON its end and so carried the
    next blend that the feasibility check had just said does not fit, and the in-point
    gave up the edge margin to make room. Every video cut keeps EDGE_S at both ends."""
    from muvid.footage.edl import EDGE_S

    durs = [1.312, 2.968, 35.715, 3.529, 7.089]
    srcs = [FreeSource(f"v{i}", f"/x/v{i}.mp4", duration_s=d) for i, d in enumerate(durs)]
    entries = fill_spans(
        "/x/s.wav",
        srcs,
        analysis=_analysis(48.835, 61.409),
        envelope_of=lambda s: None,
        anchor_of=lambda s: (0.5, 0.5),
        size_of=lambda p: (1080, 1920),
        canvas=(1080, 1920),
        archetype="ballad_dissolve",
    ).entries
    duration = {s.clip_id: s.duration_s for s in srcs}
    for i, e in enumerate(entries):
        nxt = entries[i + 1] if i + 1 < len(entries) else None
        trail = nxt.transition.duration_s / 2 if nxt and nxt.transition else 0.0
        lead = e.transition.duration_s / 2 if e.transition else 0.0
        head = e.source_in - lead
        tail = duration[e.clip_id] - e.source_in - (e.song_end - e.song_start) - trail
        assert min(head, tail) >= EDGE_S - 1e-3, (i, e)


@pytest.mark.parametrize(
    "song_s,bpm,durs",
    [
        # a sliver after the re-cap (48 ms, 67 ms) and a jump cut onto the same in-point
        (70.55114488643417, 62.89840597153406, [6.9315942320841195, 1.3870359966812091, 1.6578400311845474]),
        # coverage lost: the re-capped room is under a piece, and nothing can take over
        (19.953261375508443, 71.53734647717391, [1.2422092751826308]),
    ],
)
def test_the_re_cap_trades_a_blend_never_coverage_and_makes_no_sliver(song_s, bpm, durs):
    """The #203 re-review's two plans: re-capping the end at `holds` must leave a real
    piece after it (>= MIN_PIECE_S) or keep the whole piece and drop the next blend."""
    from muvid.footage.music_cut import MIN_PIECE_S

    srcs = [FreeSource(f"v{i}", f"/x/v{i}.mp4", duration_s=d) for i, d in enumerate(durs)]
    kw = dict(
        analysis=_analysis(song_s, bpm),
        envelope_of=lambda s: None,
        anchor_of=lambda s: (0.5, 0.5),
        size_of=lambda p: (1080, 1920),
        canvas=(1080, 1920),
        archetype="ballad_dissolve",
    )
    cut = fill_spans("/x/s.wav", srcs, **kw)
    lengths = [e.song_end - e.song_start for e in cut.entries]
    assert min(lengths) >= MIN_PIECE_S - 1e-6, sorted(lengths)[:3]
    if len(durs) == 1:  # main covered all but 9.56 s of this song
        assert cut.report["uncovered_s"] <= 9.56 + 1e-6


def test_a_beat_a_hair_before_the_piece_end_leaves_no_sliver_muvid_210():
    """muvid#210 item 4: the cutter compared moments at 1 us while the gate calls
    anything under ``COINCIDENT_S`` (1 ms) zero, so a beat 60 us before a piece's end
    left a 60 us take-over — "EDL entry 15 has a non-positive span". The plan is the
    census's (ballad_dissolve, 70.745 s at 106.014 bpm, four short videos)."""
    from muvid.footage.edl import COINCIDENT_S, fill_gaps, unplaced, validate_edl

    d, bpm = 70.74533549887813, 106.01423596998906
    durs = [
        3.356456034271889,
        0.7314478274870594,
        3.5525565513677266,
        3.780584871995159,
    ]
    srcs = [
        FreeSource(f"v{i}", f"/x/v{i}.mp4", duration_s=x) for i, x in enumerate(durs)
    ]
    cut = fill_spans(
        "/x/s.wav",
        srcs,
        analysis=_analysis(d, bpm),
        envelope_of=lambda s: None,
        anchor_of=lambda s: (0.5, 0.5),
        size_of=lambda p: (1080, 1920),
        canvas=(1080, 1920),
        archetype="ballad_dissolve",
    )
    es = cut.entries
    assert all(e.song_end - e.song_start > COINCIDENT_S for e in es)
    # and no hole either: leaving the 60 us uncovered would pass the gate unseen
    assert all(a.song_end == b.song_start for a, b in zip(es, es[1:]))
    places = [unplaced(s.clip_id, s.duration_s) for s in srcs]
    validate_edl(fill_gaps(cut.entries, d), places, d, canvas=(1080, 1920))


def test_take_over_counts_the_blends_the_piece_carries_muvid_210():
    """muvid#210 item 3: a clip that holds the rest of a piece only WITHOUT its blends
    is not picked, to be found short and replaced on the next pass."""
    from muvid.footage.edl import Transition, longest_span

    fade = Transition(duration_s=1.0, curve="fade")
    need = 2.0
    edge = music_cut.EDGE_S
    # `bare` holds `need` with no blend and not with the next one; `roomy` holds both
    bare_s = need + 2 * edge + 0.1
    assert longest_span(bare_s, edge_s=edge) >= need
    assert longest_span(bare_s, next_transition=fade, edge_s=edge) < need
    cur = FreeSource("cur", "/x/cur.mp4", duration_s=1.0)
    bare = FreeSource("bare", "/x/bare.mp4", duration_s=bare_s)
    roomy = FreeSource("roomy", "/x/roomy.mp4", duration_s=need + 2 * edge + 2.0)
    uses = {"roomy": 5}  # least-used order alone would pick `bare`
    picked = music_cut._take_over(
        [cur, bare, roomy], cur, need=need, avoid=set(), uses=uses, next_transition=fade
    )
    assert picked.clip_id == "roomy"
    assert (
        music_cut._take_over(
            [cur, bare, roomy], cur, need=need, avoid=set(), uses=uses
        ).clip_id
        == "bare"
    )
    # the blend IN counts too: the first take-over of a piece keeps the piece's fade
    assert longest_span(bare_s, transition=fade, edge_s=edge) < need
    picked_in = music_cut._take_over(
        [cur, bare, roomy], cur, need=need, avoid=set(), uses=uses, transition=fade
    )
    assert picked_in.clip_id == "roomy"


# -- muvid#134: the feel of the pictures matched to the feel of the music ------------


def _affect_pool(levels=None):
    """Videos named for their liveliness: ``{"calm": (n, activity), ...}``."""
    levels = levels or {"calm": (7, 0.05), "live": (7, 1.0)}
    srcs, activity = [], {}
    for kind, (n, level) in levels.items():
        for i in range(n):
            cid = f"{kind}{i}"
            srcs.append(FreeSource(cid, f"/x/{cid}.mp4", duration_s=30.0))
            activity[cid] = level

    def envelope_of(src):
        n = 300
        return Envelope(hop_s=0.1, activity=np.full(n, activity[src.clip_id]), hits=np.zeros(n))

    return srcs, envelope_of


def _affect_cut(srcs, envelope_of, **kw):
    return fill_spans(
        "/x/s.wav",
        srcs,
        analysis=_analysis(40.0, 120.0),  # verse -20 dB (0-20 s), chorus -10 dB
        envelope_of=envelope_of,
        anchor_of=lambda s: (0.5, 0.5),
        size_of=lambda p: (1920, 1080),
        archetype="beat_cut",
        order="planner",
        **kw,
    )


def _fit_share(cut, *, boundary=20.0):
    """The share of cut time where a calm picture is in the quiet half (before
    ``boundary``) or a lively one in the loud half."""
    good = total = 0.0
    for e in cut.entries:
        length = e.song_end - e.song_start
        quiet = (e.song_start + e.song_end) / 2 < boundary
        good += length if e.clip_id.startswith("calm") == quiet else 0.0
        total += length
    return good / total


def _longest_run(cut):
    run = best = 1
    for a, b in zip(cut.entries, cut.entries[1:]):
        run = run + 1 if a.clip_id == b.clip_id else 1
        best = max(best, run)
    return best


def test_calm_pictures_land_in_the_quiet_half_and_lively_ones_in_the_loud_half():
    """muvid#134's acceptance: a song with a quiet and a loud half, a pool of calm and
    lively videos — the obvious answer is calm-in-quiet, lively-in-loud. And affect
    only CHOOSES: every picture is still shown, none twice in a row."""
    srcs, envelope_of = _affect_pool()
    matched = _affect_cut(srcs, envelope_of)
    blind = _affect_cut(srcs, envelope_of, affect_of=None)
    assert matched.report["affect"] is True and blind.report["affect"] is False
    assert _fit_share(matched) >= 0.9
    assert _fit_share(blind) < 0.7  # the premise: blind is a coin toss
    assert set(matched.report["uses"]) == {s.clip_id for s in srcs}
    assert _longest_run(matched) == 1


def test_a_skewed_pool_never_turns_affect_into_repeats():
    """The #134 review: one lively video among seven calm ones played twenty cuts in a
    row when affect narrowed the pool before the gap rules; it is now the first thing
    relaxed, so the gap still holds."""
    srcs, envelope_of = _affect_pool({"calm": (7, 0.05), "live": (1, 1.0)})
    cut = _affect_cut(srcs, envelope_of)
    assert cut.report["affect"] is True
    assert _longest_run(cut) == 1
    assert set(cut.report["uses"]) == {s.clip_id for s in srcs}


def test_noise_between_clips_does_not_split_the_pool():
    srcs, envelope_of = _affect_pool({"calm": (4, 0.1), "live": (4, 0.1001)})
    assert _affect_cut(srcs, envelope_of).report["affect"] is False


def test_a_middling_picture_fits_both_halves():
    """Three levels: a medium picture is within AFFECT_SLACK of both halves' best
    fit, so it is shown in each; a lively one stays out of the quiet half, and the loud
    half shows lively pictures more than calm ones (the gap, not affect, decides when
    the fitting ones have all been shown recently)."""
    srcs, envelope_of = _affect_pool(
        {"calm": (4, 0.05), "mid": (4, 0.5), "live": (4, 1.0)}
    )
    cut = _affect_cut(srcs, envelope_of)
    time = {}
    for e in cut.entries:
        key = (e.clip_id[:3], (e.song_start + e.song_end) / 2 < 20.0)
        time[key] = time.get(key, 0.0) + e.song_end - e.song_start
    assert time.get(("mid", True)) and time.get(("mid", False))
    assert ("liv", True) not in time
    assert time[("liv", False)] > 2 * time.get(("cal", False), 0.0)


def test_affect_never_makes_two_tiles_alike():
    """The planner seam is general: on a 4-tile slot where one picture fits, the tiles
    still differ (the hard exclusions are never relaxed for affect)."""
    from muvid.montage import spec as spec_mod
    from muvid.montage.analysis import Media
    from muvid.montage.plan import SlotDraft, assign_media

    pool = [
        Media(index=i, path=f"{i}.jpg", kind="photo", width=10, height=10)
        for i in range(8)
    ]
    drafts = [
        SlotDraft(start=k, end=k + 1, section="v", archetype="grid", regions=4,
                  fresh=(0, 1, 2, 3))
        for k in range(3)
    ]
    picks, stats = assign_media(
        drafts,
        pool,
        spec_mod.Reuse(min_gap=2),
        affect_fit=lambda d, m: 0.0 if m.index == 0 else 1.0,
    )
    assert stats["affect"] is True
    assert all(len({v[0] for v in slot.values()}) == 4 for slot in picks)


def test_affect_leaves_the_taken_order_and_unmeasured_songs_alone():
    srcs, envelope_of = _affect_pool()
    kw = dict(envelope_of=envelope_of, anchor_of=lambda s: (0.5, 0.5),
              size_of=lambda p: (1920, 1080), archetype="beat_cut")
    taken = fill_spans("/x/s.wav", srcs, analysis=_analysis(40.0, 120.0), **kw)
    assert taken.report["affect"] is False  # the order pictures were taken in rules
    from dataclasses import replace

    flat = _analysis(40.0, 120.0)
    flat = replace(flat, sections=tuple(replace(s, energy_db=None) for s in flat.sections))
    unmeasured = fill_spans("/x/s.wav", srcs, analysis=flat, order="planner", **kw)
    assert unmeasured.report["affect"] is False  # no loudness to match against


def test_liveliness_is_the_mean_picture_activity_and_none_for_a_still():
    from muvid.footage.music_cut import liveliness

    env = Envelope(hop_s=0.1, activity=np.array([0.0, 1.0, np.nan]), hits=np.zeros(3))
    assert liveliness(FreeSource("v", "/x/v.mp4", duration_s=1.0), env) == pytest.approx(
        1 / 3
    )
    assert liveliness(FreeSource("p", "/x/p.jpg", kind="still"), None) is None


# -- the cut cap (muvid#228) ------------------------------------------------------------

#: ``_fill()``'s entries recorded on main BEFORE #228: a plan inside the cap must not move.
_FILL_GOLDEN = [[0.0, 2.0, "long", 0.25], [2.0, 4.0, "short", 0.5], [4.0, 6.0, "mid", 1.5], [6.0, 8.0, "pic", 0.0], [8.0, 10.0, "long", 13.25], [10.0, 12.0, "short", 0.25], [12.0, 14.0, "mid", 4.25], [14.0, 16.0, "pic", 0.0], [16.0, 18.0, "long", 26.25], [18.0, 20.0, "short", 0.75], [20.0, 21.0, "mid", 0.5], [21.0, 22.0, "pic", 0.0], [22.0, 23.0, "long", 12.0], [23.0, 24.0, "short", 0.25], [24.0, 25.0, "mid", 6.25], [25.0, 26.0, "pic", 0.0], [26.0, 27.0, "long", 25.25], [27.0, 28.0, "short", 1.75], [28.0, 29.0, "mid", 3.25], [29.0, 30.0, "pic", 0.0], [30.0, 31.0, "long", 10.5], [31.0, 32.0, "short", 1.75], [32.0, 33.0, "mid", 6.75], [33.0, 34.0, "pic", 0.0], [34.0, 35.0, "long", 24.0], [35.0, 36.0, "short", 0.25], [36.0, 37.0, "mid", 0.25], [37.0, 38.0, "pic", 0.0], [38.0, 39.0, "long", 9.0], [39.0, 40.0, "short", 1.25]]


def _cap_fill(analysis, sources=None, **kw):
    return fill_spans(
        "/x/song.wav", sources or _sources(), envelope_of=lambda s: None,
        anchor_of=lambda s: (0.5, 0.5), size_of=lambda p: (1080, 1920),
        analysis=analysis, **kw,
    )


def test_a_plan_inside_the_cap_is_byte_for_byte_what_it_was():
    import json

    cut = _fill()
    assert cut.report["held"] == 1 and cut.report["cap_note"] == ""
    got = [[round(e.song_start, 6), round(e.song_end, 6), e.clip_id, e.source_in]
           for e in cut.entries]
    assert got == json.loads(json.dumps(_FILL_GOLDEN))


def test_a_plan_past_the_cap_is_coarsened_and_the_gate_takes_it():
    """stop_motion on fast songs planned 625 cuts and the gate refused the whole edit."""
    from muvid.footage.edl import unplaced, validate_edl

    analysis = _analysis(60.0, 300.0)
    free = _cap_fill(analysis, archetype="stop_motion", max_cuts=10**6)
    capped = _cap_fill(analysis, archetype="stop_motion", max_cuts=60)
    assert free.report["n_cuts"] > 60 and free.report["held"] == 1
    r = capped.report
    assert len(capped.entries) <= 60 and r["held"] > 1 and "60-cut limit" in r["cap_note"]
    aligns = [unplaced(s.clip_id, s.duration_s or 60.0) for s in _sources()]
    validate_edl(capped.entries, aligns, 60.0, allow_unreliable=False)


def test_repeated_section_labels_with_short_clips_terminate_with_an_honest_note():
    """#228 review: holding cannot cross a section, and a piece longer than its clip is
    split into take-overs, so the cap can be out of reach — the loop must stop and say so
    (it hung on verse/chorus/verse/chorus)."""
    analysis = _analysis(40.0, 120.0)
    from dataclasses import replace

    labels = ("verse", "chorus", "verse", "chorus")
    analysis = replace(analysis, sections=tuple(
        Section(label=lab, start=10.0 * i, end=10.0 * (i + 1), energy_db=-15.0)
        for i, lab in enumerate(labels)
    ))
    short = [FreeSource("a", "/x/a.mp4", duration_s=1.0), FreeSource("b", "/x/b.mp4", duration_s=0.9)]
    cut = _cap_fill(analysis, short, archetype="ballad_dissolve", max_cuts=3)
    assert len(cut.entries) > 3
    assert "over the 3-cut limit" in cut.report["cap_note"]


def test_a_cap_below_one_is_refused():
    with pytest.raises(ValueError, match="max_cuts"):
        _fill(max_cuts=0)
