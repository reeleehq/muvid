"""Cut to the music in the order the pictures were TAKEN (muvid#137).

Capture time is read from the file (EXIF for a photo, QuickTime tags for a video) at
upload and kept on the clip row; ``fill_spans(order="taken")`` then lets the day read as
it happened, with upload order for whatever says nothing — and says which it did.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from muvid.footage import capture_time as ct
from muvid.footage import music_cut, service
from muvid.footage.music_cut import FreeSource, fill_spans
from tests.test_music_cut import _analysis

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def test_a_stamp_is_wall_clock_seconds_and_absent_is_none():
    base = ct.wall_clock_seconds("2024:06:01 14:03:22")
    assert ct.wall_clock_seconds("2024-06-01T14:03:22-0700") == base
    assert ct.wall_clock_seconds("2024-06-01T21:03:22.000000Z") == base + 7 * 3600
    for bad in (
        "",
        None,
        "nope",
        "0000:00:00 00:00:00",
        "1904-01-01T00:00:00Z",
        "1970:01:01 00:00:00",
        "2024:13:01 00:00:00",
    ):
        assert ct.wall_clock_seconds(bad) is None


def test_a_photos_exif_time_is_read_original_first():
    from PIL import Image

    im = Image.new("RGB", (4, 4))
    exif = Image.Exif()
    exif[306] = "2024:06:02 09:00:00"  # DateTime (when edited)
    exif.get_ifd(0x8769)[36867] = "2024:06:01 14:03:22"  # DateTimeOriginal
    im.info["exif"] = exif.tobytes()
    import io

    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif)
    buf.seek(0)
    with Image.open(buf) as reopened:
        t, source = ct.photo_capture_time(reopened)
    assert t == ct.wall_clock_seconds("2024:06:01 14:03:22")
    assert source == ct.EXIF_ORIGINAL


def test_a_photo_without_exif_has_no_time():
    from PIL import Image

    assert ct.photo_capture_time(Image.new("RGB", (4, 4))) == (None, "")


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg + ffprobe")
def test_a_videos_quicktime_tag_beats_its_utc_creation_time(tmp_path):
    out = tmp_path / "v.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x48:duration=1",
            "-metadata",
            "creation_time=2024-06-01T21:03:22Z",
            "-metadata",
            "com.apple.quicktime.creationdate=2024-06-01T14:03:22-0700",
            "-movflags",
            "use_metadata_tags",
            str(out),
        ],
        check=True,
    )
    t, source = ct.video_capture_time(out)
    assert (
        t == ct.wall_clock_seconds("2024:06:01 14:03:22")
        and source == ct.QT_CREATIONDATE
    )
    plain = tmp_path / "p.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x48:duration=1",
            "-metadata",
            "creation_time=2024-06-01T21:03:22Z",
            str(plain),
        ],
        check=True,
    )
    assert ct.video_capture_time(plain)[1] == ct.CREATION_TIME


def test_a_missing_or_unreadable_video_has_no_time(tmp_path):
    assert ct.video_capture_time(tmp_path / "nope.mp4") == (None, "")


# -- the ordering (the montage planner's `chronological` reuse order) -----------------------


def _pool(*times, strength=None):
    from muvid.montage.analysis import Media

    return [
        Media(
            index=i,
            path=f"{i}.jpg",
            kind="photo",
            width=1,
            height=1,
            taken_at=t,
            strength=(strength[i] if strength else 0.0),
        )
        for i, t in enumerate(times)
    ]


def _drafts(n, *, start=0.0):
    from muvid.montage.plan import SlotDraft

    return [
        SlotDraft(start=start + i, end=start + i + 1, section="v", archetype="beat_cut")
        for i in range(n)
    ]


def _assign(pool, drafts, **kw):
    from muvid.montage.plan import assign_media
    from muvid.montage.spec import Reuse

    picks, stats = assign_media(drafts, pool, Reuse(order="chronological"), **kw)
    return [p[0][0] for p in picks], stats


def test_pictures_follow_capture_time_not_upload_order():
    picks, stats = _assign(_pool(30.0, 10.0, 20.0), _drafts(3))
    assert (
        picks == [1, 2, 0] and stats["order"] == "taken" and stats["order_note"] == ""
    )


def test_undated_pictures_follow_the_dated_ones_and_the_note_says_so():
    picks, stats = _assign(_pool(None, 10.0, None, 5.0), _drafts(4))
    assert picks == [3, 1, 0, 2]
    assert (
        stats["order"] == "taken"
        and "2 of 4 have no capture time" in stats["order_note"]
    )


def test_nothing_dated_is_upload_order_and_says_so():
    picks, stats = _assign(_pool(None, None, None), _drafts(3))
    assert picks == [0, 1, 2] and stats["order"] == "upload"
    assert "upload order" in stats["order_note"]


def test_a_long_day_is_sampled_in_order_taking_the_strongest_of_each_share():
    pool = _pool(*range(6), strength=(0.1, 0.9, 0.2, 0.3, 0.8, 0.1))
    assert _assign(pool, _drafts(3))[0] == [
        1,
        3,
        4,
    ]  # one per third of the day, in order


def test_a_short_day_repeats_from_its_start():
    assert _assign(_pool(1.0, 2.0), _drafts(5))[0] == [0, 1, 0, 1, 0]


def test_only_the_slots_that_will_be_shown_spend_the_day():
    """A synced take over the first half must not eat the first half of the day."""
    drafts = _drafts(6)
    picks, stats = _assign(
        _pool(*range(3)),
        drafts,
        active=lambda d: d.start >= 3,  # last three shown
    )
    assert picks[3:] == [0, 1, 2]
    assert stats["n_assignments"] == 3 and stats["uses"] == {"0": 1, "1": 1, "2": 1}


def test_the_planner_order_is_unchanged_by_default():
    from muvid.montage.plan import assign_media
    from muvid.montage.spec import Reuse

    assert Reuse().order == "least_used"
    picks, stats = assign_media(_drafts(4), _pool(1.0, 2.0, 3.0), Reuse())
    assert "order" not in stats  # the old policy's stats are as they were


def test_reuse_order_is_validated():
    from muvid.montage import spec

    assert spec.REUSE_ORDERS == ("least_used", "chronological")


def _stills(*times):
    return [
        FreeSource(f"p{i}", f"p{i}.jpg", "still", taken_at=t)
        for i, t in enumerate(times)
    ]


def _fill(order, sources, **kw):
    return fill_spans(
        "song.wav",
        sources,
        analysis=_analysis(),
        song_duration=40.0,
        size_of=lambda p: (1080, 1920),
        canvas=(1080, 1920),
        order=order,
        **kw,
    )


def test_fill_spans_shows_the_day_in_order_and_reports_it():
    src = _stills(50.0, 10.0, 30.0, 20.0, 40.0)
    cut = _fill("taken", src)
    first_seen = []
    for e in cut.entries:
        if e.clip_id not in first_seen:
            first_seen.append(e.clip_id)
    assert first_seen == ["p1", "p3", "p2", "p4", "p0"]  # by capture time
    assert cut.report["order"] == "taken" and cut.report["order_note"] == ""


def test_planner_order_is_still_available_and_differs():
    src = _stills(50.0, 10.0, 30.0, 20.0, 40.0)
    taken = _fill("taken", src)
    planner = _fill("planner", src)
    assert planner.report["order"] == "planner"
    assert [e.clip_id for e in taken.entries] != [e.clip_id for e in planner.entries]


def test_spans_filled_by_the_music_spend_only_their_own_share_of_the_day():
    src = _stills(*range(6))
    cut = _fill("taken", src, spans=[(20.0, 40.0)])
    first_seen = []
    for e in cut.entries:
        if e.clip_id not in first_seen:
            first_seen.append(e.clip_id)
    assert first_seen[0] == "p0"  # the day starts where the music starts, not mid-way


def test_an_unknown_order_is_refused():
    with pytest.raises(ValueError, match="order must be one of"):
        _fill("alphabetical", _stills(1.0))


# -- at upload and through propose_edit ---------------------------------------------------


@pytest.fixture
def bath(tmp_path, monkeypatch):
    from muvid.footage.workspace import FootageWorkspace

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(music_cut, "_default_analysis", lambda path: _analysis())
    proj = FootageWorkspace.for_email("u@x.com").create_project("day")
    song = tmp_path / "song.wav"
    song.write_bytes(b"RIFF-song")
    service.set_song(proj, path=str(song), duration_s=40.0)
    return proj


def _photo(tmp_path, name, stamp):
    from PIL import Image

    path = tmp_path / name
    exif = Image.Exif()
    if stamp:
        exif.get_ifd(0x8769)[36867] = stamp
    Image.new("RGB", (64, 48), (200, 30, 30)).save(path, "JPEG", exif=exif)
    return path


def test_upload_records_the_capture_time_on_the_clip_row(bath, tmp_path):
    p = _photo(tmp_path, "a.jpg", "2024:06:01 14:03:22")
    added = service.add_clip(bath, path=str(p), filename="a.jpg", clip_id="a")
    q = _photo(tmp_path, "b.jpg", None)
    service.add_clip(bath, path=str(q), filename="b.jpg", clip_id="b")
    rows = {c["clip_id"]: c for c in bath.list_clips()}
    assert added["kind"] == "still"
    assert rows["a"]["taken_at"] == ct.wall_clock_seconds("2024:06:01 14:03:22")
    assert "taken_at" not in rows["b"]  # absent, never a made-up time
    assert bath.manifest()["clips"][0]["taken_source"] == ct.EXIF_ORIGINAL


def test_propose_edit_defaults_to_taken_order_and_planner_is_one_word_away(
    bath, tmp_path
):
    for cid, stamp in (
        ("late", "2024:06:01 18:00:00"),
        ("early", "2024:06:01 08:00:00"),
        ("mid", "2024:06:01 12:00:00"),
    ):
        p = _photo(tmp_path, f"{cid}.jpg", stamp)
        service.add_clip(bath, path=str(p), filename=p.name, clip_id=cid)
    out = service.propose_edit(bath, save=False)
    seen = []
    for e in out["edl"]:
        if e["clip_id"] and e["clip_id"] not in seen:
            seen.append(e["clip_id"])
    assert seen == ["early", "mid", "late"] and out["music"]["order"] == "taken"
    assert (
        service.propose_edit(bath, save=False, order="planner")["music"]["order"]
        == "planner"
    )
    with pytest.raises(service.FootageError, match="order must be one of"):
        service.propose_edit(bath, save=False, order="alphabetical")


def test_the_saved_edit_records_the_order_that_was_used(bath, tmp_path):
    for cid, stamp in (("b", "2024:06:01 12:00:00"), ("a", "2024:06:01 08:00:00")):
        p = _photo(tmp_path, f"{cid}.jpg", stamp)
        service.add_clip(bath, path=str(p), filename=p.name, clip_id=cid)
    out = service.propose_edit(bath)
    assert bath.read_edit(out["edit_id"])["selection"]["order"] == "taken"


def test_a_project_with_no_dates_is_upload_order_and_the_reply_says_so(bath, tmp_path):
    for cid in ("one", "two"):
        p = _photo(tmp_path, f"{cid}.jpg", None)
        service.add_clip(bath, path=str(p), filename=p.name, clip_id=cid)
    music = service.propose_edit(bath, save=False)["music"]
    assert music["order"] == "upload" and "upload order" in music["order_note"]


def test_mixing_a_utc_only_video_with_dated_photos_is_flagged():
    src = [
        FreeSource("p", "p.jpg", "still", taken_at=1.0, taken_source=ct.EXIF_ORIGINAL),
        FreeSource(
            "v", "v.mp4", "video", 5.0, taken_at=2.0, taken_source=ct.CREATION_TIME
        ),
    ]
    assert "UTC" in music_cut._mixed_clock_note(src)
    assert music_cut._mixed_clock_note(src[:1]) == ""


def test_the_connector_propose_edit_takes_order():
    pytest.importorskip("fastmcp")
    import inspect

    import muvid.mcp.footage_tools as ft

    assert "order" in inspect.signature(ft.propose_edit).parameters
