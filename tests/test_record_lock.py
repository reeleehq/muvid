"""The read-modify-writes #254 left unlocked take a lock too (muvid#280).

``LyricVideoProduction``'s manifest and a render's ``meta.json`` (``organise``, the
``ensure_render_refs`` backfill) were each re-read, changed and written back with
nothing between two writers, so one lost the other's update. Both now go through
``workspace.update_json_record`` — dol's ``update_json`` under muvid's lock. These race
real threads through the real lock.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time

import pytest

from muvid.footage import workspace as W


def _file(path, payload: bytes):
    path.write_bytes(payload)
    return path


# -- the helper ---------------------------------------------------------------


def test_a_record_that_must_exist_is_not_created(tmp_path):
    path = tmp_path / "meta.json"
    with pytest.raises(FileNotFoundError):
        W.update_json_record(path, lambda m: m.update(a=1), default=W.no_record)
    assert not path.exists()


def test_an_unreadable_record_is_refused_not_overwritten(tmp_path):
    from dol.atomic import InvalidJSONError

    path = _file(tmp_path / "meta.json", b"{torn")
    with pytest.raises(InvalidJSONError):
        W.update_json_record(path, lambda m: m.update(a=1))
    assert path.read_bytes() == b"{torn"


def test_the_record_keeps_its_format_and_mode(tmp_path):
    import os
    import stat

    path = tmp_path / "meta.json"
    W.update_json_record(path, lambda m: m.update(a=1))
    assert path.read_text() == json.dumps({"a": 1}, indent=2)
    if os.name != "nt":  # mkstemp's 0600, as atomic_write_text always wrote
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    mtime = path.stat().st_mtime_ns
    W.update_json_record(path, lambda m: None)  # a no-op writes nothing
    assert path.stat().st_mtime_ns == mtime


# -- the lyric production's manifest -----------------------------------------


@pytest.fixture
def lyric(tmp_path):
    pytest.importorskip("nw")
    import muvid

    muvid.create_project_at(tmp_path, "lv", genre="lyric-video")
    return muvid.Project(tmp_path / "lv").lyric


def _race(update, *, barrier_inside: bool):
    """Two threads each set one key through ``update(change)``, holding the window
    open. ``barrier_inside`` makes both READ before either writes, which only an
    unlocked update allows (locked, it would wait forever — so it meets at the door)."""
    barrier = threading.Barrier(2, timeout=10)

    def run(key):
        def change(m):
            if barrier_inside:
                barrier.wait()
            m[key] = 1
            time.sleep(0.05)

        if not barrier_inside:
            barrier.wait()
        update(change)

    threads = [threading.Thread(target=run, args=(k,)) for k in "ab"]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)


def test_concurrent_lyric_manifest_writers_both_land(lyric):
    _race(lyric.update_manifest, barrier_inside=False)
    m = lyric.manifest()
    assert ("a" in m, "b" in m) == (True, True)


def test_without_a_lock_the_same_race_loses_one(lyric):
    """The control: the test above can fail."""

    def unlocked(change):
        return W.update_json_record(
            lyric.manifest_path, change, lock=contextlib.nullcontext()
        )

    lyric.root.mkdir(parents=True, exist_ok=True)
    _race(unlocked, barrier_inside=True)
    m = lyric.manifest()
    assert ("a" in m) != ("b" in m)


def test_every_lyric_writer_goes_through_the_locked_update(
    lyric, tmp_path, monkeypatch
):
    calls = []
    real = type(lyric).update_manifest

    def counting(self, change):
        calls.append(1)
        return real(self, change)

    monkeypatch.setattr(type(lyric), "update_manifest", counting)
    lyric.set_song(_file(tmp_path / "song.wav", b"RIFF"))
    lyric.add_source(_file(tmp_path / "words.md", b"la"), role="lyrics")
    lyric.add_render(_file(tmp_path / "r.mp4", b"mp4"), render_id="r1")
    assert len(calls) == 3
    m = lyric.manifest()
    assert m["song"]["file"] == "song.wav"
    assert [s["file"] for s in m["sources"]] == ["words.md"]
    assert [r["render_id"] for r in m["renders"]] == ["r1"]


def test_a_reimported_render_keeps_its_place(lyric, tmp_path):
    for rid in ("r1", "r2", "r3"):
        lyric.add_render(_file(tmp_path / f"{rid}.mp4", rid.encode()), render_id=rid)
    lyric.add_render(_file(tmp_path / "r2b.mp4", b"new"), render_id="r2", label="B")
    rows = lyric.manifest()["renders"]
    assert [r["render_id"] for r in rows] == ["r1", "r2", "r3"]
    assert rows[1]["label"] == "B"


def test_an_unreadable_lyric_manifest_is_not_overwritten(lyric, tmp_path):
    lyric.root.mkdir(parents=True, exist_ok=True)
    lyric.manifest_path.write_text("{torn")
    import nw

    with pytest.raises(nw.GenreOpRefused, match="not valid JSON"):
        lyric.add_source(_file(tmp_path / "words.md", b"la"), role="lyrics")
    assert lyric.manifest_path.read_text() == "{torn"


# -- a render's meta.json ----------------------------------------------------


def test_organise_rereads_meta_under_its_lock(tmp_path, monkeypatch):
    """A writer holding the meta's lock (the ref backfill, a render finishing) adds a
    key; organise, started meanwhile, must keep it rather than write back what it read
    before. Without the lock, organise reads the old meta and drops ``edl``."""
    pytest.importorskip("nw")
    from muvid.downloads import organise

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    proj = W.FootageWorkspace.for_email("u@x.com").create_project("p")
    rid = "r1" * 6
    rdir = proj.new_render_dir(rid)
    (rdir / "final.mp4").write_bytes(b"v")
    meta = rdir / "meta.json"
    meta.write_text(json.dumps({"render_id": rid, "ref_n": 1}))

    done = threading.Event()

    def organiser():
        organise("u@x.com", "p", rid, title="Take One")
        done.set()

    with W.file_lock(meta.with_name("meta.json.lock")):
        t = threading.Thread(target=organiser)
        t.start()
        time.sleep(0.2)  # long enough for an unlocked organise to read and write
        assert not done.is_set()
        record = json.loads(meta.read_text())
        W.atomic_write_text(meta, json.dumps({**record, "edl": ["kept"]}))
    t.join(10)
    got = json.loads(meta.read_text())
    assert got["edl"] == ["kept"] and got["organise"] == {"title": "Take One"}
    assert got["ref_n"] == 1


def test_the_ref_backfill_keeps_a_ref_another_writer_assigned(tmp_path, monkeypatch):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    proj = W.FootageWorkspace.for_email("u@x.com").create_project("p")
    import os

    for age, rid in ((200, "a" * 12), (100, "b" * 12)):  # a is the older render
        rdir = proj.new_render_dir(rid)
        (rdir / "meta.json").write_text(json.dumps({"render_id": rid}))
        os.utime(rdir / "meta.json", (time.time() - age, time.time() - age))
    real = W.update_json_record

    def racing(path, change, **kw):
        # Another process assigned this render a ref between the scan and the update.
        if path.parent.name == "a" * 12:
            record = json.loads(path.read_text())
            path.write_text(json.dumps({**record, "ref_n": 5}))
        return real(path, change, **kw)

    monkeypatch.setattr(W, "update_json_record", racing)
    refs = proj.ensure_render_refs()
    assert refs["a" * 12] == 5  # theirs, not renumbered
    assert refs["b" * 12] == 6  # and no collision with it


def test_organise_a_render_with_no_record_yet_is_not_found(tmp_path, monkeypatch):
    """A render whose video exists but whose meta.json does not (in flight, crashed)
    is refused in organise's own vocabulary — not created, not an OSError."""
    pytest.importorskip("nw")
    from muvid.downloads import organise

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    proj = W.FootageWorkspace.for_email("u@x.com").create_project("p")
    rid = "r1" * 6
    (proj.new_render_dir(rid) / "final.mp4").write_bytes(b"v")
    with pytest.raises(KeyError, match="no record"):
        organise("u@x.com", "p", rid, title="Take One")
    assert not (proj.renders_dir / rid / "meta.json").exists()


@pytest.mark.parametrize("bad", [None, "3", 2.0])
def test_the_ref_backfill_repairs_a_ref_that_is_not_an_int(tmp_path, monkeypatch, bad):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    proj = W.FootageWorkspace.for_email("u@x.com").create_project("p")
    rid = "a" * 12
    meta = proj.new_render_dir(rid) / "meta.json"
    meta.write_text(json.dumps({"render_id": rid, "ref_n": bad}))
    assert proj.ensure_render_refs() == {rid: 1}
    assert json.loads(meta.read_text())["ref_n"] == 1  # durable, so it never shifts
