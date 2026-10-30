"""Music features for cutting to the music (muvid#133): ranked beats, structure, Beat This!."""

import pytest

from muvid.montage import analysis as an


def test_cut_rank_is_an_onset_percentile_with_a_downbeat_bonus():
    assert an.cut_rank([0, 0.5, 1, 1.5], [1, 3, 2, 0.5], []) == (0.333, 1.0, 0.667, 0.0)
    boosted = an.cut_rank([0, 0.5, 1, 1.5], [1, 3, 2, 0.5], [1.5])
    assert boosted[3] == pytest.approx(an.DOWNBEAT_RANK_BONUS)
    assert an.cut_rank([], [], []) == ()
    assert an.cut_rank([0, 1], [1], []) == ()  # unmeasured: no invented ranks


def test_ranked_beats_keeps_the_strongest_in_time_order_and_falls_back_unmeasured():
    a = an.Analysis(
        duration=2.0, tempo_bpm=120.0, beats=(0.0, 0.5, 1.0, 1.5), downbeats=(0.0,),
        cut_rank=(0.2, 1.0, 0.1, 0.7),
    )
    assert a.ranked_beats(0.5) == (0.5, 1.5)
    assert a.ranked_beats(1) == a.beats
    bare = an.Analysis(duration=2.0, tempo_bpm=120.0, beats=(0.0, 0.5), downbeats=(0.0,))
    assert bare.ranked_beats(0.5) == bare.beats
    with pytest.raises(ValueError):
        a.ranked_beats(0)


def test_cut_rank_round_trips_through_the_dict():
    a = an.Analysis(
        duration=2.0, tempo_bpm=120.0, beats=(0.0, 0.5), downbeats=(0.0,), cut_rank=(0.0, 1.0)
    )
    assert an.Analysis.from_dict(a.to_dict()) == a
    assert "cut_rank" not in an.Analysis(duration=1, tempo_bpm=120, beats=(), downbeats=()).to_dict()


def test_unknown_section_source_is_refused_before_any_audio_is_read(tmp_path):
    f = tmp_path / "a.wav"
    f.write_bytes(b"")
    with pytest.raises(ValueError, match="section_source"):
        an.analyze(f, section_source="vibes")


def test_structural_labels_name_the_loud_repeat_a_chorus(monkeypatch, tmp_path):
    import mixing.audio as ma

    class S:
        def __init__(self, start, end, label):
            self.start, self.end, self.label = start, end, label

    found = [S(0, 8, "A"), S(8, 16, "B"), S(16, 24, "A"), S(24, 32, "B"), S(32, 40, "C")]
    monkeypatch.setattr(ma, "structural_sections", lambda *a, **k: found, raising=False)
    bars = [(i * 8.0, (i + 1) * 8.0) for i in range(5)]
    energy = [-30.0, -10.0, -30.0, -10.0, -40.0]
    secs = an.structural_sections(tmp_path / "x.wav", [], bars, energy, 40.0)
    assert [s.label for s in secs] == ["verse", "chorus", "verse", "chorus", "outro"]
    assert secs[1].energy_db == pytest.approx(-10.0)


def test_beat_this_source_is_registered_and_carries_downbeats(monkeypatch, tmp_path):
    import numpy as np
    import mixing.audio as ma
    from types import SimpleNamespace

    grid = SimpleNamespace(
        beat_times=np.arange(0.0, 8.0, 0.5), downbeat_times=np.arange(0.0, 8.0, 2.0),
        tempo_bpm=120.0, onset_env=np.ones(100), onset_hop_s=0.08,
    )
    seen = {}
    monkeypatch.setattr(ma, "beat_grid", lambda p, **k: seen.update(k) or grid)
    assert "beat_this" in an.BEAT_SOURCES
    *_, name, _note, down = an.beat_grid(tmp_path / "a.wav", source="beat_this", duration=8.0, with_downbeats=True)
    assert seen == {"backend": "beat_this"} and "beat_this" in name
    assert down == (0.0, 2.0, 4.0, 6.0)
