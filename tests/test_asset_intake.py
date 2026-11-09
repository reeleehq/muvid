"""A song or video already in one of the caller's projects is bound into another by
its ``asset_id`` — no fetch, stored once (muvid#22)."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("fastmcp")

from muvid.footage import assets, service  # noqa: E402
from muvid.footage.errors import FootageError  # noqa: E402
from muvid.footage.workspace import FootageWorkspace, copy_or_link  # noqa: E402
from tests.ffmpeg_support import needs_ffmpeg  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tone(path: Path, seconds: float = 2.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         f"sine=frequency=440:duration={seconds}", str(path)],
        check=True,
    )  # fmt: skip
    return path


def _video(path: Path, seconds: float = 2.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         f"testsrc=size=160x120:rate=25:duration={seconds}", "-f", "lavfi", "-i",
         f"sine=frequency=330:duration={seconds}", "-shortest", "-pix_fmt", "yuv420p",
         str(path)],
        check=True,
    )  # fmt: skip
    return path


@pytest.fixture
def two_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data"))
    ws = FootageWorkspace.for_email("u@x.com")
    return ws.create_project("a"), ws.create_project("b")


def test_copy_or_link_links_then_falls_back_to_a_copy(tmp_path, monkeypatch):
    src = tmp_path / "src.bin"
    src.write_bytes(b"bytes")
    linked = tmp_path / "linked"
    linked.touch()
    copy_or_link(src, linked, link=True)
    assert os.stat(linked).st_ino == os.stat(src).st_ino
    copied = tmp_path / "copied"
    copied.touch()
    copy_or_link(src, copied)  # default: a copy
    assert (
        os.stat(copied).st_ino != os.stat(src).st_ino
        and copied.read_bytes() == b"bytes"
    )
    monkeypatch.setattr(os, "link", lambda *a: (_ for _ in ()).throw(OSError("EXDEV")))
    fallback = tmp_path / "fallback"
    fallback.touch()
    copy_or_link(src, fallback, link=True)  # cannot link: copies
    assert fallback.read_bytes() == b"bytes"


@needs_ffmpeg
def test_a_clip_added_is_given_its_asset_id_and_binds_into_another_project(
    two_projects, tmp_path
):
    a, b = two_projects
    clip = _video(tmp_path / "c.mp4")
    out = service.add_clip(a, path=str(clip), clip_id="c1")
    assert out["asset_id"] == _sha(clip)
    stored = assets.resolve_asset("u@x.com", out["asset_id"], kind="video")
    assert stored == Path(a.clip_paths()["c1"])
    bound = service.add_clip(b, path=str(stored), clip_id="c1", link=True)
    assert bound["asset_id"] == out["asset_id"]
    pa, pb = a.clip_paths()["c1"], b.clip_paths()["c1"]
    assert os.stat(pa).st_ino == os.stat(pb).st_ino  # stored once
    # removing it from one project leaves the other's bytes
    a.remove_clip("c1")
    assert _sha(pb) == out["asset_id"]


@needs_ffmpeg
def test_a_song_binds_by_its_hash_and_is_stored_once(two_projects, tmp_path):
    a, b = two_projects
    song = _tone(tmp_path / "s.wav")
    out = service.set_song(a, path=str(song))
    assert out["asset_id"] == _sha(song)
    stored = assets.resolve_asset("u@x.com", out["asset_id"], kind="audio")
    service.set_song(b, path=str(stored), ext=stored.suffix, link=True)
    assert os.stat(a.song_path()).st_ino == os.stat(b.song_path()).st_ino
    assert b.song_hash() == out["asset_id"]


@needs_ffmpeg
def test_the_resolver_refuses_what_it_cannot_find_without_naming_anyone(
    two_projects, tmp_path
):
    a, _ = two_projects
    service.add_clip(a, path=str(_video(tmp_path / "c.mp4")), clip_id="c1")
    with pytest.raises(FootageError, match="SHA-256"):
        assets.resolve_asset(
            "u@x.com", "c1", kind="video"
        )  # a clip id is not an asset id
    with pytest.raises(FootageError, match="no video with that asset_id"):
        assets.resolve_asset("u@x.com", "0" * 64, kind="video")
    # another caller's asset is not found by this one, and the refusal is the same
    held = _sha(tmp_path / "c.mp4")
    with pytest.raises(FootageError, match="no video with that asset_id"):
        assets.resolve_asset("someone@else.com", held, kind="video")
    # a video's hash is not a song
    with pytest.raises(FootageError, match="no song with that asset_id"):
        assets.resolve_asset("u@x.com", held, kind="audio")


def test_a_registered_resolver_is_tried_and_can_go_first(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "_RESOLVERS", [])
    f = tmp_path / "x.mp4"
    f.write_bytes(b"v")
    seen = []

    def library(email, asset_id, kind):
        seen.append((email, asset_id, kind))
        return f

    assets.register_asset_resolver(library)
    assets.register_asset_resolver(library)  # twice: once
    assert assets._RESOLVERS == [library]
    assert assets.resolve_asset("u@x.com", "a" * 64, kind="video") == f
    assert seen == [("u@x.com", "a" * 64, "video")]


@needs_ffmpeg
def test_the_tools_bind_by_asset_id_with_no_fetch(two_projects, tmp_path, monkeypatch):
    import muvid.mcp._fetch as fetch_mod
    import muvid.mcp.footage_tools as ft
    from muvid.mcp.identity import use_email

    a, b = two_projects
    clip = service.add_clip(a, path=str(_video(tmp_path / "c.mp4")), clip_id="c1")
    service.set_song(a, path=str(_tone(tmp_path / "s.wav")))

    def no_network(*args, **kw):
        raise AssertionError("an asset_id must not fetch anything")

    monkeypatch.setattr(fetch_mod, "fetch_to_file_streaming", no_network)
    monkeypatch.setattr(fetch_mod, "fetch_media", no_network)
    with use_email("u@x.com"):
        got = ft.add_footage("b", asset_id=clip["asset_id"], name="again")
        song = ft.set_song("b", asset_id=a.song_hash())
    assert got["asset_id"] == clip["asset_id"] and got["name"] == "again"
    assert song["asset_id"] == a.song_hash()
    [c] = b.list_clips()
    assert (
        os.stat(b.clip_paths()[c["clip_id"]]).st_ino
        == os.stat(a.clip_paths()["c1"]).st_ino
    )
    assert os.stat(b.song_path()).st_ino == os.stat(a.song_path()).st_ino


def test_exactly_one_of_url_and_asset_id(two_projects):
    import muvid.mcp.footage_tools as ft
    from fastmcp.exceptions import ToolError
    from muvid.mcp.identity import use_email

    with use_email("u@x.com"):
        for call in (
            lambda: ft.add_footage("b"),
            lambda: ft.add_footage("b", url="https://e.com/x.mp4", asset_id="a" * 64),
            lambda: ft.set_song("b"),
            lambda: ft.set_song("b", url="https://e.com/s.mp3", asset_id="a" * 64),
        ):
            with pytest.raises(ToolError, match="`url`.*`asset_id`"):
                call()
        with pytest.raises(ToolError, match="no video with that asset_id"):
            ft.add_footage("b", asset_id="a" * 64)
