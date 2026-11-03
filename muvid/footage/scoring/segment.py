"""Shot boundaries + the per-clip coverage mask.

- ``coverage_mask`` is dependency-free: the boolean of song-grid frames a clip actually
  covers (from its offset + duration). It is the base mask every metric ANDs with, and the
  authority for "does this clip exist at song time t".
- Shot boundaries are song-times of within-clip scene cuts. Consumed by the selector
  ONLY when ``boundary_mode="beats+shots"`` (they become *inter-clip* cut candidates at
  shot-boundary times — a within-clip jump cut is unrepresentable in the single-offset
  EDL model). Two ways to find them, by ``shot_strategy``:

  - ``"frames"`` (the default since muvid#259): :func:`shots_from_frame_pass`, from the
    picture changes the scoring decode pass ALREADY measured (``FramePass.shot_change``),
    through ``mixing.shot_changes`` with its ``"spike"`` rule. No second decode, no extra
    dependency, and it sees what cv2 decodes. The ``"spike"`` rule is what makes it
    usable on phone footage: mixing's plain threshold reported a false cut about every
    second on handheld clips (mixing#160: 473 false cuts at 5 Hz on 14 single-take clips;
    the spike rule, 11; PySceneDetect, 16). Its price is recall (about 71 % of real cuts
    at 5 Hz) and cuts on consecutive samples, which continuous footage does not have.
  - any ``mixing.video.shots`` strategy by name (``"pyscenedetect"`` — frame-accurate,
    the ``scoring-shots`` extra — or ``"diff"``): :func:`shot_boundaries`, a second
    decode at full rate (muvid#220). A missing optional package is ``[]``.
"""

from __future__ import annotations

import os

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


#: The strategy that reads the scoring pass's own frames (:func:`shots_from_frame_pass`).
FRAMES_STRATEGY = "frames"
#: What ``score_project(shot_strategy=None)`` uses: ``MUVID_SCORING_SHOT_STRATEGY``, else
#: :data:`FRAMES_STRATEGY`. Any other value names a ``mixing.video.shots`` strategy.
SHOT_STRATEGY_ENV_VAR = "MUVID_SCORING_SHOT_STRATEGY"
DEFAULT_SHOT_STRATEGY = os.environ.get(SHOT_STRATEGY_ENV_VAR) or FRAMES_STRATEGY
#: The frames strategy's ``mixing.shot_changes.cut_indices`` rule: for continuous
#: footage (see the module docstring), not for edited video.
FRAMES_CUT_RULE = "spike"
#: The ``mixing.video.shots`` strategy that needs an optional package, and that package
#: (the ``scoring-shots`` extra): absent, it is ``[]``, never a fallback decode.
PYSCENEDETECT_STRATEGY = "pyscenedetect"
_PYSCENEDETECT_PACKAGE = "scenedetect"


def shots_available(strategy: str = DEFAULT_SHOT_STRATEGY) -> bool:
    """Whether ``strategy`` can detect anything here."""
    from importlib.util import find_spec

    return (
        strategy != PYSCENEDETECT_STRATEGY
        or find_spec(_PYSCENEDETECT_PACKAGE) is not None
    )


def shots_from_frame_pass(
    frame_pass, *, offset_s: float, rule: str = FRAMES_CUT_RULE
) -> list[float]:
    """Song-times of the cuts in the scoring pass's own frames (``frames`` strategy).

    ``frame_pass.shot_change[i]`` is the change between samples ``i`` and ``i + 1``, so
    a cut there is at ``clip_times[i + 1]``; ``mixing.shot_changes.shots_from_changes``
    picks the cuts (its adaptive threshold, ``rule``) and its spans tile the sampled
    clip. The cuts are the span starts after the first, moved onto the song by
    ``offset_s``. No changes (one sample, or none) → no cuts.
    """
    from mixing.shot_changes import shots_from_changes  # numpy only

    changes = np.asarray(frame_pass.shot_change, dtype=np.float64)
    times = np.asarray(frame_pass.clip_times, dtype=np.float64)
    if changes.size == 0 or times.size != changes.size + 1:
        return []
    spans = shots_from_changes(changes, times=times, rule=rule)
    return [float(start) + offset_s for start, _end in spans[1:]]


def shot_boundaries(
    clip_path: str, *, offset_s: float, strategy: str = PYSCENEDETECT_STRATEGY
) -> list[float]:
    """Song-times of within-clip scene cuts, or ``[]`` when ``strategy``'s package is
    not installed (so ``beats+shots`` degrades to beats-only).

    The detection is ``mixing.video.shots(clip_path, strategy=strategy)``: its spans tile
    the clip, so the cuts are the span starts after the first, moved onto the song by
    ``offset_s``. A failure INSIDE the detector raises (the house rule for ``mixing``
    calls: a swallowed error is a quietly empty result) — the scoring orchestrator
    records it per clip; only a missing optional package is a degrade here.
    """
    if not shots_available(strategy):
        return []
    from mixing.video import shots  # lazy: mixing.video is not free to import

    return [
        start + offset_s for start, _end in shots(str(clip_path), strategy=strategy)[1:]
    ]
