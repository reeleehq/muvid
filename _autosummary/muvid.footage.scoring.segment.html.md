# muvid.footage.scoring.segment

Shot boundaries (via `mixing.video.shots`) + the per-clip coverage mask.

- `coverage_mask` is dependency-free: the boolean of song-grid frames a clip actually
  covers (from its offset + duration). It is the base mask every metric ANDs with, and the
  authority for “does this clip exist at song time t”.
- `shot_boundaries` returns song-times of within-clip scene cuts, detected by
  `mixing.video.shots` (muvid#220 — the detector lives in mixing, muvid maps it onto the
  song). Consumed by the selector ONLY when `boundary_mode="beats+shots"` (they become
  *inter-clip* cut candidates at shot-boundary times — a within-clip jump cut is
  unrepresentable in the single-offset EDL model). The default strategy is PySceneDetect
  (BSD-3, the `scoring-shots` extra); absent → `[]` and the mode degrades to beats-only.

### Module Attributes

| [`DEFAULT_SHOT_STRATEGY`](#muvid.footage.scoring.segment.DEFAULT_SHOT_STRATEGY)   | The `mixing.video.shots` strategy [`shot_boundaries()`](#muvid.footage.scoring.segment.shot_boundaries) uses by default, and the package it needs (the `scoring-shots` extra).   |
|--------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

### Functions

| [`coverage_mask`](#muvid.footage.scoring.segment.coverage_mask)(\*, offset_s, duration_s, ...)    | Grid frames (bool[n]) the clip covers — using its clamped `coverage` span.                                                          |
|--------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| [`shot_boundaries`](#muvid.footage.scoring.segment.shot_boundaries)(clip_path, \*, offset_s[, ...]) | Song-times of within-clip scene cuts, or `[]` when `strategy`'s package is not installed (so `beats+shots` degrades to beats-only). |
| [`shots_available`](#muvid.footage.scoring.segment.shots_available)([strategy])                     | Whether [`shot_boundaries()`](#muvid.footage.scoring.segment.shot_boundaries) can detect anything with `strategy` here.                |

### muvid.footage.scoring.segment.DEFAULT_SHOT_STRATEGY *= 'pyscenedetect'*

The `mixing.video.shots` strategy [`shot_boundaries()`](#muvid.footage.scoring.segment.shot_boundaries) uses by default, and the
package it needs (the `scoring-shots` extra). NOT mixing’s own default `"diff"` as a
fallback when that package is absent: every install without it pays no shot decode
today, and a fallback would add one per clip to every scoring run — paid even when the
selector’s default `boundary_mode="beats"` never reads a shot.

### muvid.footage.scoring.segment.coverage_mask(, offset_s, duration_s, coverage, t0, hop_s, n)

Grid frames (bool[n]) the clip covers — using its clamped `coverage` span.

* **Return type:**
  `ndarray`

### muvid.footage.scoring.segment.shot_boundaries(clip_path, , offset_s, strategy='pyscenedetect')

Song-times of within-clip scene cuts, or `[]` when `strategy`’s package is
not installed (so `beats+shots` degrades to beats-only).

The detection is `mixing.video.shots(clip_path, strategy=strategy)`: its spans tile
the clip, so the cuts are the span starts after the first, moved onto the song by
`offset_s`. A failure INSIDE the detector raises (the house rule for `mixing`
calls: a swallowed error is a quietly empty result) — the scoring orchestrator
records it per clip; only a missing optional package is a degrade here.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### muvid.footage.scoring.segment.shots_available(strategy='pyscenedetect')

Whether [`shot_boundaries()`](#muvid.footage.scoring.segment.shot_boundaries) can detect anything with `strategy` here.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)
