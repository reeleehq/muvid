"""When a photo or a video was taken, read from the file itself (muvid#137).

"Cut to the music" should let a day read in order, as Apple Memories and GoPro Quik do, so
each clip row carries the time its file says it was captured: EXIF ``DateTimeOriginal``
for a photo, the QuickTime ``creationdate`` (else ``creation_time``) tag for a video.

**Times are wall-clock seconds, not instants.** A camera writes the local time it showed
and (for EXIF) no zone, so every source here is reduced to the same thing — the time on
the wall clock, read as if it were UTC — which makes a photo and a video from one phone
comparable. A video that only carries a UTC ``creation_time`` is the exception and is
compared as is (off by the zone offset from the photos beside it); the ``source`` returned
beside the time says which tag it came from so a caller can tell.

**Absent is not zero.** A file with no tag, a tag that is not a date, or one before
:data:`MIN_PLAUSIBLE_YEAR` (cameras without a clock write 1904 or 1970) gives ``None`` —
never a made-up time. Reading is best effort and must never fail an upload.
"""

from __future__ import annotations

import calendar
import json
import re
import subprocess
from pathlib import Path
from typing import Optional

#: A capture time earlier than this year is a camera with no clock set, not a date.
MIN_PLAUSIBLE_YEAR = 1990
#: Seconds ffprobe may spend on one file.
PROBE_TIMEOUT_S = 20.0
#: ``source`` values of a returned time.
EXIF_ORIGINAL, EXIF_DATETIME = "exif:DateTimeOriginal", "exif:DateTime"
QT_CREATIONDATE, CREATION_TIME = "quicktime:creationdate", "creation_time"

_EXIF_DATETIME_ORIGINAL, _EXIF_DATETIME, _EXIF_IFD = 36867, 306, 0x8769
_STAMP = re.compile(r"^\s*(\d{4})[:\-](\d{2})[:\-](\d{2})[T ](\d{2}):(\d{2}):(\d{2})")


def wall_clock_seconds(text: str) -> Optional[float]:
    """Seconds since 1970 of the wall-clock stamp in ``text``; any zone suffix is ignored.

    >>> wall_clock_seconds("2024:06:01 14:03:22")
    1717250602.0
    >>> wall_clock_seconds("2024-06-01T14:03:22-0700") == wall_clock_seconds("2024:06:01 14:03:22")
    True
    >>> wall_clock_seconds("0000:00:00 00:00:00") is None, wall_clock_seconds("nope") is None
    (True, True)
    """
    m = _STAMP.match(str(text or ""))
    if not m:
        return None
    y, mo, d, h, mi, s = (int(g) for g in m.groups())
    if y < MIN_PLAUSIBLE_YEAR or not 1 <= mo <= 12:
        return None
    if not (1 <= d <= calendar.monthrange(y, mo)[1] and h < 24 and mi < 60 and s < 61):
        return None
    try:
        return float(calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0)))
    except (ValueError, OverflowError):
        return None


def photo_capture_time(image) -> tuple[Optional[float], str]:
    """``(time, source)`` from an open PIL image's EXIF."""
    try:
        exif = image.getexif()
        original = exif.get_ifd(_EXIF_IFD).get(_EXIF_DATETIME_ORIGINAL)
        for tag, source in (
            (original, EXIF_ORIGINAL),
            (exif.get(_EXIF_DATETIME), EXIF_DATETIME),
        ):
            t = wall_clock_seconds(tag) if tag else None
            if t is not None:
                return t, source
    except Exception:  # noqa: BLE001 — a damaged EXIF block is "no time", never a failed upload
        pass
    return None, ""


def video_capture_time(path: Path | str) -> tuple[Optional[float], str]:
    """``(time, source)`` from a video's container tags (``ffprobe``)."""
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format_tags:stream_tags",
                "-of",
                "json",
                str(Path(path).resolve()),  # absolute: a name starting "-" is no option
            ],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
        )
        doc = json.loads(out.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, ""  # no ffprobe, a hung probe, unparseable output: no time
    tags: dict[str, str] = {}
    for bag in [doc.get("format", {}).get("tags", {})] + [
        s.get("tags", {}) for s in doc.get("streams", [])
    ]:
        for key, value in (bag or {}).items():
            tags.setdefault(str(key).lower(), str(value))
    # the QuickTime tag carries the LOCAL time (with its offset); creation_time is UTC
    for key, source in (
        ("com.apple.quicktime.creationdate", QT_CREATIONDATE),
        ("creation_time", CREATION_TIME),
    ):
        t = wall_clock_seconds(tags[key]) if key in tags else None
        if t is not None:
            return t, source
    return None, ""
