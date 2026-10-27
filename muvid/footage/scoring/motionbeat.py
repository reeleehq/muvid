"""Motion-to-beat tier: ``motion_beat_bas`` + ``motion_onset_xcorr`` → song-grid tracks.

Pure given a :class:`~muvid.footage.scoring.frames.FramePass` (the camera-compensated motion
envelope) + the master :class:`mixing.audio.BeatGrid` (computed ONCE on the clean song). No
per-clip beat/onset recomputation — everything maps to song time via the clip's offset.

- ``motion_beat_bas`` — a per-beat Beat Alignment Score (AIST++ [11] idea, localized): each
  audio beat scores how close its nearest MOTION peak is (``exp(−(Δt/σ)²/2)``); the score is
  held over that beat's interval. NA where the clip has no motion (static / no person) — never
  0 (a 0 would penalize valid instrumental footage). Person-present signal.
- ``motion_onset_xcorr`` — the clip-level normalized cross-correlation of the motion envelope
  vs the master onset envelope at the best lag within a bounded A/V-latency window (the lag
  refines per-clip capture latency). Content-agnostic (covers no-person clips). Held over the
  clip's coverage.

The BAS formula is also a PURE function over event and beat times (muvid#238),
:func:`beat_alignment_score`, so a caller with its own motion signal (pose landmarks, say)
gets the number the ``motion_beat_bas`` track is built from; the track calls the same core.
(The onset lag is NOT exposed: the track's search shifts circularly over its window, which
is harmless for the ``|r|`` it keeps and wrong for a lag a caller would read — a correct
public one belongs beside mixing's overlap-normalised cross-correlation.)

Commercial-clean (librosa beats via ``mixing[beats]``, numpy motion). See the design §3b.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from muvid.footage.scoring.grid import ScoreTrack, resample_to_grid

if TYPE_CHECKING:
    from muvid.footage.scoring.frames import FramePass

#: Gaussian width (s) for beat↔motion-peak proximity in the BAS.
BAS_SIGMA_S = 0.12
#: The two directions papers measure the BAS in: AIST++'s (each MOTION beat scored by its
#: nearest music beat) and Bailando's (each MUSIC beat scored by its nearest motion beat).
BAS_DIRECTIONS = ("motion_to_music", "music_to_motion")
#: Bounded lag search for the onset xcorr (±s) — also the plausible A/V capture-latency range.
_XCORR_MAX_LAG_S = 1.0

MOTIONBEAT_METRICS = ("motion_beat_bas", "motion_onset_xcorr")


def beat_alignment_score(
    event_times,
    beat_times,
    *,
    sigma_s: float = BAS_SIGMA_S,
    direction: str = "motion_to_music",
) -> float:
    """The Beat Alignment Score of motion ``event_times`` (kinematic beats, seconds)
    against music ``beat_times``: the mean of ``exp(-(d/σ)²/2)``, ``d`` the distance to
    the nearest beat of the other kind (AIST++, Li et al. 2021, §BeatAlign).

    ``direction`` is :data:`BAS_DIRECTIONS`: ``motion_to_music`` (AIST++) averages over
    the motion events, ``music_to_motion`` (Bailando) over the music beats — the per-beat
    form the ``motion_beat_bas`` track holds over each beat's interval. ``nan`` when
    either list is empty: no evidence is not a score of 0. A non-finite time or a
    ``sigma_s`` that is not positive is refused rather than read as ``nan``.

    >>> round(beat_alignment_score([0.5, 1.0, 1.62], [0.5, 1.0, 1.5]), 3)  # one 0.12 s late
    0.869
    >>> round(beat_alignment_score([0.5], [0.5, 1.0], direction="music_to_motion"), 3)
    0.5
    """
    if direction not in BAS_DIRECTIONS:
        raise ValueError(f"direction must be one of {BAS_DIRECTIONS}, got {direction!r}")
    if not sigma_s > 0:
        raise ValueError(f"sigma_s must be positive, got {sigma_s}")
    events = np.asarray(event_times, dtype=float)
    beats = np.asarray(beat_times, dtype=float)
    if events.ndim != 1 or beats.ndim != 1:
        raise ValueError("event_times and beat_times must be 1-D sequences of seconds")
    if not (np.isfinite(events).all() and np.isfinite(beats).all()):
        raise ValueError("event_times and beat_times must be finite")
    if events.size == 0 or beats.size == 0:
        return float("nan")
    sources, targets = (events, beats) if direction == "motion_to_music" else (beats, events)
    return float(np.mean(_proximity(sources, targets, sigma_s)))


def _proximity(sources: np.ndarray, targets: np.ndarray, sigma_s: float) -> np.ndarray:
    """``exp(-(d/σ)²/2)`` per source, ``d`` its distance to the nearest target — found
    by bisection on the sorted targets (memory O(n), not sources x targets)."""
    ts = np.sort(targets)
    i = np.clip(np.searchsorted(ts, sources), 1, ts.size - 1) if ts.size > 1 else 0
    d = np.abs(sources - ts[i]) if ts.size == 1 else np.minimum(
        np.abs(sources - ts[i - 1]), np.abs(sources - ts[i])
    )
    return np.exp(-0.5 * (d / sigma_s) ** 2)


def motionbeat_tracks(
    frame_pass: "FramePass",
    *,
    clip_id: str,
    offset_s: float,
    beat_times: np.ndarray,
    onset_env: np.ndarray,
    onset_hop_s: float,
    t0: float,
    hop_s: float,
    n: int,
) -> list[ScoreTrack]:
    """The two motion-to-beat tracks for one clip."""
    # A motion sample measured between frames k-1 and k represents the INTERVAL midpoint, so
    # shift the motion sample times back half a frame before gridding (else the envelope — and
    # thus the on-beat BAS — reads ~half a sample late). Quality metrics keep clip_times as-is.
    half = (
        0.5 * float(np.median(np.diff(frame_pass.clip_times)))
        if frame_pass.clip_times.size >= 2
        else 0.0
    )
    song_t = frame_pass.clip_times + offset_s - half
    # Motion envelope on the song grid (camera-compensated residual; NaN @ frame 0 dropped).
    motion, mmask = resample_to_grid(
        song_t, frame_pass.motion_residual, t0=t0, hop_s=hop_s, n=n
    )
    cover = (song_t[0] if song_t.size else 0.0, song_t[-1] if song_t.size else 0.0)

    bas_vals, bas_mask = _bas_track(
        motion, mmask, np.asarray(beat_times, dtype=float), t0, hop_s, n, cover
    )  # cover uses the (shifted) song_t span; the shift is sub-frame so coverage is unaffected
    xcorr_vals, xcorr_mask = _onset_xcorr_track(
        motion, mmask, onset_env, onset_hop_s, t0, hop_s, n, cover
    )
    return [
        ScoreTrack(
            clip_id, "motion_beat_bas", t0, hop_s, bas_vals, bas_mask, "higher_better"
        ),
        ScoreTrack(
            clip_id,
            "motion_onset_xcorr",
            t0,
            hop_s,
            xcorr_vals,
            xcorr_mask,
            "higher_better",
        ),
    ]


def _motion_peaks(
    motion: np.ndarray, mask: np.ndarray, t0: float, hop_s: float
) -> np.ndarray:
    """Song-times of local maxima of the motion envelope above a robust threshold."""
    m = np.where(mask, motion, np.nan)
    finite = m[np.isfinite(m)]
    if finite.size < 3:
        return np.asarray([], dtype=float)
    med = np.median(finite)
    mad = np.median(np.abs(finite - med)) or (finite.std() or 1.0)
    thr = med + 1.0 * mad
    peaks = []
    for k in range(1, len(m) - 1):
        if not (np.isfinite(m[k]) and np.isfinite(m[k - 1]) and np.isfinite(m[k + 1])):
            continue
        if m[k] >= m[k - 1] and m[k] > m[k + 1] and m[k] >= thr:
            peaks.append(
                t0 + k * hop_s
            )  # absolute song time (matches _bas_track's beats)
    return np.asarray(peaks, dtype=float)


def _bas_track(motion, mmask, beat_times, t0, hop_s, n, cover):
    vals = np.full(n, np.nan, dtype=np.float32)
    mask = np.zeros(n, dtype=bool)
    peaks = _motion_peaks(motion, mmask, t0, hop_s)
    lo, hi = cover
    beats = beat_times[(beat_times >= lo - _EPS_T) & (beat_times <= hi + _EPS_T)]
    if peaks.size == 0 or beats.size == 0:
        return vals, mask  # no motion peaks / no beats in coverage → NA (never 0)
    beats_sorted = np.sort(beats)
    # each beat scored by its nearest motion peak: the music_to_motion BAS, per beat
    scores = _proximity(beats_sorted, peaks, BAS_SIGMA_S)
    for bi, (b, score) in enumerate(zip(beats_sorted, scores)):
        end = beats_sorted[bi + 1] if bi + 1 < len(beats_sorted) else hi
        k0 = max(0, int(np.floor((b - t0) / hop_s)))
        k1 = min(n, int(np.ceil((end - t0) / hop_s)))
        # only over the motion-covered part of the interval
        for k in range(k0, k1):
            if mmask[k]:
                vals[k] = score
                mask[k] = True
    return vals, mask


def _onset_xcorr_track(motion, mmask, onset_env, onset_hop_s, t0, hop_s, n, cover):
    """Clip-level normalized xcorr strength (best lag within ±_XCORR_MAX_LAG_S), held over
    the motion-covered span."""
    vals = np.full(n, np.nan, dtype=np.float32)
    mask = np.zeros(n, dtype=bool)
    valid = np.flatnonzero(mmask)
    if valid.size < 4 or onset_env is None or len(onset_env) < 4:
        return vals, mask
    lo_k, hi_k = valid[0], valid[-1]
    # Resample the master onset envelope onto the SAME song grid over the covered span.
    onset_times = np.arange(len(onset_env)) * onset_hop_s
    onset_on_grid, on_mask = resample_to_grid(
        onset_times, np.asarray(onset_env, float), t0=t0, hop_s=hop_s, n=n
    )
    a = np.where(mmask, motion, np.nan)[lo_k : hi_k + 1]
    b = np.where(on_mask, onset_on_grid, np.nan)[lo_k : hi_k + 1]
    both = np.isfinite(a) & np.isfinite(b)
    if np.count_nonzero(both) < 4:
        return vals, mask
    a = np.nan_to_num(a - np.nanmean(a[both]))
    b = np.nan_to_num(b - np.nanmean(b[both]))
    max_lag = int(round(_XCORR_MAX_LAG_S / hop_s))
    best = 0.0
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
    for lag in range(-max_lag, max_lag + 1):
        r = float(np.dot(a, np.roll(b, lag))) / denom
        best = max(best, abs(r))
    vals[lo_k : hi_k + 1] = np.where(mmask[lo_k : hi_k + 1], best, np.nan)
    mask[lo_k : hi_k + 1] = mmask[lo_k : hi_k + 1]
    return vals, mask


_EPS_T = 1e-6
