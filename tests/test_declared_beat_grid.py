"""A beat grid a person DECLARES beats the estimate and survives a re-estimate (muvid#123).

Que Calor's librosa grid is 129.2 BPM and the fitted one 126.905, so bar numbers and beat
snapping drift over 2.5 minutes. ``set_beat_grid`` mirrors ``set_offset``: recorded as
``declared``, returned by ``beat_grid``, never replaced by an estimate, forgotten only by
``clear_beat_grid``. No ffmpeg, no librosa: the estimator is faked.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from muvid.footage import service
from muvid.footage.errors import FootageError

SONG_DURATION = 30.0


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(
        "muvid.footage.workspace._probe_duration", lambda p: SONG_DURATION
    )
    from muvid.footage.workspace import FootageWorkspace

    p = FootageWorkspace.for_email("u@x.com").create_project("p")
    song = tmp_path / "song.wav"
    song.write_bytes(b"RIFF-one")
    p.set_song(str(song), ext="wav")
    return p


def _estimator(monkeypatch, tempo=129.2):
    calls = []

    def fake(audio, **kw):
        calls.append(audio)
        return SimpleNamespace(
            tempo_bpm=tempo,
            beat_times=[0.5 * k for k in range(60)],
            downbeat_times=[],
            onset_env=None,
            onset_hop_s=None,
        )

    monkeypatch.setattr("mixing.audio.beat_grid", fake, raising=False)
    return calls


def test_a_declared_tempo_makes_a_steady_grid_with_bars(proj):
    out = service.set_beat_grid(proj, tempo_bpm=120.0, first_beat_s=0.5)
    assert out["source"] == "declared" and out["tempo_bpm"] == 120.0
    out = {k: v for k, v in out.items() if k != "changed"}
    assert out["beats"][:3] == [0.5, 1.0, 1.5] and out["beats"][-1] <= SONG_DURATION
    assert out["downbeats"][:2] == [0.5, 2.5] and out["downbeats_source"] == "declared"
    assert out["bar_of_beat"][:5] == [1, 1, 1, 1, 2]
    assert service.beat_grid(proj) == out


def test_explicit_beats_a_pickup_and_the_bar_length(proj):
    out = service.set_beat_grid(
        proj, beats=[1.0, 2.0, 3.0, 4.0, 5.0], beats_per_bar=3, first_bar_beat=1
    )
    assert out["downbeats"] == [2.0, 5.0]
    assert out["bar_of_beat"] == [0, 1, 1, 1, 2]  # beat 0 is a pickup, bar 0
    assert out["tempo_bpm"] is None  # too few beats to fit one, and none declared


def test_it_is_returned_instead_of_the_estimate_and_never_replaced(proj, monkeypatch):
    calls = _estimator(monkeypatch)
    service.set_beat_grid(proj, tempo_bpm=126.905, first_beat_s=0.0)
    again = service.beat_grid(proj)
    assert again["source"] == "declared" and again["tempo_bpm"] == 126.905
    assert calls == []  # the estimator was never asked


def test_clearing_returns_to_the_estimate(proj, monkeypatch):
    calls = _estimator(monkeypatch)
    service.set_beat_grid(proj, tempo_bpm=126.905)
    assert service.clear_beat_grid(proj) == {"cleared": True}
    assert service.beat_grid(proj)["source"] == "computed" and len(calls) == 1
    with pytest.raises(FootageError, match="nothing to forget"):
        service.clear_beat_grid(proj)


def test_a_grid_declared_for_another_song_does_not_apply(proj, tmp_path):
    service.set_beat_grid(proj, tempo_bpm=120.0)
    other = tmp_path / "other.wav"
    other.write_bytes(b"RIFF-two")
    proj.set_song(str(other), ext="wav")
    assert service.declared_beat_grid(proj) is None


@pytest.mark.parametrize(
    "kw, match",
    [
        ({}, "either tempo_bpm"),
        ({"tempo_bpm": 120.0, "beats": [1.0, 2.0]}, "either tempo_bpm"),
        ({"tempo_bpm": 5.0}, "tempo_bpm must be"),
        ({"tempo_bpm": float("nan")}, "finite"),
        ({"tempo_bpm": "fast"}, "must be a number"),
        ({"tempo_bpm": 120.0, "first_beat_s": SONG_DURATION}, "inside the song"),
        ({"tempo_bpm": 120.0, "beats_per_bar": 0}, "beats_per_bar"),
        ({"tempo_bpm": 120.0, "first_bar_beat": 4}, "first_bar_beat"),
        ({"beats": [1.0]}, "needs 2..100000"),
        ({"beats": [2.0, 1.0]}, "ascending"),
        ({"beats": [1.0, 99.0]}, "inside the song"),
    ],
)
def test_bad_grids_are_refused(proj, kw, match):
    with pytest.raises(FootageError, match=match):
        service.set_beat_grid(proj, **kw)
    assert service.declared_beat_grid(proj) is None


def test_declaring_the_same_grid_twice_does_not_rewrite_it(proj):
    assert service.set_beat_grid(proj, tempo_bpm=120.0)["changed"] is True
    first = service.declared_beat_grid(proj)["declared_at"]
    assert service.set_beat_grid(proj, tempo_bpm=120.0)["changed"] is False
    assert service.declared_beat_grid(proj)["declared_at"] == first
    assert service.set_beat_grid(proj, tempo_bpm=121.0)["changed"] is True


@pytest.mark.parametrize(
    "kw, match",
    [
        ({"beats": "12"}, "must be a list"),
        ({"beats": {"1": 2}}, "must be a list"),
        ({"beats": [True, 2.0]}, "must be a number"),
        ({"beats": [1.0, 2.0], "first_beat_s": 0.5}, "goes with tempo_bpm"),
        ({"tempo_bpm": True}, "must be a number"),
        ({"tempo_bpm": "120"}, "must be a number"),
        ({"tempo_bpm": 120.0, "first_beat_s": True}, "must be a number"),
        ({"tempo_bpm": 120.0, "beats_per_bar": True}, "whole number"),
        ({"tempo_bpm": 20.0, "first_beat_s": SONG_DURATION - 0.01}, "needs 2"),
        ({"beats": [1.00001, 1.00002, 2.0]}, "ascending"),  # rounds to a duplicate
    ],
)
def test_loose_types_and_rounding_duplicates_are_refused(proj, kw, match):
    with pytest.raises(FootageError, match=match):
        service.set_beat_grid(proj, **kw)


def test_an_unreadable_record_is_an_absent_grid(proj):
    import json

    service.set_beat_grid(proj, tempo_bpm=120.0)
    path = proj.root / service._DECLARED_BEAT_GRID_NAME
    record = json.loads(path.read_text())
    for broken in ({**record, "beat_times": "x"}, {**record, "beats_per_bar": 0}, []):
        path.write_text(json.dumps(broken))
        assert service.declared_beat_grid(proj) is None
    assert service.clear_beat_grid(proj) == {
        "cleared": True
    }  # still on file: forgettable


def test_the_planner_and_explain_see_the_declared_beats_and_the_estimate_returns(
    proj, monkeypatch
):
    from dataclasses import replace

    from muvid.montage.analysis import Analysis

    est = Analysis(duration=30.0, tempo_bpm=129.2, beats=(0.1, 0.5), downbeats=(0.1,))
    monkeypatch.setattr(service, "_measured_song_analysis", lambda fp: est)
    assert service.song_analysis(proj) == est
    service.set_beat_grid(proj, tempo_bpm=120.0, first_beat_s=0.5, beats_per_bar=3)
    a = service.song_analysis(proj)
    assert a.beats[:3] == (0.5, 1.0, 1.5) and a.downbeats[:2] == (0.5, 2.0)
    assert a.beats_per_bar == 3 and a.tempo_bpm == 120.0 and a.beat_source == "declared"
    service.clear_beat_grid(proj)
    assert service.song_analysis(proj) == est


def test_weighted_selection_snaps_to_the_declared_grid(proj):
    service.set_beat_grid(proj, tempo_bpm=120.0, first_beat_s=0.5)
    ctx = service._selection_context(proj, "weighted", "", None, None)
    assert ctx.beat_times[:3] == [0.5, 1.0, 1.5] and ctx.downbeat_times[:2] == [
        0.5,
        2.5,
    ]


def test_the_catalogue_lists_both_ops_and_the_tools_follow():
    names = {o.name: o for o in service.FOOTAGE_OP_SPECS}
    assert names["set_beat_grid"].effect == "write"
    assert names["clear_beat_grid"].effect == "destroy"


def test_the_importer_declares_it_idempotently(proj):
    from muvid.importing import ImportRefused, _import_beat_grid

    spec = {"tempo_bpm": 126.905, "first_beat_s": 0.0, "beats_per_bar": 4}
    assert _import_beat_grid(proj, spec) == "declared"
    assert _import_beat_grid(proj, spec) == "unchanged"
    with pytest.raises(ImportRefused, match="unknown key"):
        _import_beat_grid(proj, {"bpm": 120})
    with pytest.raises(ImportRefused, match="tempo_bpm must be"):
        _import_beat_grid(proj, {"tempo_bpm": 1.0})


def test_the_connector_beat_grid_keeps_a_declared_grids_bars(proj, monkeypatch):
    pytest.importorskip("fastmcp")
    import muvid.mcp.footage_tools as ft

    service.set_beat_grid(proj, tempo_bpm=120.0, first_beat_s=0.0)
    monkeypatch.setattr(ft, "_call", lambda pid, fn: fn(proj))
    out = ft.beat_grid("p")
    assert out["source"] == "declared" and out["downbeats"][:2] == [0.0, 2.0]
    assert out["beats_per_bar"] == 4 and out["bar_of_beat"][:5] == [1, 1, 1, 1, 2]


# -- scoring reads the declared grid (muvid#187) --------------------------------------


@pytest.fixture
def scored_proj(proj, tmp_path, monkeypatch):
    """``proj`` with one clip at a declared offset, an estimator that returns a real
    ``BeatGrid`` (beats every 0.5 s, an onset envelope), and ONE registered scorer that
    records the beats it was handed. No frames, no ffmpeg, no librosa."""
    import numpy as np
    from mixing.audio.beats import BeatGrid

    from muvid.footage.scoring import registry as R

    clip = tmp_path / "A.mp4"
    clip.write_bytes(b"clip-a")
    service.add_clip(proj, path=str(clip), clip_id="A", duration_s=SONG_DURATION)
    service.set_offset(proj, clip_id="A", offset_s=0.0)
    estimate = BeatGrid(
        beat_times=np.arange(0.0, SONG_DURATION, 0.5),
        downbeat_times=np.array([]),
        onset_env=np.ones(10),
        onset_hop_s=0.1,
        sample_rate=22050,
        tempo_bpm=120.0,
    )
    monkeypatch.setattr("mixing.audio.beat_grid", lambda audio, **kw: estimate)
    monkeypatch.setattr(
        "muvid.footage.scoring.segment.shot_boundaries", lambda p, **kw: []
    )
    seen = []

    def run(ctx):
        from muvid.footage.scoring.grid import ScoreTrack

        seen.append((list(ctx.beat.beat_times), ctx.beat.onset_env))
        n = ctx.grid.n
        raw = np.ones(n, dtype="float32")
        return [
            ScoreTrack(
                ctx.clip_id,
                "beats_seen",
                ctx.grid.t0,
                ctx.grid.hop_s,
                raw,
                np.isfinite(raw),
                "higher_better",
            )
        ]

    before = dict(R._SCORERS)
    R.register_scorer(
        R.Scorer(
            "beats_seen",
            ("beats_seen",),
            run,
            needs_frames=False,
            gated=False,
            # it reads the beat grid, so a grid change stales it
            inputs={"beats_seen": (R.BEATS,)},
        )
    )
    yield proj, seen, estimate
    R._SCORERS.clear()
    R._SCORERS.update(before)


def test_scoring_measures_on_the_declared_grid_and_keeps_the_onset_envelope(
    scored_proj,
):
    proj, seen, estimate = scored_proj
    out = service.run_scoring(proj, metrics=["beats_seen"])
    assert out["status"] == "ok" and out["clips_scored"] == ["A"], out
    assert seen[-1][0] == list(estimate.beat_times)  # no declaration: the estimate
    assert service.scores(proj)["beats"]["source"] == "estimated"

    service.set_beat_grid(proj, tempo_bpm=100.0, first_beat_s=0.3)
    declared = service.declared_beat_grid(proj)["beat_times"]
    with pytest.raises(FootageError, match="beat grid changed"):
        service.scores(proj)  # measured on the estimate: stale now

    service.run_scoring(proj, metrics=["beats_seen"])
    beats, onset_env = seen[-1]
    assert beats == declared and onset_env is estimate.onset_env
    out = service.scores(proj)
    assert out["beats"]["source"] == "declared" and out["tempo_bpm"] == 100.0


def test_clearing_the_grid_makes_declared_scores_stale_and_never_leaks_its_beats(
    scored_proj,
):
    proj, _seen, estimate = scored_proj
    service.set_beat_grid(proj, tempo_bpm=100.0, first_beat_s=0.3)
    service.run_scoring(proj, metrics=["beats_seen"])
    service.clear_beat_grid(proj)
    with pytest.raises(FootageError, match="stale"):
        service.scores(proj)
    # the manifest's beats were a person's grid: not served back as the estimate
    assert service.beat_grid(proj)["beats"] == [
        round(float(t), 4) for t in estimate.beat_times
    ]


def test_every_reader_of_the_scores_sees_a_grid_change_as_stale(scored_proj):
    """The #187 review: a beat grid change deletes nothing, so each reader of the tensor
    must ask whether it is current — the weighted selector and the editor document as
    well as ``scores``. And set/clear say when they left the scores stale."""
    proj, _seen, _estimate = scored_proj
    service.run_scoring(proj, metrics=["beats_seen"])
    ctx = lambda: service._selection_context(proj, "weighted", None, None, None)  # noqa: E731
    assert ctx().tensor is not None

    out = service.set_beat_grid(proj, tempo_bpm=100.0, first_beat_s=0.3)
    assert out["scores_stale"] is True
    assert ctx().tensor is None  # measured on the estimate: not used to cut
    service.run_scoring(proj, metrics=["beats_seen"])
    assert ctx().tensor is not None
    assert "scores_stale" not in service.set_beat_grid(
        proj, tempo_bpm=100.0, first_beat_s=0.3, beats_per_bar=3
    )  # renumbering the bars moves no beat: the scores stay current

    assert service.clear_beat_grid(proj)["scores_stale"] is True
    pytest.importorskip("lacing")
    doc = service.editor_document(proj)
    assert any("stale" in w for w in doc.get("warnings", []))
    assert "clip-score-track" not in json.dumps(doc)


def test_a_grid_change_stales_only_the_beat_metrics_and_rescoring_redoes_only_them(
    scored_proj,
):
    """muvid#206: declaring a grid keeps the quality-like metrics usable — served,
    and used by the weighted selector — names the beat metric stale (masked, never a
    low score), and a default re-score recomputes only it."""
    import numpy as np

    from muvid.footage.scoring import registry as R
    from muvid.footage.scoring.grid import ScoreTrack, load_tensor

    proj, _seen, _ = scored_proj
    calls = {"q": 0, "b": 0}

    def track(ctx, metric, value):
        raw = np.full(ctx.grid.n, value, dtype="float32")
        return ScoreTrack(
            ctx.clip_id, metric, ctx.grid.t0, ctx.grid.hop_s, raw, np.isfinite(raw)
        )

    def q(ctx):
        calls["q"] += 1
        return [track(ctx, "q_m", 0.7)]

    def b(ctx):
        calls["b"] += 1
        return [track(ctx, "b_m", float(len(ctx.beat.beat_times)))]

    R._SCORERS.clear()
    R.register_scorer(R.Scorer("q", ("q_m",), q, needs_frames=False, gated=False))
    R.register_scorer(
        R.Scorer(
            "b",
            ("b_m",),
            b,
            needs_frames=False,
            gated=False,
            inputs={"b_m": (R.BEATS,)},
        )
    )
    service.run_scoring(proj)
    before = load_tensor(proj.root)

    service.set_beat_grid(proj, tempo_bpm=100.0, first_beat_s=0.3)
    out = service.scores(proj, clip_id="A")
    assert out["stale_metrics"] == ["b_m"]
    assert service.scores(proj)["stale_metrics"] == ["b_m"]
    ctx = service._selection_context(proj, "weighted", None, None, None)
    t = ctx.tensor
    assert t is not None and t.M[0, :, t.metric_index("q_m")].all()
    assert not t.M[0, :, t.metric_index("b_m")].any()  # masked, not zero

    calls.update(q=0, b=0)
    rescore = service.run_scoring(proj)
    assert rescore["rescored"] == ["b_m"] and calls == {"q": 0, "b": 1}
    after = load_tensor(proj.root)
    assert "stale_metrics" not in service.scores(proj)
    qi, bi = after.metric_index("q_m"), after.metric_index("b_m")
    assert np.array_equal(
        after.raw[0, :, qi], before.raw[0, :, before.metric_index("q_m")]
    )
    declared = len(service.declared_beat_grid(proj)["beat_times"])
    assert float(after.raw[0, 0, bi]) == declared  # measured on the declared grid


def _two_scorers(calls, *, b_available=True):
    """`q` reads no beat grid, `b` does; both count their runs."""
    import numpy as np

    from muvid.footage.scoring import registry as R
    from muvid.footage.scoring.grid import ScoreTrack

    def track(ctx, metric, value):
        raw = np.full(ctx.grid.n, value, dtype="float32")
        return ScoreTrack(
            ctx.clip_id, metric, ctx.grid.t0, ctx.grid.hop_s, raw, np.isfinite(raw)
        )

    def q(ctx):
        calls["q"] += 1
        return [track(ctx, "q_m", 0.7)]

    def b(ctx):
        calls["b"] += 1
        return [track(ctx, "b_m", 1.0)]

    R._SCORERS.clear()
    R.register_scorer(R.Scorer("q", ("q_m",), q, needs_frames=False, gated=False))
    R.register_scorer(
        R.Scorer(
            "b",
            ("b_m",),
            b,
            needs_frames=False,
            gated=False,
            inputs={"b_m": (R.BEATS,)},
            available=None if b_available else (lambda: (False, "no weights")),
        )
    )


def test_kept_tracks_read_under_another_offset_are_never_kept(scored_proj):
    """The #206 review's race: tracks read for keeping, then an offset moved before the
    job took the scoring lock. The run must score in full, not save old-offset tracks
    under the new alignment."""
    from dataclasses import replace

    from muvid.footage.scoring.orchestrator import score_project

    proj, _seen, _ = scored_proj
    calls = {"q": 0, "b": 0}
    _two_scorers(calls)
    service.run_scoring(proj)
    service.set_beat_grid(proj, tempo_bpm=100.0, first_beat_s=0.3)
    keep = service._kept_scores(proj, hop_s=service.DEFAULT_SCORE_HOP_S)
    assert keep is not None and keep.recompute == ("b_m",)
    calls.update(q=0, b=0)
    out = score_project(
        proj,
        beat_source=service._master_beats,
        keep=replace(keep, align_fingerprint="old"),
    )
    assert calls == {"q": 1, "b": 1} and set(out["metrics"]) == {"q_m", "b_m"}


def test_a_clip_with_no_kept_tracks_is_scored_in_full(
    scored_proj, tmp_path, monkeypatch
):
    """The #206 review: a clip skipped last run has no tracks to keep, so a partial
    re-score would give it only the stale metrics — it is scored in full instead."""
    from dataclasses import replace

    import muvid.footage.scoring.grid as G

    proj, _seen, _ = scored_proj
    calls = {"q": 0, "b": 0}
    _two_scorers(calls)
    clip = tmp_path / "B.mp4"
    clip.write_bytes(b"clip-b")
    service.add_clip(proj, path=str(clip), clip_id="B", duration_s=SONG_DURATION)
    service.set_offset(proj, clip_id="B", offset_s=0.0)
    service.run_scoring(proj)
    service.set_beat_grid(proj, tempo_bpm=100.0, first_beat_s=0.3)
    assert service._kept_scores(proj, hop_s=service.DEFAULT_SCORE_HOP_S) is not None
    tensor = G.load_tensor(proj.root)
    only_a = replace(
        tensor, clip_ids=["A"], S=tensor.S[:1], M=tensor.M[:1], raw=tensor.raw[:1]
    )
    monkeypatch.setattr(G, "load_tensor", lambda root: only_a)  # B skipped last time
    assert service._kept_scores(proj, hop_s=service.DEFAULT_SCORE_HOP_S) is None


def test_an_implicit_partial_re_score_skips_an_unavailable_scorer(scored_proj):
    proj, _seen, _ = scored_proj
    calls = {"q": 0, "b": 0}
    _two_scorers(calls)
    service.run_scoring(proj)
    service.set_beat_grid(proj, tempo_bpm=100.0, first_beat_s=0.3)
    _two_scorers(calls, b_available=False)
    out = service.run_scoring(proj)  # not refused: nobody named b_m
    assert out["skipped_scorers"] == {"b": "no weights"}


def test_the_weighted_cut_says_which_stale_metrics_it_left_out(scored_proj):
    from muvid.footage.select_score import selection_notice

    proj, _seen, _ = scored_proj
    calls = {"q": 0, "b": 0}
    _two_scorers(calls)
    service.run_scoring(proj)
    service.set_beat_grid(proj, tempo_bpm=100.0, first_beat_s=0.3)
    weights = {"q_m": 1.0, "b_m": 1.0}  # the cut would have used b_m
    ctx = service._selection_context(proj, "weighted", None, weights, None)
    assert tuple(ctx.stale_metrics) == ("b_m",)
    notice = selection_notice(ctx)
    assert notice["stale_metrics"] == ["b_m"] and "b_m" in notice["message"]


def test_the_motion_beat_scorer_declares_only_its_beat_metric():
    from muvid.footage.scoring import registry as R

    assert R._SCORERS["motion_beat"].reads(R.BEATS) == ["motion_beat_bas"]
    with pytest.raises(ValueError, match="unknown input"):
        R.Scorer("x", ("x_m",), lambda c: [], inputs={"x_m": ("tempo",)})
    with pytest.raises(ValueError, match="does not produce"):
        R.Scorer("x", ("x_m",), lambda c: [], inputs={"y_m": (R.BEATS,)})


def test_kept_scores_name_what_their_tracks_were_measured_under(scored_proj):
    """The #206 re-review: the key comes from the MANIFEST the kept tracks were loaded
    with, so an offset moving after they were read is seen under the scoring lock."""
    from muvid.footage.scoring.orchestrator import score_project

    proj, _seen, _ = scored_proj
    calls = {"q": 0, "b": 0}
    _two_scorers(calls)
    service.run_scoring(proj)
    service.set_beat_grid(proj, tempo_bpm=100.0, first_beat_s=0.3)
    keep = service._kept_scores(proj, hop_s=service.DEFAULT_SCORE_HOP_S)
    service.set_offset(proj, clip_id="A", offset_s=2.0)  # moves after the read
    calls.update(q=0, b=0)
    out = score_project(proj, beat_source=service._master_beats, keep=keep)
    assert calls == {"q": 1, "b": 1} and "rescored" not in out


def test_a_stale_metric_nobody_weighs_is_not_warned_about(scored_proj):
    proj, _seen, _ = scored_proj
    calls = {"q": 0, "b": 0}
    _two_scorers(calls)
    service.run_scoring(proj)
    service.set_beat_grid(proj, tempo_bpm=100.0, first_beat_s=0.3)
    weighed = service._selection_context(proj, "weighted", None, {"b_m": 1.0}, None)
    unweighed = service._selection_context(proj, "weighted", None, {"q_m": 1.0}, None)
    assert tuple(weighed.stale_metrics) == ("b_m",) and unweighed.stale_metrics == ()


def test_the_old_tuple_shape_of_inputs_is_refused_plainly():
    from muvid.footage.scoring import registry as R

    with pytest.raises(TypeError, match="maps each metric"):
        R.Scorer("x", ("x_m",), lambda c: [], inputs=(R.BEATS,))


def test_a_rescore_of_stale_metrics_that_read_no_frames_skips_the_decode(
    scored_proj, monkeypatch
):
    """muvid#213 item 2: the decode pass is the expensive one, and it runs only when a
    scorer that RUNS needs frames — so a partial re-score whose stale metrics read no
    frames decodes nothing, though a current metric beside them does read frames."""
    import numpy as np

    from muvid.footage.scoring import frames as F
    from muvid.footage.scoring import quality
    from muvid.footage.scoring import registry as R
    from muvid.footage.scoring.grid import ScoreTrack

    decodes = []
    monkeypatch.setattr(
        F, "sample_clip_frames", lambda path, **kw: decodes.append(path) or object()
    )
    monkeypatch.setattr(F, "make_face_scorer", lambda: None)
    monkeypatch.setattr(quality, "quality_gate_mask", lambda fp, **kw: np.array([True]))

    def track(ctx, metric):
        raw = np.full(ctx.grid.n, 0.5, dtype="float32")
        return [
            ScoreTrack(
                ctx.clip_id, metric, ctx.grid.t0, ctx.grid.hop_s, raw, np.isfinite(raw)
            )
        ]

    proj, _seen, _ = scored_proj
    R._SCORERS.clear()
    R.register_scorer(R.Scorer("q", ("q_m",), lambda c: track(c, "q_m"), gated=False))
    R.register_scorer(
        R.Scorer(
            "b",
            ("b_m",),
            lambda c: track(c, "b_m"),
            needs_frames=False,
            gated=False,
            inputs={"b_m": (R.BEATS,)},
        )
    )
    service.run_scoring(proj)
    assert len(decodes) == 1  # q reads frames: the full run decodes

    service.set_beat_grid(proj, tempo_bpm=100.0, first_beat_s=0.3)
    decodes.clear()
    out = service.run_scoring(proj)
    assert out["rescored"] == ["b_m"]
    assert decodes == []  # only b re-ran, and it reads no frames


def test_a_partial_rescore_keeps_the_inputs_of_the_metrics_it_kept(
    scored_proj, monkeypatch
):
    """The #213 review: the record of which metrics read which input was built from the
    scorers that RAN, so a partial re-score dropped a kept metric's input — and once
    that input changed, the metric measured on its old value was served as current."""
    import numpy as np

    from muvid.footage.scoring import registry as R
    from muvid.footage.scoring.grid import ScoreTrack, load_manifest

    monkeypatch.setattr(R, "INPUTS", (R.BEATS, "sections"))
    sections = {"fp": ""}
    rows = service._keyed_inputs
    # since muvid#224 a second input is ONE row, read by the run and the readers alike
    monkeypatch.setattr(
        service,
        "_keyed_inputs",
        lambda: {
            **rows(),
            "sections": R.KeyedInput(
                read=lambda fp: (None, sections["fp"]),
                fingerprint=lambda fp: sections["fp"],
            ),
        },
    )

    def track(ctx, metric):
        raw = np.full(ctx.grid.n, 0.5, dtype="float32")
        return [
            ScoreTrack(
                ctx.clip_id, metric, ctx.grid.t0, ctx.grid.hop_s, raw, np.isfinite(raw)
            )
        ]

    proj, _seen, _ = scored_proj
    R._SCORERS.clear()
    frameless = dict(needs_frames=False, gated=False)
    R.register_scorer(R.Scorer("q", ("q_m",), lambda c: track(c, "q_m"), **frameless))
    for name, inp in (("b", R.BEATS), ("s", "sections")):
        R.register_scorer(
            R.Scorer(
                name,
                (f"{name}_m",),
                lambda c, m=f"{name}_m": track(c, m),
                inputs={f"{name}_m": (inp,)},
                **frameless,
            )
        )
    service.run_scoring(proj)
    service.set_beat_grid(proj, tempo_bpm=100.0, first_beat_s=0.3)
    assert service.run_scoring(proj)["rescored"] == ["b_m"]  # s_m kept
    assert load_manifest(proj.root)["input_metrics"] == {
        R.BEATS: ["b_m"],
        "sections": ["s_m"],
    }
    sections["fp"] = "map1"  # a section map is declared
    assert service.scores(proj)["stale_metrics"] == ["s_m"]


def test_every_keyed_input_has_a_provider_in_the_service():
    """muvid#224: a keyed input with no provider used to be read as its default by the
    staleness question, silently. The service's one table must cover them all."""
    from muvid.footage.scoring import registry as R

    assert set(service._keyed_inputs()) == set(R.INPUTS)


def test_a_run_refuses_an_input_with_no_provider_or_an_unknown_one(
    scored_proj, monkeypatch
):
    from muvid.footage.scoring import registry as R
    from muvid.footage.scoring.orchestrator import _read_inputs

    proj, _seen, _ = scored_proj
    monkeypatch.setattr(R, "INPUTS", (R.BEATS, "sections"))
    with pytest.raises(ValueError, match="no provider.*sections"):
        _read_inputs(proj, None)

    def bogus(fp):
        return None, ""

    with pytest.raises(ValueError, match="unknown keyed input.*typo"):
        _read_inputs(proj, {"sections": bogus, "typo": bogus})


def _with_sections(monkeypatch, R, *, read_fp, now_fp):
    """A second keyed input, ``sections``, whose ``read`` reports ``read_fp`` and whose
    cheap ``fingerprint`` reports ``now_fp`` — callables, so a test can move them."""
    monkeypatch.setattr(R, "INPUTS", (R.BEATS, "sections"))
    rows = service._keyed_inputs
    monkeypatch.setattr(
        service,
        "_keyed_inputs",
        lambda: {
            **rows(),
            "sections": R.KeyedInput(
                read=lambda fp: (None, read_fp()), fingerprint=lambda fp: now_fp()
            ),
        },
    )


def _frameless(R, name, metric, inputs=()):
    import numpy as np

    from muvid.footage.scoring.grid import ScoreTrack

    def run(ctx):
        raw = np.full(ctx.grid.n, 0.5, dtype="float32")
        return [
            ScoreTrack(
                ctx.clip_id, metric, ctx.grid.t0, ctx.grid.hop_s, raw, np.isfinite(raw)
            )
        ]

    return R.Scorer(
        name,
        (metric,),
        run,
        needs_frames=False,
        gated=False,
        inputs={metric: tuple(inputs)} if inputs else {},
    )


def test_the_run_records_the_fingerprint_it_read_with_the_value(
    scored_proj, monkeypatch
):
    """The value and its key come from ONE read (the #187 race, for every input): the
    manifest records what ``read`` returned, never a second look — here the cheap
    ``fingerprint`` disagrees on purpose (the #224 review's mutation passed before)."""
    from muvid.footage.scoring import registry as R
    from muvid.footage.scoring.grid import load_manifest

    proj, _seen, _ = scored_proj
    _with_sections(monkeypatch, R, read_fp=lambda: "READ", now_fp=lambda: "WRONG")
    service.run_scoring(proj)
    assert load_manifest(proj.root)["input_fingerprints"]["sections"] == "READ"


def test_a_kept_metric_whose_input_moved_while_waiting_is_measured_again(
    scored_proj, monkeypatch
):
    """The #224 review: a partial re-score re-checked only the song and the offsets, so
    an input changing between choosing the kept tracks and reading the inputs left a
    kept metric measured on its old value — served as current."""
    from muvid.footage.scoring import registry as R
    from muvid.footage.scoring.grid import load_manifest

    proj, _seen, _ = scored_proj
    current = {"read": "m1", "now": "m1"}
    _with_sections(
        monkeypatch, R, read_fp=lambda: current["read"], now_fp=lambda: current["now"]
    )
    R._SCORERS.clear()
    R.register_scorer(_frameless(R, "b", "b_m", (R.BEATS,)))
    R.register_scorer(_frameless(R, "s", "s_m", ("sections",)))
    service.run_scoring(proj)
    service.set_beat_grid(proj, tempo_bpm=100.0, first_beat_s=0.3)  # b_m stale
    current["read"] = "m2"  # the section map moves AFTER the kept tracks are chosen
    out = service.run_scoring(proj)
    assert "rescored" not in out  # scored in full: s_m was not kept
    assert load_manifest(proj.root)["input_fingerprints"]["sections"] == "m2"


def test_naming_the_beat_provider_twice_is_refused(scored_proj):
    from muvid.footage.scoring import registry as R
    from muvid.footage.scoring import score_project

    proj, _seen, _ = scored_proj
    with pytest.raises(ValueError, match="once"):
        score_project(
            proj,
            inputs={R.BEATS: lambda p: (None, "")},
            beat_source=service._master_beats,
        )


def test_a_shot_detector_failure_is_recorded_per_clip_and_keeps_the_tracks(
    scored_proj, monkeypatch
):
    """muvid#220: shot detection now raises out of mixing; the orchestrator must not
    throw away every clip's tracks for a by-product only ``beats+shots`` reads."""
    proj, _seen, _ = scored_proj

    def broken(path, **kw):
        raise OSError("Video file not found.")

    monkeypatch.setattr("muvid.footage.scoring.segment.shot_boundaries", broken)
    out = service.run_scoring(proj, metrics=["beats_seen"])
    assert out["shots_skipped"] == {"A": "shot detection failed: Video file not found."}
    assert "beats_seen" in out["metrics"]
