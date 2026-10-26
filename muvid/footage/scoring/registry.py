"""The scorer registry: what a metric IS, so adding one touches no orchestrator code (muvid#19).

A *scorer* turns one clip (plus the shared, compute-once-on-master artifacts) into
:class:`~muvid.footage.scoring.grid.ScoreTrack`\\ s on the song grid. The orchestrator
used to call three extractors by name and keep a hardcoded metric tuple, so a new
scorer meant editing four places and ``metrics=`` could only *filter* what those calls
produced. Now it walks this registry — the house idiom (``register_visual``,
``register_selection_strategy``, ``register_aligner``) — and the metric axis, the
default metric set and the wanted-set filter are all derived from the rows.

A scorer is handed a :class:`ClipContext` and returns tracks. It declares:

- ``metrics`` — the names it produces (a ``metrics=`` request is matched against them);
- ``needs_frames`` — whether it reads the shared decode pass (one decode per clip,
  however many scorers read it: the design review's fix for the double decode);
- ``gated`` — whether the optional hard quality gate is ANDed into its masks;
- ``tier`` — ``"core"`` (the commercial-clean default) or ``"lipsync"`` (the opt-in,
  off-prod tier of the licence boundary in the repo guide). A new scorer is ``"core"``
  only if every dependency it brings is MIT/BSD/Apache/ISC.

**Absent is not zero.** A scorer that could not measure a frame returns the frame
masked (``NaN`` raw, ``False`` mask), never ``0.0``: the composite renormalises over
the weight that was available (muvid#19), and a ``0.0`` would count as the worst
possible score.

Import-safe: this module is stdlib-only; every built-in's heavy import lives inside its
``run`` function. A registered metric weighs ``0`` in the ``weighted`` selector until a
caller gives it a weight (``weights={"my_metric": 0.3}``) — registering changes what is
*measured and shown*, never what an existing edit selects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

if TYPE_CHECKING:  # pragma: no cover
    from muvid.footage.scoring.grid import ScoreTrack

#: The tiers. ``core`` runs by default; ``lipsync`` only when the opt-in is enabled.
CORE_TIER = "core"
LIPSYNC_TIER = "lipsync"
TIERS = (CORE_TIER, LIPSYNC_TIER)


@dataclass(frozen=True)
class ClipContext:
    """What a scorer is handed for ONE clip. Paths and primitives, never the project.

    ``frames`` is the shared decode pass (``None`` when no selected scorer declares
    ``needs_frames``); ``beat`` is the master beat grid; ``vocal_stem`` the master vocal
    stem path (``None`` unless the lip-sync tier is running); ``grid`` is
    ``{"t0", "hop_s", "n"}``.
    """

    clip_id: str
    path: str
    alignment: Any  # FootageAlignment — offset_s, duration_s, coverage …
    frames: Any  # FramePass | None
    beat: Any  # mixing BeatGrid
    vocal_stem: str | None
    grid: Mapping[str, Any]


@dataclass(frozen=True)
class Scorer:
    """One row of the registry. ``run(ctx) -> tracks`` is the whole behaviour."""

    name: str
    metrics: tuple[str, ...]
    run: Callable[[ClipContext], Sequence["ScoreTrack"]]
    needs_frames: bool = True
    gated: bool = True
    tier: str = CORE_TIER
    #: ``() -> (ok, reason)``; ``None`` means always available. Surfaced by
    #: ``list_available_extractors`` — a missing dependency is a recorded reason, not a crash.
    available: Callable[[], tuple[bool, str]] | None = field(
        default=None, compare=False
    )

    def __post_init__(self) -> None:
        if not self.metrics:
            raise ValueError(f"scorer {self.name!r} declares no metrics")
        if self.tier not in TIERS:
            raise ValueError(f"scorer tier must be one of {TIERS}, not {self.tier!r}")


_SCORERS: dict[str, Scorer] = {}


def register_scorer(scorer: Scorer, *, replace: bool = False) -> Scorer:
    """Add ``scorer``. A name or a metric already taken is refused unless ``replace``.

    Two scorers producing one metric would silently overwrite each other's track in
    the tensor, so the metric names are unique across the registry, not just the scorer
    names.
    """
    if scorer.name in _SCORERS and not replace:
        raise ValueError(
            f"scorer {scorer.name!r} is already registered (replace=True?)"
        )
    taken = {
        m: s.name for s in _SCORERS.values() if s.name != scorer.name for m in s.metrics
    }
    clash = sorted(m for m in scorer.metrics if m in taken)
    if clash:
        raise ValueError(
            f"metric(s) {clash} already produced by "
            f"{sorted({taken[m] for m in clash})}; metric names are unique"
        )
    _SCORERS[scorer.name] = scorer
    return scorer


def unregister_scorer(name: str) -> None:
    """Remove a scorer (tests, plugin teardown). Unknown names raise ``KeyError``."""
    del _SCORERS[name]


def scorers(*, include_lipsync: bool = False) -> list[Scorer]:
    """Registered scorers in registration order; the opt-in tier only when asked."""
    return [s for s in _SCORERS.values() if include_lipsync or s.tier == CORE_TIER]


def default_metrics(*, include_lipsync: bool = False) -> list[str]:
    """The metric axis order: every registered scorer's metrics, in registration order."""
    return [m for s in scorers(include_lipsync=include_lipsync) for m in s.metrics]


def metrics_of_tier(tier: str) -> set[str]:
    """Every metric a tier's scorers produce."""
    return {m for s in _SCORERS.values() if s.tier == tier for m in s.metrics}


# --------------------------------------------------------------------------
# The built-ins. Each ``run`` lazy-imports its extractor (cv2 / librosa / torch).
# --------------------------------------------------------------------------


def _grid_kw(ctx: ClipContext) -> dict:
    return {"t0": ctx.grid["t0"], "hop_s": ctx.grid["hop_s"], "n": ctx.grid["n"]}


def _run_quality(ctx: ClipContext):
    from muvid.footage.scoring.quality import quality_tracks

    return quality_tracks(
        ctx.frames,
        clip_id=ctx.clip_id,
        offset_s=ctx.alignment.offset_s,
        **_grid_kw(ctx),
    )


def _run_motion_beat(ctx: ClipContext):
    from muvid.footage.scoring.motionbeat import motionbeat_tracks

    return motionbeat_tracks(
        ctx.frames,
        clip_id=ctx.clip_id,
        offset_s=ctx.alignment.offset_s,
        beat_times=ctx.beat.beat_times,
        onset_env=ctx.beat.onset_env,
        onset_hop_s=ctx.beat.onset_hop_s,
        **_grid_kw(ctx),
    )


def _run_lipsync(ctx: ClipContext):
    if ctx.vocal_stem is None:  # the stem could not be made: skip, never a silent 0
        return []
    from muvid.footage.scoring.lipsync import lipsync_tracks

    a = ctx.alignment
    return lipsync_tracks(
        ctx.path,
        clip_id=ctx.clip_id,
        offset_s=a.offset_s,
        duration_s=a.duration_s,
        coverage=a.coverage,
        vocal_stem_path=str(ctx.vocal_stem),
        **_grid_kw(ctx),
    )


def _lipsync_available() -> tuple[bool, str]:
    from muvid.footage.scoring.lipsync import lipsync_available

    return lipsync_available()


register_scorer(
    Scorer(
        "quality",
        ("sharpness", "exposure", "stability_shake", "face_framing"),
        _run_quality,
    )
)
register_scorer(
    Scorer("motion_beat", ("motion_beat_bas", "motion_onset_xcorr"), _run_motion_beat)
)
register_scorer(
    Scorer(
        "lipsync",
        ("lip_sync_lse_c", "lse_d_offset"),
        _run_lipsync,
        needs_frames=False,
        gated=False,
        tier=LIPSYNC_TIER,
        available=_lipsync_available,
    )
)
