# muvid.footage.sound

The clips’ own sound under the song — and the song kept removable.

A music video’s audio is the clean song and nothing else (the assembler mutes every clip).
A promo, a recap or a class video is different: the picture is cut to the music, but the
people in it talk, breathe and laugh, and that sound (“production sound”, “nat sound”) is
part of what sells it. Editors keep it on its own track under a music bed and duck the
music when someone speaks; and because the music is the part most often replaced (a
licence, a client’s taste, a better track found later), they deliver it as **stems** —
the music, the production sound, and the mix — rather than one baked track.

This module is that, for a rendered footage edit:

- [`song_stem()`](#muvid.footage.sound.song_stem) is the music as the render plays it (cut to the edit’s window, faded
  at its tail when the window ends early), taken from the song itself, not decoded back
  out of the render (each AAC pass shifts audio by the encoder’s priming).
- [`clip_sound_track()`](#muvid.footage.sound.clip_sound_track) builds the production-sound stem from the same cuts the
  picture was rendered from: each video cut contributes its own audio for exactly its span
  (from its in-point, on the clip’s own clock: an audio stream that starts after its
  video is padded, not pulled early) at its own level (`EdlEntry.sound_db`), with a
  short fade at each edge so a cut does not click; a photo, a gap, a retimed cut (slow
  motion has no sync sound) or a clip with no audio stream is silence. Its length is the
  render’s, sample for sample.
- the clips’ sound is split in two stems by each cut’s level: **dialogue** (the cuts
  meant to be heard: soundbites, nat pops) and **nat** (the room under every other
  shot). [`mix_under()`](#muvid.footage.sound.mix_under) raises the dialogue toward a speech level, ducks the music
  under it alone (`mixing.audio.duck_audio`, the fleet’s one ducker) by as much as
  puts the speech [`SPEECH_OVER_MUSIC_DB`](#muvid.footage.sound.SPEECH_OVER_MUSIC_DB) over the music, lays the nat sound in as a
  bed, and limits the sum to [`PEAK_DBFS`](#muvid.footage.sound.PEAK_DBFS).
- [`mux_audio()`](#muvid.footage.sound.mux_audio) puts one audio track on a picture, compensating the AAC encoder’s
  priming so the sound lands on the frame it was cut to.

The render op ([`muvid.footage.service.render()`](muvid.footage.service.html.md#muvid.footage.service.render), `sound="song_and_clips"`) is
their one caller and records the stems and the mix parameters beside `final.mp4`.
Research behind the numbers: `misc/docs/research/general/promo_video_editing_and_music.md`.

### Module Attributes

| [`SAMPLE_RATE`](#muvid.footage.sound.SAMPLE_RATE)           | Sample rate and channel count of every stem — the delivery contract's (aac 48 kHz 2ch).                                                                                                                |
|------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`EDGE_FADE_S`](#muvid.footage.sound.EDGE_FADE_S)           | Fade at each edge of a cut's sound, so a hard cut in the picture is not a click in the sound.                                                                                                          |
| [`DEFAULT_CLIP_SOUND_DB`](#muvid.footage.sound.DEFAULT_CLIP_SOUND_DB) | The level of a cut's own sound when its edit entry names none (`sound_db` `None`).                                                                                                                     |
| [`DIALOGUE_MIN_DB`](#muvid.footage.sound.DIALOGUE_MIN_DB)       | what the people in it say is meant to be heard (a soundbite, a nat-sound pop).                                                                                                                         |
| [`SPEECH_TARGET_DBFS`](#muvid.footage.sound.SPEECH_TARGET_DBFS)    | Dialogue is raised (never lowered) toward this speech level (dBFS, median RMS of its active frames) — a phone held across a room records a voice at -35..-30 dBFS — by at most `MAX_DIALOGUE_GAIN_DB`. |
| [`SPEECH_OVER_MUSIC_DB`](#muvid.footage.sound.SPEECH_OVER_MUSIC_DB)  | speech 12-15 LU over the music, at least 10).                                                                                                                                                          |
| [`DIALOGUE_ACTIVE_DBFS`](#muvid.footage.sound.DIALOGUE_ACTIVE_DBFS)  | Inside the dialogue stem (only the cuts meant to be heard), a frame louder than this (dBFS) is speech for the ducker: the whole of a soundbite, its pauses included, holds the music down.             |
| [`SPEECH_PERCENTILE`](#muvid.footage.sound.SPEECH_PERCENTILE)     | this percentile of its active frames' RMS (dB), high enough that the pauses between words do not drag it down.                                                                                         |
| [`PEAK_DBFS`](#muvid.footage.sound.PEAK_DBFS)             | headroom for the AAC encode, the research's -1 dBTP delivery rule approximated on samples.                                                                                                             |
| [`AAC_PRIMING_SAMPLES`](#muvid.footage.sound.AAC_PRIMING_SAMPLES)   | Samples the AAC encoder prepends ("priming").                                                                                                                                                          |

### Functions

| [`clip_sound_track`](#muvid.footage.sound.clip_sound_track)(cuts, out_path, \*[, ...])      | Write the production-sound stem of `cuts` (`AssemblyCut`-like: `song_start`, `song_end`, `clip_id`, `clip_in`, `clip_path`, `rate`, `sound_db`) to `out_path` (wav).                                                        |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`is_dialogue`](#muvid.footage.sound.is_dialogue)(cut, level)                          | A cut whose sound is meant to be heard (at or over [`DIALOGUE_MIN_DB`](#muvid.footage.sound.DIALOGUE_MIN_DB)).                                                                                                       |
| `is_nat`(cut, level)                                                                              |                                                                                                                                                                                                                             |
| [`mix_params`](#muvid.footage.sound.mix_params)(\*[, default_db])                     | What a `song_and_clips` render records about its mix, so a later change of these defaults is visible against an old render (and a re-render can reproduce it).                                                              |
| [`mix_under`](#muvid.footage.sound.mix_under)(music, dialogue, nat, out_path, \*)    | Mix `music` over the clips' sound, split as `dialogue` and `nat` (wav stems of equal length), into `out_path`:                                                                                                              |
| [`mux_audio`](#muvid.footage.sound.mux_audio)(video, audio, out_path, \*[, ...])     | `video`'s picture (stream-copied) with `audio` as its one audio track (aac), at the video's length; the encoder's priming is trimmed off the input (and the tail padded back), so the sound is where it was on the picture. |
| [`read_wav`](#muvid.footage.sound.read_wav)(path)                                   | `(samples, rate)` of a PCM wav: float in [-1, 1], shape `(n, channels)`.                                                                                                                                                    |
| [`silent_unless_set`](#muvid.footage.sound.silent_unless_set)(cuts, mute, \*[, level])       | `cuts` with every cut of a `mute` clip that names no `sound_db` set to `level` — the clips whose own audio is a recording of the song (a music video's synced footage), which under the master would double it.             |
| [`song_stem`](#muvid.footage.sound.song_stem)(song_path, out_path, \*, start_s, ...) | The music stem: `duration_s` of the song from `start_s` (wav), faded out over its last `fade_out_s` seconds — the same window and fade the render applies.                                                                  |
| [`write_wav`](#muvid.footage.sound.write_wav)(path, samples, rate)                   | Write float samples (`(n, channels)` or `(n,)`, clipped to [-1, 1]) as 16-bit PCM wav.                                                                                                                                      |

### muvid.footage.sound.AAC_PRIMING_SAMPLES *= 1024*

Samples the AAC encoder prepends (“priming”). Without an edit list (muvid’s delivery
contract writes none) a player plays them, so the sound would land 21.3 ms late at
48 kHz; [`mux_audio()`](#muvid.footage.sound.mux_audio) trims them off the input to compensate.

### muvid.footage.sound.DEFAULT_CLIP_SOUND_DB *= 0.0*

The level of a cut’s own sound when its edit entry names none (`sound_db` `None`).

### muvid.footage.sound.DIALOGUE_ACTIVE_DBFS *= -55.0*

Inside the dialogue stem (only the cuts meant to be heard), a frame louder than this
(dBFS) is speech for the ducker: the whole of a soundbite, its pauses included, holds
the music down. Silence (the other cuts) is far below it.

### muvid.footage.sound.DIALOGUE_MIN_DB *= -6.0*

what
the people in it say is meant to be heard (a soundbite, a nat-sound pop). Quieter cuts
are NAT sound: the room as a bed under the music. `None` (the default level, 0 dB)
is dialogue, so a render whose cuts name no level ducks on all of them, as before.

* **Type:**
  A cut whose own sound is at least this loud (dB, its `sound_db`) is DIALOGUE

### muvid.footage.sound.EDGE_FADE_S *= 0.04*

Fade at each edge of a cut’s sound, so a hard cut in the picture is not a click in the
sound. Short enough to keep a word that starts on the cut intelligible.

### muvid.footage.sound.PEAK_DBFS *= -1.0*

headroom for the AAC encode, the
research’s -1 dBTP delivery rule approximated on samples.

* **Type:**
  The mix’s sample peak never exceeds this (dBFS)

### muvid.footage.sound.SAMPLE_RATE *= 48000*

Sample rate and channel count of every stem — the delivery contract’s (aac 48 kHz 2ch).

### muvid.footage.sound.SPEECH_OVER_MUSIC_DB *= 12.0*

speech
12-15 LU over the music, at least 10). The duck is sized to reach it, between
`DUCK_DB` (the least it ducks) and `MAX_DUCK_DB` (the most).

* **Type:**
  Speech sits at least this far over the music under it (dB; research rule 17

### muvid.footage.sound.SPEECH_PERCENTILE *= 75.0*

this percentile of its active frames’ RMS (dB), high
enough that the pauses between words do not drag it down.

* **Type:**
  The speech level of the dialogue

### muvid.footage.sound.SPEECH_TARGET_DBFS *= -20.0*

Dialogue is raised (never lowered) toward this speech level (dBFS, median RMS of its
active frames) — a phone held across a room records a voice at -35..-30 dBFS — by at
most `MAX_DIALOGUE_GAIN_DB`.

### muvid.footage.sound.clip_sound_track(cuts, out_path, , edge_fade_s=0.04, default_db=0.0, sample_rate=48000, keep=None)

Write the production-sound stem of `cuts` (`AssemblyCut`-like: `song_start`,
`song_end`, `clip_id`, `clip_in`, `clip_path`, `rate`, `sound_db`) to
`out_path` (wav).

The stem starts at `cuts[0].song_start` and is exactly as long as the cuts span: each
sounding cut is its clip’s audio from `clip_in` for the cut’s duration at its
`sound_db` (`default_db` when `None`), padded with silence where the clip’s
audio starts late or runs out; every other cut is silence, and so is every cut
`keep(cut, level)` rejects (how the dialogue and nat stems are split).

```pycon
>>> clip_sound_track([], "x.wav")
Traceback (most recent call last):
...
ValueError: no cuts
```

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### muvid.footage.sound.is_dialogue(cut, level)

A cut whose sound is meant to be heard (at or over [`DIALOGUE_MIN_DB`](#muvid.footage.sound.DIALOGUE_MIN_DB)).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### muvid.footage.sound.mix_params(, default_db=0.0, \*\*measured)

What a `song_and_clips` render records about its mix, so a later change of these
defaults is visible against an old render (and a re-render can reproduce it).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### muvid.footage.sound.mix_under(music, dialogue, nat, out_path, , clips_out=None, speech_target_dbfs=-20.0, speech_over_music_db=12.0, duck_db=-8.0, max_duck_db=-30.0, active_dbfs=-55.0, peak_dbfs=-1.0)

Mix `music` over the clips’ sound, split as `dialogue` and `nat` (wav
stems of equal length), into `out_path`:

- the dialogue is raised toward `speech_target_dbfs` (never lowered), and the music
  ducked under it (`mixing.audio.duck_audio`, keyed on the dialogue alone) by as much
  as puts the speech `speech_over_music_db` over the music, between `duck_db` and
  `max_duck_db`;
- the nat sound (the room under the other shots) is laid in as it is, never ducking
  anything;
- all of it summed in floating point and scaled down (never up) so the peak stays
  at or under `peak_dbfs`.

`clips_out` (optional) receives the clips’ sound as mixed (dialogue at its gain +
nat): with the ducked music it sums to the mix. Returns the parameters that made it
(dialogue gain, duck depth, speech and music levels, the limiter’s gain).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### muvid.footage.sound.mux_audio(video, audio, out_path, , bitrate='192k', priming_samples=1024)

`video`’s picture (stream-copied) with `audio` as its one audio track (aac),
at the video’s length; the encoder’s priming is trimmed off the input (and the tail
padded back), so the sound is where it was on the picture.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### muvid.footage.sound.read_wav(path)

`(samples, rate)` of a PCM wav: float in [-1, 1], shape `(n, channels)`.
Stdlib `wave` + numpy, so the stems need no audio library beyond ffmpeg.

### muvid.footage.sound.silent_unless_set(cuts, mute, , level=-60.0)

`cuts` with every cut of a `mute` clip that names no `sound_db` set to
`level` — the clips whose own audio is a recording of the song (a music video’s
synced footage), which under the master would double it.

### muvid.footage.sound.song_stem(song_path, out_path, , start_s, duration_s, fade_out_s=0.0, sample_rate=48000)

The music stem: `duration_s` of the song from `start_s` (wav), faded out over
its last `fade_out_s` seconds — the same window and fade the render applies.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### muvid.footage.sound.write_wav(path, samples, rate)

Write float samples (`(n, channels)` or `(n,)`, clipped to [-1, 1]) as 16-bit
PCM wav.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
