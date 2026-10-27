"""Shot boundaries (via ``mixing.video.shots``) + the per-clip coverage mask.

- ``coverage_mask`` is dependency-free: the boolean of song-grid frames a clip actually
  covers (from its offset + duration). It is the base mask every metric ANDs with, and the
  authority for "does this clip exist at song time t".
- ``shot_boundaries`` returns song-times of within-clip scene cuts, detected by
  ``mixing.video.shots`` (muvid#220 — the detector lives in mixing, muvid maps it onto the
  song). Consumed by the selector ONLY when ``boundary_mode="beats+shots"`` (they become
  *inter-clip* cut candidates at shot-boundary times — a within-clip jump cut is
  unrepresentable in the single-offset EDL model). The default strategy is PySceneDetect
  (BSD-3, the ``scoring-shots`` extra); absent → ``[]`` and the mode degrades to beats-only.
"""

from __future__ import annotations

import numpy as np

from muvid.footage.edl import _EPS


def coverage_mask(
    *,
    offset_s: float,
    duration_s: float,
    coverage: tuple,
    t0: float,
    hop_s: float,
    n: int,
) -> np.ndarray:
    """Grid frames (bool[n]) the clip covers — using its clamped ``coverage`` span."""
    lo, hi = coverage
    times = t0 + np.arange(n) * hop_s
    return (times >= lo - _EPS) & (times < hi + _EPS)


#: The ``mixing.video.shots`` strategy :func:`shot_boundaries` uses by default, and the
#: package it needs. NOT ``"diff"`` (mixing's own default, ffmpeg-only) as a silent
#: fallback: scoring decodes each clip once (``frames.py``), and ``diff`` would be a
#: second full decode per clip on every scoring run, paid even when the selector's
#: default ``boundary_mode="beats"`` never reads a shot. Pass ``strategy="diff"`` to ask.
DEFAULT_SHOT_STRATEGY = "pyscenedetect"
_STRATEGY_PACKAGES = {"pyscenedetect": "scenedetect"}


def shot_boundaries(
    clip_path: str, *, offset_s: float, strategy: str = DEFAULT_SHOT_STRATEGY
) -> list[float]:
    """Song-times of within-clip scene cuts, or ``[]`` when ``strategy``'s package is
    not installed (so ``beats+shots`` degrades to beats-only).

    The detection is ``mixing.video.shots(clip_path, strategy=strategy)``: its spans tile
    the clip, so the cuts are the span starts after the first, moved onto the song by
    ``offset_s``. A failure INSIDE the detector raises (the house rule for ``mixing``
    calls: a swallowed error is a quietly empty result); only a missing optional package
    is a degrade.
    """
    from importlib.util import find_spec

    package = _STRATEGY_PACKAGES.get(strategy)
    if package and find_spec(package) is None:
        return []
    from mixing.video import shots  # lazy: mixing.video is not free to import

    return [start + offset_s for start, _end in shots(str(clip_path), strategy=strategy)[1:]]
