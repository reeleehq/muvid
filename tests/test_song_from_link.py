"""A project's song from a page link, through yb's bounded download (muvid#274).

``muvid_set_song(url)`` fetched only direct media and share links, so a video or music
page was refused as "an HTML page". Now a page that answers with a web page — and is not
a share link, whose web page is a sign-in page with its own diagnosis — has its audio
taken through ``yb.download.download_audio_bounded``, with muvid's SSRF check and caps,
and the song keeps the copyright notice. No network here: the page fetch and yb are
stood in for; yb's own behaviour is yb's tests'.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("graze")

PAGE = "https://www.youtube.com/watch?v=abc123"
DRIVE_PAGE = "https://drive.google.com/file/d/1AbCdEf/view?usp=drivesdk"
SIGNIN_PAGE = b'<!doctype html><html><head><base href="https://accounts.google.com/">'


@dataclass
class _Got:
    path: Path
    title: str = "Que Calor (live)"
    duration_s: float = 12.0
    notice: str = "Downloaded from a user-supplied link — respect the source's copyright."


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data"))
    from muvid.footage.workspace import FootageWorkspace

    return FootageWorkspace.for_email("u@x.com").create_project("p")


@pytest.fixture
def page_answers_html(monkeypatch):
    """The direct fetch of ``PAGE`` returns a web page, as a real page link does."""
    import muvid.mcp._fetch as fetch_mod

    def fetch(uri, dest, *, max_bytes, expect_kind=""):
        from graze.content_kind import ContentKindMismatch, assert_content_kind

        try:
            assert_content_kind(SIGNIN_PAGE, expect_kind=expect_kind, url=uri)
        except ContentKindMismatch as e:
            raise fetch_mod.FetchError(str(e)) from e

    monkeypatch.setattr(fetch_mod, "fetch_to_file_streaming", fetch)
    import muvid.mcp.footage_tools as ft

    monkeypatch.setattr(ft, "_duration", lambda p: 12.0)


def _fake_yb(calls):
    def download(url, *, download_dir, max_bytes, max_duration_s, validate_target):
        calls.append(
            dict(url=url, max_bytes=max_bytes, max_duration_s=max_duration_s,
                 validate_target=validate_target)
        )
        validate_target(url)  # as yb does, before any network
        out = Path(download_dir) / ".yb-audio-x" / "song.mp3"
        out.parent.mkdir(parents=True)
        out.write_bytes(b"ID3fake-mp3")
        return _Got(path=out)

    return download


def test_a_page_link_becomes_the_song_through_yb_with_its_notice(
    project, page_answers_html, monkeypatch
):
    import muvid.mcp._audio_link as AL
    import muvid.mcp.footage_tools as ft
    from muvid.footage import service
    from muvid.mcp.identity import use_email

    calls = []
    real = AL.song_from_page_link
    monkeypatch.setattr(
        AL, "song_from_page_link", lambda url, **kw: real(url, download=_fake_yb(calls), **kw)
    )
    monkeypatch.setattr("muvid.mcp._fetch._host_is_public", lambda host: True)
    with use_email("u@x.com"):
        out = ft.set_song("p", url=PAGE)
    [call] = calls
    assert call["url"] == PAGE
    # muvid's caps and muvid's own target check, not yb's defaults
    assert call["max_bytes"] == service.SONG_MAX_BYTES
    assert call["max_duration_s"] == service.SONG_MAX_DURATION_S
    from muvid.mcp._fetch import _validate_target

    assert call["validate_target"] is _validate_target
    song = out["song"]
    assert song["name"] == "Que Calor (live).mp3" and song["file"] == "song.mp3"
    assert song["notice"].startswith("Downloaded from a user-supplied link")
    assert project.manifest()["song_notice"] == song["notice"]


def test_muvids_target_check_refuses_a_private_host(project, page_answers_html, monkeypatch):
    import muvid.mcp._audio_link as AL
    import muvid.mcp.footage_tools as ft
    from fastmcp.exceptions import ToolError
    from muvid.mcp.identity import use_email

    real = AL.song_from_page_link
    monkeypatch.setattr(
        AL, "song_from_page_link", lambda url, **kw: real(url, download=_fake_yb([]), **kw)
    )
    with use_email("u@x.com"), pytest.raises(ToolError, match="could not take the song"):
        ft.set_song("p", url="https://10.0.0.5/watch?v=x")


def test_without_yb_the_refusal_says_what_to_install(project, page_answers_html, monkeypatch):
    import sys

    import muvid.mcp.footage_tools as ft
    from fastmcp.exceptions import ToolError
    from muvid.mcp.identity import use_email

    monkeypatch.setitem(sys.modules, "yb.download", None)  # import fails
    with use_email("u@x.com"), pytest.raises(ToolError, match=r"yb\[download\]"):
        ft.set_song("p", url=PAGE)


def test_an_older_yb_without_the_bounds_is_refused(project, page_answers_html, monkeypatch):
    """yb before reeleehq/yb#56 fetches around muvid's SSRF guard; its absence of
    ``AudioSourceError`` is how that is told, so it is treated as not installed."""
    import types

    import muvid.mcp.footage_tools as ft
    import sys
    from fastmcp.exceptions import ToolError
    from muvid.mcp.identity import use_email

    old = types.ModuleType("yb.download")
    old.download_audio_bounded = lambda *a, **k: pytest.fail("old yb must not run")
    monkeypatch.setitem(sys.modules, "yb.download", old)
    with use_email("u@x.com"), pytest.raises(ToolError, match=r"yb\[download\]>=0\.1\.28"):
        ft.set_song("p", url=PAGE)


def test_a_share_links_sign_in_page_keeps_its_own_diagnosis(
    project, page_answers_html, monkeypatch
):
    """A private Drive link answers with a sign-in page too; that is not a page link to
    hand to yb, and graze's "set it to anyone-with-the-link" is the answer."""
    import muvid.mcp._audio_link as AL
    import muvid.mcp.footage_tools as ft
    from fastmcp.exceptions import ToolError
    from muvid.mcp.identity import use_email

    monkeypatch.setattr(AL, "song_from_page_link", lambda *a, **k: pytest.fail("yb"))
    with use_email("u@x.com"), pytest.raises(ToolError, match="anyone-with-the-link"):
        ft.set_song("p", url=DRIVE_PAGE)


def test_a_song_set_without_a_notice_records_none(project, tmp_path):
    from muvid.footage import service

    song = tmp_path / "s.wav"
    song.write_bytes(b"RIFF-song")
    service.set_song(project, path=str(song), duration_s=10.0)
    assert "song_notice" not in project.manifest()
    assert "notice" not in project.song_info()
