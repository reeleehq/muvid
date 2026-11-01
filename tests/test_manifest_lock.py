"""Every ``manifest.json`` writer takes one lock, and the locks are dol's (muvid#254).

Each manifest write was atomic, but a read-modify-write is two steps: two writers that
read the same manifest each wrote back their own copy, and one update was lost — an
upload's clip record against a duration being recorded, a cover against a ``has_song``.
These race real threads through the real lock rather than reasoning about it.
"""

from __future__ import annotations

import threading
import time

import pytest

from muvid.footage import service
from muvid.footage import workspace as W


@pytest.fixture
def fp(tmp_path, monkeypatch):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(W, "_probe_duration", lambda p: 30.0)
    return W.FootageWorkspace.for_email("u@x.com").create_project("p")


def _two_writers(fp, *, barrier_inside: bool):
    """Two threads each set one key through ``update_manifest``, holding the
    read-modify-write window open. ``barrier_inside`` makes both READ before either
    writes — only possible when nothing serialises them (with the lock it would
    deadlock, so the locked test meets at the door instead)."""
    barrier = threading.Barrier(2, timeout=10)

    def run(key):
        def change(m):
            if barrier_inside:
                barrier.wait()
            m[key] = 1
            time.sleep(0.05)

        if not barrier_inside:
            barrier.wait()
        fp.update_manifest(change)

    threads = [threading.Thread(target=run, args=(k,)) for k in "ab"]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    m = fp.manifest()
    return "a" in m, "b" in m


def test_concurrent_manifest_writers_both_land(fp):
    assert _two_writers(fp, barrier_inside=False) == (True, True)


def test_without_the_lock_the_same_race_loses_an_update(fp, monkeypatch):
    """The control: the test above can fail. With the lock removed, one write is lost."""
    import contextlib

    monkeypatch.setattr(type(fp), "manifest_lock", lambda self: contextlib.nullcontext())
    a, b = _two_writers(fp, barrier_inside=True)
    assert a != b


def test_a_refused_change_writes_nothing(fp, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    fp.add_clip("A", str(src), ext=".mp4")
    before = fp._manifest_path().read_bytes()
    with pytest.raises(service.FootageError):
        service.set_has_song(fp, clip_id="nope", has_song="yes")
    assert fp._manifest_path().read_bytes() == before


def test_clip_measurements_go_through_the_lock(fp, tmp_path, monkeypatch):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    fp.add_clip("A", str(src), ext=".mp4")
    taken = []
    real = type(fp).manifest_lock

    def counting(self):
        taken.append(1)
        return real(self)

    monkeypatch.setattr(type(fp), "manifest_lock", counting)
    service._record_clip_duration(fp, "A", 12.5)
    service.set_has_song(fp, clip_id="A", has_song="no")
    fp.set_cover(src, taken_from="A")
    assert len(taken) == 3
    row = fp.manifest()["clips"][0]
    assert (row["duration"], row["has_song"]) == (12.5, "no")


def test_a_hash_measured_against_a_replaced_clip_is_not_recorded(fp, tmp_path):
    """The measurement runs outside the lock, so the clip may be re-uploaded between
    the hash and the record; the record then belongs to a file that is gone."""
    a, b = tmp_path / "a.mp4", tmp_path / "b.mov"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    fp.add_clip("A", str(a), ext=".mp4")
    fp.add_clip("A", str(b), ext=".mov")  # now clips/A.mov
    service._set_clip_field(fp, "A", "hash", "stale", file="A.mp4")
    assert "hash" not in fp.manifest()["clips"][0]


def test_the_lock_files_keep_their_names(fp):
    with fp.alignments_lock() as held:
        assert held is True
    with fp.edits_lock():
        pass
    with fp.manifest_lock():
        pass
    assert (fp.root / "locks" / "alignments.lock").exists()
    assert (fp.root / "locks" / "manifest.lock").exists()
    assert (fp.root / "edits" / ".lock").exists()


def test_file_lock_refuses_a_name_that_is_not_a_lock_file(tmp_path):
    with pytest.raises(ValueError, match=".lock"):
        W.file_lock(tmp_path / "manifest.json")
