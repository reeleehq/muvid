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
    old = fp.root / "clips" / "A.mp4"
    measured = (old, W.file_identity(old))
    fp.add_clip("A", str(b), ext=".mov")  # now clips/A.mov
    service._set_clip_field(fp, "A", "hash", "stale", measured=measured)
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
        with W.file_lock(tmp_path / "manifest.json"):
            pass


@pytest.mark.parametrize("ext, kind", [(".mp4", ""), (".jpg", "still")])
def test_a_measurement_of_the_old_file_never_lands_on_a_same_name_reupload(
    fp, tmp_path, ext, kind
):
    """The #254 review's race: a recorder measured the OLD A.<ext>, the clip was
    removed and re-added under the SAME name, and the late record must not land on
    the new row. A photo records no hash of its own after an upload, so absence
    alone would have let the old photo's hash stand for good."""
    one, two = tmp_path / f"one{ext}", tmp_path / f"two{ext}"
    one.write_bytes(b"one")
    two.write_bytes(b"two!")
    fp.add_clip("A", str(one), ext=ext, kind=kind)
    path = fp.root / "clips" / f"A{ext}"
    measured = (path, W.file_identity(path))  # taken before measuring
    fp.remove_clip("A")
    fp.add_clip("A", str(two), ext=ext, kind=kind)  # same name, new file
    service._set_clip_field(fp, "A", "hash", "the old file's", measured=measured)
    service._set_clip_field(fp, "A", "duration", 1.0, measured=measured)
    row = fp.manifest()["clips"][0]
    assert "hash" not in row and "duration" not in row


def test_a_measurement_of_the_current_file_is_recorded(fp, tmp_path):
    from muvid.catalog import hash_file
    from muvid.footage.media_views import _clip_hash

    a = tmp_path / "a.mp4"
    a.write_bytes(b"new")
    fp.add_clip("A", str(a), ext=".mp4")
    path = fp.root / "clips" / "A.mp4"
    assert _clip_hash(fp, "A", path) == hash_file(path)
    assert fp.manifest()["clips"][0]["hash"] == hash_file(path)


def test_a_song_hash_of_a_replaced_song_is_not_recorded(fp, tmp_path, monkeypatch):
    """song_hash() hashes outside the lock; a set_song landing meanwhile replaces
    song/song.mp3 under the same name, and the old file's hash must not be recorded."""
    one, two = tmp_path / "one.mp3", tmp_path / "two.mp3"
    one.write_bytes(b"one")
    two.write_bytes(b"two!")
    fp.set_song(str(one), ext=".mp3")
    m = fp.manifest()
    m.pop("song_hash")
    fp._write_manifest(m)
    real_hash = W._hash_file

    def hash_then_replace(path):
        digest = real_hash(path)
        monkeypatch.setattr(W, "_hash_file", real_hash)  # set_song hashes too
        fp.set_song(str(two), ext=".mp3")  # lands while the old one was being hashed
        return digest

    monkeypatch.setattr(W, "_hash_file", hash_then_replace)
    fp.song_hash()
    monkeypatch.setattr(W, "_hash_file", real_hash)
    assert fp.manifest()["song_hash"] == real_hash(fp.song_path())


def test_a_no_op_change_writes_nothing(fp):
    path = fp._manifest_path()
    path.unlink()  # a project nothing has written yet (a host-placed one)
    assert fp.remove_song_candidate("nope") is False
    assert not path.exists()  # a refused no-op creates no manifest
    fp._write_manifest(fp.manifest())
    stamp = path.stat().st_mtime_ns
    fp.update_manifest(lambda m: None)
    assert path.stat().st_mtime_ns == stamp


def test_a_manifest_that_cannot_be_read_is_not_written_back_as_defaults(fp):
    """``manifest()`` reads an unreadable manifest as the DEFAULTS; under the lock that
    would be written back as "defaults plus this change", dropping every clip. A real
    read failure (here: the path is a directory) must raise and write nothing."""
    path = fp._manifest_path()
    path.unlink()
    path.mkdir()
    with pytest.raises(OSError):
        fp.update_manifest(lambda m: m.update(a=1))
    assert path.is_dir()  # nothing was written over it


def test_a_corrupt_manifest_is_a_clean_refusal(fp):
    fp._manifest_path().write_text("{not json")
    with pytest.raises(service.FootageError, match="not valid JSON"):
        fp.update_manifest(lambda m: m.update(a=1))
    assert fp._manifest_path().read_text() == "{not json"


def test_an_unlockable_folder_warns(tmp_path, monkeypatch):
    import contextlib

    import dol.atomic

    @contextlib.contextmanager
    def unheld(*a, **k):
        yield False

    monkeypatch.setattr(dol.atomic, "file_lock", unheld)
    with pytest.warns(UserWarning, match="could not lock"):
        with W.file_lock(tmp_path / "x.lock"):
            pass
