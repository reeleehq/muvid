"""Tests for muvid.mcp._fetch — the SSRF-guarded fetch EXECUTION path.

The load-bearing guarantee (module docstring): redirects are not auto-followed and every
hop's target is re-validated, so a public URL can't 302 into an internal one; plus a hard
byte cap. These drive the streaming fetch end-to-end (:func:`_get`) with a fake opener (no network) so a
regression that dropped ``_NoRedirect``, skipped per-hop re-validation, or broke the byte
cap fails here rather than silently re-opening an SSRF hole. Internal redirect targets are
literal IPs, validated by the REAL ``_host_is_public`` (no DNS).
"""

from __future__ import annotations

import email.message
import io
import urllib.error

import pytest

pytest.importorskip("nw")  # keep in step with the [mcp]-extra gating

from muvid.mcp import _fetch  # noqa: E402


class _FakeResp:
    """A minimal response: chunked ``read`` + context-manager, like urllib's."""

    def __init__(self, body: bytes, url: str = "https://public.test/x"):
        self._buf = io.BytesIO(body)
        self._url = url

    def read(self, n: int) -> bytes:
        return self._buf.read(n)

    def geturl(self) -> str:
        """The post-redirect URL, as urllib's response exposes it."""
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _ScriptedOpener:
    """An opener whose ``open`` replays a scripted list of steps, one per call.

    A step is ``("redirect", location)`` → raises a 302 ``HTTPError`` carrying that
    ``Location`` (the loop must re-validate + re-request it), ``("redirect_noloc", None)``
    → a 302 with no ``Location``, or ``("body", bytes)`` → returns a ``_FakeResp``.
    """

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = 0

    def open(self, url, timeout=None):
        self.calls += 1
        kind, payload = self.steps.pop(0)
        if kind in ("redirect", "redirect_noloc"):
            hdrs = email.message.Message()
            if kind == "redirect":
                hdrs["Location"] = payload
            raise urllib.error.HTTPError(url, 302, "Found", hdrs, None)
        if kind == "status":
            raise urllib.error.HTTPError(
                url, payload, "Denied", email.message.Message(), None
            )
        return _FakeResp(payload, url=url)


@pytest.fixture
def allow_public_test(monkeypatch):
    """Let the fake host ``public.test`` validate; internal IPs use the REAL check."""
    real = _fetch._host_is_public
    monkeypatch.setattr(
        _fetch, "_host_is_public", lambda h: True if h == "public.test" else real(h)
    )


def _use_opener(monkeypatch, opener):
    monkeypatch.setattr(_fetch, "_opener", lambda: opener)


def _get(url: str, tmp_path) -> bytes:
    """The body as the one fetch path writes it (``fetch_to_file_streaming``, under the
    module's cap). These tests drove ``fetch_bytes`` until it was removed as dead code
    (muvid#293); the guarantees they pin are the streaming path's."""
    out = _fetch.fetch_to_file_streaming(
        url, tmp_path / "out", max_bytes=_fetch.MAX_BYTES
    )
    return out.read_bytes()


def test_redirect_into_a_private_target_is_rejected(monkeypatch, allow_public_test, tmp_path):
    # 200-OK-looking public URL that 302s to link-local metadata must be rejected — the
    # single most important SSRF-bypass vector.
    _use_opener(
        monkeypatch, _ScriptedOpener([("redirect", "http://169.254.169.254/latest")])
    )
    with pytest.raises(_fetch.FetchError):
        _get("http://public.test/song.mp3", tmp_path)


def test_redirect_to_loopback_is_rejected(monkeypatch, allow_public_test, tmp_path):
    _use_opener(monkeypatch, _ScriptedOpener([("redirect", "http://127.0.0.1/x")]))
    with pytest.raises(_fetch.FetchError):
        _get("http://public.test/song.mp3", tmp_path)


def test_too_many_redirects_is_rejected(monkeypatch, allow_public_test, tmp_path):
    steps = [("redirect", "http://public.test/next")] * (_fetch.MAX_REDIRECTS + 2)
    _use_opener(monkeypatch, _ScriptedOpener(steps))
    with pytest.raises(_fetch.FetchError, match="too many redirects"):
        _get("http://public.test/a", tmp_path)


def test_redirect_without_location_is_rejected(monkeypatch, allow_public_test, tmp_path):
    _use_opener(monkeypatch, _ScriptedOpener([("redirect_noloc", None)]))
    with pytest.raises(_fetch.FetchError, match="Location"):
        _get("http://public.test/a", tmp_path)


def test_byte_cap_is_enforced(monkeypatch, allow_public_test, tmp_path):
    monkeypatch.setattr(_fetch, "MAX_BYTES", 1024)
    _use_opener(monkeypatch, _ScriptedOpener([("body", b"x" * 5000)]))
    with pytest.raises(_fetch.FetchError, match="limit"):
        _get("http://public.test/big", tmp_path)


def test_happy_path_returns_bounded_bytes(monkeypatch, allow_public_test, tmp_path):
    _use_opener(monkeypatch, _ScriptedOpener([("body", b"hello-bytes")]))
    assert _get("http://public.test/ok", tmp_path) == b"hello-bytes"


def test_a_public_redirect_hop_is_followed_then_bodied(monkeypatch, allow_public_test, tmp_path):
    # A public→public redirect is allowed (each hop re-validated) and the final body wins.
    opener = _ScriptedOpener(
        [("redirect", "http://public.test/final"), ("body", b"final-body")]
    )
    _use_opener(monkeypatch, opener)
    assert _get("http://public.test/start", tmp_path) == b"final-body"
    assert opener.calls == 2  # both hops were actually requested


# -- streaming (video) fetch: chunk-to-disk, byte-capped, cleaned on failure --


def test_streaming_fetch_writes_to_disk_under_the_cap(
    monkeypatch, allow_public_test, tmp_path
):
    _use_opener(monkeypatch, _ScriptedOpener([("body", b"hello-video-bytes")]))
    dest = tmp_path / "clip.mp4"
    out = _fetch.fetch_to_file_streaming("http://public.test/v", dest, max_bytes=1024)
    assert out == dest and dest.read_bytes() == b"hello-video-bytes"


def test_streaming_fetch_enforces_the_cap_and_cleans_up(
    monkeypatch, allow_public_test, tmp_path
):
    _use_opener(monkeypatch, _ScriptedOpener([("body", b"x" * 5000)]))
    dest = tmp_path / "big.mp4"
    with pytest.raises(_fetch.FetchError, match="limit"):
        _fetch.fetch_to_file_streaming("http://public.test/big", dest, max_bytes=1024)
    assert not dest.exists()  # partial file removed on failure


def test_streaming_fetch_revalidates_a_redirect_to_internal(
    monkeypatch, allow_public_test, tmp_path
):
    _use_opener(
        monkeypatch, _ScriptedOpener([("redirect", "http://169.254.169.254/x")])
    )
    dest = tmp_path / "ssrf.mp4"
    with pytest.raises(_fetch.FetchError):
        _fetch.fetch_to_file_streaming("http://public.test/v", dest, max_bytes=1024)
    assert not dest.exists()


# -- honest permission errors (muvid#23, acceptance criterion 2) ---------------


@pytest.mark.parametrize("code", [401, 403])
def test_an_auth_status_names_the_permission_problem(
    monkeypatch, allow_public_test, tmp_path, code
):
    # A 401/403 is not transient and no URL reformatting fixes it, so it must not
    # collapse into the generic "fetch failed: HTTP {code}" that reads as retryable.
    _use_opener(monkeypatch, _ScriptedOpener([("status", code)]))
    dest = tmp_path / "clip.mp4"
    with pytest.raises(_fetch.PermissionDeniedError) as excinfo:
        _fetch.fetch_to_file_streaming("http://public.test/v", dest, max_bytes=1024)
    message = str(excinfo.value)
    assert "private or not shared" in message
    # Same wording graze uses for the HTML-interstitial half, so the two paths
    # tell the caller to do the same thing.
    assert "anyone-with-the-link" in message  # the fix, not just the diagnosis
    assert not dest.exists()


def test_permission_errors_are_still_caught_as_fetch_errors():
    # A subclass, deliberately: every existing `except FetchError` in the tool layer
    # keeps working, so callers gain the distinction without needing to change.
    assert issubclass(_fetch.PermissionDeniedError, _fetch.FetchError)


# -- the one intake (muvid#293) ----------------------------------------------------


def test_a_folder_link_is_a_typed_refusal_before_any_fetch(monkeypatch):
    def no_fetch(*a, **k):
        raise AssertionError("a folder link must not be fetched")

    monkeypatch.setattr(_fetch, "fetch_to_file_streaming", no_fetch)
    monkeypatch.setattr(
        _fetch, "resolve_share_link", lambda url: ("https://x/folder.zip", "archive")
    )
    with pytest.raises(_fetch.FolderLinkError):
        _fetch.fetch_media("https://drive.example/folders/abc", "/tmp/never")
    assert issubclass(_fetch.FolderLinkError, _fetch.FetchError)  # old excepts still catch


def test_fetch_media_resolves_then_streams_with_the_declared_kind(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(
        _fetch, "resolve_share_link", lambda url: ("https://direct/x.mp3", "file")
    )

    def stream(uri, dest, *, max_bytes, expect_kind=""):
        seen.update(uri=uri, max_bytes=max_bytes, kind=expect_kind)
        return dest

    monkeypatch.setattr(_fetch, "fetch_to_file_streaming", stream)
    out = _fetch.fetch_media("  https://share/x  ", tmp_path / "a", kind="audio")
    assert out == tmp_path / "a"
    assert seen == {"uri": "https://direct/x.mp3", "max_bytes": _fetch.MAX_BYTES, "kind": "audio"}


@pytest.mark.parametrize("bad", ["", "   ", None, 3])
def test_a_missing_link_is_refused_in_words(bad):
    with pytest.raises(_fetch.FetchError, match="http"):
        _fetch.resolve_media_link(bad)
