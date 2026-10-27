"""A look's output is conformed back to the canvas (muvid#244).

Nothing scaled after the look, so a look ending at another size handed THAT frame to
the encoder — ``scale=7680:4320`` alone encoded 8K at 2.6-3.7 GB peak while its own
links cost 186 MB — and a part off the canvas cannot be stream-copied into the others.
The conform is ``scale``+``pad`` after the look; the property worth pinning besides
"it ends at the canvas" is that a look which already returns to the canvas renders
**byte for byte** as before (ffmpeg passes a same-size frame through both filters).
"""

from __future__ import annotations

import hashlib
import subprocess

import pytest

from muvid.footage import assemble
from muvid.footage.assemble import _part_filter, _render_part
from muvid.footage.edl import AssemblyCut, look_may_resize
from tests.ffmpeg_support import needs_ffmpeg

_CONFORM = "scale=64:48:force_original_aspect_ratio=decrease,pad=64:48:(ow-iw)/2:(oh-ih)/2,setsar=1"


def _cut(look=None, path="/tmp/a.mp4"):
    return AssemblyCut(0.0, 1.0, "A", 0.0, path, look=look)


@pytest.mark.parametrize(
    "look, resizes",
    [
        ("eq=gamma=1.1", False),
        ("scale=in_color_matrix=bt709:out_color_matrix=bt709,lutrgb=r=val", False),
        ("pad", False),
        ("scale=128:96", True),
        ("pad=w=128:h=96", True),
        ("crop=w='iw*0.5':h=ih", True),
        ("zoompan=d=1", True),
    ],
)
def test_only_a_look_that_can_change_the_size_is_conformed(look, resizes):
    assert look_may_resize(look) is resizes
    chain = _part_filter(_cut(look), w=64, h=48, fps=30, tail=",format=yuv420p")
    assert (f",{look},{_CONFORM},setparams=" in chain) is resizes
    assert chain.endswith(",format=yuv420p")  # still before the transition tail


def _render(tmp_path, look, name, *, conform=True, monkeypatch=None):
    src = tmp_path / "src.mp4"
    if not src.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             "testsrc2=size=96x64:rate=30:duration=1", "-pix_fmt", "yuv420p", str(src)],
            check=True,
        )
    if not conform:
        monkeypatch.setattr(assemble, "look_may_resize", lambda _look: False)
    out = tmp_path / f"{name}.mp4"
    _render_part(
        _cut(look, str(src)), out, w=64, h=48, fps=30, n_frames=10, crf=0, preset="ultrafast"
    )
    if not conform:
        monkeypatch.undo()
    return out


def _size_and_frames(path):
    size = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    md5 = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "framemd5", "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    body = "\n".join(line for line in md5.splitlines() if not line.startswith("#"))
    return size, hashlib.md5(body.encode()).hexdigest()


@needs_ffmpeg
@pytest.mark.parametrize("look", ["scale=256:192", "zoompan=d=1", "crop=w='iw*0.5':h=ih"])
def test_a_look_ending_off_the_canvas_renders_at_the_canvas(tmp_path, look):
    size, _ = _size_and_frames(_render(tmp_path, look, "off"))
    assert size == "64,48"


@needs_ffmpeg
@pytest.mark.parametrize(
    "look", ["scale=256:192,scale=64:48", "crop=32:24,scale=64:48", "zoompan=d=1:s=64x48:fps=30"]
)
def test_a_look_returning_to_the_canvas_is_unchanged_by_the_conform(
    tmp_path, monkeypatch, look
):
    with_conform = _size_and_frames(_render(tmp_path, look, "with"))
    without = _size_and_frames(
        _render(tmp_path, look, "without", conform=False, monkeypatch=monkeypatch)
    )
    assert with_conform == without
