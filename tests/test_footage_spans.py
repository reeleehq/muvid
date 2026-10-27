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


def test_overlapping_spans_and_the_tolerance_edge():
    overlap = (MeasuredSpan(0.0, 50.0, 0.0, 0.9), MeasuredSpan(10.0, 30.0, 0.0, 0.9))
    assert unverified_stretches(_a(overlap)) == [(50.0, 78.0)]  # the longer one holds
    edge = (MeasuredSpan(0.0, 78.0, 0.25, 0.9),)  # exactly at the tolerance: confirms
    assert unverified_stretches(_a(edge)) == []
    beyond = (MeasuredSpan(0.0, 78.0, 0.2501, 0.9),)
    assert unverified_stretches(_a(beyond)) == [(0.0, 78.0)]


def test_a_span_outside_the_placement_confirms_none_of_it():
    """The #16 review: clipped to the placement, a span past it inverted into an
    interval running beyond the clip."""
    a = _a((MeasuredSpan(40.0, 50.0, 0.0, 0.9),), duration=30.0, coverage=(0.0, 30.0))
    assert unverified_stretches(a) == [(0.0, 30.0)]


def test_a_malformed_span_on_disk_is_skipped_never_the_record():
    record = FootageAlignment("c", 1.0, 0.9, 10.0, (1.0, 11.0)).to_dict()
    record["spans"] = [
        {"clip_start_s": 0, "clip_end_s": 5, "offset_s": 1, "confidence": "abc"},
        {"clip_start_s": 0},
        None,
        {"clip_start_s": 0, "clip_end_s": 5, "offset_s": 1, "confidence": 0.8},
    ]
    a = FootageAlignment.from_dict(record)
    assert a.offset_s == 1.0 and a.spans == (MeasuredSpan(0.0, 5.0, 1.0, 0.8),)


def test_the_span_tolerance_is_mixings():
    """Restated so edl stays import-light; pinned so the two cannot drift."""
    pytest.importorskip("mixing.audio")
    from mixing.audio.audio_ops import SPAN_OFFSET_TOLERANCE_S

    from muvid.footage.edl import SPAN_OFFSET_TOLERANCE_S as ours

    assert ours == SPAN_OFFSET_TOLERANCE_S


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


def test_a_hand_placed_photo_is_not_listened_to(fp, tmp_path, monkeypatch):
    """The #16 review: a photo placed by hand reached the audio aligner and crashed the
    whole operation; photos have no sound, as in ``align``."""
    Image = pytest.importorskip("PIL.Image")
    import muvid.footage.align as A

    asked = []

    def fake(song, clips, *, song_duration):
        asked.extend(c for c, _ in clips)
        return {c: () for c, _ in clips}, 20.0

    monkeypatch.setattr(A, "measure_spans", fake)
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (8, 8)).save(photo)
    service.add_clip(fp, path=str(photo), clip_id="P")
    service.set_offset(fp, clip_id="P", offset_s=5.0)
    service.measure_spans(fp)
    assert asked == ["A"]


def test_a_placement_changed_while_measuring_is_kept_not_reverted(fp, monkeypatch):
    """The #16 review: the measurement took minutes and then wrote its old copy of the
    placements back, reverting an offset set meanwhile."""
    import muvid.footage.align as A

    def slow_measure(song, clips, *, song_duration):
        service.set_offset(fp, clip_id="A", offset_s=2.5)  # a person moves it meanwhile
        return {c: (MeasuredSpan(0.0, 20.0, 0.0, 0.9),) for c, _ in clips}, 20.0

    monkeypatch.setattr(A, "measure_spans", slow_measure)
    service.measure_spans(fp)
    (a,) = [x for x in fp.load_alignments() if x.clip_id == "A"]
    assert (
        a.offset_s == 2.5 and a.spans is None
    )  # kept; spans of the OLD placement dropped


def test_a_song_changed_while_measuring_refuses(fp, tmp_path, monkeypatch):
    import muvid.footage.align as A
    from muvid.footage.errors import FootageError

    def slow_measure(song, clips, *, song_duration):
        other = tmp_path / "other.wav"
        other.write_bytes(b"RIFF-other")
        service.set_song(fp, path=str(other), duration_s=30.0)
        return {c: () for c, _ in clips}, 20.0

    monkeypatch.setattr(A, "measure_spans", slow_measure)
    with pytest.raises(FootageError, match="song changed"):
        service.measure_spans(fp)
    assert fp.load_alignments() == []  # the new song's state, not the old offsets


def test_measure_spans_is_not_an_mcp_tool():
    """Minutes per project: a host runs it as a job; the MCP transport would block a
    request on it (muvid#16's latency decision is still open)."""
    from muvid.mcp._footage_ops import FOOTAGE_TOOLS, GENERATED_OPS

    assert "measure_spans" not in GENERATED_OPS
    assert "footage_measure_spans" not in FOOTAGE_TOOLS


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


# -- one lock for every writer of alignments.json (muvid#236) --------------------------


def _writers(fp, tmp_path):
    """Each writer of alignments.json, as a call that should block while the lock is held."""
    song = tmp_path / "song2.wav"
    song.write_bytes(b"RIFF-other-song")
    return {
        "set_offset": lambda: service.set_offset(fp, clip_id="C", offset_s=2.0),
        "clear_offset": lambda: service.clear_offset(fp, clip_id="A"),
        "measure_spans": lambda: service.measure_spans(fp),
        "align": lambda: service.align(fp),
        "remove_clip": lambda: fp.remove_clip("C"),
        "set_song": lambda: service.set_song(fp, path=str(song), duration_s=30.0),
    }


@pytest.mark.parametrize(
    "writer",
    ["set_offset", "clear_offset", "measure_spans", "align", "remove_clip", "set_song"],
)
def test_every_writer_of_the_alignments_waits_for_the_lock(fp, tmp_path, monkeypatch, writer):
    import threading
    import time

    import muvid.footage.align as A

    monkeypatch.setattr(
        A, "measure_spans", lambda song, clips, *, song_duration: ({c: () for c, _ in clips}, 20.0)
    )
    monkeypatch.setattr(
        A,
        "align_footage",
        lambda song, clips, *, song_duration: [
            FootageAlignment(c, 1.0, 0.9, 20.0, (1.0, 21.0)) for c, _ in clips
        ],
    )
    call = _writers(fp, tmp_path)[writer]
    path = fp.root / "alignments.json"
    before = path.read_bytes() if path.exists() else None
    errors = []

    def run():
        try:
            call()
        except Exception as exc:  # noqa: BLE001 - reported by the assertion below
            errors.append(exc)

    with fp.alignments_lock():
        t = threading.Thread(target=run)
        t.start()
        time.sleep(0.5)
        assert t.is_alive(), f"{writer} did not wait for the alignments lock"
        assert (path.read_bytes() if path.exists() else None) == before
    t.join(10)
    assert not t.is_alive() and not errors, errors


def test_an_offset_declared_while_align_measures_survives_it(fp, monkeypatch):
    """align measures without the lock and merges under it, against what is on disk."""
    import muvid.footage.align as A

    def slow_align(song, clips, *, song_duration):
        service.set_offset(fp, clip_id="C", offset_s=5.0)  # a person, meanwhile
        return [FootageAlignment(c, 1.0, 0.9, 20.0, (1.0, 21.0)) for c, _ in clips]

    monkeypatch.setattr(A, "align_footage", slow_align)
    out = service.align(fp)
    c = next(a for a in fp.load_alignments() if a.clip_id == "C")
    assert (c.offset_s, c.source) == (5.0, "declared")
    assert "C" in out["kept_declared"]


def test_a_clip_removed_while_align_measures_gets_no_record(fp, monkeypatch):
    import muvid.footage.align as A

    def slow_align(song, clips, *, song_duration):
        fp.remove_clip("C")
        return [FootageAlignment(c, 1.0, 0.9, 20.0, (1.0, 21.0)) for c, _ in clips]

    monkeypatch.setattr(A, "align_footage", slow_align)
    service.align(fp)
    assert "C" not in {a.clip_id for a in fp.load_alignments()}


def test_a_song_replaced_while_align_measures_is_refused(fp, tmp_path, monkeypatch):
    import muvid.footage.align as A
    from muvid.footage.errors import FootageError

    other = tmp_path / "other.wav"
    other.write_bytes(b"RIFF-new")

    def slow_align(song, clips, *, song_duration):
        service.set_song(fp, path=str(other), duration_s=30.0)
        return [FootageAlignment(c, 1.0, 0.9, 20.0, (1.0, 21.0)) for c, _ in clips]

    monkeypatch.setattr(A, "align_footage", slow_align)
    with pytest.raises(FootageError, match="song changed"):
        service.align(fp)
    assert fp.load_alignments() == []


def test_a_placement_cleared_while_align_measures_is_reported_not_a_bug(fp, monkeypatch):
    """A was declared when align started, so it was not measured; forgetting it meanwhile
    leaves it with no record — named in `cleared_meanwhile`, not in `unrecorded`."""
    import muvid.footage.align as A

    def slow_align(song, clips, *, song_duration):
        assert [c for c, _ in clips] == ["C"]  # A was declared, so not measured
        service.clear_offset(fp, clip_id="A")  # a person, meanwhile
        return [FootageAlignment(c, 1.0, 0.9, 20.0, (1.0, 21.0)) for c, _ in clips]

    monkeypatch.setattr(A, "align_footage", slow_align)
    out = service.align(fp)
    assert out["cleared_meanwhile"] == ["A"]
    assert out["unrecorded"] == []
    assert {a.clip_id for a in fp.load_alignments()} == {"C"}


def test_an_overlapping_second_remove_refuses_and_keeps_newer_records(fp, monkeypatch):
    """The clip is looked up under the lock: a remove that waited behind another remove
    of the same clip must not drop the measurements saved since the first one."""
    cls = type(fp)  # a frozen dataclass: patch the class, monkeypatch restores it
    real_lock = cls.alignments_lock
    measured = FootageAlignment("A", 1.0, 0.9, 20.0, (1.0, 21.0))

    def racing_lock(self):
        # the first remove, then a measurement, land before this call gets the lock
        monkeypatch.setattr(cls, "alignments_lock", real_lock)
        self.remove_clip("C")
        self.save_alignments([measured])
        return real_lock(self)

    monkeypatch.setattr(cls, "alignments_lock", racing_lock)
    with pytest.raises(KeyError):
        fp.remove_clip("C")
    assert fp.load_alignments() == [measured]
