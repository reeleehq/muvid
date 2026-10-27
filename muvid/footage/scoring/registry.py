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
  only if every dependency it brings is MIT/BSD/Apache/ISC;
- ``available`` — ``() -> (ok, reason)``, enforced by the orchestrator: an unavailable
  scorer is skipped with its reason recorded (refused, if its metric was asked for);
- ``needs`` — the shared master artifacts it reads (:func:`register_artifact`; the
  lip-sync tier's vocal stem is one), each built once per run and only when a running
  scorer needs it (muvid#184). The orchestrator names no artifact itself.

The :class:`ClipContext` it is handed is primitives (muvid#184): the clip's placement,
the :class:`MasterBeats`, the :class:`Grid` and its declared artifacts — never the
project and never a sibling package's record — plus ``frames``, the one rich object,
documented as unstable.

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

#: The master input "the beat grid" (:attr:`Scorer.inputs`): ``ClipContext.beat``'s
#: ``beat_times``. The onset envelope is the song's own measurement, so reading only it
#: is not reading the grid.
BEATS = "beats"
#: Every master input a score is keyed on beyond the song and the placement.
INPUTS = (BEATS,)


@dataclass(frozen=True)
class KeyedInput:
    """How a host provides one keyed master input (:data:`INPUTS`, muvid#224) — the
    single place an input is read, for the run that measures on it AND for the readers
    that ask whether the scores are still current.

    ``read(project) -> (value, fingerprint)`` is called once per scoring run and the two
    come back TOGETHER, so the manifest can never record one value's key beside another
    value's measurement (the beat grid's #187 rule, for every input). ``fingerprint
    (project) -> str`` is the cheap current fingerprint alone, for the staleness
    question; ``""`` means the input's default, which ``song_hash`` already keys.
    """

    read: Callable[[Any], "tuple[Any, str]"]
    fingerprint: Callable[[Any], str]


#: The tiers. ``core`` runs by default; ``lipsync`` only when the opt-in is enabled.
CORE_TIER = "core"
LIPSYNC_TIER = "lipsync"
TIERS = (CORE_TIER, LIPSYNC_TIER)


@dataclass(frozen=True)
class MasterBeats:
    """The master beat grid a scoring run measures on, and the name of it (muvid#187).

    One record, read once: ``fingerprint`` names THESE beats (``""`` for the estimator's,
    which ``song_hash`` already keys; else the declared grid's), so the manifest can never
    record one grid's key beside another grid's beats. The fields are primitives, the
    shape muvid#184 wants ``ClipContext`` to hand plugins; ``onset_env`` is the
    estimator's measurement of the song's onsets, which a declared grid does not change.
    """

    beat_times: Sequence[float]
    downbeat_times: Sequence[float]
    tempo_bpm: float
    onset_env: Any  # numpy array, one value per ``onset_hop_s``
    onset_hop_s: float
    fingerprint: str = ""

    @classmethod
    def estimated(cls, bg) -> "MasterBeats":
        """From the estimator's ``mixing.audio.BeatGrid``."""
        return cls(
            beat_times=bg.beat_times,
            downbeat_times=bg.downbeat_times,
            tempo_bpm=float(bg.tempo_bpm),
            onset_env=bg.onset_env,
            onset_hop_s=bg.onset_hop_s,
        )


@dataclass(frozen=True)
class Grid:
    """The song-time grid every track lands on: ``n`` frames, ``hop_s`` apart, from ``t0``."""

    t0: float
    hop_s: float
    n: int

    def as_kwargs(self) -> dict:
        """``{"t0", "hop_s", "n"}``, the keyword arguments the extractors take."""
        return {"t0": self.t0, "hop_s": self.hop_s, "n": self.n}


@dataclass(frozen=True)
class ClipContext:
    """What a scorer is handed for ONE clip: paths and primitives, never the project
    and never a sibling package's record (muvid#184), so a plugin's contract is these
    fields and nothing behind them.

    ``offset_s`` / ``duration_s`` / ``coverage`` place the clip on the song (seconds;
    ``coverage`` is the song span it covers); ``beat`` is the master beat grid
    (:class:`MasterBeats`, primitives); ``grid`` the song-time :class:`Grid`;
    ``artifacts`` the shared master artifacts the scorer declared in ``needs``
    (:func:`register_artifact`), by name. ``frames`` is the one rich object — the shared
    decode pass, ``None`` unless a selected scorer declares ``needs_frames`` — and it is
    documented as unstable: a plugin reading it accepts that its shape may change.
    """

    clip_id: str
    path: str
    offset_s: float
    duration_s: float
    coverage: "tuple[float, float]"
    frames: Any  # FramePass | None — documented-unstable
    beat: MasterBeats
    grid: Grid
    artifacts: Mapping[str, Any] = field(default_factory=dict)
    #: every keyed input's value by name (:data:`INPUTS`; ``beat`` is the beat grid's)
    inputs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Artifact:
    """A shared master artifact — computed ONCE per run on the song, never per clip —
    that a scorer can declare in ``needs``. ``build(song_path, scores_dir)`` makes it;
    ``stage`` is its progress label."""

    name: str
    build: Callable[[str, str], Any]
    stage: str


_ARTIFACTS: dict[str, Artifact] = {}


def register_artifact(artifact: Artifact, *, replace: bool = False) -> Artifact:
    """Add a shared master artifact; a taken name is refused unless ``replace``."""
    if artifact.name in _ARTIFACTS and not replace:
        raise ValueError(f"artifact {artifact.name!r} is already registered")
    _ARTIFACTS[artifact.name] = artifact
    return artifact


def artifact(name: str) -> Artifact:
    """The registered artifact ``name``; ``KeyError`` names the registered ones."""
    try:
        return _ARTIFACTS[name]
    except KeyError:
        raise KeyError(
            f"no artifact {name!r} is registered; registered: {sorted(_ARTIFACTS)}"
        ) from None


@dataclass(frozen=True)
class Scorer:
    """One row of the registry. ``run(ctx) -> tracks`` is the whole behaviour."""

    name: str
    metrics: tuple[str, ...]
    run: Callable[[ClipContext], Sequence["ScoreTrack"]]
    needs_frames: bool = True
    gated: bool = True
    tier: str = CORE_TIER
    #: ``() -> (ok, reason)``; ``None`` means always available. ENFORCED by the
    #: orchestrator: an unavailable scorer does not run and its reason is recorded in the
    #: run's ``skipped_scorers`` (a missing dependency is a recorded reason, not a crash).
    available: Callable[[], tuple[bool, str]] | None = field(
        default=None, compare=False
    )
    #: the shared master artifacts it reads (:func:`register_artifact`), by name. Each is
    #: built once per run, and only when a running scorer needs it.
    needs: tuple[str, ...] = ()
    #: the master INPUTS each metric is measured on beyond the song and the clip's
    #: placement (which every metric reads), by metric: ``{"motion_beat_bas": (BEATS,)}``.
    #: A change to one stales only the metrics that declared it (muvid#206).
    inputs: Mapping[str, tuple[str, ...]] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if not self.metrics:
            raise ValueError(f"scorer {self.name!r} declares no metrics")
        if self.tier not in TIERS:
            raise ValueError(f"scorer tier must be one of {TIERS}, not {self.tier!r}")
        if not isinstance(self.inputs, Mapping):
            raise TypeError(
                f"scorer {self.name!r}: inputs maps each metric to the inputs it reads, "
                f"e.g. {{{self.metrics[0]!r}: (BEATS,)}}, not {self.inputs!r}"
            )
        for metric, names in self.inputs.items():
            if metric not in self.metrics:
                raise ValueError(
                    f"scorer {self.name!r} declares inputs for {metric!r}, which it "
                    f"does not produce ({list(self.metrics)})"
                )
            unknown = sorted(set(names) - set(INPUTS))
            if unknown:
                raise ValueError(
                    f"scorer {self.name!r}: unknown input(s) {unknown}; muvid keys "
                    f"scores on {sorted(INPUTS)} (an input it does not know would never "
                    "make a metric stale)"
                )

    def reads(self, input_name: str) -> list[str]:
        """The metrics of this scorer measured on ``input_name``."""
        return [m for m in self.metrics if input_name in self.inputs.get(m, ())]


_SCORERS: dict[str, Scorer] = {}


def metrics_reading(input_name: str) -> "set[str]":
    """Every registered metric measured on ``input_name`` (:attr:`Scorer.inputs`)."""
    return {m for sc in _SCORERS.values() for m in sc.reads(input_name)}


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


def _run_quality(ctx: ClipContext):
    from muvid.footage.scoring.quality import quality_tracks

    return quality_tracks(
        ctx.frames,
        clip_id=ctx.clip_id,
        offset_s=ctx.offset_s,
        **ctx.grid.as_kwargs(),
    )


def _run_motion_beat(ctx: ClipContext):
    from muvid.footage.scoring.motionbeat import motionbeat_tracks

    return motionbeat_tracks(
        ctx.frames,
        clip_id=ctx.clip_id,
        offset_s=ctx.offset_s,
        beat_times=ctx.beat.beat_times,
        onset_env=ctx.beat.onset_env,
        onset_hop_s=ctx.beat.onset_hop_s,
        **ctx.grid.as_kwargs(),
    )


def _run_lipsync(ctx: ClipContext):
    stem = ctx.artifacts.get(VOCAL_STEM)
    if stem is None:  # the stem could not be made: skip, never a silent 0
        return []
    from muvid.footage.scoring.lipsync import lipsync_tracks

    return lipsync_tracks(
        ctx.path,
        clip_id=ctx.clip_id,
        offset_s=ctx.offset_s,
        duration_s=ctx.duration_s,
        coverage=ctx.coverage,
        vocal_stem_path=str(stem),
        **ctx.grid.as_kwargs(),
    )


def _lipsync_available() -> tuple[bool, str]:
    from muvid.footage.scoring.lipsync import lipsync_available

    return lipsync_available()


#: The master vocal stem (Demucs), the lip-sync tier's shared artifact.
VOCAL_STEM = "vocal_stem"


def _build_vocal_stem(song_path: str, scores_dir: str):
    from pathlib import Path

    from muvid.footage.scoring.lipsync import separate_master_vocals

    return separate_master_vocals(song_path, out_dir=str(Path(scores_dir) / "_stems"))


register_artifact(Artifact(VOCAL_STEM, _build_vocal_stem, stage="separate_vocals"))


register_scorer(
    Scorer(
        "quality",
        ("sharpness", "exposure", "stability_shake", "face_framing"),
        _run_quality,
    )
)
register_scorer(
    Scorer(
        "motion_beat",
        ("motion_beat_bas", "motion_onset_xcorr"),
        _run_motion_beat,
        # the onset envelope is the song's measurement, not the grid's
        inputs={"motion_beat_bas": (BEATS,)},
    )
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
        needs=(VOCAL_STEM,),
    )
)
