"""Choose the best-matching song from several (muvid#135): the footage cut to each
candidate by the planner — nothing rendered — and ranked on the plan's own terms."""

from __future__ import annotations

import numpy as np
import pytest

from muvid.footage.music_cut import Envelope, FreeSource, song_fit, song_fit_sentence
from tests.test_music_cut import _analysis

nw = pytest.importorskip("nw")

from muvid.footage import service  # noqa: E402
from muvid.footage.errors import FootageError  # noqa: E402
from muvid.footage.workspace import FootageWorkspace  # noqa: E402


def _pool(n=4, seconds=30.0):
    return [FreeSource(f"v{i}", f"/x/v{i}.mp4", duration_s=seconds) for i in range(n)]


_KW = dict(
    envelope_of=lambda s: None,
    anchor_of=lambda s: (0.5, 0.5),
    size_of=lambda p: (1920, 1080),
)


def test_a_song_the_pool_fills_without_repeating_beats_one_it_must_repeat_for():
    """Four 30 s videos: a 40 s song needs each shown about once; a 400 s one needs
    each shown many times — repetition is what the reuse term charges."""
    short = song_fit("/x/s.wav", _pool(), analysis=_analysis(40.0, 120.0), **_KW)
    long = song_fit("/x/l.wav", _pool(), analysis=_analysis(400.0, 120.0), **_KW)
    assert short["shows_per_picture"] < long["shows_per_picture"]
    assert short["score"] > long["score"]
    assert "shown" in song_fit_sentence("Long", long)


def test_the_feel_of_the_footage_counts_toward_the_fit():
    """Calm and lively videos fit a song with a quiet and a loud half better than a
    song whose sections are all as loud (affect does not apply there)."""
    srcs = [FreeSource(f"calm{i}", f"/x/c{i}.mp4", duration_s=30.0) for i in range(7)]
    srcs += [FreeSource(f"live{i}", f"/x/l{i}.mp4", duration_s=30.0) for i in range(7)]

    def env(s):
        level = 0.05 if s.clip_id.startswith("calm") else 1.0
        return Envelope(hop_s=0.1, activity=np.full(300, level), hits=np.zeros(300))

    kw = dict(_KW, envelope_of=env, archetype="beat_cut")
    shaped = song_fit("/x/a.wav", srcs, analysis=_analysis(40.0, 120.0), **kw)
    assert shaped["affect_fit"] is not None and shaped["affect_fit"] >= 0.9
    assert "lively videos land in its loud parts" in song_fit_sentence("A", shaped)


# -- the operations --------------------------------------------------------------------


@pytest.fixture
def fp(tmp_path, monkeypatch):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data"))
    proj = FootageWorkspace.for_email("u@x.com").create_project("p")
    song = tmp_path / "song.wav"
    song.write_bytes(b"RIFF-song")
    service.set_song(proj, path=str(song), duration_s=40.0, filename="Ours.wav")
    for cid in ("A", "B"):
        clip = tmp_path / f"{cid}.mp4"
        clip.write_bytes(cid.encode())
        service.add_clip(proj, path=str(clip), clip_id=cid, duration_s=30.0)
    monkeypatch.setattr(service, "_probe_duration", lambda p: 400.0)
    return proj


def _candidate(fp, tmp_path, name, payload):
    f = tmp_path / name
    f.write_bytes(payload)
    return service.add_song_candidate(fp, path=str(f), filename=name)


def test_candidates_are_stored_listed_and_removed_without_paths(fp, tmp_path):
    out = _candidate(fp, tmp_path, "Long Song (final).mp3", b"ID3-long")
    assert out["candidate_id"] == "Long_Song_final"
    (row,) = out["candidates"]
    assert row["name"] == "Long Song (final).mp3" and "file" not in row
    assert fp.song_candidate_path("Long_Song_final").read_bytes() == b"ID3-long"
    with pytest.raises(FootageError, match="no song candidate"):
        service.remove_song_candidate(fp, candidate_id="nope")
    assert (
        service.remove_song_candidate(fp, candidate_id="Long_Song_final")["candidates"]
        == []
    )


def test_rank_songs_ranks_every_candidate_and_the_project_song(
    fp, tmp_path, monkeypatch
):
    _candidate(fp, tmp_path, "long.mp3", b"ID3-long")
    durations = {"Ours.wav": 40.0, "long.mp3": 400.0}

    def analysis_of(fp_, path):
        name = "Ours.wav" if path == fp.song_path() else "long.mp3"
        return _analysis(durations[name], 120.0)

    monkeypatch.setattr(service, "_analysis_of", analysis_of)
    monkeypatch.setattr(service, "_activity_envelope", lambda fp_, s: None)
    out = service.rank_songs(fp)
    names = [r["name"] for r in out["ranking"]]
    assert names == ["Ours.wav", "long.mp3"] and out["best"] is None  # ours fits best
    assert all(r["sentence"].startswith(r["name"] + ":") for r in out["ranking"])


def test_rank_songs_needs_two_songs(fp):
    with pytest.raises(FootageError, match="nothing to choose between"):
        service.rank_songs(fp)


def test_set_song_takes_a_candidate(fp, tmp_path):
    _candidate(fp, tmp_path, "long.mp3", b"ID3-long")
    out = service.set_song(fp, candidate_id="long")
    assert out["song"]["name"] == "long.mp3"
    assert fp.song_path().read_bytes() == b"ID3-long"
    with pytest.raises(FootageError, match="not both"):
        service.set_song(fp, candidate_id="long", path="/x/y.wav")
    with pytest.raises(FootageError, match="no song candidate"):
        service.set_song(fp, candidate_id="nope")


def test_the_candidate_ops_are_host_only():
    from muvid.mcp._footage_ops import FOOTAGE_TOOLS

    for op in ("add_song_candidate", "remove_song_candidate", "rank_songs"):
        assert f"footage_{op}" not in FOOTAGE_TOOLS
    import muvid.genre  # noqa: F401

    assert nw.genre_op("music_video", "rank_songs").effect == "read"
    add = nw.genre_op("music_video", "add_song_candidate")
    assert add.host_params == ("path", "filename")
