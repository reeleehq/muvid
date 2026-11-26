"""A visualizer render's picture covers its song exactly, and keeps all its audio (muvid#392).

Measured on main before the fix, for a 4.000 s song:
- ``cqt`` and ``scope`` with a cover came out one frame short (3.900 s at 10 fps).
  Those visuals flush their last frame only when the audio ends, and beside an
  endless looping cover that frame was lost.
- ``cqt`` with no cover was one frame short at 24 fps.
- the ``still`` visual was two frames LONG at every rate (4.2 s at 10 fps). Its
  picture is a stream copy, cut by ``-t`` on packets.

With ``normalize=True`` the song also lost its last 65-130 ms: ``loudnorm`` emits
its output late, and a render whose picture ended stopped the graph before that
tail was flushed (muvid#393). The loudness pass now runs as a step of its own.

For songs that are not a whole number of frames long, ``-shortest`` and ``-t`` at
the song's length also ended the picture a frame early and cut up to 60 ms off the
song's tail (the review of #392).

Which visual lost a frame moved with small changes to the graph, so the fix is a
count rather than a bound. The picture is ``ceil(duration * fps)`` frames: it may
run under one frame past the song, but never stops before it. The filtergraph path
clones its last frame forward and trims to that count, and the still path copies
exactly that many frames. The audio is never cut by the picture.
"""

from __future__ import annotations

import json
import math
import subprocess

import pytest

from tests.ffmpeg_support import needs_ffmpeg_filter

#: AAC codes in 1024-sample frames, so a decoded track may end up to one frame
#: (21.3 ms at 48 kHz) off the song's length either way.
AAC_FRAME_S = 1024 / 48000


def _probe(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v"]
        + ["-show_entries", "stream=nb_read_frames", "-of", "json", str(video)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(json.loads(out)["streams"][0]["nb_read_frames"])


def _audio_seconds(video, tmp_path):
    from muvid.visualize.ffmpeg import media_duration

    wav = tmp_path / "back.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video), str(wav)], check=True
    )
    return media_duration(wav)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("len")
    cover = d / "c.png"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240"]
        + ["-frames:v", "1", str(cover)],
        check=True,
    )

    def song(seconds):
        path = d / f"s{seconds}.wav"
        if not path.exists():
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i"]
                + [f"sine=frequency=330:duration={seconds}", "-ac", "2"]
                + ["-ar", "48000", str(path)],
                check=True,
            )
        return path

    return song, cover


@needs_ffmpeg_filter("showcqt")
@pytest.mark.parametrize(
    "visual, with_cover, fps, seconds, normalize",
    [
        # the issue's cases, on a whole number of frames
        ("cqt", True, 10, 4.0, False),
        ("scope", True, 10, 4.0, False),
        ("scope", True, 30, 4.0, False),
        ("cqt", False, 24, 4.0, False),
        ("still", True, 10, 4.0, False),
        # fractional songs: -shortest / -t ended these a frame early
        ("cqt", True, 10, 4.31, False),
        ("scope", False, 30, 4.37, False),
        ("waves", False, 30, 4.049, False),
        ("waves", True, 24, 4.05, False),
        ("still", True, 10, 4.049, False),
        ("still", True, 24, 4.31, False),
        # normalize=True: loudnorm's late tail was cut by the picture's end (#393)
        ("cqt", False, 24, 4.31, True),
        ("waves", True, 24, 4.31, True),
        ("still", True, 24, 4.31, True),
    ],
)
def test_the_picture_covers_the_song_and_the_song_is_whole(
    media, tmp_path, visual, with_cover, fps, seconds, normalize
):
    from muvid.visualize import render_audio_video

    song, cover = media
    result = render_audio_video(
        song(seconds),
        cover if with_cover else None,
        visual=visual,
        saveas=tmp_path / "out.mp4",
        size=(640, 360),
        fps=fps,
        normalize=normalize,
    )
    case = (
        f"{visual}{' + cover' if with_cover else ''}, {seconds} s at {fps} fps"
        f"{', normalized' if normalize else ''}"
    )
    got, want = _probe(result.path), math.ceil(seconds * fps - 1e-6)
    assert got == want, f"{case}: {got} frames, {want} cover the song"
    heard = _audio_seconds(result.path, tmp_path)
    assert heard >= seconds - AAC_FRAME_S, (
        f"{case}: the song's tail was cut ({heard} s)"
    )
