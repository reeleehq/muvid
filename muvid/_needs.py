"""Say which extra a module needs when its import of ``nw`` would fail (muvid#368).

``nw`` is declared only in muvid's ``[mcp]`` extra, deliberately: it brings falaw,
lacing and pydantic to an ffmpeg-only core (muvid#248). The modules that register nw
genres or speak nw's delivery types import it at module top, so an environment with
muvid but without that extra used to get a bare ``ModuleNotFoundError: nw``. The
failure stays an import failure (the right one: a half-registered genre is worse),
but it now names the remedy.
"""

from __future__ import annotations

import importlib.util

#: The extra that carries nw; the one place the remedy names it.
NW_EXTRA = "mcp"


def require_nw(*, needed_by: str) -> None:
    """Raise an ImportError naming the extra to add when ``nw`` is absent."""
    if importlib.util.find_spec("nw") is None:
        raise ImportError(
            f"{needed_by} needs the 'nw' package, which muvid declares only in its "
            f"{NW_EXTRA!r} extra: add that extra, i.e. the requirement 'muvid[{NW_EXTRA}]'"
        )
