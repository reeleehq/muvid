"""A look's ``lut3d`` names a LUT; the assembler loads it, bounded, from muvid's LUT
folder (muvid#244, muvid#252).

Before #244, ``lut3d=file=`` was the one unchecked path on the look seam: it would try
to open anything the renderer could read (a probe of the host's disk from a remote
EDL), and its memory is the cube's — 12 bytes x size^3, 201 MB at 256 points — which
the frame-cost budget cannot see. #252 split the check: the EDL gate reads only the
NAME (an edit is a plan, so a deleted LUT must not freeze it), and the assembler
resolves and size-checks the file where the encode is.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from muvid.footage import luts as L
from muvid.footage.edl import EdlEntry, FootageAlignment, validate_edl
from muvid.footage.luts import MAX_LUT_SIZE
from tests.ffmpeg_support import needs_ffmpeg

_A = FootageAlignment("A", 0.0, 0.9, 10.0, (0.0, 10.0))
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")


@pytest.fixture
def luts(tmp_path, monkeypatch):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data"))
    d = tmp_path / "data" / "luts"
    d.mkdir(parents=True)
    return d


def _cube(path, size=2):
    path.parent.mkdir(parents=True, exist_ok=True)
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


# --- the gate: text only ---------------------------------------------------------------


def test_the_gate_accepts_a_lut_name_without_reading_the_file(luts):
    """A name the folder does not hold yet still validates: an edit is a plan."""
    for look in (
        "lut3d=file=warm.cube",
        "lut3d=warm.cube",
        "lut3d=file=film/Warm_2.CUBE:interp=trilinear",
        "lut3d=file=warm.cube:enable='between(t,0,1)'",
        "lut3d=file='warm.cube'",  # quoted at the graph level: ffmpeg reads warm.cube
        "lut3d=../x.cube:file=warm.cube",  # the last file wins, in ffmpeg and here
        "hue=s=0,lut3d@grade=file=missing.cube",
        "lut3d",
    ):
        [e] = _validate(look)
        assert e.look == look  # the gate transforms nothing


def test_an_edit_whose_lut_was_deleted_stays_editable(luts):
    cube = _cube(luts / "warm.cube")
    _validate("lut3d=file=warm.cube")
    cube.unlink()
    _validate("lut3d=file=warm.cube")  # still a valid plan; the RENDER refuses


@pytest.mark.parametrize(
    "look, match",
    [
        ("lut3d=file=/etc/passwd", "not a LUT name"),
        ("lut3d=file=/tmp/outside.cube", "not a LUT name"),
        ("lut3d=file=../escape.cube", "not a LUT name"),
        ("lut3d=file=film/../../escape.cube", "not a LUT name"),
        ("lut3d=file=.hidden.cube", "not a LUT name"),
        ("lut3d=file=warm.png", "not a LUT name"),
        (r"lut3d=file=a\[b\].cube", "not a LUT name"),
        ("lut3d=file=/abs/luts/warm.cube", "not a LUT name"),  # #244's spelling
        ("lut3d=file=" + "a" * 300 + ".cube", "not a LUT name"),
        # a separator escaped for the GRAPH level is one for the option level: ffmpeg
        # resolves both, so each of these sets a second `file` (muvid#252 review)
        (r"lut3d=interp=nearest\:file=/elsewhere.cube", "not a LUT name"),
        ("lut3d=interp='nearest:file=/elsewhere.cube'", "not a LUT name"),
        ("lut3d=enable='1:file=/elsewhere.cube'", "not a LUT name"),
        (r"lut3d=file=warm.cube:interp=x\:file=/elsewhere.cube", "not a LUT name"),
        (r"lut3d=interp=nearest\:foo=1", "does not offer"),
        ("lut3d=file=warm.cube:foo=1", "does not offer"),
        ("lut3d=warm.cube:1", "does not offer"),
    ],
)
def test_anything_else_is_refused(luts, look, match):
    with pytest.raises(ValueError, match=match):
        _validate(look)


def test_an_escaped_separator_cannot_reach_a_geometry_option():
    """The same two-level reading guards the frame-size gate (muvid#75): ``aspect``
    smuggled through ``color`` rendered a 64x48 frame 64x1920 before the fix."""
    for look in (
        r"pad=w=1920:h=1080:color=black\:aspect=1/30",
        "pad=w=1920:h=1080:color='black:aspect=1/30'",
    ):
        with pytest.raises(ValueError, match="aspect"):
            validate_edl(
                [EdlEntry(0.0, 4.0, "A", look=look)], [_A], 4.0, canvas=(1920, 1080)
            )


# --- the render: resolve and check ---------------------------------------------------


def test_bind_replaces_the_name_with_the_checked_file(luts):
    cube = _cube(luts / "film" / "warm.cube")
    bound = L.bind_look_luts("hue=s=0,lut3d@g=file=film/warm.cube:interp=nearest")
    assert bound == f"hue=s=0,lut3d@g=file={cube.resolve()}:interp=nearest"
    assert L.bind_look_luts("lut3d=film/warm.cube") == f"lut3d=file={cube.resolve()}"
    assert L.bind_look_luts("lut3d") == "lut3d"


def test_bind_escapes_a_folder_path_ffmpeg_would_split(tmp_path, monkeypatch):
    home = tmp_path / "a b,c'd"
    monkeypatch.setenv("MUVID_DATA_HOME", str(home))
    _cube(home / "luts" / "warm.cube")
    bound = L.bind_look_luts("lut3d=file=warm.cube")
    assert "\\," in bound and ",c" not in bound.replace("\\,", "")


def test_bind_rebuilds_the_link_from_what_ffmpeg_reads(luts):
    cube = _cube(luts / "warm.cube")
    # one `file` reaches ffmpeg, the one the gate read; quoting is re-escaped
    assert L.bind_look_luts("lut3d=../x.cube:file=warm.cube") == f"lut3d=file={cube}"
    assert (
        L.bind_look_luts("lut3d=file='warm.cube':enable='between(t,0,1)'")
        == f"lut3d=file={cube}:enable=between(t\\,0\\,1)"
    )
    # check and bind are one path: whatever check passes, bind binds
    for look in ("lut3d=:file=warm.cube", "lut3d=/etc/passwd:file=warm.cube"):
        L.check_look_luts(look)
        assert L.bind_look_luts(look) == f"lut3d=file={cube}"


def test_a_long_or_odd_name_is_a_lut_refusal_not_an_oserror(luts):
    for name in ("a" * 300 + ".cube", "/".join(["a" * 120] * 9) + "/w.cube"):
        with pytest.raises(L.LutError) as exc:
            L.check_look_luts(f"lut3d=file={name}")
        assert str(luts) not in str(exc.value)


def test_a_missing_lut_is_refused_at_render_without_printing_the_folder(luts):
    with pytest.raises(L.LutError, match="no LUT named 'missing.cube'") as exc:
        L.bind_look_luts("lut3d=file=missing.cube")
    assert str(luts) not in str(exc.value)


@posix_only
def test_a_symlink_out_of_the_folder_is_refused(luts, tmp_path):
    os.symlink(_cube(tmp_path / "elsewhere.cube"), luts / "link.cube")
    with pytest.raises(L.LutError, match="no LUT named"):
        L.resolve_lut("link.cube")


def test_a_cube_larger_than_the_cap_or_without_a_size_is_refused(luts):
    (luts / "big.cube").write_text(f"LUT_3D_SIZE {MAX_LUT_SIZE + 1}\n0 0 0\n")
    with pytest.raises(L.LutError, match=f"{MAX_LUT_SIZE + 1}-point cube"):
        L.resolve_lut("big.cube")
    # ffmpeg reads the FIRST declaration; a later smaller one must not vouch for it
    (luts / "two.cube").write_text(
        f"LUT_3D_SIZE {MAX_LUT_SIZE + 1} # big\nLUT_3D_SIZE 2\n0 0 0\n"
    )
    with pytest.raises(L.LutError, match="declares no LUT_3D_SIZE"):
        L.resolve_lut("two.cube")
    (luts / "bare.cube").write_text("0 0 0\n")
    with pytest.raises(L.LutError, match="declares no LUT_3D_SIZE"):
        L.resolve_lut("bare.cube")


def test_an_unreadable_cube_is_a_refusal_not_a_traceback(luts, monkeypatch):
    _cube(luts / "locked.cube")

    def denied(_path):
        raise PermissionError("denied")

    monkeypatch.setattr(L, "cube_size", denied)
    with pytest.raises(L.LutError, match="cannot be read"):
        L.resolve_lut("locked.cube")


def test_list_luts_names_what_a_look_can_load(luts, monkeypatch):
    assert L.list_luts() == {"luts": [], "total": 0}
    _cube(luts / "warm.cube", size=3)
    _cube(luts / "film" / "cold.CUBE")
    (luts / "big.cube").write_text(f"LUT_3D_SIZE {MAX_LUT_SIZE + 1}\n")
    (luts / ".hidden.cube").write_text("LUT_3D_SIZE 2\n")
    (luts / "notes.txt").write_text("x")
    listing = L.list_luts()
    got = listing["luts"]
    assert [r["name"] for r in got] == ["big.cube", "film/cold.CUBE", "warm.cube"]
    assert got[2] == {"name": "warm.cube", "size": 3, "usable": True}
    assert got[0]["usable"] is False and str(luts) not in got[0]["problem"]
    monkeypatch.setattr(L, "MAX_LISTED_LUTS", 1)
    assert L.list_luts() == {"luts": got[:1], "total": 3}


def test_list_luts_on_a_missing_folder_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "nowhere"))
    assert L.list_luts() == {"luts": [], "total": 0}


def test_the_service_offers_the_luts_op(luts):
    from muvid.footage import service

    _cube(luts / "warm.cube")
    assert service.luts()["luts"][0]["name"] == "warm.cube"
    assert "luts" in {s.name for s in service.FOOTAGE_OP_SPECS}


@needs_ffmpeg
def test_a_named_lut_renders(tmp_path, monkeypatch):
    """The bound spelling is one ffmpeg loads — through a folder whose path needs
    escaping — and not a rule that refuses everything."""
    from muvid.footage.assemble import _render_part
    from muvid.footage.edl import AssemblyCut

    home = tmp_path / "data dir,x"
    monkeypatch.setenv("MUVID_DATA_HOME", str(home))
    _cube(home / "luts" / "identity.cube", size=3)
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         "testsrc2=size=64x48:rate=30:duration=1", "-pix_fmt", "yuv420p", str(src)],
        check=True,
    )
    [e] = _validate("lut3d=file=identity.cube")
    out = tmp_path / "out.mp4"
    _render_part(
        AssemblyCut(0.0, 1.0, "A", 0.0, str(src), look=L.bind_look_luts(e.look)),
        out, w=64, h=48, fps=30, n_frames=10, crf=20, preset="ultrafast",
    )
    assert out.stat().st_size > 0


def _red_cube(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("LUT_3D_SIZE 2\n" + "1 0 0\n" * 8)


def _media(tmp_path):
    clip, song = tmp_path / "clip.mp4", tmp_path / "song.wav"
    run = lambda *a: subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)
    run("-f", "lavfi", "-i", "color=gray:size=64x48:rate=30:duration=2",
        "-pix_fmt", "yuv420p", str(clip))
    run("-f", "lavfi", "-i", "sine=duration=2", str(song))
    return clip, song


def _first_pixel(video):
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-frames:v", "1", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout
    return tuple(out[:3])


@needs_ffmpeg
def test_the_assembler_binds_the_name_itself(tmp_path, monkeypatch):
    """The binding inside ``assemble_music_video`` is what makes a name load: without
    it ffmpeg would look for ``red.cube`` relative to the server's working directory."""
    from muvid.footage.assemble import assemble_music_video
    from muvid.footage.edl import AssemblyCut

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data, dir"))
    _red_cube(tmp_path / "data, dir" / "luts" / "red.cube")
    monkeypatch.chdir(tmp_path)  # no red.cube here for an unbound name to find
    clip, song = _media(tmp_path)
    out = assemble_music_video(
        [AssemblyCut(0.0, 2.0, "A", 0.0, str(clip), look="lut3d=file=red.cube")],
        str(song), str(tmp_path / "out.mp4"), canvas=(64, 48), preset="ultrafast",
    )
    r, g, b = _first_pixel(out)
    assert r > 200 and g < 60 and b < 60


def test_the_service_refuses_a_missing_lut_before_spending_a_render(tmp_path, monkeypatch):
    """The edit saves (it is a plan); the RENDER refuses, as a FootageError, before a
    render id or reference number is allocated — and nothing is encoded."""
    from muvid.footage import service
    from muvid.footage.workspace import FootageWorkspace
    import muvid.footage.assemble as A

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data"))
    fp = FootageWorkspace.for_email("u@x.com").create_project("p")
    song, clip = tmp_path / "song.wav", tmp_path / "A.mp4"
    song.write_bytes(b"RIFF-song")
    clip.write_bytes(b"clip")
    service.set_song(fp, path=str(song), duration_s=10.0)
    service.add_clip(fp, path=str(clip), clip_id="A", duration_s=10.0)
    service.set_offset(fp, clip_id="A", offset_s=0.0)
    edl = [{"song_start": 0.0, "song_end": 10.0, "clip_id": "A",
            "look": "lut3d=file=gone.cube"}]
    service.save_edit(fp, edl=edl, edit_id="e")
    monkeypatch.setattr(A, "assemble_music_video", lambda *a, **k: pytest.fail("encoded"))
    with pytest.raises(service.FootageError, match="no LUT named 'gone.cube'"):
        service.render(fp, edit_id="e")
    assert service.renders(fp)["renders"] == []
    assert fp.next_render_ref() == 1  # the refusal spent no reference number
