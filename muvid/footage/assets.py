"""Bind an asset that is already in one of the caller's projects into another (muvid#22).

A song or a clip is identified by the SHA-256 of its bytes — the ``asset_id`` a
``set_song`` / ``add_footage`` reply returns (it equals ``artifact_id`` in a hosted
project's catalog). Handing that id to ``set_song(asset_id=...)`` or
``add_footage(asset_id=...)`` takes the file from where it already is, with no network
fetch, and the new project's copy is a HARDLINK of it (:func:`~muvid.footage.workspace.
replace_file` ``link=True``): the same asset bound to two projects is stored once. Nothing
ever writes into a stored media file in place (every rewrite is a new inode), so two
projects sharing one inode cannot change each other's bytes, and removing a clip from one
project leaves the other's.

*Where* an asset is looked for is a seam, :func:`register_asset_resolver` — the house
idiom (``register_visual``, ``register_aligner``): a resolver is
``(email, asset_id, kind) -> Path | None``, tried in order. The default, :func:`own_projects`,
searches the caller's own footage projects (muvid's and a host's); a library that holds
assets outside any project (braidio's, muvid#7) registers its own and ``muvid`` needs no
import of it.

Only an asset whose hash was recorded is found: a clip's ``hash`` is recorded when it is
added (and by the first filmstrip or beat measurement of an older one), a song's
``song_hash`` always. Never hashed on a lookup — that would read every file of every
project of the caller.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from muvid.footage.errors import FootageError

#: ``(email, asset_id, kind) -> the file | None``; ``kind`` is ``"audio"`` (a song) or
#: ``"video"`` (a clip).
AssetResolver = Callable[[str, str, str], Optional[Path]]

#: The kinds an asset can be bound as, each with the sentence naming it in a refusal.
ASSET_KINDS = {"audio": "song", "video": "video"}

_RESOLVERS: list[AssetResolver] = []


def register_asset_resolver(resolver: AssetResolver, *, first: bool = False) -> None:
    """Add ``resolver`` to the ones :func:`resolve_asset` tries (last, or ``first``).
    Registering the same callable twice is a no-op."""
    if resolver in _RESOLVERS:
        return
    _RESOLVERS.insert(0, resolver) if first else _RESOLVERS.append(resolver)


def resolve_asset(email: str, asset_id: str, *, kind: str) -> Path:
    """The file of asset ``asset_id`` as ``kind`` for this caller; ``FootageError`` when
    no resolver finds it. The refusal does not say whose project holds it, or whether
    another caller's does (the existence of someone else's asset is not the caller's to
    learn)."""
    if kind not in ASSET_KINDS:
        raise ValueError(f"kind is one of {sorted(ASSET_KINDS)}, got {kind!r}")
    wanted = (asset_id or "").strip().lower()
    if not _looks_like_a_hash(wanted):
        raise FootageError(
            "an asset_id is the 64-character SHA-256 of the file — the `asset_id` that "
            "set_song and add_footage return"
        )
    for resolver in (*_RESOLVERS, own_projects):
        found = resolver(email, wanted, kind)
        if found is not None and Path(found).is_file():
            return Path(found)
    raise FootageError(
        f"no {ASSET_KINDS[kind]} with that asset_id in your projects — use `url` to "
        "bring it in"
    )


def _looks_like_a_hash(text: str) -> bool:
    return len(text) == 64 and all(c in "0123456789abcdef" for c in text)


def own_projects(email: str, asset_id: str, kind: str) -> Optional[Path]:
    """The default resolver: the caller's own footage projects, muvid's drawer then a
    host's, by the hashes their manifests recorded."""
    from muvid.downloads import caller_workspaces

    for ws in caller_workspaces(email, "footage"):
        for row in ws.list_projects():
            try:
                proj = ws.open_project(row["project_id"])
            except (FileNotFoundError, ValueError):
                continue  # vanished mid-scan, or not a project of this genre
            found = _in_project(proj, asset_id, kind)
            if found is not None:
                return found
    return None


def _in_project(proj, asset_id: str, kind: str) -> Optional[Path]:
    manifest = proj.manifest()
    if kind == "audio":
        if manifest.get("song_hash") == asset_id and proj.has_song():
            return proj.song_path()
        return None
    paths = proj.clip_paths()
    for clip in manifest.get("clips", []):
        if (
            clip.get("hash") == asset_id
            and clip.get("kind") != "still"
            and clip.get("clip_id") in paths
        ):
            return Path(paths[clip["clip_id"]])
    return None
