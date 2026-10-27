"""Measured spans on a clip's alignment (muvid#16 slice 1): which stretches of a clip
match the song and where, recorded and reported — and used by nothing else yet."""

from __future__ import annotations

import json
import shutil
import wave
from pathlib import Path

import pytest

from muvid.footage.edl import FootageAlignment, MeasuredSpan, unverified_stretches

nw = pytest.importorskip("nw")

from muvid.footage import service  # noqa: E402
from muvid.footage.workspace import FootageWorkspace  # noqa: E402


def _a(spans, *, offset=0.0, duration=78.0, coverage=(0.0, 78.0)):
    return FootageAlignment("c", offset, 0.9, duration, coverage, spans=spans)


def test_unverified_stretches_are_the_placement_no_span_confirms():
    assert unverified_stretches(_a(None)) is None  # not measured
    assert unverified_stretches(_a(())) == [(0.0, 78.0)]  # nothing aligns
    assert unverified_stretches(_a((MeasuredSpan(0.0, 78.0, 0.1, 0.9),))) == []
    # a dropout: two spans at the clip's own offset with a gap between
    dropout = (MeasuredSpan(0.0, 66.0, 0.0, 0.9), MeasuredSpan(72.0, 78.0, 0.0, 0.9))
    assert unverified_stretches(_a(dropout)) == [(66.0, 72.0)]
    # another take: a span at a DIFFERENT offset confirms nothing here
    take = (MeasuredSpan(0.0, 40.0, 0.0, 0.9), MeasuredSpan(40.0, 78.0, 30.0, 0.9))
    assert unverified_stretches(_a(take)) == [(40.0, 78.0)]
    # only the part of the clip that is ON the song counts (clip time 10..30 here)
    placed = _a(
        (MeasuredSpan(10.0, 30.0, -10.0, 0.9),),
        offset=-10.0,
        duration=40.0,
        coverage=(0.0, 20.0),
    )
    assert unverified_stretches(placed) == []


def test_a_record_without_spans_is_byte_identical_and_with_them_round_trips():
    bare = FootageAlignment("c", 1.0, 0.9, 10.0, (1.0, 11.0))
    assert "spans" not in bare.to_dict()
    spans = (MeasuredSpan(0.0, 6.0, 1.0, 0.8, support=0.9, margin=0.4),)
    with_spans = FootageAlignment("c", 1.0, 0.9, 10.0, (1.0, 11.0), spans=spans)
    assert FootageAlignment.from_dict(json.loads(json.dumps(with_spans.to_dict()))) == (
        with_spans
    )
    empty = FootageAlignment("c", 1.0, 0.9, 10.0, (1.0, 11.0), spans=())
    assert FootageAlignment.from_dict(empty.to_dict()).spans == ()


def test_spans_are_not_a_scoring_input():
    """Nothing scores by them yet, so they must not stale the most expensive artifact."""
    from muvid.footage.scoring.grid import align_fingerprint

    bare = FootageAlignment("c", 1.0, 0.9, 10.0, (1.0, 11.0))
    spans = FootageAlignment(
        "c", 1.0, 0.9, 10.0, (1.0, 11.0), spans=(MeasuredSpan(0.0, 6.0, 1.0, 0.8),)
    )
    assert align_fingerprint([bare]) == align_fingerprint([spans])


@pytest.fixture
def fp(tmp_path, monkeypatch):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data"))
    proj = FootageWorkspace.for_email("u@x.com").create_project("p")
    song = tmp_path / "song.wav"
    song.write_bytes(b"RIFF-song")
    service.set_song(proj, path=str(song), duration_s=30.0)
    for cid in ("A", "C"):
        clip = tmp_path / f"{cid}.mp4"
        clip.write_bytes(cid.encode())
        service.add_clip(proj, path=str(clip), clip_id=cid, duration_s=20.0)
    service.set_offset(proj, clip_id="A", offset_s=0.0)
    return proj


def test_measure_spans_records_and_reports_and_align_is_untouched(fp, monkeypatch):
    """Its own operation (the align op's schema is pinned parameterless): it checks
    every PLACED video, hand-placed ones included, and writes nothing else."""
    import muvid.footage.align as A
    from muvid.footage.scoring.grid import align_fingerprint

    asked = []

    def fake_spans(song, clips, *, song_duration):
        asked.extend(cid for cid, _ in clips)
        return {cid: (MeasuredSpan(0.0, 15.0, 0.0, 0.8),) for cid, _ in clips}, 20.0

    monkeypatch.setattr(A, "measure_spans", fake_spans)
    before = fp.load_alignments()
    out = service.measure_spans(fp)
    assert asked == ["A"]  # the one placed video (C is not placed yet)
    assert out["unverified"] == [
        {"clip_id": "A", "stretches": [[15.0, 20.0]], "seconds": 5.0}
    ]
    assert out["span_edge_accuracy_s"] == 20.0 and set(out["spans"]) == {"A"}
    after = fp.load_alignments()
    assert after[0].spans == (MeasuredSpan(0.0, 15.0, 0.0, 0.8),)
    assert align_fingerprint(after) == align_fingerprint(before)  # scores stay current
    service.set_offset(fp, clip_id="A", offset_s=1.0)  # a new placement: a new record
    assert fp.load_alignments()[0].spans is None


def test_measure_spans_needs_a_placed_video(fp):
    from muvid.footage.errors import FootageError

    service.clear_offset(fp, clip_id="A")
    with pytest.raises(FootageError, match="no video is placed"):
        service.measure_spans(fp)


# -- the real measurement ------------------------------------------------------------


def _write_wav(path: Path, samples, rate: int) -> Path:
    import numpy as np

    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return path


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_clip_that_stops_matching_is_reported_where_it_stops(tmp_path):
    """A 60 s clip whose first 30 s are the song from 10 s and whose last 30 s are
    unrelated audio: spans at offset +10 cover the start, and the tail is unverified
    (to within the 20 s window the edges are measured on). Measured: a 15 s foreign
    tail is NOT seen at that window — the last half-matching window still counts —
    which is the resolution limit the reply states as ``span_edge_accuracy_s``."""
    np = pytest.importorskip("numpy")
    pytest.importorskip("mixing.audio")
    from muvid.footage.align import measure_spans

    rate = 16000
    rng = np.random.default_rng(16)
    song = 0.3 * rng.standard_normal(60 * rate)
    other = 0.3 * np.random.default_rng(17).standard_normal(30 * rate)
    clip = np.concatenate([song[10 * rate : 40 * rate], other])
    song_wav = _write_wav(tmp_path / "song.wav", song, rate)
    clip_wav = _write_wav(tmp_path / "clip.wav", clip, rate)

    spans, window_s = measure_spans(
        str(song_wav), [("c", clip_wav)], song_duration=60.0
    )
    (first, *_) = spans["c"]
    assert first.offset_s == pytest.approx(10.0, abs=0.25)
    placed = FootageAlignment("c", 10.0, 0.9, 60.0, (10.0, 60.0), spans=spans["c"])
    tail = unverified_stretches(placed)
    # on the song the clip runs 10..60 s (the song ends at 60), i.e. clip time 0..50
    assert tail and tail[-1][1] == pytest.approx(50.0)
    assert sum(e - s for s, e in tail) == pytest.approx(20.0, abs=window_s)
