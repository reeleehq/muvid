"""A look's ``lut3d`` loads only a bounded ``.cube`` from muvid's LUT folder (muvid#244).

Before, ``lut3d=file=`` was the one unchecked path on the look seam: it would try to
open anything the renderer could read (a probe of the host's disk from a remote EDL),
and its memory is the cube's — 12 bytes x size^3, 201 MB at 256 points — which the
frame-cost budget cannot see.
"""

from __future__ import annotations

import os

import pytest

from muvid.footage.edl import MAX_LUT_SIZE, EdlEntry, validate_edl
from muvid.footage.edl import FootageAlignment
from tests.ffmpeg_support import needs_ffmpeg

_A = FootageAlignment("A", 0.0, 0.9, 10.0, (0.0, 10.0))


@pytest.fixture
def luts(tmp_path, monkeypatch):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data"))
    d = tmp_path / "data" / "luts"
    d.mkdir(parents=True)
    return d


def _cube(path, size=2):
    rows = "\n".join(
        f"{r / (size - 1):.3f} {g / (size - 1):.3f} {b / (size - 1):.3f}"
        for b in range(size)
        for g in range(size)
        for r in range(size)
    )
    path.write_text(f'TITLE "t"\nLUT_3D_SIZE {size}\n{rows}\n')
    return path


def _validate(look):
    return validate_edl([EdlEntry(0.0, 4.0, "A", look=look)], [_A], 4.0)


def test_a_cube_in_the_lut_folder_is_accepted(luts):
    cube = _cube(luts / "warm.cube")
    for look in (f"lut3d={cube}", f"lut3d=file={cube}:interp=trilinear", "lut3d"):
        [e] = _validate(look)
        assert e.look == look


@pytest.mark.parametrize(
    "make, match",
    [
        (lambda d, t: "lut3d=file=/etc/passwd", "absolute .cube path"),
        (lambda d, t: f"lut3d=file={_cube(t / 'outside.cube')}", "LUT folder"),
        (lambda d, t: f"lut3d=file={d}/../escape.cube", "LUT folder"),
        (lambda d, t: f"lut3d=file={d}/missing.cube", "LUT folder"),
        (lambda d, t: "lut3d=file=warm.cube", "absolute"),
        (lambda d, t: rf"lut3d=file={d}/a\[b\].cube", "without escapes"),
        (lambda d, t: f"lut3d=file='{d}/warm.cube'", "without escapes"),
        (lambda d, t: f"lut3d=file={_cube(d / 'w.cube')}:foo=1", "does not offer"),
        (lambda d, t: f"lut3d={_cube(d / 'w.cube')}:1", "does not offer"),
    ],
)
def test_anything_else_is_refused(luts, tmp_path, make, match):
    with pytest.raises(ValueError, match=match):
        _validate(make(luts, tmp_path))


def test_a_symlink_out_of_the_folder_is_refused(luts, tmp_path):
    target = _cube(tmp_path / "elsewhere.cube")
    os.symlink(target, luts / "link.cube")
    with pytest.raises(ValueError, match="LUT folder"):
        _validate(f"lut3d=file={luts}/link.cube")


def test_a_cube_larger_than_the_cap_or_without_a_size_is_refused(luts):
    big = luts / "big.cube"
    big.write_text(f"LUT_3D_SIZE {MAX_LUT_SIZE + 1}\n0 0 0\n")
    with pytest.raises(ValueError, match=f"{MAX_LUT_SIZE + 1}-point cube"):
        _validate(f"lut3d=file={big}")
    bare = luts / "bare.cube"
    bare.write_text("0 0 0\n")
    with pytest.raises(ValueError, match="no LUT_3D_SIZE"):
        _validate(f"lut3d=file={bare}")


def test_the_refusal_does_not_print_the_folder(luts):
    with pytest.raises(ValueError) as exc:
        _validate(f"lut3d=file={luts}/missing.cube")
    assert str(luts) not in str(exc.value)


@needs_ffmpeg
def test_an_accepted_lut_renders(luts, tmp_path):
    """The accepted spelling is one ffmpeg loads — not a rule that refuses everything."""
    from muvid.footage.assemble import _render_part
    from muvid.footage.edl import AssemblyCut
    import subprocess

    cube = _cube(luts / "identity.cube", size=3)
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         "testsrc2=size=64x48:rate=30:duration=1", "-pix_fmt", "yuv420p", str(src)],
        check=True,
    )
    [e] = _validate(f"lut3d=file={cube}")
    out = tmp_path / "out.mp4"
    _render_part(
        AssemblyCut(0.0, 1.0, "A", 0.0, str(src), look=e.look),
        out, w=64, h=48, fps=30, n_frames=10, crf=20, preset="ultrafast",
    )
    assert out.stat().st_size > 0
