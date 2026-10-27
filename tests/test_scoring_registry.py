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
        n = ctx.grid.n
        raw = np.linspace(0, 1, n, dtype="float32")
        raw[: n // 2] = np.nan  # not measurable in the first half: masked, not 0.0
        mask = np.isfinite(raw)
        return [
            ScoreTrack(
                ctx.clip_id,
                "ramp",
                ctx.grid.t0,
                ctx.grid.hop_s,
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


# -- generic availability and shared artifacts (muvid#184) ----------------------------

from tests.test_declared_beat_grid import proj, scored_proj  # noqa: E402,F401


def _only(*scorers):
    R._SCORERS.clear()
    for sc in scorers:
        R.register_scorer(sc)


def _track(ctx):
    import numpy as np

    from muvid.footage.scoring.grid import ScoreTrack

    raw = np.ones(ctx.grid.n, dtype="float32")
    return lambda metric: ScoreTrack(
        ctx.clip_id, metric, ctx.grid.t0, ctx.grid.hop_s, raw, np.isfinite(raw)
    )


def test_an_unavailable_scorer_is_skipped_with_its_reason_or_refused_if_asked(
    scored_proj, clean_registry
):
    """``Scorer.available`` is enforced by the orchestrator, for any scorer — no longer a
    lip-sync special case — and an explicitly requested metric is refused, not empty."""
    from muvid.footage import service

    proj, _seen, _ = scored_proj

    def never(ctx):
        raise AssertionError("an unavailable scorer ran")

    _only(
        R.Scorer(
            "ok",
            ("ok_m",),
            lambda c: [_track(c)("ok_m")],
            needs_frames=False,
            gated=False,
        ),
        R.Scorer(
            "never",
            ("never_m",),
            never,
            needs_frames=False,
            gated=False,
            available=lambda: (False, "no weights on this machine"),
        ),
    )
    out = service.run_scoring(proj)
    assert out["metrics"] == ["ok_m"]
    assert out["skipped_scorers"] == {"never": "no weights on this machine"}
    with pytest.raises(ValueError, match="never_m.*no weights on this machine"):
        service.run_scoring(proj, metrics=["never_m"])


def test_a_shared_artifact_is_built_once_and_only_when_a_running_scorer_needs_it(
    scored_proj, clean_registry, monkeypatch
):
    from muvid.footage import service

    proj, _seen, _ = scored_proj
    built, seen = [], []
    monkeypatch.setitem(
        R._ARTIFACTS,
        "drum_stem",
        R.Artifact(
            "drum_stem",
            lambda song, d: built.append(song) or "/stems/drums.wav",
            stage="drums",
        ),
    )

    def needs_drums(ctx):
        seen.append(ctx.artifacts.get("drum_stem"))
        return [_track(ctx)("drum_m")]

    _only(
        R.Scorer(
            "drums",
            ("drum_m",),
            needs_drums,
            needs_frames=False,
            gated=False,
            needs=("drum_stem",),
        ),
        R.Scorer(
            "plain",
            ("plain_m",),
            lambda c: [_track(c)("plain_m")],
            needs_frames=False,
            gated=False,
        ),
    )
    events = []
    service.run_scoring(proj, metrics=["plain_m"])
    assert built == []  # nobody running needed it
    service.run_scoring(proj, progress_cb=events.append)
    assert len(built) == 1 and seen == ["/stems/drums.wav"]
    assert "drums" in [e.get("current_transform") for e in events]


def test_a_scorer_sees_only_the_artifacts_it_declared(
    scored_proj, clean_registry, monkeypatch
):
    """The #184 review: one shared ``artifacts`` map let a scorer come to rely on
    another's ``needs``."""
    from muvid.footage import service

    proj, _seen, _ = scored_proj
    monkeypatch.setitem(
        R._ARTIFACTS,
        "drum_stem",
        R.Artifact("drum_stem", lambda s, d: "/d.wav", "drums"),
    )
    seen = {}

    def run(name):
        def _run(ctx):
            seen[name] = dict(ctx.artifacts)
            return [_track(ctx)(f"{name}_m")]

        return _run

    _only(
        R.Scorer(
            "a",
            ("a_m",),
            run("a"),
            needs_frames=False,
            gated=False,
            needs=("drum_stem",),
        ),
        R.Scorer("b", ("b_m",), run("b"), needs_frames=False, gated=False),
    )
    out = service.run_scoring(proj)
    assert seen == {"a": {"drum_stem": "/d.wav"}, "b": {}}
    assert "skipped_scorers" not in out  # omit-when-absent: nothing was skipped


def test_an_unregistered_need_is_refused_before_any_work(
    scored_proj, clean_registry, monkeypatch
):
    from muvid.footage import service

    proj, _seen, _ = scored_proj
    estimated = []
    monkeypatch.setattr(
        "muvid.footage.service._master_beats", lambda fp: estimated.append(1)
    )
    _only(
        R.Scorer(
            "t",
            ("t_m",),
            lambda c: [],
            needs_frames=False,
            gated=False,
            needs=("typo_stem",),
        )
    )
    with pytest.raises(ValueError, match="no artifact 'typo_stem'"):
        service.run_scoring(proj)
    assert estimated == []  # the beat grid was never computed


def test_a_plugin_whose_check_cannot_import_is_a_recorded_reason(
    scored_proj, clean_registry
):
    from muvid.footage import service
    from muvid.footage.scoring.orchestrator import list_available_extractors

    proj, _seen, _ = scored_proj

    def broken():
        raise ImportError("No module named 'fancylib'")

    _only(
        R.Scorer(
            "ok",
            ("ok_m",),
            lambda c: [_track(c)("ok_m")],
            needs_frames=False,
            gated=False,
        ),
        R.Scorer(
            "fancy",
            ("f_m",),
            lambda c: [],
            needs_frames=False,
            gated=False,
            available=broken,
        ),
    )
    assert "fancylib" in service.run_scoring(proj)["skipped_scorers"]["fancy"]
    info = list_available_extractors()["scorers"]
    assert info["ok"]["available"] is True and "reason" not in info["ok"]
    assert info["fancy"]["available"] is False and "fancylib" in info["fancy"]["reason"]
