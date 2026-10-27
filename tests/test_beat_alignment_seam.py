"""The Beat Alignment Score as a pure function (muvid#238): a caller with its own motion
signal (pose landmarks) gets the number the ``motion_beat_bas`` track is built from,
without a decoded clip or a song grid — and the track is bit-identical to before."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from muvid.footage.scoring.motionbeat import BAS_SIGMA_S, beat_alignment_score

_GOLDEN = Path(__file__).parent / "data" / "motion_beat_bas_golden.json"


def _by_hand(sources, targets, sigma):
    """The AIST++ formula written out, independent of the code under test."""
    return sum(
        math.exp(-0.5 * (min(abs(s - t) for t in targets) / sigma) ** 2) for s in sources
    ) / len(sources)


def test_bas_is_the_aist_formula():
    events, beats = [0.5, 1.03, 1.62, 2.4], [0.5, 1.0, 1.5, 2.0, 2.5]
    assert beat_alignment_score(events, beats) == pytest.approx(
        _by_hand(events, beats, BAS_SIGMA_S)
    )
    assert beat_alignment_score(events, beats, direction="music_to_motion") == pytest.approx(
        _by_hand(beats, events, BAS_SIGMA_S)
    )
    assert beat_alignment_score(events, beats, sigma_s=0.3) == pytest.approx(
        _by_hand(events, beats, 0.3)
    )
    assert beat_alignment_score([2.4], [2.5]) == pytest.approx(_by_hand([2.4], [2.5], BAS_SIGMA_S))


def test_the_two_directions_differ_where_papers_differ():
    """AIST++ averages over motion events, Bailando over music beats: extra motion off
    the beat lowers the first and not the second."""
    beats = [1.0, 2.0]
    events = [1.0, 2.0, 1.5]  # one move on the off-beat
    assert beat_alignment_score(events, beats) < 0.7
    assert beat_alignment_score(events, beats, direction="music_to_motion") == pytest.approx(1.0)


def test_no_evidence_is_nan_and_bad_input_is_refused():
    assert math.isnan(beat_alignment_score([], [1.0]))
    assert math.isnan(beat_alignment_score([1.0], []))
    with pytest.raises(ValueError, match="direction"):
        beat_alignment_score([1.0], [1.0], direction="both")
    with pytest.raises(ValueError, match="sigma_s"):
        beat_alignment_score([1.0], [1.0], sigma_s=0.0)
    with pytest.raises(ValueError, match="finite"):
        beat_alignment_score([1.0, float("nan")], [1.0])


def test_the_track_is_bit_identical_to_before():
    """Score tensors are keyed on INPUTS, so a changed number would be served as current:
    the golden is ``_bas_track`` recorded on main before the refactor."""
    from muvid.footage.scoring import motionbeat as M

    for case in json.loads(_GOLDEN.read_text()):
        vals, mask = M._bas_track(
            np.asarray(case["motion"]),
            np.asarray(case["mmask"]),
            np.asarray(case["beats"]),
            case["t0"],
            case["hop"],
            case["n"],
            tuple(case["cover"]),
        )
        want = np.asarray([np.nan if v is None else v for v in case["vals"]], dtype=np.float32)
        assert np.array_equal(vals, want, equal_nan=True)
        assert mask.tolist() == case["mask"]


def test_importing_the_formula_pulls_no_decoder():
    code = (
        "import sys, muvid.footage.scoring.motionbeat; "
        "print([m for m in ('cv2', 'mediapipe', 'muvid.footage.scoring.frames') "
        "if m in sys.modules])"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
