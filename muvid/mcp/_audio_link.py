"""A project's song from a PAGE link — a video or music page, not a media file (muvid#274).

The link-to-audio *policy* lives once, in ``yb``: :func:`yb.download.download_audio_bounded`
refuses a bad target before the network, a playlist, live stream or over-long source
before a byte of media is fetched, caps the size, always yields mp3, and carries a
copyright notice (reeleehq/yb#44, the owner's decision on reeleehq/reelee#676). This is
muvid's thin caller, the same shape as reelee's ``reelee.audio_link``: it supplies
muvid's own SSRF check (:func:`muvid.mcp._fetch._validate_target`) and muvid's song caps,
and hands back the file for :func:`muvid.footage.service.set_song`. yb is called, not
wrapped or re-exposed.

``yb`` with its ``download`` extra (yt-dlp) is an optional install, in no muvid extra
— the same standing as the other sibling packages a caller brings (see the repo
guide). Without it the refusal says what to install.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

#: What to install for page links.
INSTALL_HINT = "pip install 'yb[download]>=0.1.28'"


@dataclass(frozen=True)
class PageAudio:
    """The song a page link yielded: the mp3 (in the caller's ``workdir``), the page's
    title, its duration when the source said, and the notice to store with it."""

    path: Path
    title: str
    duration_s: Optional[float]
    notice: str


class PageAudioUnavailable(RuntimeError):
    """yb (with yt-dlp) is not installed, so a page link cannot be read here."""


def song_from_page_link(
    url: str,
    *,
    workdir: Path,
    max_bytes: int,
    max_duration_s: float,
    download: Optional[Callable] = None,
) -> PageAudio:
    """Download the audio of the page at ``url`` as mp3 into ``workdir`` through yb.

    ``download`` replaces :func:`yb.download.download_audio_bounded` (tests); it takes
    ``(url, download_dir=..., max_bytes=..., max_duration_s=..., validate_target=...)``.
    Refusals propagate as yb raised them: ``ValueError`` for a target muvid refuses or a
    bad cap, ``yb``'s ``AudioLimitError`` (a ``ValueError``) for a playlist, live stream,
    or over-long / over-large source. Raises :class:`PageAudioUnavailable` without yb.
    """
    from muvid.mcp._fetch import _validate_target

    if download is None:
        try:
            # AudioSourceError arrived with the SSRF and unknown-size bounds
            # (reeleehq/yb#56, yb 0.1.28): asked for as a CAPABILITY, so an older yb
            # that would fetch around muvid's guard is refused rather than trusted.
            from yb.download import AudioSourceError  # noqa: F401
            from yb.download import download_audio_bounded as download
        except ImportError as exc:
            raise PageAudioUnavailable(
                f"reading the song from a page link needs yb with yt-dlp: {INSTALL_HINT}"
            ) from exc
    got = download(
        url,
        download_dir=workdir,
        max_bytes=max_bytes,
        max_duration_s=max_duration_s,
        validate_target=_validate_target,
    )
    return PageAudio(
        path=Path(got.path),
        title=got.title or "",
        duration_s=got.duration_s,
        notice=got.notice,
    )
