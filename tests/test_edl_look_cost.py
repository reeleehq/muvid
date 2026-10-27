"""The look gate's cost table is a measurement of the binary (muvid#229).

``muvid.footage.edl._LOOK_FILTER_COSTS`` prices each filter a look may use — the frames
it allocates and the pixel family it works in, which decides where ffmpeg inserts a
frame-sized conversion. A table that reads a filter CHEAPER than it is, or in the wrong
family, lets a look past the budget that costs more than it says. So:

1. ``tests/data/ffmpeg_filter_costs.json`` records the measurement (regenerate with
   :func:`_refresh_census` on a new ffmpeg), and the table may never read cheaper than
   it or disagree on a family;
2. every filter a look may use has a price (a new allowlisted filter fails here until
   someone measures it);
3. on a runner with ffmpeg, the binary itself is re-measured — at 4x the canvas area,
   one link against three for the allocation, and alternated with a known-RGB and a
   known-YUV filter for the family — and the table checked against what it does now.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from muvid.footage.edl import LOOK_FILTERS, _LOOK_FILTER_COSTS
from tests.ffmpeg_support import needs_ffmpeg

CENSUS_PATH = Path(__file__).parent / "data" / "ffmpeg_filter_costs.json"

#: The measurement's canvas and the larger frame it measures at (4x the area).
_CANVAS, _LARGE = (1920, 1080), (3840, 2160)
#: One YUV 4:2:0 frame at the large size, in MB — the unit the table counts in.
_FRAME_MB = _LARGE[0] * _LARGE[1] * 1.5 / (1024 * 1024)
#: Frames of conversion (over the six an alternation makes) above which a family
#: change is read: a real one measured about 2.5 frames EACH, so 15 over six.
_CONVERSION_SIGNAL_FRAMES = 3.0
#: How far below the measurement the table may sit, in frames (RSS noise).
_TOLERANCE_FRAMES = 0.35
#: Each filter as the measurement runs it, at the large size.
_PROBES = {
    "null": "null",
    "setpts": "setpts=PTS",
    "crop": f"crop={_LARGE[0]}:{_LARGE[1]}",
    "pad": f"pad={_LARGE[0]}:{_LARGE[1]}",
    "scale": f"scale={_LARGE[0]}:{_LARGE[1]}",
    "zoompan": f"zoompan=d=1:s={_LARGE[0]}x{_LARGE[1]}",
    "noise": "noise=alls=1",
    "vignette": "vignette",
    "gblur": "gblur=sigma=5",
    "eq": "eq=gamma=1",
    "hue": "hue=s=1",
    "lutyuv": "lutyuv=y=val",
    "boxblur": "boxblur",
    "unsharp": "unsharp",
    "bilateral": "bilateral=sigmaS=1",
    "colorchannelmixer": "colorchannelmixer=rr=1",
    "colorlevels": "colorlevels",
    "colorbalance": "colorbalance=rs=0.1",
    "lutrgb": "lutrgb=r=val",
}
#: Filters the measurement cannot run unaided (``lut3d`` needs a cube file); the table
#: prices them conservatively and says so.
_UNMEASURED = frozenset({"lut3d"})

_PROBE = (
    "import resource, subprocess, sys\n"
    "subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',\n"
    f"    'testsrc2=size={_CANVAS[0]}x{_CANVAS[1]}:rate=30:duration=0.3', '-vf',\n"
    "    sys.argv[1], '-f', 'null', '-'], check=True)\n"
    "rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss\n"
    "print(rss / (1024 * 1024) if sys.platform == 'darwin' else rss / 1024)\n"
)


def _rss_mb(vf: str) -> float:
    out = subprocess.run(
        [sys.executable, "-c", _PROBE, vf], capture_output=True, text=True, check=True
    )
    return float(out.stdout.strip())


def _measure() -> dict:
    """``{filter: {"family": ..., "frames": ...}}`` measured on THIS binary."""
    up = f"scale={_LARGE[0]}:{_LARGE[1]}"
    down = f"scale={_CANVAS[0]}:{_CANVAS[1]}"
    rgb, yuv = _PROBES["colorchannelmixer"], _PROBES["eq"]

    def chain(*links):
        return ",".join([up, *links, down])

    base = _rss_mb(chain())
    eq_alloc = (_rss_mb(chain(yuv, yuv, yuv)) - _rss_mb(chain(yuv))) / 2
    out = {}
    for name, f in _PROBES.items():
        alloc = max(0.0, (_rss_mb(chain(f, f, f)) - _rss_mb(chain(f))) / 2)
        with_rgb = _rss_mb(chain(*[rgb, f] * 3)) - (base + 3 * alloc)
        with_yuv = _rss_mb(chain(*[yuv, f] * 3)) - (base + 3 * alloc + 3 * eq_alloc)
        signal = _CONVERSION_SIGNAL_FRAMES * _FRAME_MB
        family = "yuv" if with_rgb > signal else "rgb" if with_yuv > signal else "any"
        out[name] = {"family": family, "frames": round(alloc / _FRAME_MB, 2)}
    return out


def _refresh_census() -> None:  # pragma: no cover - a maintenance helper
    """Regenerate :data:`CENSUS_PATH` from THIS binary."""
    CENSUS_PATH.write_text(json.dumps(_measure(), indent=2, sort_keys=True) + "\n")


def _check(table: dict, measured: dict) -> "list[str]":
    """Every way ``table`` reads a filter cheaper, or in another family, than
    ``measured`` says."""
    wrong = []
    for name, m in measured.items():
        family, frames = table[name]
        # one-sided: a table that charges a conversion the binary does not make is
        # stricter, not wrong (ffmpeg 6.0 negotiates `scale` as either family, the
        # #229 review); one that charges none where the binary makes one under-reads
        if m["family"] != "any" and family != m["family"]:
            wrong.append(f"{name}: family {family!r}, measured {m['family']!r}")
        if frames < m["frames"] - _TOLERANCE_FRAMES:
            wrong.append(f"{name}: {frames} frames, measured {m['frames']}")
    return wrong


def test_every_filter_a_look_may_use_has_a_price():
    assert set(LOOK_FILTERS) <= set(_LOOK_FILTER_COSTS), (
        "a look filter with no price in edl._LOOK_FILTER_COSTS — measure it "
        "(tests.test_edl_look_cost._refresh_census) and add it"
    )
    assert set(_PROBES) | _UNMEASURED == set(LOOK_FILTERS)


def test_the_table_never_reads_cheaper_than_the_recorded_census():
    census = json.loads(CENSUS_PATH.read_text())
    assert set(census) == set(_PROBES)
    assert _check(_LOOK_FILTER_COSTS, census) == []


@needs_ffmpeg
@pytest.mark.skipif(sys.platform == "win32", reason="no `resource` module on Windows")
def test_the_table_never_reads_cheaper_than_this_binary():
    """The census re-measured on the runner's own ffmpeg (6.x in CI)."""
    assert _check(_LOOK_FILTER_COSTS, _measure()) == []


def test_after_an_rgb_link_allocations_cost_double():
    """The #229 review: ffmpeg stays in a three-byte format (gbrp, then yuv444p) after
    an RGB link, so a link's frames there are twice the 4:2:0 unit."""
    from muvid.footage.edl import _LOOK_WIDE_FACTOR, _look_cost

    canvas = (1920, 1080)
    plain = _look_cost("gblur=sigma=5", canvas)[1][-1][1]
    after_rgb = _look_cost("colorchannelmixer=rr=1,gblur=sigma=5", canvas)[1][-1][1]
    assert after_rgb == pytest.approx(_LOOK_WIDE_FACTOR * plain)


def test_a_literal_crop_returns_the_frame_to_its_size():
    """Links after `crop=1920:1080` are priced at the canvas, not the larger frame."""
    from muvid.footage.edl import _look_cost

    canvas = (1920, 1080)
    upsized = "scale=3840:2160,crop=1920:1080,gblur=sigma=5"
    expression = "scale=3840:2160,crop=w='iw/2':h='ih/2',gblur=sigma=5"
    assert (
        _look_cost(upsized, canvas)[1][-1][1] < _look_cost(expression, canvas)[1][-1][1]
    )
