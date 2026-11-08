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
#: Samples of the two probes whose DIFFERENCE prices a filter. Each probe string keeps
#: the smallest reading it has ever had (:class:`_Rss`), and the price is computed once
#: from those floors. Never a minimum of the price itself: a difference's noise runs both
#: ways, so the lowest of several prices is biased low and would hide a real under-read
#: (muvid#304's review). One run is enough for the family probes (a 3-frame threshold
#: against a ~15-frame signal).
_SAMPLES = 3
#: Extra rounds, each over only the filters still reading too high for the table.
_CONFIRMATIONS = 2
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
    f"    'testsrc2=size={_CANVAS[0]}x{_CANVAS[1]}:rate=30:duration=0.15', '-vf',\n"
    "    sys.argv[1], '-f', 'null', '-'], check=True)\n"
    "rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss\n"
    "print(rss / (1024 * 1024) if sys.platform == 'darwin' else rss / 1024)\n"
)


class _Rss:
    """Peak resident MB of ffmpeg running a ``-vf``, floored per probe string.

    Contention and scheduling add memory to a single reading, so the smallest reading of
    a probe is its least-contaminated estimate; pooling across calls (and so across
    confirmation rounds) can only tighten it.
    """

    def __init__(self):
        self.floor: dict = {}

    def _read(self, vf: str) -> float:
        out = subprocess.run(
            [sys.executable, "-c", _PROBE, vf],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(out.stdout.strip())

    def __call__(self, vf: str, *, samples: int = 1) -> float:
        for _ in range(samples):
            self.floor[vf] = min(self._read(vf), self.floor.get(vf, 1e18))
        return self.floor[vf]


def _measure(names=None, rss=None) -> dict:
    """``{filter: {"family": ..., "frames": ...}}`` measured on THIS binary (just
    ``names`` when given); ``rss`` carries the floors from an earlier call."""
    rss = rss or _Rss()
    up = f"scale={_LARGE[0]}:{_LARGE[1]}"
    down = f"scale={_CANVAS[0]}:{_CANVAS[1]}"
    rgb, yuv = _PROBES["colorchannelmixer"], _PROBES["eq"]

    def chain(*links):
        return ",".join([up, *links, down])

    def alloc_of(f):
        return max(
            0.0,
            (rss(chain(f, f, f), samples=_SAMPLES) - rss(chain(f), samples=_SAMPLES))
            / 2,
        )

    base = rss(chain(), samples=_SAMPLES)
    eq_alloc = alloc_of(yuv)
    out = {}
    for name, f in _PROBES.items():
        if names is not None and name not in names:
            continue
        alloc = alloc_of(f)
        with_rgb = rss(chain(*[rgb, f] * 3)) - (base + 3 * alloc)
        with_yuv = rss(chain(*[yuv, f] * 3)) - (base + 3 * alloc + 3 * eq_alloc)
        signal = _CONVERSION_SIGNAL_FRAMES * _FRAME_MB
        family = "yuv" if with_rgb > signal else "rgb" if with_yuv > signal else "any"
        out[name] = {"family": family, "frames": round(alloc / _FRAME_MB, 2)}
    return out


def _refresh_census() -> None:  # pragma: no cover - a maintenance helper
    """Regenerate :data:`CENSUS_PATH` from THIS binary."""
    CENSUS_PATH.write_text(json.dumps(_measure(), indent=2, sort_keys=True) + "\n")


def _suspects(wrong: "list[str]") -> "set[str]":
    """The filter names in :func:`_check`'s findings (each reads ``"<name>: ..."``)."""
    return {w.split(":", 1)[0] for w in wrong}


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
    rss = _Rss()
    measured = _measure(rss=rss)
    # A filter the table seems to under-read is measured again, alone, into the SAME
    # floors, and the price recomputed from them: it fails only if the tightest readings
    # still say so (muvid#304; one reading's noise rivals the tolerance).
    for _ in range(_CONFIRMATIONS):
        suspects = _suspects(_check(_LOOK_FILTER_COSTS, measured))
        if not suspects:
            break
        measured.update(_measure(suspects, rss))
    assert _check(_LOOK_FILTER_COSTS, measured) == []


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


class _NoisyRss(_Rss):
    """A stand-in binary: ``gblur`` truly costs 1.0 frame per link, the others 0.3, and
    every reading carries two-sided noise (so the instrument, not the table, is tested)."""

    def __init__(self, seed: int, sigma_frames: float = 0.2):
        super().__init__()
        import random

        self._rng, self._sigma = random.Random(seed), sigma_frames

    def _read(self, vf: str) -> float:
        frames = sum(1.0 if "gblur" in link else 0.3 for link in vf.split(","))
        return 100 + (frames + self._rng.gauss(0, self._sigma)) * _FRAME_MB


def _verdict(table_frames: float, seed: int) -> "list[str]":
    rss = _NoisyRss(seed)
    measured = _measure({"gblur"}, rss)
    table = {"gblur": ("any", table_frames)}
    for _ in range(_CONFIRMATIONS):
        suspects = _suspects(_check(table, measured))
        if not suspects:
            break
        measured.update(_measure(suspects, rss))
    return _check(table, measured)


def test_confirmation_rounds_do_not_flake_a_correct_table():
    assert sum(bool(_verdict(1.0, seed)) for seed in range(40)) <= 2


def test_confirmation_rounds_do_not_hide_a_table_that_reads_too_cheap():
    """The #304 review: taking the lowest PRICE over rounds is biased low and widened the
    tolerance; pooling raw floors must still catch a table 0.6 frames under the truth."""
    assert sum(not _verdict(0.4, seed) for seed in range(40)) <= 2
