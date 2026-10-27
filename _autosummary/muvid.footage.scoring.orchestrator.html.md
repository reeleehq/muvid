# muvid.footage.scoring.orchestrator

The scoring orchestrator: a project (song + aligned clips) → the persisted score tensor.

Owns the shared, compute-once artifacts and the single decode pass per clip (the design
review’s fix for the double-decode / camera-motion-sharing problem):

1. **Master beat grid** (`mixing.audio.beat_grid`, or the `beat_grid` a caller injects —
   the footage service’s prefers a grid a person declared, muvid#187) — computed ONCE; every
   clip maps to it via its offset.
2. (opt-in) **Master vocal stem** (Demucs) — ONCE, for the lip-sync tier.
3. **Per clip: ONE decode pass** ([`sample_clip_frames()`](muvid.footage.scoring.frames.html.md#muvid.footage.scoring.frames.sample_clip_frames))
   feeds BOTH quality and motion-beat (sharpness/exposure/face + the camera-compensated motion
   envelope come out of the same loop). Plus shot boundaries (PySceneDetect) and, when enabled,
   the lip-sync tracks.
4. Assemble + **persist** the tensor (per-metric-global normalization, atomic writes).

Resource safety (LOCKED decisions): a **process-wide concurrency=1 semaphore**
(`MUVID_SCORING_MAX_CONCURRENT`) serializes scoring runs; the lip-sync tier is \*\*off by
default\*\* (`MUVID_SCORING_ENABLE_LIPSYNC`); `should_cancel` is polled between every clip
and stage (cancel latency ≈ one clip); progress is emitted as `{'kind':'progress',
'stage_index','stage_count','current_transform'}` dicts (the nw.jobs mirror contract).

Import-safe: every heavy import (cv2/mediapipe/librosa/torch) is inside a function body.

### Module Attributes

| [`DEFAULT_METRICS`](#muvid.footage.scoring.orchestrator.DEFAULT_METRICS)   | The torch-free CORE metric set (prod-safe) AS REGISTERED AT IMPORT — a snapshot kept for callers that read the constant.   |
|--------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|

### Functions

| [`list_available_extractors`](#muvid.footage.scoring.orchestrator.list_available_extractors)()                       | Which tiers can run here (import + weight availability) — for diagnostics / the tool.   |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| [`score_project`](#muvid.footage.scoring.orchestrator.score_project)(project, \*[, metrics, hop_s, ...]) | Score every aligned clip of `project` → persist the tensor; return a summary dict.      |

### Classes

| [`KeptScores`](#muvid.footage.scoring.orchestrator.KeptScores)(tracks, recompute, song_hash, ...)   | What a partial re-score keeps (muvid#206): the CURRENT metrics' tracks per clip, the stale metrics to measure again, and the song and alignments the kept tracks were measured under — re-checked under the scoring lock.   |
|--------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

### muvid.footage.scoring.orchestrator.DEFAULT_METRICS *= ('sharpness', 'exposure', 'stability_shake', 'face_framing', 'motion_beat_bas', 'motion_onset_xcorr')*

The torch-free CORE metric set (prod-safe) AS REGISTERED AT IMPORT — a snapshot kept
for callers that read the constant. A scorer registered later is picked up by the
orchestrator through `registry.default_metrics()`, which this does not shadow.
Lip-sync metrics are added only when the opt-in tier is enabled.

### *class* muvid.footage.scoring.orchestrator.KeptScores(tracks, recompute, song_hash, align_fingerprint)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a partial re-score keeps (muvid#206): the CURRENT metrics’ tracks per clip,
the stale metrics to measure again, and the song and alignments the kept tracks
were measured under — re-checked under the scoring lock.

### muvid.footage.scoring.orchestrator.list_available_extractors()

Which tiers can run here (import + weight availability) — for diagnostics / the tool.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### muvid.footage.scoring.orchestrator.score_project(project, , metrics=None, hop_s=0.1, sample_fps=None, enable_lipsync=None, progress_cb=None, should_cancel=None, beat_source=None, keep=None)

Score every aligned clip of `project` → persist the tensor; return a summary dict.

* **Parameters:**
  * **project** – a `MusicVideoFootageProject` (needs `song_path`/`song_duration`/
    `load_alignments`/`clip_paths`/`root`/`song_hash`).
  * **metrics** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – restrict to these metric names (default: the core set, + lip-sync if enabled).
  * **hop_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – grid step (default 10 Hz).
  * **sample_fps** ([`float`](https://docs.python.org/3/builtins/functions.html#float) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – frame analysis rate (default from `frames.DEFAULT_SAMPLE_FPS`).
  * **enable_lipsync** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – force the opt-in tier on/off (default: the env flag).
  * **progress_cb** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]]) – sink for `{'kind':'progress', ...}` dict events (nw.jobs mirror shape).
  * **should_cancel** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[], [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]]) – polled between clips/stages; a True short-circuits to a clean cancel.
  * **beat_source** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`Any`](https://docs.python.org/3/library/typing.html#typing.Any)], [`MasterBeats`](muvid.footage.scoring.registry.html.md#muvid.footage.scoring.registry.MasterBeats)]]) – `project -> MasterBeats`, the master beat grid and its name,
    read together (default: the estimator, `mixing.audio.beat_grid` on the
    song). The footage service passes one that prefers a declared grid
    (muvid#187). Its `fingerprint` goes into the manifest, so
    [`manifest_is_current()`](muvid.footage.scoring.grid.html.md#muvid.footage.scoring.grid.manifest_is_current) can tell scores
    measured on one grid from another.
  * **keep** ([`KeptScores`](#muvid.footage.scoring.orchestrator.KeptScores) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – a partial re-score (muvid#206): the CURRENT metrics’ tracks to persist
    beside the `keep.recompute` ones this run measures (`metrics` is then
    ignored). Re-checked against the song and alignments under the scoring lock:
    if either changed since they were read, the run scores in full instead.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
