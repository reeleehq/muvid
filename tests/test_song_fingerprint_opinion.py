"""The song-fingerprint second opinion beside the vote (muvid#251).

``mixing.audio.fingerprint.contains_song`` asks a different question from the windowed
vote ("is the song in this clip at all?", by landmark hashes), calibrated on the
muvid#59 shoot. It may only REFUSE: an "absent" verdict refuses an offset the vote
vouched for; "contains", "undecided" and "not measured" change nothing (whether a
"contains" may rescue is muvid#330, the user's decision).
"""

from __future__ import annotations

import numpy as np
import pytest

from muvid.footage import align as A
from muvid.footage.edl import (
    SONG_ABSENT,
    SONG_THRESHOLDS,
    FootageAlignment,
    vouches_for,
)

VOUCHED = dict(confidence=0.9, support=0.9, margin=0.5, window_s=6.0)


@pytest.mark.parametrize("verdict", ["contains", "undecided", None])
def test_only_absent_changes_the_verdict(verdict):
    assert vouches_for(**VOUCHED, song_verdict=verdict) is True


def test_absent_refuses_an_offset_the_vote_vouched_for():
    assert vouches_for(**VOUCHED, song_verdict=SONG_ABSENT) is False


def test_it_never_rescues():
    refused = dict(confidence=0.9, support=0.3, margin=0.5, window_s=6.0)
    assert vouches_for(**refused, song_verdict="contains") is False


def _alignment(**kw):
    base = dict(
        clip_id="A", offset_s=1.0, confidence=0.9, duration_s=10.0, coverage=(1.0, 11.0)
    )
    return FootageAlignment(**{**base, **kw})


def test_a_record_without_a_song_match_is_byte_identical():
    assert "song_match" not in _alignment().to_dict()


def test_the_song_match_round_trips():
    record = {"votes": 3, "ratio": 1.0, "query_hashes": 9000, "verdict": "absent"}
    again = FootageAlignment.from_dict(_alignment(song_match=record).to_dict())
    assert again.song_match == record


# -- through the aligner, with a stand-in vote -------------------------------------


class _Vote:
    """A ``mixing.audio.ClipAlignment``-shaped vote that vouches."""

    def __init__(self, index):
        self.index = index
        self.offset_s, self.confidence, self.duration_s = 1.0, 0.9, 10.0
        self.coverage, self.overlaps = (1.0, 11.0), True
        self.support, self.margin, self.window_s, self.hop_s = 0.9, 0.5, 6.0, 3.0


@pytest.fixture
def vouching_vote(monkeypatch):
    mixing_audio = pytest.importorskip("mixing.audio")
    monkeypatch.setattr(
        mixing_audio,
        "align_clips_to_reference",
        lambda song, clips, **kw: [_Vote(i) for i in range(len(clips))],
    )


def test_an_absent_song_refuses_the_clip(vouching_vote, monkeypatch):
    monkeypatch.setattr(A, "judge_song_match", lambda m: SONG_ABSENT)
    (a,) = A.align_footage(
        "song.wav",
        [("A", "a.mp4")],
        song_duration=60.0,
        song_matcher=lambda song: lambda clip: {"votes": 3},
    )
    assert a.reliable is False and a.song_match == {"votes": 3}


def test_no_matcher_means_no_opinion(vouching_vote):
    (a,) = A.align_footage(
        "song.wav", [("A", "a.mp4")], song_duration=60.0, song_matcher=None
    )
    assert a.reliable is True and a.song_match is None


# -- the real fingerprint, end to end on synthetic music -----------------------------

SR = 22050


def _music(seed, seconds, notes):
    rng = np.random.default_rng(seed)
    n = SR // 4
    pitches = rng.choice(notes, size=int(seconds * 4))
    y = np.concatenate([np.sin(2 * np.pi * f * np.arange(n) / SR) for f in pitches])
    return (0.5 * y + 0.05 * rng.standard_normal(len(y))).astype(np.float32)


def test_the_real_fingerprint_calls_another_song_absent_and_the_song_contained():
    import mixing.audio.fingerprint as fp  # core dependency: never skipped

    from muvid.footage.edl import judge_song_match

    song = _music(1, 120, [220, 247, 262, 294, 330, 349, 392, 440])
    index = fp.landmarks(song, sr=SR)
    bars = fp.SongThresholds(**SONG_THRESHOLDS)
    other = _music(3, 60, [523, 587, 659, 698, 784, 880, 988])
    absent = fp.contains_song(other, index, sr=SR, thresholds=bars).to_dict()
    present = fp.contains_song(song[SR * 30 : SR * 90], index, sr=SR, thresholds=bars)
    assert judge_song_match(absent) == SONG_ABSENT
    assert judge_song_match(present.to_dict()) == "contains"


def _wav(path, y):
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def test_the_default_matcher_judges_live_under_muvids_bars(tmp_path):
    """The probes that can veto an "absent" run only under the bars a call was made
    with, so the default matcher must call with muvid's — its record says which."""
    import mixing.audio.fingerprint as fp  # core dependency: never skipped

    from muvid.footage.edl import judge_song_match

    song = _wav(
        tmp_path / "song.wav", _music(1, 120, [220, 247, 262, 294, 330, 349, 392, 440])
    )
    other = _wav(
        tmp_path / "other.wav", _music(3, 60, [523, 587, 659, 698, 784, 880, 988])
    )
    record = A.fingerprint_matcher(str(song))(str(other))
    assert record["thresholds"] == SONG_THRESHOLDS
    assert judge_song_match(record) == SONG_ABSENT


def test_the_installed_mixing_has_the_rate_the_bars_use():
    """The canary (no skip): muvid's floor must reach the field SONG_THRESHOLDS uses,
    or align fails for every clip with a TypeError (the #251 review)."""
    from dataclasses import fields

    from mixing.audio.fingerprint import SongThresholds

    assert "max_absent_vote_rate" in {f.name for f in fields(SongThresholds)}
    SongThresholds(**SONG_THRESHOLDS)  # the bars construct


def test_an_absent_song_makes_the_clip_b_roll_and_says_why(monkeypatch):
    """The #251 review: a fingerprint refusal must be explained to the caller, and a
    clip the song is absent from is cut to the music, not a synced clip that failed."""
    from muvid.footage import edl, service

    monkeypatch.setattr(
        edl, "song_opinion", lambda m: None if m is None else ("absent", "K=3 on 9000")
    )
    monkeypatch.setattr(
        edl, "judge_song_match", lambda m: None if m is None else "absent"
    )
    a = _alignment(
        support=0.9, margin=0.5, window_s=6.0, hop_s=3.0, song_match={"k": 1}
    )
    assert service.heard_the_song(a) is False
    row = service._alignment_row(a)
    assert row["song_verdict"] == "absent" and "K=3" in row["song_reason"]
    assert "song_verdict" not in service._alignment_row(
        _alignment()
    )  # omit-when-absent
