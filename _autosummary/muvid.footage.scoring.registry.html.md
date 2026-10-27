# muvid.footage.scoring.registry

The scorer registry: what a metric IS, so adding one touches no orchestrator code (muvid#19).

A *scorer* turns one clip (plus the shared, compute-once-on-master artifacts) into
[`ScoreTrack`](muvid.footage.scoring.grid.html.md#muvid.footage.scoring.grid.ScoreTrack)s on the song grid. The orchestrator
used to call three extractors by name and keep a hardcoded metric tuple, so a new
scorer meant editing four places and `metrics=` could only *filter* what those calls
produced. Now it walks this registry — the house idiom (`register_visual`,
`register_selection_strategy`, `register_aligner`) — and the metric axis, the
default metric set and the wanted-set filter are all derived from the rows.

A scorer is handed a [`ClipContext`](#muvid.footage.scoring.registry.ClipContext) and returns tracks. It declares:

- `metrics` — the names it produces (a `metrics=` request is matched against them);
- `needs_frames` — whether it reads the shared decode pass (one decode per clip,
  however many scorers read it: the design review’s fix for the double decode);
- `gated` — whether the optional hard quality gate is ANDed into its masks;
- `tier` — `"core"` (the commercial-clean default) or `"lipsync"` (the opt-in,
  off-prod tier of the licence boundary in the repo guide). A new scorer is `"core"`
  only if every dependency it brings is MIT/BSD/Apache/ISC;
- `available` — `() -> (ok, reason)`, enforced by the orchestrator: an unavailable
  scorer is skipped with its reason recorded (refused, if its metric was asked for);
- `needs` — the shared master artifacts it reads ([`register_artifact()`](#muvid.footage.scoring.registry.register_artifact); the
  lip-sync tier’s vocal stem is one), each built once per run and only when a running
  scorer needs it (muvid#184). The orchestrator names no artifact itself.

The [`ClipContext`](#muvid.footage.scoring.registry.ClipContext) it is handed is primitives (muvid#184): the clip’s placement,
the [`MasterBeats`](#muvid.footage.scoring.registry.MasterBeats), the [`Grid`](#muvid.footage.scoring.registry.Grid) and its declared artifacts — never the
project and never a sibling package’s record — plus `frames`, the one rich object,
documented as unstable.

**Absent is not zero.** A scorer that could not measure a frame returns the frame
masked (`NaN` raw, `False` mask), never `0.0`: the composite renormalises over
the weight that was available (muvid#19), and a `0.0` would count as the worst
possible score.

Import-safe: this module is stdlib-only; every built-in’s heavy import lives inside its
`run` function. A registered metric weighs `0` in the `weighted` selector until a
caller gives it a weight (`weights={"my_metric": 0.3}`) — registering changes what is
*measured and shown*, never what an existing edit selects.

### Module Attributes

| [`BEATS`](#muvid.footage.scoring.registry.BEATS)      | `ClipContext.beat`'s `beat_times`.                                        |
|-------------------------------------------------------------|---------------------------------------------------------------------------|
| [`INPUTS`](#muvid.footage.scoring.registry.INPUTS)     | Every master input a score is keyed on beyond the song and the placement. |
| [`CORE_TIER`](#muvid.footage.scoring.registry.CORE_TIER)  | The tiers.                                                                |
| [`VOCAL_STEM`](#muvid.footage.scoring.registry.VOCAL_STEM) | The master vocal stem (Demucs), the lip-sync tier's shared artifact.      |

### Functions

| [`artifact`](#muvid.footage.scoring.registry.artifact)(name)                             | The registered artifact `name`; `KeyError` names the registered ones.                                              |
|---------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------|
| [`default_metrics`](#muvid.footage.scoring.registry.default_metrics)(\*[, include_lipsync])     | The metric axis order: every registered scorer's metrics, in registration order.                                   |
| [`metrics_of_tier`](#muvid.footage.scoring.registry.metrics_of_tier)(tier)                      | Every metric a tier's scorers produce.                                                                             |
| [`metrics_reading`](#muvid.footage.scoring.registry.metrics_reading)(input_name)                | Every registered metric measured on `input_name` ([`Scorer.inputs`](#muvid.footage.scoring.registry.Scorer.inputs)). |
| [`register_artifact`](#muvid.footage.scoring.registry.register_artifact)(artifact, \*[, replace]) | Add a shared master artifact; a taken name is refused unless `replace`.                                            |
| [`register_scorer`](#muvid.footage.scoring.registry.register_scorer)(scorer, \*[, replace])     | Add `scorer`.                                                                                                      |
| [`scorers`](#muvid.footage.scoring.registry.scorers)(\*[, include_lipsync])             | Registered scorers in registration order; the opt-in tier only when asked.                                         |
| [`unregister_scorer`](#muvid.footage.scoring.registry.unregister_scorer)(name)                    | Remove a scorer (tests, plugin teardown).                                                                          |

### Classes

| [`Artifact`](#muvid.footage.scoring.registry.Artifact)(name, build, stage)                     | A shared master artifact — computed ONCE per run on the song, never per clip — that a scorer can declare in `needs`.                                                                                                                                                                                                           |
|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`ClipContext`](#muvid.footage.scoring.registry.ClipContext)(clip_id, path, offset_s, ...[, ...]) | What a scorer is handed for ONE clip: paths and primitives, never the project and never a sibling package's record (muvid#184), so a plugin's contract is these fields and nothing behind them.                                                                                                                                |
| [`Grid`](#muvid.footage.scoring.registry.Grid)(t0, hop_s, n)                               | The song-time grid every track lands on: `n` frames, `hop_s` apart, from `t0`.                                                                                                                                                                                                                                                 |
| [`KeyedInput`](#muvid.footage.scoring.registry.KeyedInput)(read, fingerprint)                    | How a host provides one keyed master input ([`INPUTS`](#muvid.footage.scoring.registry.INPUTS), muvid#224) — the single place an input is read, for the run that measures on it (`read`, what the host hands `score_project(inputs=)`) AND for the readers that ask whether the scores are still current (`fingerprint`). |
| [`MasterBeats`](#muvid.footage.scoring.registry.MasterBeats)(beat_times, downbeat_times, ...)     | The master beat grid a scoring run measures on, and the name of it (muvid#187).                                                                                                                                                                                                                                                |
| [`Scorer`](#muvid.footage.scoring.registry.Scorer)(name, metrics, run[, needs_frames, ...])  | One row of the registry.                                                                                                                                                                                                                                                                                                       |

### *class* muvid.footage.scoring.registry.Artifact(name, build, stage)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A shared master artifact — computed ONCE per run on the song, never per clip —
that a scorer can declare in `needs`. `build(song_path, scores_dir)` makes it;
`stage` is its progress label.

### muvid.footage.scoring.registry.BEATS *= 'beats'*

`ClipContext.beat`’s
`beat_times`. The onset envelope is the song’s own measurement, so reading only it
is not reading the grid.

* **Type:**
  The master input “the beat grid” ([`Scorer.inputs`](#muvid.footage.scoring.registry.Scorer.inputs))

### muvid.footage.scoring.registry.CORE_TIER *= 'core'*

The tiers. `core` runs by default; `lipsync` only when the opt-in is enabled.

### *class* muvid.footage.scoring.registry.ClipContext(clip_id, path, offset_s, duration_s, coverage, frames, beat, grid, artifacts=dict(), inputs=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a scorer is handed for ONE clip: paths and primitives, never the project
and never a sibling package’s record (muvid#184), so a plugin’s contract is these
fields and nothing behind them.

`offset_s` / `duration_s` / `coverage` place the clip on the song (seconds;
`coverage` is the song span it covers); `beat` is the master beat grid
([`MasterBeats`](#muvid.footage.scoring.registry.MasterBeats), primitives); `grid` the song-time [`Grid`](#muvid.footage.scoring.registry.Grid);
`artifacts` the shared master artifacts the scorer declared in `needs`
([`register_artifact()`](#muvid.footage.scoring.registry.register_artifact)), by name. `frames` is the one rich object — the shared
decode pass, `None` unless a selected scorer declares `needs_frames` — and it is
documented as unstable: a plugin reading it accepts that its shape may change.

#### inputs *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]*

every keyed input’s value by name ([`INPUTS`](#muvid.footage.scoring.registry.INPUTS); `beat` is the beat grid’s)

### *class* muvid.footage.scoring.registry.Grid(t0, hop_s, n)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The song-time grid every track lands on: `n` frames, `hop_s` apart, from `t0`.

#### as_kwargs()

`{"t0", "hop_s", "n"}`, the keyword arguments the extractors take.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### muvid.footage.scoring.registry.INPUTS *= ('beats',)*

Every master input a score is keyed on beyond the song and the placement.

### *class* muvid.footage.scoring.registry.KeyedInput(read, fingerprint)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

How a host provides one keyed master input ([`INPUTS`](#muvid.footage.scoring.registry.INPUTS), muvid#224) — the
single place an input is read, for the run that measures on it (`read`, what the
host hands `score_project(inputs=)`) AND for the readers that ask whether the
scores are still current (`fingerprint`).

`read(project) -> (value, fingerprint)` is called once per scoring run and the two
come back TOGETHER, so the manifest can never record one value’s key beside another
value’s measurement (the beat grid’s #187 rule, for every input). `fingerprint
(project) -> str` is the cheap current fingerprint alone, for the staleness
question; `""` means the input’s default, which `song_hash` already keys.

### *class* muvid.footage.scoring.registry.MasterBeats(beat_times, downbeat_times, tempo_bpm, onset_env, onset_hop_s, fingerprint='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The master beat grid a scoring run measures on, and the name of it (muvid#187).

One record, read once: `fingerprint` names THESE beats (`""` for the estimator’s,
which `song_hash` already keys; else the declared grid’s), so the manifest can never
record one grid’s key beside another grid’s beats. The fields are primitives, the
shape muvid#184 wants `ClipContext` to hand plugins; `onset_env` is the
estimator’s measurement of the song’s onsets, which a declared grid does not change.

#### *classmethod* estimated(bg)

From the estimator’s `mixing.audio.BeatGrid`.

* **Return type:**
  [`MasterBeats`](#muvid.footage.scoring.registry.MasterBeats)

### *class* muvid.footage.scoring.registry.Scorer(name, metrics, run, needs_frames=True, gated=True, tier='core', available=None, needs=(), inputs=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One row of the registry. `run(ctx) -> tracks` is the whole behaviour.

#### available *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[Callable](https://docs.python.org/3/library/typing.html#typing.Callable)[[], [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[bool](https://docs.python.org/3/builtins/functions.html#bool), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]]]* *= None*

`() -> (ok, reason)`; `None` means always available. ENFORCED by the
orchestrator: an unavailable scorer does not run and its reason is recorded in the
run’s `skipped_scorers` (a missing dependency is a recorded reason, not a crash).

#### inputs *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]]*

the master INPUTS each metric is measured on beyond the song and the clip’s
placement (which every metric reads), by metric: `{"motion_beat_bas": (BEATS,)}`.
A change to one stales only the metrics that declared it (muvid#206).

#### needs *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ()*

the shared master artifacts it reads ([`register_artifact()`](#muvid.footage.scoring.registry.register_artifact)), by name. Each is
built once per run, and only when a running scorer needs it.

#### reads(input_name)

The metrics of this scorer measured on `input_name`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### muvid.footage.scoring.registry.VOCAL_STEM *= 'vocal_stem'*

The master vocal stem (Demucs), the lip-sync tier’s shared artifact.

### muvid.footage.scoring.registry.artifact(name)

The registered artifact `name`; `KeyError` names the registered ones.

* **Return type:**
  [`Artifact`](#muvid.footage.scoring.registry.Artifact)

### muvid.footage.scoring.registry.default_metrics(, include_lipsync=False)

The metric axis order: every registered scorer’s metrics, in registration order.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### muvid.footage.scoring.registry.metrics_of_tier(tier)

Every metric a tier’s scorers produce.

* **Return type:**
  [`set`](https://docs.python.org/3/builtins/stdtypes.html#set)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### muvid.footage.scoring.registry.metrics_reading(input_name)

Every registered metric measured on `input_name` ([`Scorer.inputs`](#muvid.footage.scoring.registry.Scorer.inputs)).

* **Return type:**
  [`set`](https://docs.python.org/3/builtins/stdtypes.html#set)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### muvid.footage.scoring.registry.register_artifact(artifact, , replace=False)

Add a shared master artifact; a taken name is refused unless `replace`.

* **Return type:**
  [`Artifact`](#muvid.footage.scoring.registry.Artifact)

### muvid.footage.scoring.registry.register_scorer(scorer, , replace=False)

Add `scorer`. A name or a metric already taken is refused unless `replace`.

Two scorers producing one metric would silently overwrite each other’s track in
the tensor, so the metric names are unique across the registry, not just the scorer
names.

* **Return type:**
  [`Scorer`](#muvid.footage.scoring.registry.Scorer)

### muvid.footage.scoring.registry.scorers(, include_lipsync=False)

Registered scorers in registration order; the opt-in tier only when asked.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Scorer`](#muvid.footage.scoring.registry.Scorer)]

### muvid.footage.scoring.registry.unregister_scorer(name)

Remove a scorer (tests, plugin teardown). Unknown names raise `KeyError`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
