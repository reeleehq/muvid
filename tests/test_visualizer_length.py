"""A visualizer render is exactly as long as its song, in frames (muvid#392).

Measured on main before the fix, a 4.000 s song gave:
- ``cqt`` and ``scope`` with a cover, one frame short (3.900 s at 10 fps). Those
  visuals flush their last frame only when the audio ends, and beside an endless
  looping cover that frame was lost.
- ``cqt`` with no cover, also one frame short at 24 fps.
- the ``still`` visual, two frames LONG at every rate (4.2 s at 10 fps). Its
  picture is a stream copy cut by ``-t`` on packets.

Which visual lost a frame moved with small changes to the graph, so the fix is a
count rather than a bound: the filtergraph path clones its last frame forward and
trims at ``round(duration * fps)``, and the still path copies exactly that many
frames. This test pins the count for every case above, on whichever ffmpeg runs it.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from tests.ffmpeg_support import needs_ffmpeg_filter

SONG_S = 4.0


def _decoded_frames(video) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v"]
        + ["-show_entries", "stream=nb_read_frames", "-of", "json", str(video)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(json.loads(out)["streams"][0]["nb_read_frames"])


@pytest.fixture(scope="module")
def song_and_cover(tmp_path_factory):
    d = tmp_path_factory.mktemp("len")
    song, cover = d / "s.wav", d / "c.png"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i"]
        + [f"sine=frequency=330:duration={SONG_S}", "-ac", "2", "-ar", "48000"]
        + [str(song)],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240"]
        + ["-frames:v", "1", str(cover)],
        check=True,
    )
    return song, cover


@needs_ffmpeg_filter("showcqt")
@pytest.mark.parametrize(
    "visual, with_cover, fps",
    [
        ("cqt", True, 10),
        ("scope", True, 10),
        ("scope", True, 30),
        ("cqt", False, 24),
        ("waves", True, 10),
        ("still", True, 10),
        ("still", True, 24),
    ],
)
def test_the_picture_has_exactly_the_songs_frames(
    song_and_cover, tmp_path, visual, with_cover, fps
):
    from muvid.visualize import render_audio_video

    song, cover = song_and_cover
    result = render_audio_video(
        song,
        cover if with_cover else None,
        visual=visual,
        saveas=tmp_path / "out.mp4",
        size=(640, 360),
        fps=fps,
    )
    got, want = _decoded_frames(result.path), round(SONG_S * fps)
    assert got == want, (
        f"{visual}{' + cover' if with_cover else ''} at {fps} fps: {got} frames for "
        f"a {SONG_S} s song ({want} expected)"
    )
