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

Both formulas are also PURE functions over arrays (muvid#238) — :func:`beat_alignment_score`
over event and beat times, :func:`onset_lag` over a ``(t, value)`` motion envelope and an
onset envelope — so a caller with its own motion signal (pose landmarks, say) uses the same
numbers the tracks are built from. The tracks call them; numpy only.

Commercial-clean (librosa beats via ``mixing[beats]``, numpy motion). See the design §3b.
"""

from __future__ import annotations

import numpy as np

from typing import TYPE_CHECKING, NamedTuple, Optional

from muvid.footage.scoring.grid import ScoreTrack, resample_to_grid

if TYPE_CHECKING:
    from muvid.footage.scoring.frames import FramePass

#: Gaussian width (s) for beat↔motion-peak proximity in the BAS.
BAS_SIGMA_S = 0.12
#: Bounded lag search for the onset xcorr (±s) — also the plausible A/V capture-latency range.
XCORR_MAX_LAG_S = 1.0
#: The fewest overlapping samples a cross-correlation is computed from.
_MIN_XCORR_SAMPLES = 4
#: The two directions papers measure the BAS in: AIST++'s (each MOTION beat scored by its
#: nearest music beat) and Bailando's (each MUSIC beat scored by its nearest motion beat).
BAS_DIRECTIONS = ("motion_to_music", "music_to_motion")


def _proximity(sources: np.ndarray, targets: np.ndarray, sigma_s: float) -> np.ndarray:
    """``exp(-(d/σ)²/2)`` per source, ``d`` its distance to the nearest target."""
    d = np.abs(sources[:, None] - targets[None, :]).min(axis=1)
    return np.exp(-0.5 * (d / sigma_s) ** 2)


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
    either list is empty: no evidence is not a score of 0.

    >>> round(beat_alignment_score([0.5, 1.0, 1.62], [0.5, 1.0, 1.5]), 3)  # one 0.12 s late
    0.869
    >>> round(beat_alignment_score([0.5], [0.5, 1.0], direction="music_to_motion"), 3)
    0.5
    """
    if direction not in BAS_DIRECTIONS:
        raise ValueError(f"direction must be one of {BAS_DIRECTIONS}, got {direction!r}")
    events = np.asarray(event_times, dtype=float)
    beats = np.asarray(beat_times, dtype=float)
    if events.size == 0 or beats.size == 0:
        return float("nan")
    sources, targets = (events, beats) if direction == "motion_to_music" else (beats, events)
    return float(np.mean(_proximity(sources, targets, sigma_s)))


class OnsetLag(NamedTuple):
    """The best lag between a motion envelope and the music's onset envelope."""

    #: seconds; positive = the motion comes AFTER the music
    lag_s: float
    #: the normalized cross-correlation there, in [-1, 1] (the track holds ``abs``)
    r: float


def _onset_xcorr(a: np.ndarray, b: np.ndarray, *, hop_s: float, max_lag_s: float):
    """:class:`OnsetLag` of two envelopes on ONE grid (``nan`` = missing), or ``None``
    with fewer than :data:`_MIN_XCORR_SAMPLES` samples where both are present. Mean-
    removed over the shared samples; the shift is circular over the window, as the
    ``motion_onset_xcorr`` track has always computed it (a lag is at most
    ``max_lag_s``, so only that much wraps)."""
    both = np.isfinite(a) & np.isfinite(b)
    if np.count_nonzero(both) < _MIN_XCORR_SAMPLES:
        return None
    a = np.nan_to_num(a - np.nanmean(a[both]))
    b = np.nan_to_num(b - np.nanmean(b[both]))
    max_lag = int(round(max_lag_s / hop_s))
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
    best_lag, best = 0, 0.0
    for lag in range(-max_lag, max_lag + 1):
        r = float(np.dot(a, np.roll(b, lag))) / denom
        if abs(r) > abs(best):
            best_lag, best = lag, r
    return OnsetLag(float(best_lag * hop_s), float(best))


def onset_lag(
    t,
    motion,
    onset_env,
    onset_hop_s: float,
    *,
    max_lag_s: float = XCORR_MAX_LAG_S,
    hop_s: Optional[float] = None,
) -> Optional[OnsetLag]:
    """How far a motion envelope (``motion`` sampled at times ``t``, seconds) lags the
    music's onset envelope (``onset_env``, one value per ``onset_hop_s`` from 0), within
    ``±max_lag_s`` — the audio-visual lag and how strongly the two agree there.

    Both are put on one grid of ``hop_s`` (default ``onset_hop_s``) over the motion's
    span, then cross-correlated. ``None`` when they share too few samples.

    >>> import numpy as np
    >>> hop = 0.05; tt = np.arange(0, 10, hop)
    >>> onsets = (np.sin(2 * np.pi * 1.3 * tt) > 0.95).astype(float)
    >>> got = onset_lag(tt + 0.2, onsets, onsets, hop)  # the same moves, 0.2 s later
    >>> round(got.lag_s, 2), round(got.r, 2)
    (0.2, 1.0)
    """
    t = np.asarray(t, dtype=float)
    if t.size < _MIN_XCORR_SAMPLES or len(onset_env) < _MIN_XCORR_SAMPLES:
        return None
    hop = float(hop_s or onset_hop_s)
    n = int(np.floor((t[-1] - t[0]) / hop)) + 1
    m, m_mask = resample_to_grid(t, np.asarray(motion, float), t0=t[0], hop_s=hop, n=n)
    onset_times = np.arange(len(onset_env)) * onset_hop_s
    o, o_mask = resample_to_grid(
        onset_times, np.asarray(onset_env, float), t0=t[0], hop_s=hop, n=n
    )
    return _onset_xcorr(
        np.where(m_mask, m, np.nan),
        np.where(o_mask, o, np.nan),
        hop_s=hop,
        max_lag_s=max_lag_s,
    )

MOTIONBEAT_METRICS = ("motion_beat_bas", "motion_onset_xcorr")


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
    if (
        valid.size < _MIN_XCORR_SAMPLES
        or onset_env is None
        or len(onset_env) < _MIN_XCORR_SAMPLES
    ):
        return vals, mask
    lo_k, hi_k = valid[0], valid[-1]
    # Resample the master onset envelope onto the SAME song grid over the covered span.
    onset_times = np.arange(len(onset_env)) * onset_hop_s
    onset_on_grid, on_mask = resample_to_grid(
        onset_times, np.asarray(onset_env, float), t0=t0, hop_s=hop_s, n=n
    )
    found = _onset_xcorr(
        np.where(mmask, motion, np.nan)[lo_k : hi_k + 1],
        np.where(on_mask, onset_on_grid, np.nan)[lo_k : hi_k + 1],
        hop_s=hop_s,
        max_lag_s=XCORR_MAX_LAG_S,
    )
    if found is None:
        return vals, mask
    best = abs(found.r)
    vals[lo_k : hi_k + 1] = np.where(mmask[lo_k : hi_k + 1], best, np.nan)
    mask[lo_k : hi_k + 1] = mmask[lo_k : hi_k + 1]
    return vals, mask


_EPS_T = 1e-6
