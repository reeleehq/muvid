"""The visualizer's (and lyric-video's, and subgenres') URL inputs take the footage
tools' intake (muvid#23): a share link is normalised, a folder link refused, and an audio
or cover input must be that kind before a byte is written — so a private link's HTTP-200
sign-in page is refused with graze's diagnosis instead of reaching ffmpeg."""

from __future__ import annotations

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("graze")

DRIVE_PAGE = "https://drive.google.com/file/d/1AbCdEf/view?usp=drivesdk"
DROPBOX_FOLDER = "https://www.dropbox.com/scl/fo/x9y8/z7?rlkey=abc&dl=0"
SIGNIN_PAGE = b'<!doctype html><html><head><base href="https://accounts.google.com/">'
FAKE_MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64


class _Resp:
    def __init__(self, body):
        self._chunks = [body]

    def read(self, _n):
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def serve(monkeypatch):
    import muvid.mcp._fetch as F

    seen = []

    def serve(body):
        def opener(uri, deadline):
            seen.append(uri)
            return _Resp(body)

        monkeypatch.setattr(F, "_open_following_redirects", opener)
        return seen

    return serve


def test_a_share_link_is_normalised_and_audio_must_be_audio(serve, tmp_path):
    from muvid.mcp.tools import _resolve_input

    seen = serve(FAKE_MP3)
    out = _resolve_input(DRIVE_PAGE, tmp_path / "audio", label="audio")
    assert out.read_bytes() == FAKE_MP3
    assert "uc?export=download" in seen[0] and "1AbCdEf" in seen[0]


def test_a_sign_in_page_is_refused_with_its_diagnosis_and_nothing_written(serve, tmp_path):
    from fastmcp.exceptions import ToolError
    from muvid.mcp.tools import _resolve_input

    serve(SIGNIN_PAGE)
    with pytest.raises(ToolError, match="anyone-with-the-link"):
        _resolve_input(DRIVE_PAGE, tmp_path / "cover", label="cover")
    assert not (tmp_path / "cover").exists()


def test_a_folder_link_is_refused(serve, tmp_path):
    from fastmcp.exceptions import ToolError
    from muvid.mcp.tools import _resolve_input

    serve(FAKE_MP3)
    with pytest.raises(ToolError, match="FOLDER link"):
        _resolve_input(DROPBOX_FOLDER, tmp_path / "audio", label="audio")


def test_an_unnamed_input_is_not_kind_checked(serve, tmp_path):
    from muvid.mcp.tools import _resolve_input

    serve(b"Verse one\nVerse two\n")
    out = _resolve_input("https://example.com/lyrics.md", tmp_path / "lyrics", label="lyrics")
    assert out.read_text().startswith("Verse one")
