"""The delivery colour (muvid#195), and ``stylize``'s Rule 22 declaration of it.

The assembler converts every cut to BT.709 limited range and tags the encode, so
``stylize`` declares that colour as a FACT for ``looks`` Rule 22 (muvid#190 had to
assume it). Three things are pinned here: the declaration matches the assembler's
constants; every colour wrapper ``looks`` can emit passes the look gate; and a
BT.601 clip or a full-range JPEG still really is converted — measured against
the RGB original, decoded the way a player reads a BT.709-tagged file.
"""

import subprocess
from pathlib import Path

import pytest

import looks

from tests.ffmpeg_support import needs_ffmpeg
from muvid.footage.assemble import (
    DELIVERY_COLOR_RANGE,
    DELIVERY_COLOR_SPACE,
    _render_part,
    assemble_music_video,
)
from muvid.footage.edl import AssemblyCut, EdlEntry, _validate_look
from muvid.footage.look import stylize

_GRADE = looks.Look(steps=(looks.Effect(name="saturation", params={"amount": 0.0}),))
_KW = dict(canvas=(640, 360), fps=25, duration_s=3.0)
_W, _H, _FPS = 320, 240, 25

#: On ffmpeg 8 the encoder's ``-colorspace``/``-color_range`` alone also convert
#: (format negotiation), so there these tests cannot tell the ``scale`` from the
#: options; on ffmpeg 6 (CI) they can. See ``assemble.DELIVERY_COLOR_SPACE``.
#:
#: Below this the source's colour was mis-read. Measured on ffmpeg 8.0.1: 24 dB for
#: both sources before muvid#195, 37 dB (BT.601) and 41 dB (JPEG) after.
_MIN_PSNR_DB = 32.0


@needs_ffmpeg
def test_stylize_declares_the_assemblers_delivery_colour():
    frag = stylize(_GRADE, **_KW)
    assert f"in_color_matrix={DELIVERY_COLOR_SPACE}" in frag
    assert "in_range=limited" in frag and DELIVERY_COLOR_RANGE == "tv"


@pytest.mark.parametrize("space", ["bt709", "bt601", "smpte170m", "bt2020nc"])
@pytest.mark.parametrize("range_", [None, "tv", "pc"])
def test_every_colour_wrapper_looks_emits_passes_the_gate(space, range_):
    """``looks.ffmpeg.matrix_wrap`` is the colour-only ``scale`` Rule 22 puts around
    every RGB step; a variant the gate refuses would kill every grade on a clip of
    that colour, with no change in muvid (the #196 review's follow-up)."""
    from looks.ffmpeg import matrix_wrap

    clip = looks.ClipSpec(
        width=_W, height=_H, fps=_FPS, color_space=space, color_range=range_
    )
    wrap = matrix_wrap(clip)
    _validate_look(0, EdlEntry(0.0, 1.0, "A", look=f"{wrap},hue=s=0,{wrap}"), (_W, _H))


def _run(args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def _psnr(a: Path, b: Path) -> float:
    out = subprocess.run(
        ["ffmpeg", "-i", str(a), "-i", str(b), "-lavfi", "psnr", "-f", "null", "-"],
        capture_output=True,
        text=True,
    ).stderr
    return float(out.rsplit("average:", 1)[1].split()[0])


def _as_a_player_reads_it(video: Path, out: Path) -> Path:
    """The first frame decoded as BT.709 limited, whatever the file says."""
    _run(
        ["-i", str(video), "-frames:v", "1", "-vf"]
        + ["scale=in_color_matrix=bt709:in_range=tv,format=rgb24", str(out)]
    )
    return out


@pytest.fixture
def sources(tmp_path):
    """An RGB reference frame, a correctly tagged BT.601 clip and a JPEG still of it."""
    ref = tmp_path / "ref.png"
    _run(
        ["-f", "lavfi", "-i", f"testsrc2=size={_W}x{_H}:rate={_FPS}:duration=0.1"]
        + ["-frames:v", "1", str(ref)]
    )
    clip = tmp_path / "bt601.mp4"
    _run(
        ["-loop", "1", "-i", str(ref), "-t", "1", "-vf"]
        + ["scale=out_color_matrix=bt601:out_range=tv,format=yuv420p"]
        + ["-colorspace", "smpte170m", "-color_primaries", "smpte170m"]
        + ["-color_trc", "smpte170m", "-color_range", "tv"]
        + ["-c:v", "libx264", "-crf", "1", str(clip)]
    )
    still = tmp_path / "still.jpg"
    _run(["-i", str(ref), "-q:v", "1", str(still)])
    return ref, clip, still


def _cut(path: Path, seconds: float = 0.4) -> AssemblyCut:
    return AssemblyCut(0.0, seconds, "A", 0.0, str(path))


@needs_ffmpeg
@pytest.mark.parametrize("which", ["bt601", "jpeg"])
def test_a_cut_is_converted_to_the_delivery_colour(sources, tmp_path, which):
    ref, clip, still = sources
    src = clip if which == "bt601" else still
    part = tmp_path / "part.mp4"
    _render_part(
        _cut(src),
        part,
        w=_W,
        h=_H,
        fps=_FPS,
        n_frames=int(0.4 * _FPS),
        crf=1,
        preset="veryfast",
    )
    seen = _as_a_player_reads_it(part, tmp_path / "seen.png")
    assert _psnr(seen, ref) >= _MIN_PSNR_DB


@needs_ffmpeg
def test_the_delivered_video_is_tagged_with_the_delivery_colour(sources, tmp_path):
    _ref, clip, _still = sources
    song = tmp_path / "song.m4a"
    _run(
        ["-f", "lavfi", "-i", "sine=frequency=220:duration=1", "-c:a", "aac"]
        + [str(song)]
    )
    out = assemble_music_video(
        [_cut(clip, 1.0)],
        str(song),
        str(tmp_path / "out.mp4"),
        canvas=(_W, _H),
        fps=_FPS,
    )
    tags = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries"]
        + ["stream=color_space,color_range,color_primaries,color_transfer"]
        + ["-of", "default=nw=1", str(out)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert dict(line.split("=") for line in tags.split()) == {
        "color_space": DELIVERY_COLOR_SPACE,
        "color_range": DELIVERY_COLOR_RANGE,
        "color_primaries": DELIVERY_COLOR_SPACE,
        "color_transfer": DELIVERY_COLOR_SPACE,
    }
