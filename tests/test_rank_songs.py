"""Choose the best-matching song from several (muvid#135): the footage cut to each
candidate by the planner — nothing rendered — and ranked on the plan's own terms."""

from __future__ import annotations

import numpy as np
import pytest

from muvid.footage.music_cut import (
    SONG_FIT_WEIGHTS,
    Envelope,
    FreeSource,
    song_fit,
    song_fit_sentence,
)
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


def _hits_envelope(period_s, *, n=300, hop=0.1):
    """A picture that changes every ``period_s`` seconds."""
    hits = np.zeros(n)
    hits[:: max(1, int(round(period_s / hop)))] = 1.0
    return Envelope(hop_s=hop, activity=np.full(n, 0.5), hits=hits)


# -- the score --------------------------------------------------------------------------


def test_repetition_is_footage_time_not_cut_count():
    """The #135 review: counting cuts per picture made the slowest song always win.
    A 40 s song from 120 s of footage repeats nothing at ANY tempo; a 400 s one must
    show the footage over three times."""
    slow = song_fit("/x/a.wav", _pool(), analysis=_analysis(40.0, 60.0), **_KW)
    fast = song_fit("/x/b.wav", _pool(), analysis=_analysis(40.0, 180.0), **_KW)
    long = song_fit("/x/c.wav", _pool(), analysis=_analysis(400.0, 120.0), **_KW)
    assert slow["times_over"] == fast["times_over"] < 1.0
    assert slow["score"] == fast["score"]  # tempo alone decides nothing here
    assert long["times_over"] > 3.0 and long["score"] < slow["score"]
    assert "shown about" in song_fit_sentence("Long", long)
    assert "no footage twice" in song_fit_sentence("Slow", slow)


def test_unmeasured_pictures_are_not_off_the_beat():
    fit = song_fit("/x/a.wav", _pool(), analysis=_analysis(40.0, 120.0), **_KW)
    assert fit["on_beat"] is None  # no envelope measured: no claim either way
    assert "beat" not in song_fit_sentence("A", fit)


def test_pictures_that_change_on_the_beat_raise_the_score():
    """Videos changing every 0.5 s fit a 120 bpm song (a beat every 0.5 s) better
    than an 87 bpm one, where the same changes fall between its beats."""
    kw = dict(_KW, envelope_of=lambda s: _hits_envelope(0.5))
    on = song_fit("/x/a.wav", _pool(), analysis=_analysis(40.0, 120.0), **kw)
    off = song_fit("/x/b.wav", _pool(), analysis=_analysis(40.0, 87.0), **kw)
    assert on["on_beat"] > off["on_beat"] and on["score"] > off["score"]


def test_the_feel_of_the_footage_counts_toward_the_fit():
    """Calm and lively videos fit a song with a quiet and a loud half; flip the halves
    and the same footage fits worse."""
    from dataclasses import replace

    srcs = [FreeSource(f"calm{i}", f"/x/c{i}.mp4", duration_s=30.0) for i in range(7)]
    srcs += [FreeSource(f"live{i}", f"/x/l{i}.mp4", duration_s=30.0) for i in range(7)]

    def env(s):
        level = 0.05 if s.clip_id.startswith("calm") else 1.0
        return Envelope(hop_s=0.1, activity=np.full(300, level), hits=np.zeros(300))

    kw = dict(_KW, envelope_of=env, archetype="beat_cut")
    shaped = _analysis(40.0, 120.0)
    fit = song_fit("/x/a.wav", srcs, analysis=shaped, **kw)
    assert fit["affect_fit"] >= 0.9
    assert "lively videos land in its loud parts" in song_fit_sentence("A", fit)
    flat = replace(
        shaped, sections=tuple(replace(s, energy_db=None) for s in shaped.sections)
    )
    assert song_fit("/x/b.wav", srcs, analysis=flat, **kw)["affect_fit"] is None
    assert fit["score"] > song_fit("/x/b.wav", srcs, analysis=flat, **kw)["score"]


def test_the_reuse_term_charges_repetition():
    fit = song_fit("/x/a.wav", _pool(), analysis=_analysis(400.0, 120.0), **_KW)
    free = dict(SONG_FIT_WEIGHTS, reuse=0.0)
    other = song_fit(
        "/x/a.wav", _pool(), analysis=_analysis(400.0, 120.0), weights=free, **_KW
    )
    assert other["score"] > fit["score"]  # repetition was charged


# -- the operations --------------------------------------------------------------------


#: The song files the stubbed beat estimator was asked about, in order.
MEASURED: list = []


@pytest.fixture
def fp(tmp_path, monkeypatch):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data"))
    proj = FootageWorkspace.for_email("u@x.com").create_project("p")
    song = tmp_path / "Ours.wav"
    song.write_bytes(b"RIFF-ours")
    service.set_song(proj, path=str(song), duration_s=40.0, filename="Ours.wav")
    for cid in ("A", "B"):
        clip = tmp_path / f"{cid}.mp4"
        clip.write_bytes(cid.encode())
        service.add_clip(proj, path=str(clip), clip_id=cid, duration_s=30.0)
    monkeypatch.setattr(service, "_probe_duration", lambda p: 400.0)
    monkeypatch.setattr(service, "_activity_envelope", lambda fp_, s: None)
    MEASURED.clear()
    measured = MEASURED

    def estimate(path):  # the beat estimator, by file: the song 40 s, others 400 s
        measured.append(path)
        return _analysis(40.0 if path.endswith("song.wav") else 400.0, 120.0)

    import muvid.footage.music_cut as music_cut

    monkeypatch.setattr(music_cut, "_default_analysis", estimate)
    return proj


def _candidate(fp, tmp_path, name, payload, **kw):
    f = tmp_path / name
    f.write_bytes(payload)
    return service.add_song_candidate(fp, path=str(f), filename=name, **kw)


def test_candidates_are_stored_listed_and_removed_without_paths(fp, tmp_path):
    out = _candidate(fp, tmp_path, "Long Song (final).mp3", b"ID3-long")
    assert out["candidate_id"] == "Long_Song_final"
    (row,) = out["candidates"]
    assert row["name"] == "Long Song (final).mp3" and "file" not in row
    path = fp.song_candidate_path("Long_Song_final")
    assert path.read_bytes() == b"ID3-long"
    service.remove_song_candidate(fp, candidate_id="Long_Song_final")
    assert fp.song_candidates() == [] and not path.exists()


def test_status_lists_the_candidates_without_paths(fp, tmp_path):
    """A screen lists the songs to choose from off ``status`` (reelee-web#593)."""
    assert service.status(fp)["song_candidates"] == []
    _candidate(fp, tmp_path, "Other Song.mp3", b"ID3-other")
    (row,) = service.status(fp)["song_candidates"]
    assert row["candidate_id"] == "Other_Song" and row["name"] == "Other Song.mp3"
    assert "file" not in row


def test_a_default_id_is_made_unique_and_an_explicit_duplicate_refused(fp, tmp_path):
    """The #135 review: "a_b.mp3" silently replaced "a b.mp3"; non-Latin names all
    became one id."""
    first = _candidate(fp, tmp_path, "a b.mp3", b"ID3-1")["candidate_id"]
    second = _candidate(fp, tmp_path, "a_b.mp3", b"ID3-2")["candidate_id"]
    third = _candidate(fp, tmp_path, "情歌.mp3", b"ID3-3")["candidate_id"]
    assert (first, second, third) == ("a_b", "a_b_2", "song")
    assert fp.song_candidate_path("a_b").read_bytes() == b"ID3-1"
    with pytest.raises(FootageError, match="already exists"):
        _candidate(fp, tmp_path, "x.mp3", b"ID3-4", candidate_id="a_b")


@pytest.mark.parametrize("bad", ["../x", "*", ""])
def test_a_malformed_candidate_id_is_a_refusal_not_a_crash(fp, bad):
    for op in (service.remove_song_candidate, service.use_song_candidate):
        with pytest.raises(FootageError):
            op(fp, candidate_id=bad)


def test_rank_songs_ranks_every_candidate_and_the_project_song(fp, tmp_path):
    _candidate(fp, tmp_path, "long.mp3", b"ID3-long")
    out = service.rank_songs(fp)
    names = [r["name"] for r in out["ranking"]]
    assert names == ["Ours.wav", "long.mp3"] and out["best"] is None  # ours fits best
    assert all(r["sentence"].startswith(r["name"] + ":") for r in out["ranking"])
    n_measured = len(MEASURED)
    service.rank_songs(fp)
    assert len(MEASURED) == n_measured  # analyses are kept, not measured again


def test_the_project_song_is_ranked_once_and_on_its_declared_grid(
    fp, tmp_path, monkeypatch
):
    """The #135 review: after choosing a candidate it was ranked twice; and the
    ranking ignored a declared beat grid "Cut it for me" cuts on."""
    _candidate(fp, tmp_path, "long.mp3", b"ID3-long")
    _candidate(fp, tmp_path, "again.wav", b"RIFF-ours")  # the project's song, again
    seen = []
    real = service.song_analysis
    monkeypatch.setattr(service, "song_analysis", lambda f: seen.append(1) or real(f))
    out = service.rank_songs(fp)
    assert [r["candidate_id"] for r in out["ranking"]].count(None) == 1
    assert "again" not in [r["candidate_id"] for r in out["ranking"]]
    assert seen  # the project's song went through song_analysis (its declared grid)


def test_rank_songs_needs_two_songs(fp):
    with pytest.raises(FootageError, match="nothing to choose between"):
        service.rank_songs(fp)


def test_use_song_candidate_makes_it_the_song(fp, tmp_path):
    _candidate(fp, tmp_path, "long.mp3", b"ID3-long")
    out = service.use_song_candidate(fp, candidate_id="long")
    assert out["song"]["name"] == "long.mp3"
    assert fp.song_path().read_bytes() == b"ID3-long"
    assert [c["candidate_id"] for c in fp.song_candidates()] == ["long"]  # still one
    with pytest.raises(FootageError, match="no song candidate"):
        service.use_song_candidate(fp, candidate_id="nope")


def test_the_candidate_ops_are_host_only_and_set_song_is_unchanged():
    import inspect

    from muvid.mcp._footage_ops import FOOTAGE_TOOLS

    for op in (
        "add_song_candidate",
        "remove_song_candidate",
        "use_song_candidate",
        "rank_songs",
    ):
        assert f"footage_{op}" not in FOOTAGE_TOOLS
    import muvid.genre  # noqa: F401

    assert nw.genre_op("music_video", "rank_songs").effect == "read"
    add = nw.genre_op("music_video", "add_song_candidate")
    assert add.host_params == ("path", "filename")
    # the studio's "Set the song" still needs an upload
    assert inspect.signature(service.set_song).parameters["path"].default is (
        inspect.Parameter.empty
    )


def test_each_candidate_gets_its_own_analysis(fp, tmp_path):
    """Analyses are cached by each file's content hash — never one shared entry."""
    _candidate(fp, tmp_path, "long.mp3", b"ID3-long")
    _candidate(fp, tmp_path, "song.wav", b"RIFF-other")  # 40 s by the stub's rule
    out = service.rank_songs(fp)
    by_id = {r["candidate_id"]: r["duration_s"] for r in out["ranking"]}
    assert by_id["long"] == 400.0 and by_id["song"] == 40.0
