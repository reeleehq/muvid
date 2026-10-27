"""``score_candidates``: how candidate stretches of the videos score (muvid#184 item 1).

Span-keyed answers over the CURRENT scores: the composite mean over measured frames,
the measured fraction, and each metric's mean — absent is ``null``, never a low score.
No frames, no ffmpeg: a registered scorer writes a known ramp.
"""

from __future__ import annotations

import numpy as np
import pytest

from muvid.footage import service
from muvid.footage.errors import FootageError
from muvid.footage.scoring import registry as R
from tests.test_declared_beat_grid import SONG_DURATION, proj, scored_proj  # noqa: F401


@pytest.fixture
def ramp_scores(scored_proj):
    """Scores for clip A: metric ``ramp`` rises 0 -> 1 over the song and is NOT measured
    in its first 10 s; metric ``half`` is 0.5 everywhere."""
    project, _seen, _ = scored_proj
    from muvid.footage.scoring.grid import ScoreTrack

    def run(ctx):
        n = ctx.grid.n
        ramp = np.linspace(0.0, 1.0, n, dtype="float32")
        t = ctx.grid.t0 + np.arange(n) * ctx.grid.hop_s
        ramp[t < 10.0] = np.nan
        half = np.full(n, 0.5, dtype="float32")
        g = (ctx.grid.t0, ctx.grid.hop_s)
        return [
            ScoreTrack(ctx.clip_id, "ramp", *g, ramp, np.isfinite(ramp)),
            ScoreTrack(ctx.clip_id, "half", *g, half, np.isfinite(half)),
        ]

    before = dict(R._SCORERS)
    R._SCORERS.clear()
    R.register_scorer(
        R.Scorer("toy", ("ramp", "half"), run, needs_frames=False, gated=False)
    )
    service.run_scoring(project)
    yield project
    R._SCORERS.clear()
    R._SCORERS.update(before)


def test_each_answer_carries_its_span_and_absent_is_null(ramp_scores):
    later = {"clip_id": "A", "song_start": 20.0, "song_end": 25.0}
    early = {"clip_id": "A", "song_start": 0.0, "song_end": 5.0}
    out = service.score_candidates(
        ramp_scores, candidates=[later, early], weights={"ramp": 1.0}
    )
    a, b = out["candidates"]
    assert {k: a[k] for k in later} == later and {k: b[k] for k in early} == early
    assert a["composite"] is not None and a["measured"] == 1.0
    # the first 10 s of `ramp` were never measured: no composite, not a zero one
    assert b["composite"] is None and b["measured"] == 0.0
    assert b["metrics"]["ramp"] is None and b["metrics"]["half"] is not None
    assert out["weights"]["ramp"] == 1.0


def test_a_later_stretch_of_a_rising_metric_scores_higher(ramp_scores):
    spans = [
        {"clip_id": "A", "song_start": s, "song_end": s + 4.0} for s in (11.0, 25.0)
    ]
    first, second = service.score_candidates(
        ramp_scores, candidates=spans, weights={"ramp": 1.0}
    )["candidates"]
    assert second["composite"] > first["composite"]


@pytest.mark.parametrize(
    "bad,match",
    [
        ([], "non-empty"),
        (
            [{"clip_id": "A", "song_start": 5.0, "song_end": 5.0}],
            "song_start < song_end",
        ),
        ([{"clip_id": "A", "song_start": 0.0, "song_end": SONG_DURATION + 9}], "song"),
        ([{"clip_id": "Z", "song_start": 0.0, "song_end": 1.0}], "no video 'Z'"),
        ([{"song_start": 0.0, "song_end": 1.0}], "clip_id"),
    ],
)
def test_bad_candidates_are_refused_plainly(ramp_scores, bad, match):
    with pytest.raises(FootageError, match=match):
        service.score_candidates(ramp_scores, candidates=bad)


def test_it_needs_current_scores(ramp_scores):
    service.set_beat_grid(ramp_scores, tempo_bpm=100.0)
    with pytest.raises(FootageError, match="stale"):
        service.score_candidates(
            ramp_scores,
            candidates=[{"clip_id": "A", "song_start": 0.0, "song_end": 1.0}],
        )


def test_a_span_shorter_than_a_hop_reads_the_frame_it_sits_on(ramp_scores):
    """The #184 review: ``[20.01, 20.06)`` holds no frame instant at hop 0.1; it must read
    the frame at 20.0, not 20.1 — and ``measured`` is never NaN (invalid JSON)."""
    tiny = {"clip_id": "A", "song_start": 20.01, "song_end": 20.06}
    exact = {"clip_id": "A", "song_start": 20.0, "song_end": 20.05}
    out = service.score_candidates(
        ramp_scores, candidates=[tiny, exact], weights={"ramp": 1.0}
    )
    a, b = out["candidates"]
    assert a["measured"] == 1.0 and a["composite"] == b["composite"]


def test_an_odd_clip_id_is_refused_without_echoing_it_whole(ramp_scores):
    huge = "x" * 1_000_000
    with pytest.raises(FootageError) as e:
        service.score_candidates(
            ramp_scores,
            candidates=[{"clip_id": huge, "song_start": 0.0, "song_end": 1.0}],
        )
    assert len(str(e.value)) < 300
