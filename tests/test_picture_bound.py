"""A free cut is bounded by the clip's PICTURE, not its audio (muvid#322).

The renderer reads only the picture for a cut (``-an``), so what a free cut may read is
the video stream's own length. Both failure modes of bounding it by the audio are pinned
here against real files: the audio ending before the picture refused a cut that would
render, and the audio outlasting the picture accepted a cut past the last frame."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from muvid.footage import service
from muvid.footage.edl import EdlEntry, placed_as, unplaced, validate_edl

from tests.ffmpeg_support import needs_ffmpeg


def _clip(path: Path, *, picture_s: float, audio_s: float) -> Path:
    """A video whose picture and audio tracks have DIFFERENT lengths."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=25:duration={picture_s}",
            "-f", "lavfi", "-i", f"sine=frequency=330:duration={audio_s}",
            "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


def _project(tmp_path, *, picture_s, audio_s):
    import muvid

    muvid.create_project_at(tmp_path, "mv")
    fp = muvid.Project(tmp_path / "mv").footage
    service.add_clip(
        fp,
        path=str(_clip(tmp_path / "a.mp4", picture_s=picture_s, audio_s=audio_s)),
        clip_id="a",
    )
    return fp


def _free_cut(fp, *, source_in, length=1.0):
    edl = [
        {"song_start": 0.0, "song_end": length, "clip_id": "a", "source_in": source_in}
    ]
    return validate_edl(
        [EdlEntry(**edl[0])], service._placements(fp), 12.0, allow_unreliable=True
    )


def test_placed_as_bounds_a_free_cut_by_the_picture_when_it_is_recorded():
    a = unplaced("c", 10.0)
    e = EdlEntry(0.0, 1.0, "c", source_in=2.0)
    assert placed_as(e, a).duration_s == 10.0  # nothing recorded: today's bound
    assert placed_as(e, replace(a, picture_s=6.0)).duration_s == 6.0
    assert placed_as(e, replace(a, picture_s=6.0)).coverage[1] == -2.0 + 6.0


@needs_ffmpeg
def test_the_picture_length_is_recorded_when_a_clip_is_added(tmp_path):
    fp = _project(tmp_path, picture_s=3.0, audio_s=5.0)
    row = next(c for c in fp.manifest()["clips"] if c["clip_id"] == "a")
    assert row["picture_duration"] == pytest.approx(3.0, abs=0.1)
    assert row["duration"] > row["picture_duration"] + 1.0  # the container's, longer


@needs_ffmpeg
def test_a_cut_between_the_audios_end_and_the_pictures_end_is_accepted(tmp_path):
    fp = _project(tmp_path, picture_s=5.0, audio_s=3.0)
    assert _free_cut(fp, source_in=3.5)  # past the audio, inside the picture
    with pytest.raises(ValueError):
        _free_cut(fp, source_in=4.8)  # past the last frame


@needs_ffmpeg
def test_a_cut_past_the_last_frame_is_refused_though_the_audio_goes_on(tmp_path):
    fp = _project(tmp_path, picture_s=3.0, audio_s=5.0)
    assert _free_cut(fp, source_in=1.0)
    with pytest.raises(ValueError):
        _free_cut(fp, source_in=3.5)  # inside the audio: it would freeze (tpad)


@needs_ffmpeg
def test_a_clip_added_before_the_field_existed_is_measured_and_recorded(tmp_path):
    """No migration: the gate measures a clip with no recorded picture, once."""
    fp = _project(tmp_path, picture_s=3.0, audio_s=5.0)
    service._set_clip_field(fp, "a", "picture_duration", None)
    assert (
        next(c for c in fp.manifest()["clips"] if c["clip_id"] == "a").get(
            "picture_duration"
        )
        is None
    )
    with pytest.raises(ValueError):
        _free_cut(fp, source_in=3.5)
    row = next(c for c in fp.manifest()["clips"] if c["clip_id"] == "a")
    assert row["picture_duration"] == pytest.approx(3.0, abs=0.1)


@needs_ffmpeg
def test_a_matroska_picture_is_measured_from_its_tag(tmp_path):
    """Matroska gives a stream no ``duration`` of its own; its DURATION tag stands in."""
    from muvid.visualize.ffmpeg import picture_duration

    path = tmp_path / "a.mkv"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "testsrc=size=160x120:rate=25:duration=3", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )  # fmt: skip
    assert picture_duration(path) == pytest.approx(3.0, abs=0.1)


def test_free_length_is_the_pictures_when_recorded():
    from muvid.footage.edl import free_length

    assert free_length(unplaced("c", 10.0)) == 10.0
    assert free_length(replace(unplaced("c", 10.0), picture_s=4.0)) == 4.0


@needs_ffmpeg
def test_a_synced_cut_past_the_pictures_last_frame_is_refused_though_the_audio_goes_on(
    tmp_path,
):
    """muvid#344: the same freeze for a SYNCED cut. The aligner measured 5 s of audio, the
    picture ends at 3 s; the render reads only the picture."""
    fp = _project(tmp_path, picture_s=3.0, audio_s=5.0)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=12", str(tmp_path / "song.wav")],
        check=True,
    )  # fmt: skip
    service.set_song(fp, path=str(tmp_path / "song.wav"))
    service.set_offset(fp, clip_id="a", offset_s=0.0)

    def synced(start, end):
        return validate_edl(
            [EdlEntry(song_start=start, song_end=end, clip_id="a")],
            service._placements(fp),
            12.0,
            allow_unreliable=True,
        )

    assert synced(1.0, 2.5)
    with pytest.raises(ValueError):
        synced(3.5, 4.5)  # inside the audio, past the last frame
    [placement] = service._placements(fp)
    assert placement.coverage[1] == pytest.approx(3.0, abs=0.1)


def test_synced_length_is_the_smaller_of_the_audio_and_the_picture():
    from muvid.footage.edl import synced_length

    assert synced_length(unplaced("c", 10.0)) == 10.0
    assert synced_length(replace(unplaced("c", 10.0), picture_s=4.0)) == 4.0
    assert synced_length(replace(unplaced("c", 10.0), picture_s=14.0)) == 10.0


def test_the_weighted_dp_does_not_pick_what_the_picture_cannot_show():
    """muvid#344 review: ``weighted`` bounded a clip by its audio, so it picked a stretch
    the gate then refused ("does not contain song span")."""
    import numpy as np

    from muvid.footage.edl import with_pictures
    from muvid.footage.select_score import (
        SelectionContext,
        WeightedSelectionConfig,
        run_weighted,
        span_rewards,
    )
    from tests.test_scoring_select import _align, make_tensor

    song, hop = 20.0, 0.1
    n = int(np.ceil(song / hop)) + 1
    t = np.arange(n) * hop
    # A: 12 s of audio, an 8 s picture; B covers 10-20
    aligns = with_pictures(
        [_align("A", 0.0, 12.0, song), _align("B", 10.0, 10.0, song)],
        [{"clip_id": "A", "picture_duration": 8.0}],
    )
    tensor = make_tensor(
        aligns,
        {"A": np.where(t < 8.0, 1.0, np.nan), "B": np.where(t >= 10.0, 0.2, np.nan)},
        hop=hop,
        n=n,
    )
    ctx = SelectionContext(tensor=tensor, beat_times=np.arange(0, 20.01, 0.5))
    try:
        entries = run_weighted(aligns, song, ctx)[0]
    except ValueError as e:  # a gap the DP cannot fill is stated, not a gate refusal
        assert "does not contain" not in str(e)
    else:
        assert all(e.clip_id != "A" or e.song_end <= 8.0 + 1e-6 for e in entries)
    # a span past the picture has no reward to speak of
    assert span_rewards(
        tensor, aligns, [("A", 8.5, 9.5)], config=WeightedSelectionConfig()
    ) == [None]


def test_a_clamped_coverage_that_leaves_nothing_is_not_an_overlap():
    from muvid.footage.edl import FootageAlignment, with_pictures

    a = FootageAlignment("A", -10.0, 0.9, 20.0, (0.0, 10.0))
    [out] = with_pictures([a], [{"clip_id": "A", "picture_duration": 5.0}])
    assert out.coverage == (0.0, 0.0) and out.overlaps is False
    b = FootageAlignment("B", 2.0, 0.9, 20.0, (2.0, 12.0))
    [out] = with_pictures([b], [{"clip_id": "B", "picture_duration": 5.0}])
    assert out.coverage == (2.0, 7.0) and out.overlaps is True
