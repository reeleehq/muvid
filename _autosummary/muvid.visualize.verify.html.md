# muvid.visualize.verify

Check a rendered music video against what YouTube actually wants.

Rendering can succeed and still produce something wrong: a video a few seconds
longer than the song, a pixel format half the world cannot decode, a thumbnail
over the upload limit, a track 6 LU quieter than the rest of the album. Those
failures are silent — the file plays fine locally — so they are worth asserting
rather than eyeballing.

```pycon
>>> from muvid.visualize import verify_video, report
>>> checks = verify_video("song.mp4", audio="song.wav")
>>> print(report(checks))
✓ container      h264 / aac
✓ pixel format   yuv420p
...
```

This is the machine-checkable half of the quality checklist; the `music2video`
skill carries the half that needs judgement.

### Module Attributes

| [`DURATION_TOLERANCE`](#muvid.visualize.verify.DURATION_TOLERANCE)   | How far the video may run past (or short of) the audio, in seconds.           |
|-----------------------------------------------------------------------|-------------------------------------------------------------------------------|
| [`LOUDNESS_TOLERANCE`](#muvid.visualize.verify.LOUDNESS_TOLERANCE)   | How far the integrated loudness may sit from the target, in LU.               |
| [`METER_SAMPLE_RATE`](#muvid.visualize.verify.METER_SAMPLE_RATE)    | The rate and channel count the meter decodes at when the stream does not say. |
| [`LoudnessMeter`](#muvid.visualize.verify.LoudnessMeter)        | `media -> integrated LUFS` (muvid#219).                                       |

### Functions

| [`failures`](#muvid.visualize.verify.failures)(checks)                                 | Just the checks that failed.                                               |
|---------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| [`measure_integrated_lufs`](#muvid.visualize.verify.measure_integrated_lufs)(media)                   | The BS.1770-4 integrated loudness of `media`'s audio, in LUFS (muvid#219). |
| [`report`](#muvid.visualize.verify.report)(checks)                                   | Render `checks` as an aligned, readable block.                             |
| [`verify_video`](#muvid.visualize.verify.verify_video)(video, \*[, audio, thumbnail, ...]) | Check `video` against YouTube's expectations; return one result per check. |

### Classes

| [`Check`](#muvid.visualize.verify.Check)(name, ok, detail)   | One verification result.   |
|----------------------------------------------------------------------------|----------------------------|

### *class* muvid.visualize.verify.Check(name, ok, detail)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One verification result.

### muvid.visualize.verify.DURATION_TOLERANCE *= 0.5*

How far the video may run past (or short of) the audio, in seconds. A still
video is cut on a GOP boundary, so an exact match is not achievable.

### muvid.visualize.verify.LOUDNESS_TOLERANCE *= 1.5*

How far the integrated loudness may sit from the target, in LU. Encoding to
AAC moves it slightly, so demanding an exact hit would fail every time.

### muvid.visualize.verify.LoudnessMeter

`media -> integrated LUFS` (muvid#219).

* **Type:**
  A loudness meter

alias of `Callable`[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]

### muvid.visualize.verify.METER_SAMPLE_RATE *= 48000*

The rate and channel count the meter decodes at when the stream does not say.

### muvid.visualize.verify.failures(checks)

Just the checks that failed.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Check`](#muvid.visualize.verify.Check)]

### muvid.visualize.verify.measure_integrated_lufs(media)

The BS.1770-4 integrated loudness of `media`’s audio, in LUFS (muvid#219).

Decoded by muvid ([`stream_pcm()`](muvid.visualize.ffmpeg.html.md#muvid.visualize.ffmpeg.stream_pcm): the ffmpeg muvid
renders with, bounded by `$MUVID_FFMPEG_TIMEOUT_S`, a failure an
[`FfmpegError`](muvid.visualize.ffmpeg.html.md#muvid.visualize.ffmpeg.FfmpegError)) at the stream’s own rate and channel
count, and metered as it streams by `mixing.loudness.stream_loudness`, so memory
stays bounded whatever the length where the samples held whole cost 577 MB for five
minutes. Within about 0.05 LU of ffmpeg’s `loudnorm` analysis at 44.1/48 kHz
(0.15-0.35 LU at 8-22 kHz; 5.1 reads about 0.5 LU low — no surround weights — and
muvid renders stereo), in a fraction of its time. Normalising still uses two-pass
`loudnorm` ([`muvid.visualize.ffmpeg.measure_loudness()`](muvid.visualize.ffmpeg.html.md#muvid.visualize.ffmpeg.measure_loudness)). No fallback: a
failure here is a traceback, not a quietly different meter.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### muvid.visualize.verify.report(checks)

Render `checks` as an aligned, readable block.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### muvid.visualize.verify.verify_video(video, \*, audio=None, thumbnail=None, loudness=None, check_loudness=False, duration_tolerance=0.5, expected_canvas=None, expected_duration=None, loudness_meter=<function measure_integrated_lufs>)

Check `video` against YouTube’s expectations; return one result per check.

* **Parameters:**
  * **video** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)) – The rendered mp4.
  * **audio** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – The source song — enables the duration-match check, which is the
    one that catches a mis-built filtergraph.
  * **thumbnail** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – The thumbnail to check against YouTube’s limits.
  * **loudness** ([`Loudness`](muvid.visualize.ffmpeg.html.md#muvid.visualize.ffmpeg.Loudness) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – The target the video was normalized to.
  * **check_loudness** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Actually measure the output’s loudness. This decodes the
    whole track, so it is off by default.
  * **duration_tolerance** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Allowed audio/video duration difference, in seconds.
  * **expected_canvas** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – The `(width, height)` the render was ASKED for. When
    given, the aspect/resolution checks verify the output matches it —
    a deliberate portrait render must not fail a hard-coded 16:9 check.
    When `None`, the classic YouTube-landscape expectations apply.
  * **expected_duration** ([`float`](https://docs.python.org/3/builtins/functions.html#float) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – The length the render was ASKED for, when that is not
    the whole of `audio` — a trimmed edit renders only part of the song.
    Arms the duration check on its own, and wins over `audio`’s length.
  * **loudness_meter** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]) – How `check_loudness` measures: `media -> LUFS`. Default
    [`measure_integrated_lufs()`](#muvid.visualize.verify.measure_integrated_lufs).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Check`](#muvid.visualize.verify.Check)]
* **Returns:**
  A list of [`Check`](#muvid.visualize.verify.Check). Falsy checks are the problems; [`report()`](#muvid.visualize.verify.report)
  renders them, and [`failures()`](#muvid.visualize.verify.failures) filters them.
