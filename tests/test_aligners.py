"""Pluggable aligner registry + user-provided aligner."""

from __future__ import annotations

import pytest

from muvid.align import (
    AlignmentResult,
    align_lyrics,
    aligner_info,
    list_aligners,
    register_aligner,
)
from muvid.lyrics import parse_lyrics_md


SAMPLE_MD = """[verse]
hello hello hello
goodbye goodbye goodbye
"""


def test_default_aligner_is_scribe_greedy():
    transcript = {
        "words": [
            {"text": "hello", "start": 0.5, "end": 1.0, "type": "word"},
            {"text": "hello", "start": 1.0, "end": 1.5, "type": "word"},
            {"text": "hello", "start": 1.5, "end": 2.0, "type": "word"},
            {"text": "goodbye", "start": 6.0, "end": 6.5, "type": "word"},
            {"text": "goodbye", "start": 6.5, "end": 7.0, "type": "word"},
            {"text": "goodbye", "start": 7.0, "end": 7.5, "type": "word"},
        ]
    }
    result = align_lyrics(parse_lyrics_md(SAMPLE_MD), transcript, duration_s=10.0)
    assert isinstance(result, AlignmentResult)
    assert result.lines[0].start_s == pytest.approx(0.5)


def test_list_aligners_includes_builtins():
    names = list_aligners()
    assert "scribe-greedy" in names
    assert "user" in names
    assert "whisperx-lite" in names
    assert "stars" in names


def test_aligner_info_has_description():
    info = aligner_info("scribe-greedy")
    assert info.description
    assert info.fn is not None


def test_unknown_aligner_raises():
    with pytest.raises(KeyError):
        align_lyrics(parse_lyrics_md(SAMPLE_MD), {"words": []}, aligner="nope")


def test_user_aligner_uses_supplied_line_timings():
    timings = [
        {"line_index": 0, "start_s": 1.5, "end_s": 3.0},
        {"line_index": 1, "start_s": 5.0, "end_s": 7.5},
    ]
    result = align_lyrics(
        parse_lyrics_md(SAMPLE_MD),
        {},
        aligner="user",
        user_line_timings=timings,
    )
    assert result.lines[0].start_s == pytest.approx(1.5)
    assert result.lines[0].end_s == pytest.approx(3.0)
    assert result.lines[1].start_s == pytest.approx(5.0)
    assert result.lines[1].end_s == pytest.approx(7.5)
    # The user aligner doesn't produce per-word alignments.
    assert result.lines[0].word_alignments == ()


def test_user_aligner_falls_back_to_anchors_in_lyrics_md():
    md = "[v]\nfirst line  // 2.0\nsecond line  // 4.0\n"
    result = align_lyrics(parse_lyrics_md(md), {}, aligner="user", duration_s=8.0)
    assert result.lines[0].start_s == pytest.approx(2.0)
    assert result.lines[1].start_s == pytest.approx(4.0)


def test_stars_aligner_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        align_lyrics(parse_lyrics_md(SAMPLE_MD), {}, aligner="stars")


def test_register_aligner_round_trips():
    """Custom aligners can be registered + dispatched."""

    def _trivial(lyrics, transcript, *, duration_s=0.0):
        # Returns empty alignment.
        return AlignmentResult(sections=())

    register_aligner("test-trivial", _trivial, description="for tests")
    assert "test-trivial" in list_aligners()
    result = align_lyrics(parse_lyrics_md(SAMPLE_MD), {}, aligner="test-trivial")
    assert isinstance(result, AlignmentResult)
    assert result.sections == ()


def test_whisperx_lite_falls_back_to_transcript_when_no_audio_path():
    """Without an audio_path, whisperx-lite degrades to scribe-greedy."""
    transcript = {
        "words": [
            {"text": "hello", "start": 0.5, "end": 1.0, "type": "word"},
            {"text": "hello", "start": 1.0, "end": 1.5, "type": "word"},
            {"text": "hello", "start": 1.5, "end": 2.0, "type": "word"},
            {"text": "goodbye", "start": 6.0, "end": 6.5, "type": "word"},
            {"text": "goodbye", "start": 6.5, "end": 7.0, "type": "word"},
            {"text": "goodbye", "start": 7.0, "end": 7.5, "type": "word"},
        ]
    }
    # Skip the requires=("faster_whisper",) check by calling the function
    # directly — when audio_path is None, faster_whisper isn't actually used.
    from muvid.align import align_whisperx_lite

    result = align_whisperx_lite(
        parse_lyrics_md(SAMPLE_MD), transcript, duration_s=10.0
    )
    assert result.lines[0].start_s == pytest.approx(0.5)


# --- muvid#101: matches the song has no time for are dropped -------------------


def _la_song(n_words, *, per_line=10):
    md = "[verse]\n" + "\n".join(
        " ".join(["la"] * per_line) for _ in range(n_words // per_line)
    )
    return parse_lyrics_md(md + "\n")


def _transcript(times):
    return {
        "words": [
            {"text": "la", "start": t, "end": t + 0.05, "type": "word"} for t in times
        ]
    }


def _measured(result):
    return [w for la in result.lines for w in la.word_alignments]


def test_the_issues_failure_comes_back_unmeasured_not_wrong():
    """muvid#101's shape: 100 repeated words sung from the start of a 30 s song, the
    transcript garbage (nothing) until 25 s. The walk pins line 0 at 25 s and every
    later line after it — all wrong, all reading as measured. No word it matched
    leaves a singable rest (99 words in 5 s), so none is kept: everything reads as
    not measured, the honest answer."""
    lyrics = _la_song(100)
    late = _transcript([25.0 + 0.2 * i for i in range(25)])
    assert _measured(align_lyrics(lyrics, late, duration_s=30.0, max_words_per_s=None))
    assert _measured(align_lyrics(lyrics, late, duration_s=30.0)) == []


def test_an_ordinary_song_is_untouched():
    lyrics = _la_song(60)
    sung = _transcript([1.0 + i / 3 for i in range(60)])  # 3 words a second
    bounded = align_lyrics(lyrics, sung, duration_s=25.0)
    assert bounded == align_lyrics(lyrics, sung, duration_s=25.0, max_words_per_s=None)
    assert len(_measured(bounded)) == 60


def test_an_excerpt_loses_late_anchors_but_no_anchor_moves():
    """The #101 review: refusing inside the walk re-matched later tokens onto early
    words (34 newly wrong on an excerpt). Dropped after the walk, a match is only ever
    removed: what is kept is exactly what the unbounded walk found."""
    lyrics = _la_song(100)
    first_20s = _transcript([i / 3 for i in range(60)])  # the audio holds 60 words
    free = _measured(
        align_lyrics(lyrics, first_20s, duration_s=20.0, max_words_per_s=None)
    )
    kept = _measured(align_lyrics(lyrics, first_20s, duration_s=20.0))
    assert kept and len(kept) < len(free)
    assert all(k in free for k in kept)


def test_the_bound_is_inclusive_and_the_last_word_always_fits():
    from muvid.align import WordAlignment, drop_infeasible_matches

    def at(t, tok=0):
        return WordAlignment(
            line_index=0, token_index=tok, text="la", start_s=t, end_s=t
        )

    kw = dict(duration_s=10.0, max_words_per_s=8.0)
    # 40 words after, 5 s left: exactly 8 a second — kept
    assert drop_infeasible_matches({0: [at(5.0)]}, words_after={(0, 0): 40}, **kw)
    assert not drop_infeasible_matches({0: [at(5.01)]}, words_after={(0, 0): 40}, **kw)
    # at or past the end with words left: dropped; the LAST word: kept
    assert not drop_infeasible_matches({0: [at(10.0)]}, words_after={(0, 0): 1}, **kw)
    assert drop_infeasible_matches({0: [at(10.5)]}, words_after={(0, 0): 0}, **kw)
    with pytest.raises(ValueError, match="positive"):
        drop_infeasible_matches({}, words_after={}, duration_s=1.0, max_words_per_s=0)


def test_words_after_counts_the_lyric_after_each_token():
    from muvid.align import _words_after

    assert _words_after([(0, 0, "a"), (0, 1, ""), (0, 2, "b"), (1, 0, "c")]) == {
        (0, 0): 2,
        (0, 2): 1,
        (1, 0): 0,
    }


@pytest.mark.parametrize("raw", ["-1", "0", "nan", "inf", "abc"])
def test_a_bad_rate_in_the_env_is_refused(raw, monkeypatch):
    from muvid.align import _words_per_s_from_env

    monkeypatch.setenv("X_RATE", raw)
    with pytest.raises(ValueError, match="X_RATE"):
        _words_per_s_from_env("X_RATE", 8.0)
    monkeypatch.setenv("X_RATE", "12")
    assert _words_per_s_from_env("X_RATE", 8.0) == 12.0
    monkeypatch.delenv("X_RATE")
    assert _words_per_s_from_env("X_RATE", 8.0) == 8.0


def test_whisperx_lite_forwards_the_bound():
    from muvid.align import align_whisperx_lite

    lyrics = _la_song(100)
    late = _transcript([25.0 + 0.2 * i for i in range(25)])
    assert _measured(align_whisperx_lite(lyrics, late, duration_s=30.0)) == []
    assert _measured(
        align_whisperx_lite(lyrics, late, duration_s=30.0, max_words_per_s=None)
    )
