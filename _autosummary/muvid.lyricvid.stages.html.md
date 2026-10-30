# muvid.lyricvid.stages

The lyric-video production as named stages, and the settings section muvid owns.

A runner (a separate package: it composes muvid, arioso, mixing, illustration,
tituli and yb, none of which muvid imports; muvid#158) needs two things from muvid
and nothing else:

* **Stages** — [`lyric_stages()`](#muvid.lyricvid.stages.lyric_stages) returns the steps muvid owns as a `{name: Stage}`
  mapping: `stem`, `glyphs`, `render`, `pictures` and `captions`. A
  [`Stage`](#muvid.lyricvid.stages.Stage) is a *manifest* (name, what it reads, what it writes, whether it
  > costs money or memory) whose `run` is a `"module:function"` string imported
  > lazily, the same shape as [`muvid.subgenres.Subgenre`](muvid.subgenres.html.md#muvid.subgenres.Subgenre): listing the stages
  > imports no rendering code. Each function takes paths and primitives and returns a
  > report `dict` (or the output path); they are the functions the CLI calls, with
  > no new behaviour. Third parties and the runner find them through the entry-point
  > group [`ENTRY_POINT_GROUP`](#muvid.lyricvid.stages.ENTRY_POINT_GROUP) (`muvid.lyric_stages.v1`), muvid’s own included.
* **Settings** — [`LyricProductionSettings`](#muvid.lyricvid.stages.LyricProductionSettings) is the part of a song spec muvid
  reads, with `LYRIC_PRODUCTION_SCHEMA` its JSON Schema. A runner mounts it as
  the `muvid` section of its `spec.json` and hands it to muvid through one
  `settings` argument. Timing overrides accept the bare `"fine"` and the
  recorded form `{"how": "fine", "reason": "..."}`.

This module is stdlib-only at import time.

### Module Attributes

| [`ENTRY_POINT_GROUP`](#muvid.lyricvid.stages.ENTRY_POINT_GROUP)   | Entry-point group a stage manifest is registered under (muvid's own included).      |
|----------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [`MEMORY_CLASSES`](#muvid.lyricvid.stages.MEMORY_CLASSES)      | How much memory a stage needs, so a runner can run the heavy one alone under a cap. |

### Functions

| [`lyric_stages`](#muvid.lyricvid.stages.lyric_stages)(\*[, include_plugins])               | The stages available, `{name: Stage}`, muvid's own first and in order.                                |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| [`run_glyphs`](#muvid.lyricvid.stages.run_glyphs)(audio, timing, output, \*[, ...])      | Refine word TIMING (TimedText JSON) to per-glyph times; write OUTPUT JSON.                            |
| [`run_pictures`](#muvid.lyricvid.stages.run_pictures)(video, timing, pictures, output, \*) | Composite PICTURES (`[{"word", "path", "credit"?}]`) onto VIDEO at OUTPUT.                            |
| [`settings_schema`](#muvid.lyricvid.stages.settings_schema)()                                 | The JSON Schema of [`LyricProductionSettings`](#muvid.lyricvid.stages.LyricProductionSettings) (a copy). |

### Classes

| [`LyricProductionSettings`](#muvid.lyricvid.stages.LyricProductionSettings)([take, keep_unsung, ...])   | What muvid reads from a song spec (the `muvid` section of a runner's spec).   |
|------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| [`Stage`](#muvid.lyricvid.stages.Stage)(name, summary, run[, inputs, outputs, ...])   | One named step of a lyric-video production: a manifest, not a function.       |

### muvid.lyricvid.stages.ENTRY_POINT_GROUP *= 'muvid.lyric_stages.v1'*

Entry-point group a stage manifest is registered under (muvid’s own included).

### *class* muvid.lyricvid.stages.LyricProductionSettings(take=None, keep_unsung=False, repair_spills=False, timing_overrides=dict(), treatment=None, emphasis=(), captions=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What muvid reads from a song spec (the `muvid` section of a runner’s spec).

#### captions *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]*

`{language tag: transform name | {line text: caption}}`.

#### emphasis *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ()*

Words to emphasise, in the treatment’s vocabulary.

#### *classmethod* from_mapping(data)

Build from a spec section, refusing unknown keys (a typo must not be silent).

* **Return type:**
  [`LyricProductionSettings`](#muvid.lyricvid.stages.LyricProductionSettings)

#### take *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= None*

Which take of the song (a runner’s judgement point); `None` until chosen.

#### timing_override_reasons()

The recorded reason per overridden line (only those that gave one).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### timing_override_values()

`timing_overrides` with each `{"how", "reason"}` collapsed to its `how`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

#### timing_overrides *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]*

`{"<line index>": "fine" | {"how": "fine", "reason": "..."}}`.

#### treatment *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]]* *= None*

A treatment (archetype choice and parameters), as `validate_treatment` takes.

### muvid.lyricvid.stages.MEMORY_CLASSES *= ('light', 'heavy')*

How much memory a stage needs, so a runner can run the heavy one alone under a cap.

### *class* muvid.lyricvid.stages.Stage(name, summary, run, inputs=(), outputs=(), memory='light', costed=False, api_version=1)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One named step of a lyric-video production: a manifest, not a function.

#### costed *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

True when the stage spends money or fetches licensed weights.

#### memory *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'light'*

`"light"` or `"heavy"` (the aligner and the separator are heavy).

#### resolve()

Import and return the stage’s function.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### muvid.lyricvid.stages.lyric_stages(, include_plugins=True)

The stages available, `{name: Stage}`, muvid’s own first and in order.

Plugins registered under [`ENTRY_POINT_GROUP`](#muvid.lyricvid.stages.ENTRY_POINT_GROUP) are added after them; a plugin
naming an existing stage is skipped (muvid’s own wins). A plugin that fails to
load is skipped rather than taking the catalogue down.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Stage`](#muvid.lyricvid.stages.Stage)]

### muvid.lyricvid.stages.run_glyphs(audio, timing, output, , vocals='', workdir='', allow_download=False, no_reconcile=False, keep_unsung=False, silent_glyph='', overrides=None, repair_spills=False, spans=False)

Refine word TIMING (TimedText JSON) to per-glyph times; write OUTPUT JSON.

Returns the report (onsets, agreement, reconciled, and the opt-in `repaired` and
`spans`). `overrides` (`None`: not asked for) is the already-parsed `{"<line index>": "fine"}`
mapping; see [`LyricProductionSettings.timing_override_values()`](#muvid.lyricvid.stages.LyricProductionSettings.timing_override_values).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### muvid.lyricvid.stages.run_pictures(video, timing, pictures, output, , block=(0, 0, 0, 0), bounce=True, border=None)

Composite PICTURES (`[{"word", "path", "credit"?}]`) onto VIDEO at OUTPUT.

Each picture appears when its word is first sung and pops on each later one.
`block` is the text block’s `(x, y, w, h)` the mosaic keeps clear of. Words
never sung are listed under `unsung` and left out.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### muvid.lyricvid.stages.settings_schema()

The JSON Schema of [`LyricProductionSettings`](#muvid.lyricvid.stages.LyricProductionSettings) (a copy).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]
