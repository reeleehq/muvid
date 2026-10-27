"""The scoring orchestrator: a project (song + aligned clips) → the persisted score tensor.

Owns the shared, compute-once artifacts and the single decode pass per clip (the design
review's fix for the double-decode / camera-motion-sharing problem):

1. **Master beat grid** (``mixing.audio.beat_grid``, or the ``beat_grid`` a caller injects —
   the footage service's prefers a grid a person declared, muvid#187) — computed ONCE; every
   clip maps to it via its offset.
2. (opt-in) **Master vocal stem** (Demucs) — ONCE, for the lip-sync tier.
3. **Per clip: ONE decode pass** (:func:`~muvid.footage.scoring.frames.sample_clip_frames`)
   feeds BOTH quality and motion-beat (sharpness/exposure/face + the camera-compensated motion
   envelope come out of the same loop). Plus shot boundaries (PySceneDetect) and, when enabled,
   the lip-sync tracks.
4. Assemble + **persist** the tensor (per-metric-global normalization, atomic writes).

Resource safety (LOCKED decisions): a **process-wide concurrency=1 semaphore**
(``MUVID_SCORING_MAX_CONCURRENT``) serializes scoring runs; the lip-sync tier is **off by
default** (``MUVID_SCORING_ENABLE_LIPSYNC``); ``should_cancel`` is polled between every clip
and stage (cancel latency ≈ one clip); progress is emitted as ``{'kind':'progress',
'stage_index','stage_count','current_transform'}`` dicts (the nw.jobs mirror contract).

Import-safe: every heavy import (cv2/mediapipe/librosa/torch) is inside a function body.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from muvid.footage.scoring import registry
from muvid.footage.scoring.grid import DEFAULT_HOP_S, grid_len, save_scores

#: The torch-free CORE metric set (prod-safe) AS REGISTERED AT IMPORT — a snapshot kept
#: for callers that read the constant. A scorer registered later is picked up by the
#: orchestrator through :func:`registry.default_metrics`, which this does not shadow.
#: Lip-sync metrics are added only when the opt-in tier is enabled.
DEFAULT_METRICS = tuple(registry.default_metrics())
_LIPSYNC_METRICS = tuple(
    sorted(registry.metrics_of_tier(registry.LIPSYNC_TIER))
)  # snapshot

#: Process-wide serialization of scoring runs (bounds peak memory on the fragile box).
_MAX_CONCURRENT = max(1, int(os.environ.get("MUVID_SCORING_MAX_CONCURRENT", "1")))
_SCORING_SEMAPHORE = threading.BoundedSemaphore(_MAX_CONCURRENT)


def _lipsync_enabled(explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    return os.environ.get("MUVID_SCORING_ENABLE_LIPSYNC", "0") not in (
        "0",
        "",
        "false",
        "False",
    )


def list_available_extractors() -> dict:
    """Which tiers can run here (import + weight availability) — for diagnostics / the tool."""

    def _has(mod):
        import importlib.util

        return importlib.util.find_spec(mod) is not None

    from muvid.footage.scoring.lipsync import lipsync_available
    from muvid.footage.scoring.segment import shots_available

    ok, reason = lipsync_available()
    return {
        "quality": _has("cv2"),
        "face_framing": _has("mediapipe"),
        "motion_beat": _has("cv2") and _has("librosa"),
        "segment": shots_available(),
        "lipsync": {"available": ok, "reason": reason},
        # every registered scorer, built-in or not (muvid#19), with the availability the
        # orchestrator enforces (muvid#184)
        "scorers": {
            s.name: {"metrics": list(s.metrics), "tier": s.tier, **_availability(s)}
            for s in registry.scorers(include_lipsync=True)
        },
    }


def _probe(scorer) -> "tuple[bool, str]":
    """``scorer.available()``, with a plugin whose own check cannot even import its
    dependency recorded as unavailable — one broken plugin is a recorded reason, never a
    dead catalogue (``ImportError`` only: any other exception is a bug to surface)."""
    if scorer.available is None:
        return True, ""
    try:
        return scorer.available()
    except ImportError as e:
        return False, f"its availability check could not import: {e}"


def _availability(scorer) -> dict:
    ok, reason = _probe(scorer)
    return {"available": ok, **({"reason": reason} if not ok else {})}


def score_project(
    project,
    *,
    metrics: Sequence[str] | None = None,
    hop_s: float = DEFAULT_HOP_S,
    sample_fps: float | None = None,
    enable_lipsync: bool | None = None,
    progress_cb: Callable[[dict], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    inputs: "Mapping[str, Callable[[Any], tuple[Any, str]]] | None" = None,
    beat_source: "Callable[[Any], registry.MasterBeats] | None" = None,
    keep: "KeptScores | None" = None,
) -> dict:
    """Score every aligned clip of ``project`` → persist the tensor; return a summary dict.

    Args:
        project: a ``MusicVideoFootageProject`` (needs ``song_path``/``song_duration``/
            ``load_alignments``/``clip_paths``/``root``/``song_hash``).
        metrics: restrict to these metric names (default: the core set, + lip-sync if enabled).
        hop_s: grid step (default 10 Hz).
        sample_fps: frame analysis rate (default from ``frames.DEFAULT_SAMPLE_FPS``).
        enable_lipsync: force the opt-in tier on/off (default: the env flag).
        progress_cb: sink for ``{'kind':'progress', ...}`` dict events (nw.jobs mirror shape).
        should_cancel: polled between clips/stages; a True short-circuits to a clean cancel.
        inputs: ``{name: read}`` — how each keyed master input (``registry.INPUTS``)
            is read: ``read(project) -> (value, fingerprint)``, the two together
            (muvid#224; default :data:`DEFAULT_INPUTS`, the estimator's beat grid). The footage
            service passes its own, which prefers a declared grid (muvid#187). Each
            fingerprint goes into the manifest, so
            :func:`~muvid.footage.scoring.grid.stale_metrics` can tell scores measured
            on one value of an input from another.
        beat_source: ``project -> MasterBeats`` — the beat grid's provider alone, as
            before muvid#224; the ``MasterBeats.fingerprint`` is what is recorded.
            Shorthand for ``inputs={BEATS: ...}``; naming the beat grid in both is
            refused.
        keep: a partial re-score (muvid#206): the CURRENT metrics' tracks to persist
            beside the ``keep.recompute`` ones this run measures (``metrics`` is then
            ignored). Re-checked against the song and alignments under the scoring lock:
            if either changed since they were read, the run scores in full instead.
    """
    with _SCORING_SEMAPHORE:
        return _score(
            project,
            metrics=metrics,
            hop_s=hop_s,
            sample_fps=sample_fps,
            enable_lipsync=enable_lipsync,
            progress_cb=progress_cb,
            should_cancel=should_cancel,
            inputs=_with_beat_source(inputs, beat_source),
            keep=keep,
        )


@dataclass(frozen=True)
class KeptScores:
    """What a partial re-score keeps (muvid#206): the CURRENT metrics' tracks per clip,
    the stale metrics to measure again, and the song and alignments the kept tracks
    were measured under — re-checked under the scoring lock."""

    tracks: Mapping[str, Sequence[Any]]
    recompute: tuple[str, ...]
    song_hash: str
    align_fingerprint: str
    #: the keyed inputs' fingerprints the kept tracks were measured on, by name
    input_fingerprints: Mapping[str, str] = field(default_factory=dict)


def _available(scorers, *, requested: set) -> "tuple[list, dict[str, str]]":
    """``(the scorers that can run, {name: reason} for those that cannot})``.

    ``Scorer.available`` is enforced here, generically (muvid#184): an unavailable
    scorer does not run and its reason is recorded. A metric the caller ASKED for by name
    is refused instead — asking for it and getting nothing would be a silent empty."""
    ok, skipped = [], {}
    for sc in scorers:
        able, reason = _probe(sc)
        if able:
            ok.append(sc)
            continue
        asked = sorted(requested & set(sc.metrics))
        if asked:
            raise ValueError(
                f"metric(s) {asked} requested but scorer {sc.name!r} is unavailable: "
                f"{reason}"
                + (
                    " (install muvid[scoring-lipsync] + set weights)"
                    if sc.tier == registry.LIPSYNC_TIER
                    else ""
                )
            )
        skipped[sc.name] = reason
    return ok, skipped


def _estimated_beats(project) -> registry.MasterBeats:
    """The estimator's beat grid of the song — the default master grid."""
    from mixing.audio import beat_grid

    return registry.MasterBeats.estimated(beat_grid(str(project.song_path())))


#: How each keyed input is read when its host names none: the estimator's beat grid,
#: whose fingerprint is ``""`` (the song already keys it). Only the beat grid has a
#: default; a host scoring with another keyed input must provide it.
DEFAULT_INPUTS = {registry.BEATS: lambda project: (_estimated_beats(project), "")}


def _plan_run(metrics, keep, *, enable_lipsync):
    """What a run measures: ``(wanted, want_lipsync, active, skipped_scorers,
    needs_frames, needed)`` — validated (an unknown metric, an unavailable requested
    scorer, an unregistered need all raise here, before any work)."""
    if keep is not None:
        metrics = list(keep.recompute)
    want_lipsync = _lipsync_enabled(enable_lipsync)
    # If the caller explicitly asks for lip-sync metrics, requesting them must ENABLE the tier
    # (honoring availability) rather than silently returning an empty result.
    # a partial re-score asks for the stale metrics IMPLICITLY: it never switches the
    # opt-in tier on, and an unavailable scorer is skipped, not refused
    explicit = set(metrics or ()) if keep is None else set()
    requested_lipsync = explicit & registry.metrics_of_tier(registry.LIPSYNC_TIER)
    if requested_lipsync and not want_lipsync:
        want_lipsync = True
    if metrics:
        unknown = sorted(
            set(metrics) - set(registry.default_metrics(include_lipsync=True))
        )
        if unknown:
            raise ValueError(
                f"unknown metric(s) {unknown}; registered: "
                f"{registry.default_metrics(include_lipsync=True)}"
            )
    wanted = (
        set(metrics)
        if metrics
        else set(registry.default_metrics(include_lipsync=want_lipsync))
    )
    # Only the scorers that can produce a wanted metric run; the frame decode (the
    # expensive shared pass) happens iff one of them reads it.
    selected = [
        sc
        for sc in registry.scorers(include_lipsync=want_lipsync)
        if wanted & set(sc.metrics)
    ]
    active, skipped_scorers = _available(selected, requested=explicit)
    # the hard quality gate is read off the decode pass, so a gated scorer needs it too
    # (else the same metric would differ by what else was requested)
    needs_frames = any(sc.needs_frames or sc.gated for sc in active)
    needed = list(dict.fromkeys(name for sc in active for name in sc.needs))
    for name in needed:  # a typo in `needs` fails here, before any work, not mid-job
        try:
            registry.artifact(name)
        except KeyError as e:
            raise ValueError(e.args[0]) from None

    return wanted, want_lipsync, active, skipped_scorers, needs_frames, needed


def _with_beat_source(inputs, beat_source):
    """``inputs`` with ``beat_source`` (the pre-#224 argument) as the beat provider."""
    if beat_source is None:
        return inputs
    if inputs and registry.BEATS in inputs:
        raise ValueError("pass the beat grid's provider once: inputs= or beat_source=")

    def read(project):
        master = beat_source(project)
        return master, master.fingerprint

    return {registry.BEATS: read, **(inputs or {})}


def _read_inputs(project, inputs) -> "tuple[dict, dict]":
    """``(values, fingerprints)`` by name, every keyed input read ONCE with its name."""
    keyed = {**DEFAULT_INPUTS, **(inputs or {})}
    unknown = sorted(set(keyed) - set(registry.INPUTS))
    if unknown:
        raise ValueError(
            f"unknown keyed input(s) {unknown}; muvid keys {list(registry.INPUTS)}"
        )
    missing = sorted(set(registry.INPUTS) - set(keyed))
    if missing:
        raise ValueError(f"no provider for keyed input(s) {missing}")
    values, fingerprints = {}, {}
    for name, read in keyed.items():
        values[name], fingerprints[name] = read(project)
    return values, fingerprints


def _kept_inputs_moved(keep, fingerprints) -> bool:
    """Whether an input a KEPT metric reads is not the value it was measured on — read
    since the kept tracks were chosen (the #224 review: with two inputs, one changing
    while the job waited left a kept metric measured on its old value)."""
    kept = {tr.metric for trs in keep.tracks.values() for tr in trs}
    return any(
        fingerprints.get(name, "") != keep.input_fingerprints.get(name, "")
        and kept & registry.metrics_reading(name)
        for name in fingerprints
    )


def _emit(progress_cb, idx, total, name):
    if progress_cb is not None:
        progress_cb(
            {
                "kind": "progress",
                "stage_index": idx,
                "stage_count": total,
                "current_transform": name,
            }
        )


def _cancelled(should_cancel):
    return should_cancel is not None and should_cancel()


def _score(
    project,
    *,
    metrics,
    hop_s,
    sample_fps,
    enable_lipsync,
    progress_cb,
    should_cancel,
    inputs=None,
    keep=None,
):
    from muvid.footage.scoring import frames as F
    from muvid.footage.scoring.quality import quality_gate_mask
    from muvid.footage.scoring.segment import shot_boundaries

    from muvid.footage.scoring.grid import align_fingerprint

    aligns = project.load_alignments()
    if not aligns:
        raise ValueError("no alignments — run align_footage first")
    if keep is not None and (keep.song_hash, keep.align_fingerprint) != (
        project.song_hash(),
        align_fingerprint(aligns),
    ):
        # the song or an offset changed while this job waited: every kept track was
        # placed through the old one, so none is kept (muvid#59's failure otherwise)
        keep = None
    song_dur = project.song_duration()
    n = grid_len(song_dur, hop_s)
    t0 = 0.0
    clip_paths = project.clip_paths()

    # Planned BEFORE any work, so a bad metric or need is refused without estimating
    # the beat grid; planned again only if the inputs read below unseat the kept tracks.
    (wanted, want_lipsync, active, skipped_scorers, needs_frames, needed) = _plan_run(
        metrics, keep, enable_lipsync=enable_lipsync
    )

    total_stages = 1 + len(needed) + len(aligns)
    stage = 0

    # 1. Master beat grid — with every keyed input, each read ONCE with its name: a grid
    # declared or cleared while this job waited for the semaphore cannot put one grid's
    # key beside another grid's beats, and so for every input (muvid#224).
    _emit(progress_cb, stage, total_stages, "beat_grid")
    input_values, input_fingerprints = _read_inputs(project, inputs)
    bg = input_values[registry.BEATS]
    if keep is not None and _kept_inputs_moved(keep, input_fingerprints):
        # an input a kept metric reads moved since the kept tracks were chosen: none
        # is kept, and the run measures what a full run would
        keep = None
        (wanted, want_lipsync, active, skipped_scorers, needs_frames, needed) = (
            _plan_run(metrics, None, enable_lipsync=enable_lipsync)
        )
        total_stages = 1 + len(needed) + len(aligns)
    stage += 1
    if _cancelled(should_cancel):
        return {"status": "cancelled", "stage": "beat_grid"}

    # 2. The shared master artifacts the running scorers declared (once each) — the
    # lip-sync tier's vocal stem, or anything a plugin registers.
    artifacts = {}
    for name in needed:
        art = registry.artifact(name)
        _emit(progress_cb, stage, total_stages, art.stage)
        artifacts[name] = art.build(
            str(project.song_path()), str(project.root / "scores")
        )
        stage += 1
        if _cancelled(should_cancel):
            return {"status": "cancelled", "stage": art.stage}

    face_fn = F.make_face_scorer() if needs_frames else None
    fps_kw = {} if sample_fps is None else {"sample_fps": sample_fps}
    grid = registry.Grid(t0=t0, hop_s=hop_s, n=n)
    grid_kw = grid.as_kwargs()

    tracks_by_clip: dict[str, list] = {}
    shots_by_clip: dict[str, list] = {}
    shots_skipped: dict[str, str] = {}
    skipped: dict[str, str] = {}

    for a in aligns:
        _emit(progress_cb, stage, total_stages, f"clip:{a.clip_id}")
        stage += 1
        if _cancelled(should_cancel):
            return {"status": "cancelled", "stage": f"clip:{a.clip_id}"}
        path = clip_paths.get(a.clip_id)
        if not path:
            skipped[a.clip_id] = "no file"
            continue
        fp = None
        if needs_frames:
            try:
                fp = F.sample_clip_frames(
                    str(path), face_fn=face_fn, should_cancel=should_cancel, **fps_kw
                )
            except Exception as e:  # a bad clip must not sink the whole job
                skipped[a.clip_id] = f"decode failed: {e}"
                continue

        ctx = registry.ClipContext(
            clip_id=a.clip_id,
            path=str(path),
            offset_s=a.offset_s,
            duration_s=a.duration_s,
            coverage=tuple(a.coverage),
            frames=fp,
            beat=bg,
            inputs=MappingProxyType(input_values),
            grid=grid,
        )
        # Optional hard quality gate → AND into the mask of every GATED scorer's tracks.
        gate = None
        if fp is not None:
            g = quality_gate_mask(fp, offset_s=a.offset_s, **grid_kw)
            gate = None if g.all() else g
        clip_tracks = []
        for sc in active:
            # each scorer sees only the artifacts it declared, so none comes to rely
            # on another's `needs`
            own = {n: artifacts[n] for n in sc.needs if artifacts.get(n) is not None}
            # only what the scorer DECLARED: a track under another scorer's metric
            # name would overwrite it in the tensor
            produced_tracks = [
                tr
                for tr in sc.run(replace(ctx, artifacts=own))
                if tr.metric in sc.metrics
            ]
            if gate is not None and sc.gated:
                produced_tracks = [_and_mask(tr, gate) for tr in produced_tracks]
            clip_tracks.extend(produced_tracks)

        # Shot boundaries (for the selector's beats+shots mode). A detector failure is
        # recorded, never fatal: the shots are a by-product only `beats+shots` reads, and
        # raising here would throw away every clip's tracks, the most expensive artifact
        # in the pipeline (muvid#220). Recorded in `shots_skipped`, so it is not silent.
        try:
            shots_by_clip[a.clip_id] = shot_boundaries(str(path), offset_s=a.offset_s)
        except Exception as e:  # noqa: BLE001 - recorded per clip in shots_skipped
            shots_skipped[a.clip_id] = f"shot detection failed: {e}"

        tracks_by_clip[a.clip_id] = [tr for tr in clip_tracks if tr.metric in wanted]

    # A partial re-score keeps the current metrics it did not recompute (muvid#206) —
    # not the opt-in tier's when that tier is off now.
    off = set() if want_lipsync else registry.metrics_of_tier(registry.LIPSYNC_TIER)
    kept_tracks = {
        cid: [tr for tr in trs if tr.metric not in wanted and tr.metric not in off]
        for cid, trs in (keep.tracks if keep is not None else {}).items()
    }
    for cid, kept in kept_tracks.items():
        if cid in tracks_by_clip:
            tracks_by_clip[cid].extend(kept)
    kept_metrics = {tr.metric for trs in kept_tracks.values() for tr in trs}
    # Metric axis = the metrics actually produced by ≥1 clip (wanted, or kept).
    produced = {tr.metric for trs in tracks_by_clip.values() for tr in trs}
    metric_axis = [
        m
        for m in registry.default_metrics(include_lipsync=True)
        if m in produced and (m in wanted or m in kept_metrics)
    ]
    # the metrics on the axis measured on each keyed input, by what their scorers
    # declare — every registered one, so a metric KEPT by a partial re-score keeps
    # its inputs too (the #213 review: built from the running scorers only, a kept
    # metric lost them and was served as current after its input changed)
    input_metrics = {
        name: [m for m in metric_axis if m in registry.metrics_reading(name)]
        for name in registry.INPUTS
    }

    import math

    from muvid.footage.scoring.grid import align_fingerprint

    tempo = float(bg.tempo_bpm)
    save_scores(
        project.root,
        tracks_by_clip,
        t0=t0,
        hop_s=hop_s,
        n=n,
        metrics=metric_axis,
        song_hash=project.song_hash(),
        align_fingerprint=align_fingerprint(aligns),
        beat_times=bg.beat_times,
        downbeat_times=bg.downbeat_times,
        input_fingerprints=input_fingerprints,
        input_metrics=input_metrics,
        extra={
            "shot_boundaries": shots_by_clip,
            "tempo_bpm": round(tempo, 3) if math.isfinite(tempo) else None,
            "sample_fps": sample_fps or F.DEFAULT_SAMPLE_FPS,
            "lipsync_enabled": want_lipsync,
            "skipped": skipped,
            "shots_skipped": shots_skipped,
        },
    )
    return {
        "status": "ok",
        "metrics": metric_axis,
        "clips_scored": list(tracks_by_clip.keys()),
        "skipped": skipped,
        "shots_skipped": shots_skipped,
        "n_frames": n,
        "hop_s": hop_s,
        "beats": int(len(bg.beat_times)),
        "lipsync_enabled": want_lipsync,
        **({"skipped_scorers": skipped_scorers} if skipped_scorers else {}),
        # a partial re-score that kept the current metrics names what it measured again
        **({"rescored": sorted(keep.recompute)} if keep is not None else {}),
    }


def _and_mask(track, gate):
    import numpy as np

    from muvid.footage.scoring.grid import ScoreTrack

    new_mask = track.mask & gate
    new_vals = np.where(new_mask, track.raw_values, np.nan).astype("float32")
    return ScoreTrack(
        track.clip_id,
        track.metric,
        track.t0,
        track.hop_s,
        new_vals,
        new_mask,
        track.direction,
    )
