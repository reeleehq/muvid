"""A dropped lyrics layout is reported in the render's meta (muvid#165).

Indented lyrics are parsed flat, and the Python ``ShapedLyricsWarning`` is
invisible to an MCP caller. ``RenderResult.meta["lyrics_layout_ignored"]`` says
so instead, and only when it applies: a live caller renders from this path
daily, so every other render's meta must stay as it was and the rendered output
must not depend on the indentation.
"""

from __future__ import annotations

import pytest

from muvid.lyricvid import pipeline
from muvid.lyricvid.timed_text import from_words
from muvid.lyrics import layout_dropped
from muvid.subgenres import RenderRequest, RenderResult

FLAT = "[v]\none two\nthree four\n"
SHAPED = "[v]\none two\n    three four\n"


def _render(tmp_path, monkeypatch, lyrics_text, *, extra_inputs=None, params=None):
    scenes = []

    def backend(scene, *, audio, output, workdir):
        scenes.append(scene)
        output.write_bytes(b"")
        return RenderResult(output=output)

    timed = from_words(
        [("one", 0.0, 0.5), ("two", 0.5, 1.0), ("three", 1.0, 1.5), ("four", 1.5, 2.0)],
        duration=2.0,
    )
    monkeypatch.setattr(pipeline, "select_renderer", lambda name: "fake")
    monkeypatch.setattr(pipeline, "resolve_renderer", lambda name: backend)
    monkeypatch.setattr(pipeline, "build_timed_text", lambda **kw: timed)
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"")
    inputs = {"audio": str(audio), **(extra_inputs or {})}
    if lyrics_text is not None:
        lyrics = tmp_path / "lyrics.md"
        lyrics.write_text(lyrics_text, encoding="utf-8")
        inputs["lyrics"] = str(lyrics)
    req = RenderRequest(
        subgenre="lyric-video",
        inputs=inputs,
        params=params or {},
        workdir=tmp_path / "wd",
        output=tmp_path / "out.mp4",
    )
    return pipeline.render(req), scenes


def test_shaped_lyrics_are_reported(tmp_path, monkeypatch):
    result, _ = _render(tmp_path, monkeypatch, SHAPED)
    assert result.meta["lyrics_layout_ignored"] == {"lines": 2, "indentations": 2}


def test_unshaped_or_absent_lyrics_add_no_key(tmp_path, monkeypatch):
    for text in (FLAT, None):
        result, _ = _render(tmp_path, monkeypatch, text)
        assert "lyrics_layout_ignored" not in result.meta


def test_lyrics_that_never_set_the_timing_report_nothing(tmp_path, monkeypatch):
    extra = {"timed_text": str(tmp_path / "t.json")}
    result, _ = _render(tmp_path, monkeypatch, SHAPED, extra_inputs=extra)
    assert "lyrics_layout_ignored" not in result.meta


def test_a_shaped_input_is_not_a_strict_failure(tmp_path, monkeypatch):
    spec = {"archetype": "stacked_lines"}
    result, _ = _render(
        tmp_path, monkeypatch, SHAPED, params={"treatment": spec, "strict": True}
    )
    assert "treatment_repairs" not in result.meta
    assert "lyrics_layout_ignored" in result.meta


def test_the_scene_does_not_depend_on_the_indentation(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _, shaped = _render(tmp_path / "a", monkeypatch, SHAPED)
    _, flat = _render(tmp_path / "b", monkeypatch, FLAT)
    assert shaped[0] == flat[0]


def test_layout_dropped_does_not_warn():
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert layout_dropped(SHAPED) == {"lines": 2, "indentations": 2}
        assert layout_dropped(FLAT) is None


def test_a_lyrics_file_that_vanishes_fails_before_any_output(tmp_path, monkeypatch):
    """The file is read before the backend runs, never after the video is written."""
    lyrics = tmp_path / "lyrics.md"
    lyrics.write_text(SHAPED, encoding="utf-8")
    def vanishing(**kw):
        lyrics.unlink()
        return real_timed

    real_timed = from_words([("one", 0.0, 1.0)], duration=1.0)
    ran = []
    monkeypatch.setattr(pipeline, "build_timed_text", vanishing)
    monkeypatch.setattr(pipeline, "select_renderer", lambda name: "fake")
    monkeypatch.setattr(pipeline, "resolve_renderer", lambda name: ran.append(1))
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"")
    req = RenderRequest(
        subgenre="lyric-video",
        inputs={"audio": str(audio), "lyrics": str(lyrics)},
        params={},
        workdir=tmp_path / "wd",
        output=tmp_path / "out.mp4",
    )
    with pytest.raises(FileNotFoundError):
        pipeline.render(req)
    assert not ran and not (tmp_path / "out.mp4").exists()
