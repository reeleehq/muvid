"""The scorer registry: a new metric touches no orchestrator code (muvid#19)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from muvid.footage.scoring import registry as R


def _scorer(name="loudness", metrics=("loudness",), **kw):
    return R.Scorer(name, metrics, lambda ctx: [], needs_frames=False, **kw)


@pytest.fixture
def clean_registry():
    before = dict(R._SCORERS)
    yield
    R._SCORERS.clear()
    R._SCORERS.update(before)


def test_the_built_ins_are_the_old_metric_set_in_the_old_order():
    assert R.default_metrics() == [
        "sharpness",
        "exposure",
        "stability_shake",
        "face_framing",
        "motion_beat_bas",
        "motion_onset_xcorr",
    ]
    assert R.default_metrics(include_lipsync=True)[-2:] == [
        "lip_sync_lse_c",
        "lse_d_offset",
    ]
    assert [s.name for s in R.scorers()] == ["quality", "motion_beat"]


def test_a_registered_scorer_joins_the_metric_axis(clean_registry):
    R.register_scorer(_scorer())
    assert R.default_metrics()[-1] == "loudness"
    assert "loudness" not in R.default_metrics(include_lipsync=False)[:-1]


def test_names_and_metrics_are_unique(clean_registry):
    with pytest.raises(ValueError, match="already registered"):
        R.register_scorer(_scorer("quality", ("x",)))
    with pytest.raises(ValueError, match=r"\['sharpness'\] already produced by"):
        R.register_scorer(_scorer("mine", ("sharpness",)))
    R.register_scorer(_scorer("quality", ("sharpness",)), replace=True)  # may replace


def test_a_scorer_must_declare_metrics_and_a_known_tier():
    with pytest.raises(ValueError, match="no metrics"):
        _scorer(metrics=())
    with pytest.raises(ValueError, match="tier"):
        _scorer(tier="gpu")


def test_the_lipsync_tier_stays_opt_in(clean_registry):
    R.register_scorer(_scorer("x", ("x",), tier=R.LIPSYNC_TIER))
    assert "x" not in R.default_metrics()
    assert "x" in R.default_metrics(include_lipsync=True)


def test_orchestrator_rejects_a_metric_nobody_registered(tmp_path):
    from muvid.footage.scoring.orchestrator import _score

    class _P:
        def load_alignments(self):
            return [object()]

        def song_duration(self):
            return 1.0

        def clip_paths(self):
            return {}

    with pytest.raises(ValueError, match=r"unknown metric\(s\) \['bogus'\]"):
        _score(
            _P(),
            metrics=["bogus"],
            hop_s=0.1,
            sample_fps=None,
            enable_lipsync=False,
            progress_cb=None,
            should_cancel=None,
        )


def test_the_registry_imports_nothing_heavy():
    code = (
        "import sys; import muvid.footage.scoring.registry; "
        "bad=[m for m in ('numpy','cv2','mediapipe','librosa','torch') if m in sys.modules]; "
        "sys.exit(1 if bad else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_a_registered_scorer_is_scored_end_to_end(
    tmp_path, monkeypatch, clean_registry
):
    """The acceptance line: add a scorer, score a project, and the metric is in the
    tensor with no edit to the orchestrator or the selector."""
    import numpy as np

    from tests.test_scoring_extractors import _clip, _song, core  # noqa: F401
    from tests import test_scoring_extractors as T

    if not (T.HAS_FFMPEG and T.HAS_CV2 and T.HAS_LIBROSA):
        pytest.skip("needs ffmpeg + cv2 + librosa (muvid[scoring] core tier)")
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("MUVID_SCORING_ENABLE_LIPSYNC", "0")
    from muvid.footage.align import align_footage
    from muvid.footage.scoring.grid import ScoreTrack, load_tensor
    from muvid.footage.scoring.orchestrator import score_project
    from muvid.footage.workspace import FootageWorkspace

    def run(ctx):
        n = ctx.grid["n"]
        raw = np.linspace(0, 1, n, dtype="float32")
        raw[: n // 2] = np.nan  # not measurable in the first half: masked, not 0.0
        mask = np.isfinite(raw)
        return [
            ScoreTrack(
                ctx.clip_id,
                "ramp",
                ctx.grid["t0"],
                ctx.grid["hop_s"],
                raw,
                mask,
                "higher_better",
            )
        ]

    R.register_scorer(R.Scorer("ramp", ("ramp",), run, needs_frames=False))
    song_p, song = _song(tmp_path)
    ca = _clip(tmp_path, song, "A", a=0.0, b=5.0)
    proj = FootageWorkspace.for_email("u@x.com").create_project("p")
    proj.set_song(str(song_p), ext="wav")
    proj.add_clip("A", str(ca), ext="mp4")
    proj.save_alignments(
        align_footage(
            str(proj.song_path()),
            list(proj.clip_paths().items()),
            song_duration=proj.song_duration(),
        )
    )
    out = score_project(proj, metrics=["ramp"])
    assert out["metrics"] == ["ramp"]
    tensor = load_tensor(proj.root)
    mi = tensor.metric_index("ramp")
    assert tensor.M[0, : tensor.n // 2, mi].sum() == 0  # masked stays masked
    assert tensor.M[0, tensor.n // 2 + 1 :, mi].all()
