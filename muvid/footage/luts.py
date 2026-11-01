"""The LUTs a look's ``lut3d`` may load: named in the EDL, found at render (muvid#252).

A look names a LUT by its **name in muvid's LUT folder** (:func:`muvid.paths.lut_dir`)
— ``lut3d=file=warm.cube``, or ``film/warm.cube`` for one in a subfolder — never by a
path on this machine. The split is what muvid#244's review asked for:

- **The EDL gate checks only the text** (:func:`lut_name`, called by
  :func:`muvid.footage.edl._validate_look_luts`). ``validate_edl`` runs on every
  named-edit change, and an edit is a plan: reading the cube there meant a deleted LUT
  made an edit holding it unchangeable, even on an unrelated cut.
- **The assembler resolves the name** (:func:`bind_look_luts`) just before it encodes:
  the file must exist, be a regular file inside the folder once symlinks are resolved,
  and declare ``LUT_3D_SIZE`` at most :data:`MAX_LUT_SIZE`. That is the environment
  refusal, and it sits where the encode is.
- **Nothing persisted carries a host path.** ``edits/*.json`` and a render's
  ``meta.json["edl"]`` keep the name, so an edit survives ``MUVID_DATA_HOME`` moving or
  the project moving to another machine, and a remote caller can name a LUT it found
  through the ``luts`` op (:func:`list_luts`) without learning where the folder is.

The #244 spelling — the cube's absolute path — is no longer accepted: it is the host
path this exists to keep out of stored edits, and it was live for five days during which
no caller could name a LUT at all (the refusal hid the folder and nothing listed it).

Stdlib only, plus :mod:`muvid.paths`: ``edl`` imports this at module top and must stay
import-light.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from muvid.paths import lut_dir

#: The largest ``LUT_3D_SIZE`` a look's ``lut3d`` may load (muvid#244). ``lut3d``'s memory
#: is its cube's, not the frame's: 12 bytes x size^3 — 3.3 MB at 65 (the usual grading
#: size), 201 MB at 256 — so the frame-cost budget cannot see it and this bounds it.
MAX_LUT_SIZE = int(os.environ.get("MUVID_FOOTAGE_MAX_LUT_SIZE", "65"))

#: The suffix a LUT file has (compared without case, as ``.CUBE`` exports exist).
LUT_SUFFIX = ".cube"

#: A LUT's name: ``/``-separated segments of letters, digits, ``.``, ``_`` and ``-``, each
#: starting with a letter, digit or ``_`` (so no ``..``, no hidden file, no absolute
#: path), the last one ending in ``.cube``. Nothing ffmpeg would unescape, quote or split.
_SEGMENT = r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}"
_LUT_NAME = re.compile(rf"(?:{_SEGMENT}/){{0,7}}{_SEGMENT}")
#: The longest LUT name, in characters — far below any filesystem's limit, so a long
#: name is a refusal of the NAME rather than an ``OSError`` carrying the folder's path.
MAX_LUT_NAME_LEN = 255

#: How much of a cube is read looking for its ``LUT_3D_SIZE`` header.
_LUT_HEADER_BYTES = 64 * 1024

#: The most LUTs :func:`list_luts` reports, so a huge folder is not one huge reply.
MAX_LISTED_LUTS = int(os.environ.get("MUVID_FOOTAGE_MAX_LISTED_LUTS", "500"))


class LutError(ValueError):
    """A look names a LUT that cannot be loaded here: absent, outside the folder,
    unreadable, or too large. Raised at render time, never by the EDL gate."""


def _is_name(text: str) -> bool:
    return (
        len(text) <= MAX_LUT_NAME_LEN
        and bool(_LUT_NAME.fullmatch(text))
        and text.lower().endswith(LUT_SUFFIX)
    )


def lut_name(text: str) -> "str | None":
    """``text`` when it is a LUT name — the cube's path relative to
    :func:`muvid.paths.lut_dir` — else ``None``. Reads no file and no environment.

    >>> lut_name("warm.cube"), lut_name("film/Warm-2.CUBE")
    ('warm.cube', 'film/Warm-2.CUBE')
    >>> [lut_name(t) for t in ("../x.cube", ".hidden.cube", "/etc/passwd", "a b.cube",
    ...                        "warm.png", "film//warm.cube", "a" * 300 + ".cube")]
    [None, None, None, None, None, None, None]
    """
    return text if _is_name(text) else None


def cube_size(path) -> "int | None":
    r"""The ``LUT_3D_SIZE`` a ``.cube`` declares in its header, or ``None``.

    >>> import tempfile, pathlib
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = pathlib.Path(d, "a.cube")
    ...     _ = p.write_text("TITLE t\nLUT_3D_SIZE 33\n0 0 0\n")
    ...     cube_size(p)
    33
    """
    with open(path, "rb") as f:
        head = f.read(_LUT_HEADER_BYTES).decode("utf-8", "replace")
    # ffmpeg decides on the FIRST line starting with the keyword, so this does too: a
    # later, smaller declaration must not vouch for a larger first one (#244 review)
    line = next((x for x in head.splitlines() if x.startswith("LUT_3D_SIZE")), None)
    words = line.split() if line else []
    return int(words[1]) if len(words) == 2 and words[1].isdigit() else None


def resolve_lut(name: str) -> Path:
    """The file LUT ``name`` loads, checked: inside the LUT folder once symlinks are
    resolved, a regular file, declaring ``LUT_3D_SIZE`` at most :data:`MAX_LUT_SIZE`.

    Raises :class:`LutError` otherwise. The message names the LUT and never the folder:
    hosted replies carry project-relative paths only.
    """
    return _checked(name)[0]


def _checked(name: str) -> "tuple[Path, int]":
    """:func:`resolve_lut`'s file and the ``LUT_3D_SIZE`` it declares."""
    rel = lut_name(name)
    if rel is None:
        raise LutError(f"{name[:80]!r} is not a LUT name (e.g. warm.cube)")
    try:
        root = lut_dir().resolve()
        path = (root / rel).resolve()
        inside = path.is_relative_to(root) and path.is_file()
        size = cube_size(path) if inside else None
    except OSError:  # never the OSError itself: it carries the folder's path
        raise LutError(f"the LUT {rel!r} cannot be read") from None
    if not inside:
        raise LutError(
            f"there is no LUT named {rel!r} in muvid's LUT folder (``luts`` lists "
            "the ones there are)"
        )
    if size is None:
        raise LutError(f"the LUT {rel!r} declares no LUT_3D_SIZE")
    if size > MAX_LUT_SIZE:
        raise LutError(
            f"the LUT {rel!r} is a {size}-point cube ({12 * size**3 / 1e6:.0f} MB to "
            f"load); muvid loads at most {MAX_LUT_SIZE} points"
        )
    return path, size


def _lut3d_links(look: str):
    """``(link text, head, options)`` for each link of ``look``: ``head`` is the text up
    to and including the link's ``=`` (name and ``@label``) and ``options`` what ffmpeg
    reads (:func:`muvid.footage.edl._link_options`, both escape levels resolved) — for
    ``lut3d`` links only; ``(link, None, None)`` for every other link."""
    from muvid.footage.edl import _link_options, _look_links, _split_significant

    for link, (name, args) in zip(_split_significant(look, ","), _look_links(look)):
        if name != "lut3d":
            yield link, None, None
            continue
        opts, _overflow = _link_options(args, ("file",))  # the gate refused overflow
        head = link[: len(link) - len(args)]
        head = head if head.endswith("=") else head + "="  # a bare `lut3d`
        yield link, head, opts


def _value(text: str) -> str:
    """An option-level value as ffmpeg finally reads it (the second escape level)."""
    from muvid.footage.edl import _strip_unescaped, _unquote

    return _unquote(_strip_unescaped(text))


def look_lut_names(look: "str | None") -> "list[str]":
    """The LUT names ``look``'s ``lut3d`` links load, as ffmpeg reads them (``[]`` for
    none) — the LAST ``file`` of a link, as ``av_opt_set`` keeps the last."""
    return [
        _value(opts["file"])
        for _, head, opts in _lut3d_links(look or "")
        if head is not None and "file" in opts
    ]


def bind_look_luts(look: "str | None") -> "str | None":
    r"""``look`` with each ``lut3d`` link REBUILT from what ffmpeg reads of it, its
    ``file`` the checked file the name loads (:func:`resolve_lut`; raises
    :class:`LutError`) — what the assembler hands ffmpeg. Every other link, and a
    look with no LUT, is returned as written.

    Rebuilt rather than spliced: the options are re-emitted from one parse, so the
    text ffmpeg receives says exactly what the gate read (one ``file``, no escaped
    separator smuggling a second), and the path is escaped at both of ffmpeg's levels.

    >>> bind_look_luts("hue=s=0")
    'hue=s=0'
    >>> bind_look_luts(None) is None
    True
    """
    if not look or not look_lut_names(look):
        return look
    from looks.ffmpeg import GRAPH_LEVEL_SPECIALS, escape_filter_value

    def graph_escaped(text: str) -> str:  # an option-level value, back into the graph
        for char in GRAPH_LEVEL_SPECIALS:
            text = text.replace(char, "\\" + char)
        return text

    from muvid.footage.edl import _LUT3D_OPTIONS

    def rebuilt(head: str, opts: dict) -> str:
        unknown = sorted(set(opts) - _LUT3D_OPTIONS)
        if unknown:  # the gate refuses these; a caller that skipped it does not
            raise LutError(f"lut3d sets {unknown}, which muvid does not offer")
        args = [
            f"file={escape_filter_value(resolve_lut(_value(v)).as_posix())}"
            if k == "file"
            else f"{k}={graph_escaped(v)}"
            for k, v in opts.items()
        ]
        return head + ":".join(args) if args else head.rstrip("=")

    return ",".join(
        link if head is None else rebuilt(head, opts)
        for link, head, opts in _lut3d_links(look)
    )


def check_look_luts(look: "str | None") -> None:
    """Raise :class:`LutError` unless every LUT ``look`` names can be bound here — the
    same code path the assembler runs, with its result discarded."""
    bind_look_luts(look)


def list_luts() -> dict:
    """Every LUT in muvid's LUT folder, by the name a look gives it: ``{"luts": [{name,
    size, usable[, problem]}], "total": n}`` — sorted by name, at most
    :data:`MAX_LISTED_LUTS` rows of ``total``. Empty when the folder does not exist."""
    root = lut_dir()
    names = (
        sorted(
            rel
            for rel in (
                p.relative_to(root).as_posix()
                for p in root.rglob("*")
                if not p.is_dir()  # a folder called x.cube is not a LUT
            )
            if _is_name(rel)
        )
        if root.is_dir()
        else []
    )
    rows = []
    for name in names[:MAX_LISTED_LUTS]:
        try:
            rows.append({"name": name, "size": _checked(name)[1], "usable": True})
        except LutError as e:
            rows.append(
                {"name": name, "size": None, "usable": False, "problem": str(e)}
            )
    return {"luts": rows, "total": len(names)}
