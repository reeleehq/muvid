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
  only if every dependency it brings is MIT/BSD/Apache/ISC.

**Absent is not zero.** A scorer that could not measure a frame returns the frame
masked (`NaN` raw, `False` mask), never `0.0`: the composite renormalises over
the weight that was available (muvid#19), and a `0.0` would count as the worst
possible score.

Import-safe: this module is stdlib-only; every built-in’s heavy import lives inside its
`run` function. A registered metric weighs `0` in the `weighted` selector until a
caller gives it a weight (`weights={"my_metric": 0.3}`) — registering changes what is
*measured and shown*, never what an existing edit selects.

### Module Attributes

| [`CORE_TIER`](#muvid.footage.scoring.registry.CORE_TIER)   | The tiers.   |
|--------------------------------------------------------------|--------------|

### Functions

| [`default_metrics`](#muvid.footage.scoring.registry.default_metrics)(\*[, include_lipsync])   | The metric axis order: every registered scorer's metrics, in registration order.   |
|-------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`metrics_of_tier`](#muvid.footage.scoring.registry.metrics_of_tier)(tier)                    | Every metric a tier's scorers produce.                                             |
| [`register_scorer`](#muvid.footage.scoring.registry.register_scorer)(scorer, \*[, replace])   | Add `scorer`.                                                                      |
| [`scorers`](#muvid.footage.scoring.registry.scorers)(\*[, include_lipsync])           | Registered scorers in registration order; the opt-in tier only when asked.         |
| [`unregister_scorer`](#muvid.footage.scoring.registry.unregister_scorer)(name)                  | Remove a scorer (tests, plugin teardown).                                          |

### Classes

| [`ClipContext`](#muvid.footage.scoring.registry.ClipContext)(clip_id, path, alignment, ...)      | What a scorer is handed for ONE clip.   |
|--------------------------------------------------------------------------------------------------|-----------------------------------------|
| [`Scorer`](#muvid.footage.scoring.registry.Scorer)(name, metrics, run[, needs_frames, ...]) | One row of the registry.                |

### muvid.footage.scoring.registry.CORE_TIER *= 'core'*

The tiers. `core` runs by default; `lipsync` only when the opt-in is enabled.

### *class* muvid.footage.scoring.registry.ClipContext(clip_id, path, alignment, frames, beat, vocal_stem, grid)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a scorer is handed for ONE clip. Paths and primitives, never the project.

`frames` is the shared decode pass (`None` when no selected scorer declares
`needs_frames`); `beat` is the master beat grid; `vocal_stem` the master vocal
stem path (`None` unless the lip-sync tier is running); `grid` is
`{"t0", "hop_s", "n"}`.

### *class* muvid.footage.scoring.registry.Scorer(name, metrics, run, needs_frames=True, gated=True, tier='core', available=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One row of the registry. `run(ctx) -> tracks` is the whole behaviour.

#### available *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[Callable](https://docs.python.org/3/library/typing.html#typing.Callable)[[], [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[bool](https://docs.python.org/3/builtins/functions.html#bool), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]]]* *= None*

`() -> (ok, reason)`; `None` means always available. Surfaced by
`list_available_extractors` — a missing dependency is a recorded reason, not a crash.

### muvid.footage.scoring.registry.default_metrics(, include_lipsync=False)

The metric axis order: every registered scorer’s metrics, in registration order.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### muvid.footage.scoring.registry.metrics_of_tier(tier)

Every metric a tier’s scorers produce.

* **Return type:**
  [`set`](https://docs.python.org/3/builtins/stdtypes.html#set)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

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
