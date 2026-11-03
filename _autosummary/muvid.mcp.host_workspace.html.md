# muvid.mcp.host_workspace

The host’s drawer: muvid projects a HOST placed in the caller’s own tree (muvid#296).

A host that serves muvid’s genres (reelee’s studio and its connector) creates a
`music_video` or `music_visualizer` project where IT keeps the caller’s projects —
`nw.create_genre_project(..., projects_dir=<the caller's bucket>)`, a
`muvid.Project` there. muvid’s own tools looked only in muvid’s data home, so
every `muvid_*` tool answered “no such project” for an id the host had just created.

nw carries the host’s answer to “where are this caller’s projects?” —
`nw.caller_projects_dir(caller)`, registered by the host (placement’s dual). This
module turns it into one more DRAWER beside muvid’s own: [`HostDrawer`](#muvid.mcp.host_workspace.HostDrawer) is shaped
like a workspace class (`for_email`), and the workspace it returns opens and lists
the host-placed projects of ONE genre, handing back the same production objects
muvid’s own drawers do — a project’s `footage`
([`MusicVideoFootageProject`](muvid.footage.workspace.html.md#muvid.footage.workspace.MusicVideoFootageProject)) or `visualizer`
([`VisualizerProject`](muvid.mcp.workspace.html.md#muvid.mcp.workspace.VisualizerProject)) — owned by the caller.

Three refusals make it safe to put beside the email-scoped drawers, each one the
same `FileNotFoundError` (“no such project”), so nothing tells an absent id from
one that is not a muvid project of this genre:

- the folder must be a DIRECT child of the caller’s directory (`safe_component`
  plus a resolved-parent check, so a symlinked child cannot lead out of it);
- it must be an nw project (its `project.json`);
- it must have been created as THIS genre: a reelee `narrative_video` id handed to
  a footage tool never sprouts a `footage/` folder inside someone’s story.

No host registered (or an `nw` that predates the locator) means no drawer: an empty
listing and “no such project”, exactly the behaviour before. Imports are lazy, so
`import muvid.mcp.host_workspace` pulls nothing heavy.

### Module Attributes

| [`PRODUCTIONS`](#muvid.mcp.host_workspace.PRODUCTIONS)   | How each genre's production is taken from a host-placed `muvid.Project`.   |
|----------------------------------------------------------------|----------------------------------------------------------------------------|

### Classes

| [`HostDrawer`](#muvid.mcp.host_workspace.HostDrawer)(genre[, locate])               | A drawer of host-placed projects of `genre`, shaped like a workspace class.   |
|--------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| [`HostWorkspace`](#muvid.mcp.host_workspace.HostWorkspace)(email, genre, projects_dir) | One caller's host-placed projects of one genre (see the module docstring).    |

### *class* muvid.mcp.host_workspace.HostDrawer(genre, locate=<function \_nw_locator>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A drawer of host-placed projects of `genre`, shaped like a workspace class.

`locate` is the seam: the caller’s projects directory, default the host’s
registration in nw (`nw.caller_projects_dir`).

#### locate()

`nw.caller_projects_dir(email)`, or `None` when no host registered one or
the installed nw predates it.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### *class* muvid.mcp.host_workspace.HostWorkspace(email, genre, projects_dir)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One caller’s host-placed projects of one genre (see the module docstring).

#### list_projects()

`[{project_id, title, created, modified}]` of this genre, newest first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### open_project(project_id)

The caller’s production in the host-placed project `project_id`.

### muvid.mcp.host_workspace.PRODUCTIONS *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Callable](https://docs.python.org/3/library/typing.html#typing.Callable)]* *= {'music_video': <function \_footage_of>, 'music_visualizer': <function \_visualizer_of>}*

How each genre’s production is taken from a host-placed `muvid.Project`.
