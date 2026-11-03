# muvid.footage.scoring.segment

Shot boundaries + the per-clip coverage mask.

- `coverage_mask` is dependency-free: the boolean of song-grid frames a clip actually
  covers (from its offset + duration). It is the base mask every metric ANDs with, and the
  authority for “does this clip exist at song time t”.
- Shot boundaries are song-times of within-clip scene cuts. Consumed by the selector
  ONLY when `boundary_mode="beats+shots"` (they become *inter-clip* cut candidates at
  shot-boundary times — a within-clip jump cut is unrepresentable in the single-offset
  EDL model). Two ways to find them, by `shot_strategy`:
  - `"frames"` (the default since muvid#259): [`shots_from_frame_pass()`](#muvid.footage.scoring.segment.shots_from_frame_pass), from the
    picture changes the scoring decode pass ALREADY measured (`FramePass.shot_change`),
    through `mixing.shot_changes` with its `"spike"` rule. No second decode, no extra
    dependency, and it sees what cv2 decodes. The `"spike"` rule is what makes it
    usable on phone footage: mixing’s plain threshold reported a false cut about every
    second on handheld clips (mixing#160: 473 false cuts at 5 Hz on 14 single-take clips;
    the spike rule, 11; PySceneDetect, 16). Its price is recall (about 71 % of real cuts
    at 5 Hz) and cuts on consecutive samples, which continuous footage does not have.
  - any `mixing.video.shots` strategy by name (`"pyscenedetect"` — frame-accurate,
    the `scoring-shots` extra — or `"diff"`): [`shot_boundaries()`](#muvid.footage.scoring.segment.shot_boundaries), a second
    decode at full rate (muvid#220). A missing optional package is `[]`.

### Module Attributes

| [`FRAMES_STRATEGY`](#muvid.footage.scoring.segment.FRAMES_STRATEGY)        | The strategy that reads the scoring pass's own frames ([`shots_from_frame_pass()`](#muvid.footage.scoring.segment.shots_from_frame_pass)).                                                                                        |
|-------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`SHOT_STRATEGY_ENV_VAR`](#muvid.footage.scoring.segment.SHOT_STRATEGY_ENV_VAR)  | The env var that picks the strategy `score_project(shot_strategy=None)` uses ([`default_shot_strategy()`](#muvid.footage.scoring.segment.default_shot_strategy)); any value but `"frames"` names a `mixing.video.shots` strategy. |
| [`FRAMES_CUT_RULE`](#muvid.footage.scoring.segment.FRAMES_CUT_RULE)        | for continuous footage (see the module docstring), not for edited video.                                                                                                                                                 |
| [`FRAMES_MIN_SHOT_S`](#muvid.footage.scoring.segment.FRAMES_MIN_SHOT_S)      | The frames strategy's shortest shot (s).                                                                                                                                                                                 |
| [`PYSCENEDETECT_STRATEGY`](#muvid.footage.scoring.segment.PYSCENEDETECT_STRATEGY) | The `mixing.video.shots` strategy that needs an optional package, and that package (the `scoring-shots` extra): absent, it is `[]`, never a fallback decode.                                                             |

### Functions

| [`coverage_mask`](#muvid.footage.scoring.segment.coverage_mask)(\*, offset_s, duration_s, ...)    | Grid frames (bool[n]) the clip covers — using its clamped `coverage` span.                                                                                                                    |
|--------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`default_shot_strategy`](#muvid.footage.scoring.segment.default_shot_strategy)()                         | `$MUVID_SCORING_SHOT_STRATEGY`, else [`FRAMES_STRATEGY`](#muvid.footage.scoring.segment.FRAMES_STRATEGY) — read when a run starts, not when this module is imported, so a host may set it later. |
| [`shot_boundaries`](#muvid.footage.scoring.segment.shot_boundaries)(clip_path, \*, offset_s[, ...]) | Song-times of within-clip scene cuts, or `[]` when `strategy`'s package is not installed (so `beats+shots` degrades to beats-only).                                                           |
| [`shots_available`](#muvid.footage.scoring.segment.shots_available)([strategy])                     | Whether `strategy` (default [`default_shot_strategy()`](#muvid.footage.scoring.segment.default_shot_strategy)) can detect anything here.                                                               |
| [`shots_from_frame_pass`](#muvid.footage.scoring.segment.shots_from_frame_pass)(frame_pass, \*, offset_s) | Song-times of the cuts in the scoring pass's own frames (`frames` strategy).                                                                                                                  |

### muvid.footage.scoring.segment.FRAMES_CUT_RULE *= 'spike'*

for continuous
footage (see the module docstring), not for edited video.

* **Type:**
  The frames strategy’s `mixing.shot_changes.cut_indices` rule

### muvid.footage.scoring.segment.FRAMES_MIN_SHOT_S *= 0.5*

The frames strategy’s shortest shot (s). The spike rule reads a missing neighbour
as no change, so a clip’s first and last change need beat only ONE neighbour: a
0.25 s fade-in (a phone settling its exposure) read as a cut 0.2 s into the clip,
a fade-out as one at its last sample (the #259 review, measured). Two sample
intervals at 5 Hz is the floor; 0.5 s removed all three edge cuts measured and
kept two real cuts 1 s apart.

### muvid.footage.scoring.segment.FRAMES_STRATEGY *= 'frames'*

The strategy that reads the scoring pass’s own frames ([`shots_from_frame_pass()`](#muvid.footage.scoring.segment.shots_from_frame_pass)).

### muvid.footage.scoring.segment.PYSCENEDETECT_STRATEGY *= 'pyscenedetect'*

The `mixing.video.shots` strategy that needs an optional package, and that package
(the `scoring-shots` extra): absent, it is `[]`, never a fallback decode.

### muvid.footage.scoring.segment.SHOT_STRATEGY_ENV_VAR *= 'MUVID_SCORING_SHOT_STRATEGY'*

The env var that picks the strategy `score_project(shot_strategy=None)` uses
([`default_shot_strategy()`](#muvid.footage.scoring.segment.default_shot_strategy)); any value but `"frames"` names a
`mixing.video.shots` strategy.

### muvid.footage.scoring.segment.coverage_mask(, offset_s, duration_s, coverage, t0, hop_s, n)

Grid frames (bool[n]) the clip covers — using its clamped `coverage` span.

* **Return type:**
  `ndarray`

### muvid.footage.scoring.segment.default_shot_strategy()

`$MUVID_SCORING_SHOT_STRATEGY`, else [`FRAMES_STRATEGY`](#muvid.footage.scoring.segment.FRAMES_STRATEGY) — read when a run
starts, not when this module is imported, so a host may set it later.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

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

### muvid.footage.scoring.segment.shots_available(strategy=None)

Whether `strategy` (default [`default_shot_strategy()`](#muvid.footage.scoring.segment.default_shot_strategy)) can detect anything
here.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### muvid.footage.scoring.segment.shots_from_frame_pass(frame_pass, , offset_s, rule='spike', min_shot_s=0.5)

Song-times of the cuts in the scoring pass’s own frames (`frames` strategy).

`frame_pass.shot_change[i]` is the change between samples `i` and `i + 1`;
`mixing.shot_changes.shots_from_changes` picks the cuts (its adaptive threshold,
`rule`; spans shorter than `min_shot_s` merged) and its spans tile the sampled
clip. The true cut lies somewhere in `(t_i, t_{i+1}]`; this reports `t_i`, the
LAST sample known to show the old shot, because the selector makes the time a hard
boundary of the segment before it, and `t_{i+1}` let that segment carry up to a
sample (0.2 s at 5 Hz) of the next shot — the within-clip jump the mode avoids.
So a cut is quantised to the sample rate, early by under one sample. Each cut is
moved onto the song by `offset_s`. No changes (one sample, or none) → no cuts.

Raises `ValueError` when the pass’s changes and times do not line up (one more
time than change): a malformed pass is a failure to record, not “no cuts”.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]
