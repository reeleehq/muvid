"""Every AAC encode muvid delivers lands on its picture (muvid#379, muvid#385).

An AAC encoder primes 1024 samples, and muvid's delivery contract writes no edit
list (``-use_editlist 0``, which YouTube asks for), so a player plays the priming
and the sound lands 21.3 ms late at 48 kHz. muvid#379 fixed the footage assembler;
the visualizer (and the montage and choreo subgenres that share its encode) and
both lyric-video renderers carried the same lateness, measured at +21.6 ms on a
click through the visualizer. ``muvid.visualize.ffmpeg.aac_priming_filter`` is the
one compensation, and this file checks it is applied wherever it is owed.

Two kinds of check, because no single one reaches every site cheaply:

- a MEASUREMENT (a click at exactly 2.000 s, decoded back, its onset within 3 ms)
  through each encode path that renders without extra machinery: the visualizer's
  still path (``-af``), its filter_complex path with and without a loudness pass,
  the choreo and montage subgenres, and both lyric renderers;
- a GUARD over the source: every module that muxes with no edit list CALLS the
  compensation, so a new encoder cannot ship the lateness unnoticed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.ffmpeg_support import needs_ffmpeg, needs_ffmpeg_filter

np = pytest.importorskip("numpy")

CLICK_AT_S = 2.0
SONG_S = 4.0
SR = 48_000
TOLERANCE_MS = 3.0


def _click_song(path: Path) -> Path:
    from muvid.footage.sound import write_wav

    x = np.zeros((int(SR * SONG_S), 2))
    i = int(SR * CLICK_AT_S)
    x[i : i + 48] = 0.9  # 1 ms
    write_wav(str(path), x, SR)
    return path


def _lateness_ms(video: Path) -> float:
    """How late the click plays in ``video``, at its onset (first sample past half
    its peak): the argmax wanders across the 1 ms click with the codec."""
    from muvid.footage.sound import read_wav

    back = video.with_suffix(".back.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video), str(back)], check=True
    )
    y, sr = read_wav(str(back))
    level = np.abs(y).mean(axis=1)
    return (int(np.argmax(level > level.max() / 2)) / sr - CLICK_AT_S) * 1000


def _cover(path: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240"]
        + ["-frames:v", "1", str(path)],
        check=True,
    )
    return path


@needs_ffmpeg
@pytest.mark.parametrize(
    "visual, normalize",
    [("still", False), ("waves", False), ("waves", True)],
    ids=["still (-af)", "filtergraph", "filtergraph+loudness"],
)
def test_the_visualizer_lands_the_song_on_its_picture(tmp_path, visual, normalize):
    from muvid.visualize import render_audio_video

    song = _click_song(tmp_path / "click.wav")
    image = _cover(tmp_path / "cover.png") if visual == "still" else None
    result = render_audio_video(
        song,
        image,
        visual=visual,
        saveas=tmp_path / "out.mp4",
        size=(640, 360),
        fps=10,
        normalize=normalize,
    )
    late = _lateness_ms(Path(result.path))
    assert abs(late) < TOLERANCE_MS, f"the song plays {late:+.1f} ms off its picture"


@needs_ffmpeg_filter("subtitles")
def test_the_ass_lyric_video_lands_the_song_on_its_words(tmp_path):
    """The lateness here is word sync: every word showed 21 ms before it was sung."""
    from muvid.lyricvid import spec as S
    from muvid.lyricvid.render_ass import render
    from muvid.lyricvid.scene import Canvas, compile_scene
    from muvid.lyricvid.timed_text import from_words

    song = _click_song(tmp_path / "click.wav")
    tt = from_words([("NOW", CLICK_AT_S, 3.0)], duration=SONG_S)
    scene = compile_scene(
        S.TreatmentSpec(), tt, canvas=Canvas(width=1280, height=720, fps=24)
    )
    result = render(
        scene, audio=song, output=tmp_path / "o.mp4", workdir=tmp_path / "w"
    )
    late = _lateness_ms(Path(result.output))
    assert abs(late) < TOLERANCE_MS, f"the song plays {late:+.1f} ms off its words"


def _registered(manifest):
    """Put a subgenre's manifest on the registry unless its entry point did."""
    from muvid.subgenres import list_subgenres, register_subgenre

    if manifest.slug not in list_subgenres():
        register_subgenre(manifest)
        return True
    return False


@needs_ffmpeg
def test_the_choreo_subgenre_lands_the_song_on_its_picture(tmp_path):
    from muvid.choreo.manifest import CHOREO
    from muvid.subgenres import render_subgenre, unregister_subgenre

    mine = _registered(CHOREO)
    try:
        result = render_subgenre(
            "choreo",
            inputs={"audio": str(_click_song(tmp_path / "click.wav"))},
            params={"archetype": "star_guitar", "seed": 1, "beat_source": "numpy"}
            | dict(width=320, height=180, fps=12),
            workdir=tmp_path / "wd",
            output=tmp_path / "out.mp4",
        )
    finally:
        if mine:
            unregister_subgenre("choreo")
    late = _lateness_ms(Path(result.output))
    assert abs(late) < TOLERANCE_MS, f"the song plays {late:+.1f} ms off its picture"


@needs_ffmpeg_filter("zoompan")
def test_the_montage_subgenre_lands_the_song_on_its_picture(tmp_path):
    from muvid.montage.manifest import MONTAGE
    from muvid.subgenres import render_subgenre, unregister_subgenre

    photos = [_cover(tmp_path / f"p{i}.png") for i in range(3)]
    mine = _registered(MONTAGE)
    try:
        result = render_subgenre(
            MONTAGE.slug,
            inputs={
                "audio": str(_click_song(tmp_path / "click.wav")),
                "photos": [str(p) for p in photos],
            },
            params=dict(width=160, height=90, fps=12, beats="numpy"),
            workdir=tmp_path / "wd",
            output=tmp_path / "out.mp4",
        )
    finally:
        if mine:
            unregister_subgenre(MONTAGE.slug)
    late = _lateness_ms(Path(result.output))
    assert abs(late) < TOLERANCE_MS, f"the song plays {late:+.1f} ms off its picture"


@needs_ffmpeg
def test_the_web_lyric_video_lands_the_song_on_its_words(tmp_path):
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception:  # noqa: BLE001 — any reason Chromium cannot start is a skip
        pytest.skip("the web renderer needs Playwright with Chromium")
    from muvid.lyricvid import spec as S
    from muvid.lyricvid.render_web import render
    from muvid.lyricvid.scene import Canvas, compile_scene
    from muvid.lyricvid.timed_text import from_words

    song = _click_song(tmp_path / "click.wav")
    tt = from_words([("NOW", CLICK_AT_S, 3.0)], duration=SONG_S)
    scene = compile_scene(
        S.TreatmentSpec(), tt, canvas=Canvas(width=1280, height=720, fps=10)
    )
    result = render(
        scene, audio=song, output=tmp_path / "o.mp4", workdir=tmp_path / "w"
    )
    late = _lateness_ms(Path(result.output))
    assert abs(late) < TOLERANCE_MS, f"the song plays {late:+.1f} ms off its words"


#: Calls that put the priming trim on an encode (directly, or through the
#: visualizer's helpers that always do).
_TRIMS = {"aac_priming_filter", "_audio_encode_args", "_audio_graph_tail"}


def _calls(tree) -> set:
    import ast

    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            names.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
    return names


def test_every_encoder_without_an_edit_list_compensates_the_priming():
    """A module that muxes with no edit list must CALL the trim.

    "Muxes with no edit list" is a module whose source says ``use_editlist`` or that
    calls the visualizer's ``_container_args`` (montage and choreo mux through it and
    never spell the flag). The check is for a CALL, not a name: a module whose
    ``-af`` pair was deleted keeps the name in its import line, which a text search
    would accept. ``verify.py`` only checks for edit lists, and the modules defining
    the trim are not muxers.
    """
    import ast

    root = Path(__file__).resolve().parents[1] / "muvid"
    exempt = {"visualize/verify.py", "visualize/ffmpeg.py", "aac.py"}
    missing = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()  # "/" on Windows too
        if rel in exempt:
            continue
        src = p.read_text(encoding="utf-8")
        calls = _calls(ast.parse(src))
        muxes = "use_editlist" in src or "_container_args" in calls
        if muxes and not (calls & _TRIMS):
            missing.append(rel)
    assert missing == [], f"these mux with no edit list and no priming trim: {missing}"


def test_the_guard_sees_a_deleted_trim():
    """The guard's own control: the shapes a review used to beat the first version
    (an ``-af`` pair deleted with its import kept; a raw ``-c:a aac`` in place of
    the helper next to ``_container_args``) must both read as missing."""
    import ast

    kept_import = (
        "from muvid.visualize.ffmpeg import aac_priming_filter\n"
        "args = ['-c:a', 'aac', '-use_editlist', '0']\n"
    )
    raw_encode = "args = ['-c:a', 'aac', *_container_args()]\n"
    for src in (kept_import, raw_encode):
        assert not (_calls(ast.parse(src)) & _TRIMS), src


def test_the_subgenres_sharing_the_visualizer_encode_get_the_trim():
    """montage and choreo map the song straight in and encode it through
    ``_audio_encode_args``: its default must carry the trim as ``-af``."""
    from muvid.visualize.ffmpeg import aac_priming_filter
    from muvid.visualize.video import _audio_encode_args

    args = _audio_encode_args("192k")
    assert args[args.index("-af") + 1] == aac_priming_filter()
    with_loud = _audio_encode_args("192k", before=("loudnorm",))
    assert with_loud[with_loud.index("-af") + 1] == f"loudnorm,{aac_priming_filter()}"
    assert "-af" not in _audio_encode_args("192k", filtered=True)
