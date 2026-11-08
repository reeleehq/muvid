"""Which picture is a host-placed visualizer's cover (muvid#311).

The storage object (:class:`~muvid.mcp.workspace.VisualizerProject`) records a cover and
registers it; the POLICY lives here, so a different one is a different function, not a
change to the bucket. Footage's rule for renders (``service.refresh_cover``): the card
shows the NEWEST render, so every render retakes it. Best-effort: a render must not fail
because its poster could not be made (``service._prepare_filmstrip``'s rule), so a failure
leaves the previous cover and is returned, not raised.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def refresh_cover(project, meta: dict) -> Optional[str]:
    """Make this render's picture the project's cover; the artifact id, or ``None``.

    The render's thumbnail (made from the caller's cover image) when it has one, else a
    frame of the video. ``None`` for a project with no catalog (muvid's own bucket) and
    when the picture could not be made.
    """
    if getattr(project, "media_catalog", None) is None:
        return None
    from muvid.footage.service import grab_cover_frame
    from muvid.footage.workspace import fresh_output
    from muvid.visualize.ffmpeg import FfmpegError

    taken_from = f"render:{meta.get('render_id')}"
    try:
        thumbnail = Path(meta.get("thumbnail") or "")
        if thumbnail.is_file():
            return project.set_cover(thumbnail, taken_from=taken_from)
        with fresh_output(project.root / ".cover.frame.jpg") as tmp:
            grab_cover_frame(meta["video"], tmp)
            return project.set_cover(tmp, taken_from=taken_from)
    except (FfmpegError, OSError, ValueError):
        return None
