"""The motion-to-beat formulas as pure functions (muvid#238): a caller with its own motion
signal (pose landmarks) gets the numbers the ``motion_beat_bas`` / ``motion_onset_xcorr``
tracks are built from, without a decoded clip or a song grid."""

from __future__ import annotations

import math
import subprocess
import sys

import numpy as np
import pytest

from muvid.footage.scoring.motionbeat import (
    BAS_SIGMA_S,
    beat_alignment_score,
    onset_lag,
)


def test_bas_is_one_on_the_beat_and_falls_off_as_a_gaussian():
    beats = [0.5, 1.0, 1.5, 2.0]
    assert beat_alignment_score(beats, beats) == pytest.approx(1.0)
    late = beat_alignment_score([b + BAS_SIGMA_S for b in beats], beats)
    assert late == pytest.approx(math.exp(-0.5))


def test_the_two_directions_differ_where_papers_differ():
    """AIST++ averages over motion events, Bailando over music beats: extra motion off
    the beat lowers the first and not the second."""
    beats = [1.0, 2.0]
    events = [1.0, 2.0, 1.5]  # one move on the off-beat
    assert beat_alignment_score(events, beats) < 0.7
    assert beat_alignment_score(events, beats, direction="music_to_motion") == pytest.approx(1.0)


def test_no_evidence_is_nan_not_zero_and_a_bad_direction_is_refused():
    assert math.isnan(beat_alignment_score([], [1.0]))
    assert math.isnan(beat_alignment_score([1.0], []))
    with pytest.raises(ValueError, match="direction"):
        beat_alignment_score([1.0], [1.0], direction="both")


@pytest.mark.parametrize("lag", [0.24, -0.16, 0.0])  # whole samples: no interpolation blur
def test_onset_lag_recovers_a_known_lag_and_its_sign(lag):
    hop = 0.02
    t = np.arange(0.0, 12.0, hop)
    rng = np.random.default_rng(1)
    onsets = (rng.random(t.size) > 0.9).astype(float)
    got = onset_lag(t + lag, onsets, onsets, hop)  # the same moves, `lag` s later
    assert got.lag_s == pytest.approx(lag, abs=hop)
    assert got.r == pytest.approx(1.0, abs=0.05)


def test_onset_lag_needs_enough_samples():
    assert onset_lag([0.0, 0.1], [1.0, 2.0], np.ones(100), 0.05) is None
    assert onset_lag(np.arange(0, 2, 0.1), np.ones(20), [1.0], 0.05) is None


def test_the_track_is_built_from_the_same_formula():
    """``motion_beat_bas`` holds, over each beat's interval, that beat's music_to_motion
    score against the motion peaks."""
    from muvid.footage.scoring import motionbeat as M

    hop, n, t0 = 0.05, 80, 0.0
    motion = np.zeros(n)
    motion[[20, 41]] = 1.0  # peaks at 1.0 s and 2.05 s
    mmask = np.ones(n, bool)
    vals, mask = M._bas_track(motion, mmask, np.array([1.0, 2.0]), t0, hop, n, (0.0, 4.0))
    peaks = M._motion_peaks(motion, mmask, t0, hop)
    for beat, k in ((1.0, 20), (2.0, 40)):
        want = beat_alignment_score(peaks, [beat], direction="music_to_motion")
        assert vals[k] == pytest.approx(want, rel=1e-6)


def test_importing_the_formulas_pulls_no_decoder():
    code = (
        "import sys, muvid.footage.scoring.motionbeat; "
        "print([m for m in ('cv2', 'mediapipe', 'muvid.footage.scoring.frames') "
        "if m in sys.modules])"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
