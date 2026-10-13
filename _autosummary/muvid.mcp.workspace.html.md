# muvid.mcp.workspace

Per-user output bucket for the muvid `music-visualizer` MCP genre.

A remote MCP connector is stateless and multi-user, so each caller must be isolated
and address work by `project_id` (never a path). The visualizer is itself stateless
— a render is a pure function of (audio, cover, visual) — so a “project” here is just a
**lightweight bucket** where a caller’s renders land, not a full nw/muvid project (no
graph, no asset store). That keeps the `music-visualizer` genre the cheapest possible
2nd genre (thorwhalen/muvid#3); a richer per-user asset library (content-addressed
uploads shared across genres) is a deliberate follow-up.

Layout (default root `~/.local/share/muvid`; override via `MUVID_DATA_HOME`):

- `{root}/visualizer/projects/{email}/{project_id}/manifest.json` — the bucket
- `{root}/visualizer/projects/{email}/{project_id}/renders/{render_id}/` — one render
  (its `.mp4`, optional `thumbnail.jpg`, and a `meta.json` sidecar)

Every **subgenre** (`lyric-video` and anything bridged by `muvid.genre_subgenres`)
gets the same kind of bucket in a directory that names it (muvid#103), so its project
ids are its own and a listing can label it:

- `{root}/subgenres/{slug}/projects/{email}/{project_id}/` — [`SubgenreWorkspace`](#muvid.mcp.workspace.SubgenreWorkspace)

Before muvid#103 subgenre projects were created in the visualizer workspace, sharing its
id space and its `visualizer` label. Those projects are not moved: every subgenre tool
opens through [`open_subgenre_project()`](#muvid.mcp.workspace.open_subgenre_project), which falls back to the visualizer bucket of
the same id, so an old project id keeps working exactly as before.

Per the app-data-lifecycle rule this lives in the user-data dir, **never** inside the
app/deploy tree (a deploy’s `rsync --delete` would erase it).

### Module Attributes

| [`DATA_HOME_ENV_VAR`](#muvid.mcp.workspace.DATA_HOME_ENV_VAR)   | Env var overriding the muvid data root (where per-user visualizer buckets live).        |
|----------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| [`SUBGENRES_SEGMENT`](#muvid.mcp.workspace.SUBGENRES_SEGMENT)   | The path segment under the data root that holds one directory per subgenre (muvid#103). |

### Functions

| [`bucket_label`](#muvid.mcp.workspace.bucket_label)(proj)                                 | What a visualizer-drawer bucket holds: `"visualizer"`, or the one subgenre whose work is all it holds.   |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------|
| [`data_root`](#muvid.mcp.workspace.data_root)()                                        | The muvid data root: `$MUVID_DATA_HOME` or `~/.local/share/muvid`.                                       |
| [`open_subgenre_project`](#muvid.mcp.workspace.open_subgenre_project)(slug, email, project_id, \*) | The bucket a subgenre renders into: its own, else a visualizer bucket of that id.                        |
| [`subgenre_of_render`](#muvid.mcp.workspace.subgenre_of_render)(meta)                           | The subgenre a render's `meta.json` says made it, if it says.                                            |
| [`subgenre_slugs_on_disk`](#muvid.mcp.workspace.subgenre_slugs_on_disk)(\*[, root])                 | The subgenres that have a directory under the data root, sorted.                                         |

### Classes

| [`SubgenreWorkspace`](#muvid.mcp.workspace.SubgenreWorkspace)(email, root, slug)       | A single caller's area for ONE subgenre: the visualizer's bucket, in its own directory.   |
|---------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| [`VisualizerProject`](#muvid.mcp.workspace.VisualizerProject)(email, project_id, root) | One caller's visualizer bucket — a folder its renders land in.                            |
| [`VisualizerWorkspace`](#muvid.mcp.workspace.VisualizerWorkspace)(email, root)           | A single caller's private visualizer area, addressed by `email`.                          |

### muvid.mcp.workspace.DATA_HOME_ENV_VAR *= 'MUVID_DATA_HOME'*

Env var overriding the muvid data root (where per-user visualizer buckets live).
Re-exported from [`muvid.paths`](muvid.paths.html.md#module-muvid.paths), the SSOT — this module used to carry its own
verbatim copy of both, beside a second copy in `muvid/footage/workspace.py`.

### muvid.mcp.workspace.SUBGENRES_SEGMENT *= 'subgenres'*

The path segment under the data root that holds one directory per subgenre (muvid#103).

### *class* muvid.mcp.workspace.SubgenreWorkspace(email, root, slug)

Bases: [`VisualizerWorkspace`](#muvid.mcp.workspace.VisualizerWorkspace)

A single caller’s area for ONE subgenre: the visualizer’s bucket, in its own directory.

A subgenre is stateless the way the visualizer is (a “project” is where renders
land), so the bucket is the same [`VisualizerProject`](#muvid.mcp.workspace.VisualizerProject); only the directory
differs, which gives each subgenre its own project-id space and a path that names
it (muvid#103). Built with `for_slug()`, never `for_email()`.

#### create_project(project_id, , title='', force=False)

Create a bucket, refusing to fork one this subgenre already made.

Before muvid#103 this subgenre’s projects were made in the visualizer
drawer. Creating the same id here would succeed and shadow it: the
subgenre’s tools would open the new, empty bucket, and the old renders
would drop out of their reach. So an id whose visualizer bucket holds
only this subgenre’s renders is refused, as it was before.

* **Return type:**
  [`VisualizerProject`](#muvid.mcp.workspace.VisualizerProject)

### *class* muvid.mcp.workspace.VisualizerProject(email, project_id, root)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One caller’s visualizer bucket — a folder its renders land in.

`root` is exposed so `nw.create_genre_project`’s all-or-nothing rollback
(`nw.genres._rollback_project` removes `project.root`) reverts a half-created
bucket. Kept storage-only: no nw graph, no asset library.

#### list_renders()

This bucket’s renders (newest-first), from each render’s `meta.json`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### new_render_dir(render_id)

Create + return a fresh directory for one render (traversal-checked id).

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### *class* muvid.mcp.workspace.VisualizerWorkspace(email, root)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A single caller’s private visualizer area, addressed by `email`.

`email` and every `project_id` are validated as single path components, so a
caller can never escape their own subtree.

#### create_project(project_id, , title='', force=False)

Create (and return) a new visualizer bucket under this user.

* **Return type:**
  [`VisualizerProject`](#muvid.mcp.workspace.VisualizerProject)

#### list_projects()

This user’s buckets: `[{project_id, title}]` (newest-modified first).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### open_project(project_id)

Open an existing visualizer bucket (raises if it doesn’t exist).

* **Return type:**
  [`VisualizerProject`](#muvid.mcp.workspace.VisualizerProject)

### muvid.mcp.workspace.bucket_label(proj)

What a visualizer-drawer bucket holds: `"visualizer"`, or the one subgenre
whose work is all it holds.

Before muvid#103 subgenre projects lived in this drawer, so the drawer cannot
label them; their renders can. Evidence is each finished render’s
`meta.json` (a render folder without one is a render that failed or is
still running, and says nothing), plus the `lyricvid/` folder the lyric
tools fetch their inputs into. A bucket with no evidence, or one that mixes
visualizer and subgenre work (allowed before and after muvid#103), stays
`"visualizer"`. Read-only: nothing is moved or rewritten.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### muvid.mcp.workspace.data_root()

The muvid data root: `$MUVID_DATA_HOME` or `~/.local/share/muvid`.

Public API (`muvid.mcp` re-exports it), so the name stays though the body moved.
A forwarder, not an alias, for the introspection reason given on the footage twin.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### muvid.mcp.workspace.open_subgenre_project(slug, email, project_id, , root=None)

The bucket a subgenre renders into: its own, else a visualizer bucket of that id.

The fallback is what keeps every project made before muvid#103 (and every
visualizer project a caller already rendered a lyric video into) working: those
live in the visualizer workspace and are read in place, never moved.

* **Return type:**
  [`VisualizerProject`](#muvid.mcp.workspace.VisualizerProject)

### muvid.mcp.workspace.subgenre_of_render(meta)

The subgenre a render’s `meta.json` says made it, if it says.

`render_subgenre` records `subgenre` (checked first, so a choreo or montage
render, whose own meta also carries `treatment_source`, is named correctly).
`render_lyric_video` records no `subgenre`; its nested pipeline meta has
`treatment_source`, which no visualizer render carries.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### muvid.mcp.workspace.subgenre_slugs_on_disk(, root=None)

The subgenres that have a directory under the data root, sorted.

Read from disk rather than from the installed plugins, so a project made by a
subgenre that has since been uninstalled is still listed and downloadable.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]
