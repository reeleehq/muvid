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
        n = ctx.grid["n"]
        raw = np.ones(n, dtype="float32")
        return [
            ScoreTrack(
                ctx.clip_id,
                "beats_seen",
                ctx.grid["t0"],
                ctx.grid["hop_s"],
                raw,
                np.isfinite(raw),
                "higher_better",
            )
        ]

    before = dict(R._SCORERS)
    R.register_scorer(
        R.Scorer("beats_seen", ("beats_seen",), run, needs_frames=False, gated=False)
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
