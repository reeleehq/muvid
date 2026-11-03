"""Generic MCP tools over the subgenre plugin surface.

Two free tools that make ANY installed subgenre reachable from a host
connector without muvid knowing it exists:

* :func:`list_subgenres` — the catalogue, import-free.
* :func:`render_subgenre` — render one, with every file input fetched through
  the SSRF-guarded, size-bounded, workspace-scoped ``_resolve_input`` and the
  request validated against the manifest's own schema before any plugin code
  is imported.

A third-party subgenre gets this transport for free; muvid's own
``lyric-video`` keeps its richer dedicated tools alongside.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from muvid.mcp.identity import current_email
from muvid.mcp.tools import _download_claim, _resolve_input, _tool_error
from muvid.mcp.workspace import open_subgenre_project

__all__ = ["list_subgenres", "render_subgenre"]

#: Inputs whose values are file references (fetched) rather than primitives
#: are identified by the manifest: a property with ``"format": "path"`` or a
#: declared media kind (``x-muvid-kind`` / ``contentMediaType``, muvid#293), OR —
#: the backstop for a plugin that declares nothing — a name in this set, fetched
#: through _resolve_input. Everything else is passed through as-is after schema
#: validation.
_FILE_INPUT_NAMES = frozenset(
    {
        "audio",
        "lyrics",
        "subtitles",
        "cover",
        "image",
        "reference_image",
        "clip",
        "video",
        # the list-valued pools (muvid#23 review): a plugin that forgets
        # `format: path` must not hand raw strings to its renderer
        "photos",
        "clips",
        "images",
        "videos",
    }
)

#: Inputs that name a SERVER path by design (lyric-video's ``project``: an existing
#: muvid project folder). A remote caller never names a server file, so the transport
#: refuses them rather than passing a host path through.
_HOST_ONLY_INPUT_NAMES = frozenset({"project"})

#: A plugin may declare list-valued file inputs (photos[], clips[]); cap them.
MAX_FILE_INPUTS = int(os.environ.get("MUVID_SUBGENRE_MAX_FILE_INPUTS", "64"))


def list_subgenres() -> dict:
    """List every installed subgenre with its input/param schemas. Free.

    Imports no rendering code — a broken plugin appears under ``load_errors``
    rather than breaking the list.
    """
    from muvid.subgenres import subgenre_catalog

    return subgenre_catalog()


#: The media kinds an input may declare (``x-muvid-kind``), ``""`` meaning "a file,
#: but nothing to assert about its bytes" (lyrics text, a subgenre's own format).
MEDIA_KINDS = ("audio", "video", "image", "")


def _property(name: str, schema: dict) -> dict:
    """The JSON-schema property of input ``name`` — its ``items`` for a list input."""
    prop = (schema.get("properties") or {}).get(name) or {}
    return (prop.get("items") or {}) if prop.get("type") == "array" else prop


def _declared_kind(name: str, schema: dict) -> "str | None":
    """The media kind input ``name`` DECLARES, or ``None`` when it declares none
    (muvid#293): ``x-muvid-kind`` (one of :data:`MEDIA_KINDS`), else JSON Schema's
    ``contentMediaType`` (``audio/*`` → ``audio``, a type outside the three → ``""``).
    Declared beats the input's name, so a plugin's ``song`` input is checked as audio
    though no name table lists it."""
    prop = _property(name, schema)
    kind = prop.get("x-muvid-kind")
    if kind is not None:
        if kind not in MEDIA_KINDS:
            raise ValueError(
                f"input {name!r} declares x-muvid-kind {kind!r}; one of {MEDIA_KINDS}"
            )
        return kind
    media = prop.get("contentMediaType")
    if isinstance(media, str) and media:
        top = media.split("/", 1)[0]
        return top if top in ("audio", "video", "image") else ""
    return None


def _is_file_input(name: str, schema: dict) -> bool:
    """Whether input ``name`` is a file reference to fetch: its schema says so
    (``format: path``, or a declared kind), else its name is a known file input —
    the backstop for a plugin that declares nothing."""
    prop = _property(name, schema)
    if prop.get("format") == "path" or _declared_kind(name, schema) is not None:
        return True
    return name in _FILE_INPUT_NAMES


def render_subgenre(
    project_id: str,
    *,
    subgenre: str,
    inputs: dict,
    params: dict | None = None,
) -> dict:
    """Render one installed subgenre into the caller's project. Free.

    ``inputs`` are the manifest's declared inputs; any file-valued one is an
    http(s) URL fetched into the caller's workspace (never a host path).
    ``params`` are validated against the manifest's ``params_schema``.
    """
    from muvid.subgenres import get_subgenre
    from muvid.subgenres import render_subgenre as _render
    from muvid.subgenres._schema import SchemaError

    if not isinstance(inputs, dict):
        raise _tool_error("inputs must be a JSON object")
    try:
        manifest = get_subgenre(subgenre)
    except KeyError as exc:
        raise _tool_error(str(exc)) from exc
    if manifest.cost_profile is not None:
        # The generic tool is FREE by declaration; a costed subgenre needs its
        # own metered tool, because a host meters by tool name.
        raise _tool_error(
            f"subgenre {subgenre!r} declares a cost profile and cannot be rendered "
            "through the free generic tool"
        )

    host_only = sorted(set(inputs) & _HOST_ONLY_INPUT_NAMES)
    if host_only:  # before any project is opened or folder made
        raise _tool_error(
            f"input {host_only[0]!r} names a folder on the server, which a remote "
            "caller cannot do; leave it out"
        )

    # Its own bucket, else a visualizer one of that id (every pre-muvid#103 project).
    try:
        proj = open_subgenre_project(manifest.slug, current_email(), project_id)
    except ValueError as exc:  # a reserved or unusable slug, or a bad project_id
        raise _tool_error(str(exc)) from exc
    import uuid

    render_id = uuid.uuid4().hex[:12]
    render_dir = proj.new_render_dir(render_id)
    fetch_dir = render_dir / "inputs"
    fetch_dir.mkdir(parents=True, exist_ok=True)

    resolved: dict[str, Any] = {}
    n_files = 0
    for name, value in inputs.items():
        if _is_file_input(name, manifest.inputs or {}):
            values = value if isinstance(value, list) else [value]
            fetched = []
            for i, url in enumerate(values):
                n_files += 1
                if n_files > MAX_FILE_INPUTS:
                    raise _tool_error(f"more than {MAX_FILE_INPUTS} file inputs")
                fetched.append(
                    str(
                        _resolve_input(
                            url,
                            fetch_dir / f"{name}-{i}",
                            label=name,
                            kind=_declared_kind(name, manifest.inputs or {}),
                        )
                    )
                )
            resolved[name] = fetched if isinstance(value, list) else fetched[0]
        else:
            resolved[name] = value

    ext = {
        "video/mp4": "mp4",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
        "audio/mpeg": "mp3",
    }.get(manifest.produces, "bin")
    out = render_dir / f"video.{ext}"
    try:
        result = _render(
            subgenre,
            inputs=resolved,
            params=params or {},
            workdir=render_dir / "work",
            output=out,
        )
    except SchemaError as exc:
        raise _tool_error(
            "request does not satisfy the subgenre's schema: " + "; ".join(exc.errors)
        ) from exc
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        raise _tool_error(f"render refused: {exc}") from exc

    meta = {
        "render_id": render_id,
        "subgenre": subgenre,
        "video": str(result.output),
        "duration": result.duration_s,
        "artifacts": {k: str(v) for k, v in result.artifacts.items()},
        "meta": dict(result.meta),
        "download": _download_claim(project_id, render_id),
        "note": (
            f"Call `reelee_get_download_url(genre='muvid', project_id='{project_id}', "
            f"artifact_id='{render_id}')` for a link to watch and download this."
        ),
    }
    proj.write_render_meta(render_id, meta)
    return meta
