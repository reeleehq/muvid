"""Per-user output bucket for the muvid ``music_visualizer`` MCP genre.

A remote MCP connector is stateless and multi-user, so each caller must be isolated
and address work by ``project_id`` (never a path). The visualizer is itself stateless
— a render is a pure function of (audio, cover, visual) — so a "project" here is just a
**lightweight bucket** where a caller's renders land, not a full nw/muvid project (no
graph, no asset store). That keeps the ``music_visualizer`` genre the cheapest possible
2nd genre (thorwhalen/muvid#3); a richer per-user asset library (content-addressed
uploads shared across genres) is a deliberate follow-up.

Layout (default root ``~/.local/share/muvid``; override via ``MUVID_DATA_HOME``):

- ``{root}/visualizer/projects/{email}/{project_id}/manifest.json`` — the bucket
- ``{root}/visualizer/projects/{email}/{project_id}/renders/{render_id}/`` — one render
  (its ``.mp4``, optional ``thumbnail.jpg``, and a ``meta.json`` sidecar)

Every **subgenre** (``lyric-video`` and anything bridged by ``muvid.genre_subgenres``)
gets the same kind of bucket in a directory that names it (muvid#103), so its project
ids are its own and a listing can label it:

- ``{root}/subgenres/{slug}/projects/{email}/{project_id}/`` — :class:`SubgenreWorkspace`

Before muvid#103 subgenre projects were created in the visualizer workspace, sharing its
id space and its ``visualizer`` label. Those projects are not moved: every subgenre tool
opens through :func:`open_subgenre_project`, which falls back to the visualizer bucket of
the same id, so an old project id keeps working exactly as before.

Per the app-data-lifecycle rule this lives in the user-data dir, **never** inside the
app/deploy tree (a deploy's ``rsync --delete`` would erase it).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from muvid.paths import (
    DATA_HOME_ENV_VAR as _DATA_HOME_ENV_VAR,
    data_home,
    safe_component,
)

#: Env var overriding the muvid data root (where per-user visualizer buckets live).
#: Re-exported from :mod:`muvid.paths`, the SSOT — this module used to carry its own
#: verbatim copy of both, beside a second copy in ``muvid/footage/workspace.py``.
DATA_HOME_ENV_VAR = _DATA_HOME_ENV_VAR


def data_root() -> Path:
    """The muvid data root: ``$MUVID_DATA_HOME`` or ``~/.local/share/muvid``.

    Public API (``muvid.mcp`` re-exports it), so the name stays though the body moved.
    A forwarder, not an alias, for the introspection reason given on the footage twin.
    """
    return data_home()


#: Module-private, so an alias is fine here — nothing documents or introspects it.
_safe_component = safe_component


@dataclass(frozen=True)
class VisualizerProject:
    """One caller's visualizer bucket — a folder its renders land in.

    ``root`` is exposed so ``nw.create_genre_project``'s all-or-nothing rollback
    (``nw.genres._rollback_project`` removes ``project.root``) reverts a half-created
    bucket. Kept storage-only: no nw graph, no asset library.
    """

    email: str
    project_id: str
    root: Path

    @property
    def renders_dir(self) -> Path:
        return self.root / "renders"

    def manifest(self) -> dict:
        spec = self.root / "manifest.json"
        try:
            return json.loads(spec.read_text())
        except (OSError, ValueError):
            return {"title": self.project_id}

    def new_render_dir(self, render_id: str) -> Path:
        """Create + return a fresh directory for one render (traversal-checked id)."""
        rid = _safe_component(render_id, label="render_id")
        d = self.renders_dir / rid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_render_meta(self, render_id: str, meta: dict) -> None:
        rid = _safe_component(render_id, label="render_id")
        (self.renders_dir / rid / "meta.json").write_text(json.dumps(meta, indent=2))

    def list_renders(self) -> list[dict]:
        """This bucket's renders (newest-first), from each render's ``meta.json``."""
        rdir = self.renders_dir
        if not rdir.exists():
            return []
        rows = []
        for child in sorted(rdir.iterdir()):
            meta = child / "meta.json"
            if not (child.is_dir() and meta.exists()):
                continue
            try:
                row = json.loads(meta.read_text())
            except (OSError, ValueError):
                row = {"render_id": child.name}
            row.setdefault("render_id", child.name)
            row["_mtime"] = meta.stat().st_mtime
            rows.append(row)
        rows.sort(key=lambda r: r.pop("_mtime"), reverse=True)
        return rows


@dataclass(frozen=True)
class VisualizerWorkspace:
    """A single caller's private visualizer area, addressed by ``email``.

    ``email`` and every ``project_id`` are validated as single path components, so a
    caller can never escape their own subtree.
    """

    email: str
    root: Path

    @classmethod
    def for_email(
        cls, email: str, *, root: Path | None = None
    ) -> "VisualizerWorkspace":
        return cls(email=email, root=root or data_root())

    @property
    def projects_dir(self) -> Path:
        return (
            self.root
            / "visualizer"
            / "projects"
            / _safe_component(self.email, label="email")
        )

    def project_root(self, project_id: str) -> Path:
        pid = _safe_component(project_id, label="project_id")
        return self.projects_dir / pid

    def create_project(
        self, project_id: str, *, title: str = "", force: bool = False
    ) -> VisualizerProject:
        """Create (and return) a new visualizer bucket under this user."""
        root = self.project_root(project_id)
        if root.exists() and not force:
            raise FileExistsError(
                f"project {project_id!r} already exists for {self.email}"
            )
        (root / "renders").mkdir(parents=True, exist_ok=True)
        (root / "manifest.json").write_text(
            json.dumps({"title": title or project_id, "created": time.time()}, indent=2)
        )
        return VisualizerProject(email=self.email, project_id=project_id, root=root)

    def open_project(self, project_id: str) -> VisualizerProject:
        """Open an existing visualizer bucket (raises if it doesn't exist)."""
        root = self.project_root(project_id)
        if not (root / "manifest.json").exists():
            raise FileNotFoundError(f"no project {project_id!r} for {self.email}")
        return VisualizerProject(email=self.email, project_id=project_id, root=root)

    def list_projects(self) -> list[dict]:
        """This user's buckets: ``[{project_id, title}]`` (newest-modified first)."""
        pdir = self.projects_dir
        if not pdir.exists():
            return []
        rows = []
        for child in pdir.iterdir():
            spec = child / "manifest.json"
            if not (child.is_dir() and spec.exists()):
                continue
            try:
                manifest = json.loads(spec.read_text())
                if not isinstance(manifest, dict):
                    manifest = {}
            except (OSError, ValueError):
                manifest = {}
            try:
                mtime = spec.stat().st_mtime
            except OSError:
                continue  # vanished mid-scan
            rows.append(
                {
                    "project_id": child.name,
                    "title": manifest.get("title") or child.name,
                    "created": manifest.get("created"),
                    "modified": mtime,
                }
            )
        rows.sort(key=lambda r: r["modified"], reverse=True)
        return rows


#: The path segment under the data root that holds one directory per subgenre (muvid#103).
SUBGENRES_SEGMENT = "subgenres"

# Drawer names a subgenre slug may not take. The set is defined beside the
# manifest (muvid#167) so a plugin is refused before it reaches a project; the
# name stays importable from here.
from muvid.subgenres._manifest import RESERVED_SLUGS  # noqa: E402


@dataclass(frozen=True)
class SubgenreWorkspace(VisualizerWorkspace):
    """A single caller's area for ONE subgenre: the visualizer's bucket, in its own directory.

    A subgenre is stateless the way the visualizer is (a "project" is where renders
    land), so the bucket is the same :class:`VisualizerProject`; only the directory
    differs, which gives each subgenre its own project-id space and a path that names
    it (muvid#103). Built with :meth:`for_slug`, never :meth:`for_email`.
    """

    slug: str

    @classmethod
    def for_slug(
        cls, slug: str, email: str, *, root: Path | None = None
    ) -> "SubgenreWorkspace":
        if slug in RESERVED_SLUGS:
            raise ValueError(
                f"subgenre slug {slug!r} is reserved for a built-in muvid drawer"
            )
        return cls(email=email, root=root or data_root(), slug=slug)

    def create_project(
        self, project_id: str, *, title: str = "", force: bool = False
    ) -> VisualizerProject:
        """Create a bucket, refusing to fork one this subgenre already made.

        Before muvid#103 this subgenre's projects were made in the visualizer
        drawer. Creating the same id here would succeed and shadow it: the
        subgenre's tools would open the new, empty bucket, and the old renders
        would drop out of their reach. So an id whose visualizer bucket holds
        only this subgenre's renders is refused, as it was before.
        """
        if not force:
            try:
                old = VisualizerWorkspace.for_email(
                    self.email, root=self.root
                ).open_project(project_id)
            except FileNotFoundError:
                old = None
            if old is not None and bucket_label(old) == self.slug:
                raise FileExistsError(
                    f"project {project_id!r} already exists for {self.email}"
                )
        return super().create_project(project_id, title=title, force=force)

    @classmethod
    def for_email(cls, email: str, *, root: Path | None = None):
        raise TypeError(
            "a SubgenreWorkspace belongs to one subgenre: use "
            "SubgenreWorkspace.for_slug(slug, email)"
        )

    @property
    def projects_dir(self) -> Path:
        return (
            self.root
            / SUBGENRES_SEGMENT
            / _safe_component(self.slug, label="subgenre")
            / "projects"
            / _safe_component(self.email, label="email")
        )


def subgenre_slugs_on_disk(*, root: Path | None = None) -> tuple[str, ...]:
    """The subgenres that have a directory under the data root, sorted.

    Read from disk rather than from the installed plugins, so a project made by a
    subgenre that has since been uninstalled is still listed and downloadable.
    """
    base = (root or data_root()) / SUBGENRES_SEGMENT
    if not base.is_dir():
        return ()
    out = []
    for child in base.iterdir():
        try:
            if (
                child.is_dir()
                and _safe_component(child.name, label="subgenre") == child.name
            ):
                out.append(child.name)
        except ValueError:
            continue
    return tuple(sorted(out))


def open_subgenre_project(
    slug: str, email: str, project_id: str, *, root: Path | None = None
) -> VisualizerProject:
    """The bucket a subgenre renders into: its own, else a visualizer bucket of that id.

    The fallback is what keeps every project made before muvid#103 (and every
    visualizer project a caller already rendered a lyric video into) working: those
    live in the visualizer workspace and are read in place, never moved.
    """
    try:
        return SubgenreWorkspace.for_slug(slug, email, root=root).open_project(
            project_id
        )
    except FileNotFoundError:
        return VisualizerWorkspace.for_email(email, root=root).open_project(project_id)


def subgenre_of_render(meta: dict) -> str | None:
    """The subgenre a render's ``meta.json`` says made it, if it says.

    ``render_subgenre`` records ``subgenre`` (checked first, so a choreo or montage
    render, whose own meta also carries ``treatment_source``, is named correctly).
    ``render_lyric_video`` records no ``subgenre``; its nested pipeline meta has
    ``treatment_source``, which no visualizer render carries.
    """
    named = meta.get("subgenre")
    if isinstance(named, str) and named:
        # A name that could not be a subgenre drawer is not evidence of one.
        try:
            ok = _safe_component(named, label="subgenre") == named
        except ValueError:
            ok = False
        return named if ok and named not in RESERVED_SLUGS else None
    inner = meta.get("meta")
    if isinstance(inner, dict) and "treatment_source" in inner:
        from muvid.lyricvid.manifest import SLUG

        return SLUG
    return None


def bucket_label(proj: VisualizerProject) -> str:
    """What a visualizer-drawer bucket holds: ``"visualizer"``, or the one subgenre
    whose work is all it holds.

    Before muvid#103 subgenre projects lived in this drawer, so the drawer cannot
    label them; their renders can. Evidence is each finished render's
    ``meta.json`` (a render folder without one is a render that failed or is
    still running, and says nothing), plus the ``lyricvid/`` folder the lyric
    tools fetch their inputs into. A bucket with no evidence, or one that mixes
    visualizer and subgenre work (allowed before and after muvid#103), stays
    ``"visualizer"``. Read-only: nothing is moved or rewritten.
    """
    from muvid.lyricvid.manifest import SLUG as lyric_slug

    kinds = set()
    if (proj.root / "lyricvid").is_dir():
        kinds.add(lyric_slug)
    rdir = proj.renders_dir
    for child in rdir.iterdir() if rdir.is_dir() else ():
        spec = child / "meta.json"
        if not (child.is_dir() and spec.is_file()):
            continue
        try:
            meta = json.loads(spec.read_text())
        except (OSError, ValueError):
            continue
        kinds.add(
            subgenre_of_render(meta if isinstance(meta, dict) else {}) or "visualizer"
        )
    return kinds.pop() if len(kinds) == 1 else "visualizer"
