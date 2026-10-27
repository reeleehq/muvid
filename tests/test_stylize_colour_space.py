"""The delivery colour (muvid#195), and ``stylize``'s Rule 22 declaration of it.

The assembler converts every cut to BT.709 limited range and tags the encode, so
``stylize`` declares that colour as a FACT for ``looks`` Rule 22 (muvid#190 had to
assume it). Three things are pinned here: the declaration matches the assembler's
constants; every colour wrapper ``looks`` can emit passes the look gate; and a
BT.601 clip or a full-range JPEG still really is converted — measured against
the RGB original, decoded the way a player reads a BT.709-tagged file.
"""

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

import looks

from tests.ffmpeg_support import needs_ffmpeg, needs_ffmpeg_filter
from muvid.footage.assemble import (
    AssemblyWarning,
    _render_part,
    _with_source_colour,
    assemble_music_video,
)
from muvid.footage.colour import DELIVERY_COLOR_RANGE, DELIVERY_COLOR_SPACE
from muvid.footage.edl import AssemblyCut, EdlEntry, _validate_look
from muvid.footage.look import stylize

_GRADE = looks.Look(steps=(looks.Effect(name="saturation", params={"amount": 0.0}),))
_KW = dict(canvas=(640, 360), fps=25, duration_s=3.0)
_W, _H, _FPS = 320, 240, 25

#: Removing the ``scale``'s conversion fails these on 8.0.1 and 7.0.2 alike (the
#: ``setparams`` tag then re-labels an unconverted frame). Removing the tag as well
#: passes on 8.0.1 only, whose encoder converts on its own (see ``_part_filter``).
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


def _hd_clip(tmp_path, name: str, *, tag: str) -> "tuple[Path, Path]":
    """A 1280x720 RGB reference and a BT.709-encoded clip of it whose tags ``tag`` sets.

    The tag is written on the frame (``setparams``) AND as encoder options, because
    the two ffmpeg builds in use read different ones."""
    ref = tmp_path / f"{name}.png"
    _run(
        ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=0.1"]
        + ["-frames:v", "1", str(ref)]
    )
    clip = tmp_path / f"{name}.mp4"
    _run(
        ["-loop", "1", "-i", str(ref), "-t", "0.5", "-vf"]
        + [f"scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,{tag}"]
        + ["-c:v", "libx264", "-crf", "1", str(clip)]
    )
    return ref, clip


@needs_ffmpeg
def test_an_untagged_hd_clip_is_read_as_bt709_the_way_players_read_it(tmp_path):
    """The #195 review's regression: ``scale`` treats an unspecified matrix as BT.601,
    so an untagged BT.709 HD clip went 41.6 -> 26.9 dB until the assembler probed it
    and told ``scale`` the matrix players assume."""
    untag = "setparams=colorspace=unknown:color_primaries=unknown:color_trc=unknown"
    ref, clip = _hd_clip(tmp_path, "untagged", tag=untag)
    (cut,) = _with_source_colour([AssemblyCut(0.0, 0.4, "A", 0.0, str(clip))])
    assert cut.source_colour.in_matrix == "bt709" and not cut.source_tonemap
    part = tmp_path / "part.mp4"
    _render_part(
        cut,
        part,
        w=1280,
        h=720,
        fps=_FPS,
        n_frames=int(0.4 * _FPS),
        crf=1,
        preset="veryfast",
    )
    seen = _as_a_player_reads_it(part, tmp_path / "seen.png")
    assert _psnr(seen, ref) >= _MIN_PSNR_DB


def _hlg_clip(tmp_path) -> "tuple[Path, Path]":
    """A 1280x720 SDR reference and an HLG BT.2020 10-bit clip of it (lossless FFV1, so
    any build can write it; tagged on the frame and in the container)."""
    ref, _ = _hd_clip(tmp_path, "sdr", tag="null")
    clip = tmp_path / "hlg.mkv"
    _run(
        ["-loop", "1", "-i", str(ref), "-t", "0.5", "-vf"]
        + [
            "zscale=tin=bt709:t=arib-std-b67:pin=bt709:p=bt2020:min=bt709:m=bt2020nc"
            ":r=tv:npl=203,format=yuv420p10le,setparams=color_trc=arib-std-b67"
            ":color_primaries=bt2020:colorspace=bt2020nc:range=tv"
        ]
        + ["-color_trc", "arib-std-b67", "-color_primaries", "bt2020"]
        + ["-colorspace", "bt2020nc", "-c:v", "ffv1", str(clip)]
    )
    return ref, clip


#: An HLG clip of an SDR original, decoded as BT.709: 10.0 dB converted in matrix only
#: (washed out), 24.7 dB tone-mapped (ffmpeg 8.0.1). The line between the two.
_MIN_TONEMAPPED_PSNR_DB = 20.0


@needs_ffmpeg_filter("zscale", "tonemap")
def test_an_hdr_clip_is_tone_mapped_to_the_sdr_delivery(tmp_path):
    """muvid#201: an HLG source is tone-mapped, not delivered washed out."""
    ref, clip = _hlg_clip(tmp_path)
    (cut,) = _with_source_colour([AssemblyCut(0.0, 0.4, "cam", 0.0, str(clip))])
    assert cut.source_tonemap

    def seen_through(c, name):
        part = tmp_path / f"{name}.mp4"
        _render_part(
            c,
            part,
            w=1280,
            h=720,
            fps=_FPS,
            n_frames=int(0.4 * _FPS),
            crf=1,
            preset="veryfast",
        )
        return _psnr(_as_a_player_reads_it(part, tmp_path / f"{name}.png"), ref)

    assert seen_through(cut, "mapped") >= _MIN_TONEMAPPED_PSNR_DB
    # the premise: converted in matrix only, it is washed out
    assert (
        seen_through(replace(cut, source_tonemap=False), "flat")
        < _MIN_TONEMAPPED_PSNR_DB
    )


@needs_ffmpeg_filter("zscale")
def test_an_hdr_clip_is_reported_when_this_ffmpeg_cannot_tone_map_it(
    tmp_path, monkeypatch
):
    """A build without zscale/tonemap delivers HLG washed out; that is a visible change
    in the picture, so it reaches the caller as a finding."""
    import muvid.footage.assemble as A

    _ref, clip = _hlg_clip(tmp_path)
    monkeypatch.setattr(A, "can_tonemap", lambda: False)
    notes: "list[str]" = []
    with pytest.warns(AssemblyWarning, match="HDR"):
        (cut,) = _with_source_colour(
            [AssemblyCut(0.0, 0.4, "cam", 0.0, str(clip))], notes.append
        )
    assert not cut.source_tonemap
    assert len(notes) == 1 and "'cam'" in notes[0] and "arib-std-b67" in notes[0]


def _flat_hlg(tmp_path, colour: str, *, untag: str = "") -> Path:
    """A flat HLG BT.2020 frame of the SDR ``colour``; ``untag`` names a tag to leave out
    (``color_primaries`` or ``colorspace``), as some cameras and phones do."""
    tags = {
        "color_trc": "arib-std-b67",
        "color_primaries": "bt2020",
        "colorspace": "bt2020nc",
    }
    if untag:
        tags[untag] = "unknown"
    setp = ":".join(f"{k}={v}" for k, v in tags.items())
    out = tmp_path / f"flat_{colour}_{untag or 'all'}.mkv"
    _run(
        ["-f", "lavfi", "-i", f"color=c={colour}:size=320x240:duration=0.4:rate={_FPS}"]
        + ["-vf"]
        + [
            "format=rgb24,zscale=tin=bt709:t=arib-std-b67:pin=bt709:p=bt2020:min=bt709"
            f":m=bt2020nc:r=tv:npl=203,format=yuv420p10le,setparams={setp}:range=tv"
        ]
        + [x for k, v in tags.items() for x in (f"-{k}", v)]
        + ["-c:v", "ffv1", str(out)]
    )
    return out


def _mean_y(video: Path) -> float:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-frames:v", "1", "-f", "rawvideo"]
        + ["-pix_fmt", "yuv420p", "-"],
        capture_output=True,
        check=True,
    ).stdout
    return sum(raw[: 320 * 240]) / (320 * 240)


def _tonemapped(tmp_path, clip: Path, name: str) -> Path:
    (cut,) = _with_source_colour([AssemblyCut(0.0, 0.4, "cam", 0.0, str(clip))])
    assert cut.source_tonemap
    part = tmp_path / f"{name}.mp4"
    _render_part(
        cut,
        part,
        w=320,
        h=240,
        fps=_FPS,
        n_frames=int(0.4 * _FPS),
        crf=1,
        preset="veryfast",
    )
    return part


@needs_ffmpeg_filter("zscale", "tonemap")
def test_reference_white_and_mid_grey_land_where_sdr_puts_them(tmp_path):
    """The #201 review: the PSNR test cannot see a wrong reference white (100 nits
    scores 24.4 dB). Levels can: measured, 18% grey comes out at Y 117 against SDR's
    116 (151 with a 100-nit white, 92 with 400), and white at Y 228 (181 with 400)."""
    grey = _mean_y(_tonemapped(tmp_path, _flat_hlg(tmp_path, "0x767676"), "grey"))
    white = _mean_y(_tonemapped(tmp_path, _flat_hlg(tmp_path, "white"), "white"))
    assert abs(grey - 116) <= 8, grey
    assert white >= 220, white


@needs_ffmpeg_filter("zscale", "tonemap")
@pytest.mark.parametrize("untag", ["color_primaries", "colorspace"])
def test_an_hdr_clip_missing_a_colour_tag_still_renders(tmp_path, untag):
    """The #201 review's regression: zscale refuses to convert from a colour it is not
    told ("no path between colorspaces"), so an HLG clip with untagged primaries or
    matrix failed the whole render where it used to render washed out. The missing
    tag is filled with BT.2020's."""
    clip = _flat_hlg(tmp_path, "0x767676", untag=untag)
    (cut,) = _with_source_colour([AssemblyCut(0.0, 0.4, "cam", 0.0, str(clip))])
    assert dict(cut.source_colour.hdr_fill), cut.source_colour
    grey = _mean_y(_tonemapped(tmp_path, clip, f"grey_{untag}"))
    assert abs(grey - 116) <= 8, grey
