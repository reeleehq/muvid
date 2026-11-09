"""The host's drawer: muvid projects a HOST placed in the caller's own tree (muvid#296).

A host that serves muvid's genres (reelee's studio and its connector) creates a
``music_video`` or ``music_visualizer`` project where IT keeps the caller's projects —
``nw.create_genre_project(..., projects_dir=<the caller's bucket>)``, a
:class:`muvid.Project` there. muvid's own tools looked only in muvid's data home, so
every ``muvid_*`` tool answered "no such project" for an id the host had just created.

nw carries the host's answer to "where are this caller's projects?" —
``nw.caller_projects_dir(caller)``, registered by the host (placement's dual). This
module turns it into one more DRAWER beside muvid's own: :class:`HostDrawer` is shaped
like a workspace class (``for_email``), and the workspace it returns opens and lists
the host-placed projects of ONE genre, handing back the same production objects
muvid's own drawers do — a project's ``footage``
(:class:`~muvid.footage.workspace.MusicVideoFootageProject`) or ``visualizer``
(:class:`~muvid.mcp.workspace.VisualizerProject`) — owned by the caller.

Three refusals make it safe to put beside the email-scoped drawers, each one the
same ``FileNotFoundError`` ("no such project"), so nothing tells an absent id from
one that is not a muvid project of this genre:

- the folder must be a DIRECT child of the caller's directory (``safe_component``
  plus a resolved-parent check, so a symlinked child cannot lead out of it);
- it must be an nw project (its ``project.json``);
- it must have been created as THIS genre: a reelee ``narrative_video`` id handed to
  a footage tool never sprouts a ``footage/`` folder inside someone's story.

No host registered (or an ``nw`` that predates the locator) means no drawer: an empty
listing and "no such project", exactly the behaviour before. Imports are lazy, so
``import muvid.mcp.host_workspace`` pulls nothing heavy.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from muvid.paths import safe_component


def _nw_locator(email: str) -> Optional[Path]:
    """``nw.caller_projects_dir(email)``, or ``None`` when no host registered one or
    the installed nw predates it."""
    try:
        import nw
    except ImportError:
        return None
    locate = getattr(nw, "caller_projects_dir", None)
    return locate(email) if locate is not None else None


def _envelope_genre(root: Path) -> Optional[str]:
    """The genre ``root`` was created as, from its document mirror (``nw.project_genre``,
    nw#223) WITHOUT opening its graph; ``None`` when unknown — an nw that predates the
    reader, a project whose envelope predates the mirror, or a mirror that cannot be
    read — and the caller falls back to the authoritative read (muvid#339)."""
    try:
        import nw
    except ImportError:
        return None
    read = getattr(nw, "project_genre", None)
    if read is None:
        return None
    try:
        envelope = read(root)
    except Exception:  # noqa: BLE001 - a neighbour's unreadable mirror is "unknown"
        return None
    genre = envelope.get("genre") if isinstance(envelope, dict) else None
    return genre if isinstance(genre, str) and genre else None


def _footage_of(project, email: str):
    return dataclasses.replace(project.footage, email=email)


def _visualizer_of(project, email: str):
    return dataclasses.replace(project.visualizer, email=email)


#: How each genre's production is taken from a host-placed :class:`muvid.Project`.
PRODUCTIONS: "dict[str, Callable]" = {
    "music_video": _footage_of,
    "music_visualizer": _visualizer_of,
}


@dataclass(frozen=True)
class HostWorkspace:
    """One caller's host-placed projects of one genre (see the module docstring)."""

    email: str
    genre: str
    projects_dir: Optional[Path]

    def _project(self, project_id: str):
        """The host-placed :class:`muvid.Project` of this genre, or ``FileNotFoundError``."""
        from nw.storage import PROJECT_FILE_NAME

        from muvid.production import Project

        missing = FileNotFoundError(f"no project {project_id!r} for {self.email}")
        if self.projects_dir is None:
            raise missing
        pid = safe_component(project_id, label="project_id")
        root = self.projects_dir / pid
        try:
            inside = root.resolve().parent == self.projects_dir.resolve()
        except OSError:
            inside = False
        if not (inside and (root / PROJECT_FILE_NAME).is_file()):
            raise missing
        # Classify from the document mirror first: a bucket of N projects of other genres
        # then costs N small reads, not N graph opens (any of which can fail on a graph
        # the host has locked), and only a project of THIS genre is opened (muvid#339).
        known = _envelope_genre(root)
        if known is not None and known != self.genre:
            raise missing
        try:
            project = Project(root, auto_migrate=False)
            genre = known or project.genre
        except Exception as e:  # noqa: BLE001 - see below
            # A neighbour's graph that cannot be read (corrupt, or locked while the
            # host writes it) is not a project this drawer can serve; letting its
            # sqlite error out would fail every listing of the caller's OWN muvid
            # projects because of a project that is not muvid's (#296 review).
            raise missing from e
        if genre != self.genre:
            raise missing
        return project

    def open_project(self, project_id: str):
        """The caller's production in the host-placed project ``project_id``."""
        return PRODUCTIONS[self.genre](self._project(project_id), self.email)

    def list_projects(self) -> list[dict]:
        """``[{project_id, title, created, modified}]`` of this genre, newest first."""
        if self.projects_dir is None or not self.projects_dir.is_dir():
            return []
        rows = []
        for child in self.projects_dir.iterdir():
            try:
                project = self._project(child.name)
                modified = child.stat().st_mtime
            except (ValueError, OSError):  # FileNotFoundError is an OSError
                continue  # not one of ours, unreadable, or vanished mid-scan
            rows.append(
                {
                    "project_id": child.name,
                    "title": project.title,
                    "created": None,
                    "modified": modified,
                }
            )
        rows.sort(key=lambda r: r["modified"], reverse=True)
        return rows


@dataclass(frozen=True)
class HostDrawer:
    """A drawer of host-placed projects of ``genre``, shaped like a workspace class.

    ``locate`` is the seam: the caller's projects directory, default the host's
    registration in nw (``nw.caller_projects_dir``).
    """

    genre: str
    locate: Callable[[str], Optional[Path]] = _nw_locator

    def for_email(self, email: str) -> HostWorkspace:
        found = self.locate(email)
        return HostWorkspace(
            email=email,
            genre=self.genre,
            projects_dir=Path(found) if found is not None else None,
        )
