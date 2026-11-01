# muvid.footage.luts

The LUTs a look’s `lut3d` may load: named in the EDL, found at render (muvid#252).

A look names a LUT by its **name in muvid’s LUT folder** ([`muvid.paths.lut_dir()`](muvid.paths.html.md#muvid.paths.lut_dir))
— `lut3d=file=warm.cube`, or `film/warm.cube` for one in a subfolder — never by a
path on this machine. The split is what muvid#244’s review asked for:

- **The EDL gate checks only the text** ([`lut_name()`](#muvid.footage.luts.lut_name), called by
  `muvid.footage.edl._validate_look_luts()`). `validate_edl` runs on every
  > named-edit change, and an edit is a plan: reading the cube there meant a deleted LUT
  > made an edit holding it unchangeable, even on an unrelated cut.
- **The assembler resolves the name** ([`bind_look_luts()`](#muvid.footage.luts.bind_look_luts)) just before it encodes:
  the file must exist, be a regular file inside the folder once symlinks are resolved,
  and declare `LUT_3D_SIZE` at most [`MAX_LUT_SIZE`](#muvid.footage.luts.MAX_LUT_SIZE). That is the environment
  refusal, and it sits where the encode is.
- **Nothing persisted carries a host path.** `edits/*.json` and a render’s
  `meta.json["edl"]` keep the name, so an edit survives `MUVID_DATA_HOME` moving or
  the project moving to another machine, and a remote caller can name a LUT it found
  through the `luts` op ([`list_luts()`](#muvid.footage.luts.list_luts)) without learning where the folder is.

The #244 spelling — the cube’s absolute path — is no longer accepted: it is the host
path this exists to keep out of stored edits, and it was live for five days during which
no caller could name a LUT at all (the refusal hid the folder and nothing listed it).

Stdlib only, plus [`muvid.paths`](muvid.paths.html.md#module-muvid.paths): `edl` imports this at module top and must stay
import-light.

### Module Attributes

| [`MAX_LUT_SIZE`](#muvid.footage.luts.MAX_LUT_SIZE)     | The largest `LUT_3D_SIZE` a look's `lut3d` may load (muvid#244).                                                                                                     |
|-------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`LUT_SUFFIX`](#muvid.footage.luts.LUT_SUFFIX)       | The suffix a LUT file has (compared without case, as `.CUBE` exports exist).                                                                                         |
| [`MAX_LUT_NAME_LEN`](#muvid.footage.luts.MAX_LUT_NAME_LEN) | The longest LUT name, in characters — far below any filesystem's limit, so a long name is a refusal of the NAME rather than an `OSError` carrying the folder's path. |
| [`MAX_LISTED_LUTS`](#muvid.footage.luts.MAX_LISTED_LUTS)  | The most LUTs [`list_luts()`](#muvid.footage.luts.list_luts) reports, so a huge folder is not one huge reply.                                          |

### Functions

| [`bind_look_luts`](#muvid.footage.luts.bind_look_luts)(look)   | `look` with each `lut3d` link REBUILT from what ffmpeg reads of it, its `file` the checked file the name loads ([`resolve_lut()`](#muvid.footage.luts.resolve_lut); raises [`LutError`](#muvid.footage.luts.LutError)) — what the assembler hands ffmpeg.   |
|-------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`check_look_luts`](#muvid.footage.luts.check_look_luts)(look)  | Raise [`LutError`](#muvid.footage.luts.LutError) unless every LUT `look` names can be bound here — the same code path the assembler runs, with its result discarded.                                                                                                    |
| [`cube_size`](#muvid.footage.luts.cube_size)(path)        | The `LUT_3D_SIZE` a `.cube` declares in its header, or `None`.                                                                                                                                                                                                                         |
| [`list_luts`](#muvid.footage.luts.list_luts)()            | Every LUT in muvid's LUT folder, by the name a look gives it: `{"luts": [{name, size, usable[, problem]}], "total": n}` — sorted by name, at most [`MAX_LISTED_LUTS`](#muvid.footage.luts.MAX_LISTED_LUTS) rows of `total`.                                                    |
| [`look_lut_names`](#muvid.footage.luts.look_lut_names)(look)   | The LUT names `look`'s `lut3d` links load, as ffmpeg reads them (`[]` for none) — the LAST `file` of a link, as `av_opt_set` keeps the last.                                                                                                                                           |
| [`lut_name`](#muvid.footage.luts.lut_name)(text)         | `text` when it is a LUT name — the cube's path relative to [`muvid.paths.lut_dir()`](muvid.paths.html.md#muvid.paths.lut_dir) — else `None`.                                                                                                                   |
| [`resolve_lut`](#muvid.footage.luts.resolve_lut)(name)      | The file LUT `name` loads, checked: inside the LUT folder once symlinks are resolved, a regular file, declaring `LUT_3D_SIZE` at most [`MAX_LUT_SIZE`](#muvid.footage.luts.MAX_LUT_SIZE).                                                                                   |

### Exceptions

| [`LutError`](#muvid.footage.luts.LutError)   | A look names a LUT that cannot be loaded here: absent, outside the folder, unreadable, or too large.   |
|-------------------------------------------------------------|--------------------------------------------------------------------------------------------------------|

### muvid.footage.luts.LUT_SUFFIX *= '.cube'*

The suffix a LUT file has (compared without case, as `.CUBE` exports exist).

### *exception* muvid.footage.luts.LutError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A look names a LUT that cannot be loaded here: absent, outside the folder,
unreadable, or too large. Raised at render time, never by the EDL gate.

### muvid.footage.luts.MAX_LISTED_LUTS *= 500*

The most LUTs [`list_luts()`](#muvid.footage.luts.list_luts) reports, so a huge folder is not one huge reply.

### muvid.footage.luts.MAX_LUT_NAME_LEN *= 255*

The longest LUT name, in characters — far below any filesystem’s limit, so a long
name is a refusal of the NAME rather than an `OSError` carrying the folder’s path.

### muvid.footage.luts.MAX_LUT_SIZE *= 65*

The largest `LUT_3D_SIZE` a look’s `lut3d` may load (muvid#244). `lut3d`’s memory
is its cube’s, not the frame’s: 12 bytes x size^3 — 3.3 MB at 65 (the usual grading
size), 201 MB at 256 — so the frame-cost budget cannot see it and this bounds it.

### muvid.footage.luts.bind_look_luts(look)

`look` with each `lut3d` link REBUILT from what ffmpeg reads of it, its
`file` the checked file the name loads ([`resolve_lut()`](#muvid.footage.luts.resolve_lut); raises
[`LutError`](#muvid.footage.luts.LutError)) — what the assembler hands ffmpeg. Every other link, and a
look with no LUT, is returned as written.

Rebuilt rather than spliced: the options are re-emitted from one parse, so the
text ffmpeg receives says exactly what the gate read (one `file`, no escaped
separator smuggling a second), and the path is escaped at both of ffmpeg’s levels.

```pycon
>>> bind_look_luts("hue=s=0")
'hue=s=0'
>>> bind_look_luts(None) is None
True
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### muvid.footage.luts.check_look_luts(look)

Raise [`LutError`](#muvid.footage.luts.LutError) unless every LUT `look` names can be bound here — the
same code path the assembler runs, with its result discarded.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### muvid.footage.luts.cube_size(path)

The `LUT_3D_SIZE` a `.cube` declares in its header, or `None`.

```pycon
>>> import tempfile, pathlib
>>> with tempfile.TemporaryDirectory() as d:
...     p = pathlib.Path(d, "a.cube")
...     _ = p.write_text("TITLE t\nLUT_3D_SIZE 33\n0 0 0\n")
...     cube_size(p)
33
```

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### muvid.footage.luts.list_luts()

Every LUT in muvid’s LUT folder, by the name a look gives it: `{"luts": [{name,
size, usable[, problem]}], "total": n}` — sorted by name, at most
[`MAX_LISTED_LUTS`](#muvid.footage.luts.MAX_LISTED_LUTS) rows of `total`. Empty when the folder does not exist.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### muvid.footage.luts.look_lut_names(look)

The LUT names `look`’s `lut3d` links load, as ffmpeg reads them (`[]` for
none) — the LAST `file` of a link, as `av_opt_set` keeps the last.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### muvid.footage.luts.lut_name(text)

`text` when it is a LUT name — the cube’s path relative to
[`muvid.paths.lut_dir()`](muvid.paths.html.md#muvid.paths.lut_dir) — else `None`. Reads no file and no environment.

```pycon
>>> lut_name("warm.cube"), lut_name("film/Warm-2.CUBE")
('warm.cube', 'film/Warm-2.CUBE')
>>> [lut_name(t) for t in ("../x.cube", ".hidden.cube", "/etc/passwd", "a b.cube",
...                        "warm.png", "film//warm.cube", "a" * 300 + ".cube")]
[None, None, None, None, None, None, None]
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### muvid.footage.luts.resolve_lut(name)

The file LUT `name` loads, checked: inside the LUT folder once symlinks are
resolved, a regular file, declaring `LUT_3D_SIZE` at most [`MAX_LUT_SIZE`](#muvid.footage.luts.MAX_LUT_SIZE).

Raises [`LutError`](#muvid.footage.luts.LutError) otherwise. The message names the LUT and never the folder:
hosted replies carry project-relative paths only.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
