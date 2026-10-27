# muvid.footage.scoring.motionbeat

Motion-to-beat tier: `motion_beat_bas` + `motion_onset_xcorr` → song-grid tracks.

Pure given a [`FramePass`](muvid.footage.scoring.frames.html.md#muvid.footage.scoring.frames.FramePass) (the camera-compensated motion
envelope) + the master `mixing.audio.BeatGrid` (computed ONCE on the clean song). No
per-clip beat/onset recomputation — everything maps to song time via the clip’s offset.

- `motion_beat_bas` — a per-beat Beat Alignment Score (AIST++ [11] idea, localized): each
  audio beat scores how close its nearest MOTION peak is (`exp(−(Δt/σ)²/2)`); the score is
  held over that beat’s interval. NA where the clip has no motion (static / no person) — never
  0 (a 0 would penalize valid instrumental footage). Person-present signal.
- `motion_onset_xcorr` — the clip-level normalized cross-correlation of the motion envelope
  vs the master onset envelope at the best lag within a bounded A/V-latency window (the lag
  refines per-clip capture latency). Content-agnostic (covers no-person clips). Held over the
  clip’s coverage.

The BAS formula is also a PURE function over event and beat times (muvid#238),
[`beat_alignment_score()`](#muvid.footage.scoring.motionbeat.beat_alignment_score), so a caller with its own motion signal (pose landmarks, say)
gets the number the `motion_beat_bas` track is built from; the track calls the same core.
(The onset lag is NOT exposed: the track’s search shifts circularly over its window, which
is harmless for the `|r|` it keeps and wrong for a lag a caller would read — a correct
public one belongs beside mixing’s overlap-normalised cross-correlation.)

Commercial-clean (librosa beats via `mixing[beats]`, numpy motion). See the design §3b.

### Module Attributes

| [`BAS_SIGMA_S`](#muvid.footage.scoring.motionbeat.BAS_SIGMA_S)    | Gaussian width (s) for beat↔motion-peak proximity in the BAS.                                                                    |
|-----------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------|
| [`BAS_DIRECTIONS`](#muvid.footage.scoring.motionbeat.BAS_DIRECTIONS) | AIST++'s (each MOTION beat scored by its nearest music beat) and Bailando's (each MUSIC beat scored by its nearest motion beat). |

### Functions

| [`beat_alignment_score`](#muvid.footage.scoring.motionbeat.beat_alignment_score)(event_times, beat_times, \*)   | The Beat Alignment Score of motion `event_times` (kinematic beats, seconds) against music `beat_times`: the mean of `exp(-(d/σ)²/2)`, `d` the distance to the nearest beat of the other kind (AIST++, Li et al. 2021, §BeatAlign).   |
|------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`motionbeat_tracks`](#muvid.footage.scoring.motionbeat.motionbeat_tracks)(frame_pass, \*, clip_id, ...)     | The two motion-to-beat tracks for one clip.                                                                                                                                                                                          |

### muvid.footage.scoring.motionbeat.BAS_DIRECTIONS *= ('motion_to_music', 'music_to_motion')*

AIST++’s (each MOTION beat scored by its
nearest music beat) and Bailando’s (each MUSIC beat scored by its nearest motion beat).

* **Type:**
  The two directions papers measure the BAS in

### muvid.footage.scoring.motionbeat.BAS_SIGMA_S *= 0.12*

Gaussian width (s) for beat↔motion-peak proximity in the BAS.

### muvid.footage.scoring.motionbeat.beat_alignment_score(event_times, beat_times, , sigma_s=0.12, direction='motion_to_music')

The Beat Alignment Score of motion `event_times` (kinematic beats, seconds)
against music `beat_times`: the mean of `exp(-(d/σ)²/2)`, `d` the distance to
the nearest beat of the other kind (AIST++, Li et al. 2021, §BeatAlign).

`direction` is [`BAS_DIRECTIONS`](#muvid.footage.scoring.motionbeat.BAS_DIRECTIONS): `motion_to_music` (AIST++) averages over
the motion events, `music_to_motion` (Bailando) over the music beats — the per-beat
form the `motion_beat_bas` track holds over each beat’s interval. `nan` when
either list is empty: no evidence is not a score of 0. A non-finite time or a
`sigma_s` that is not positive is refused rather than read as `nan`.

```pycon
>>> round(beat_alignment_score([0.5, 1.0, 1.62], [0.5, 1.0, 1.5]), 3)  # one 0.12 s late
0.869
>>> round(beat_alignment_score([0.5], [0.5, 1.0], direction="music_to_motion"), 3)
0.5
```

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### muvid.footage.scoring.motionbeat.motionbeat_tracks(frame_pass, , clip_id, offset_s, beat_times, onset_env, onset_hop_s, t0, hop_s, n)

The two motion-to-beat tracks for one clip.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`ScoreTrack`](muvid.footage.scoring.grid.html.md#muvid.footage.scoring.grid.ScoreTrack)]
