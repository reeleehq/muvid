# muvid.footage.capture_time

When a photo or a video was taken, read from the file itself (muvid#137).

“Cut to the music” should let a day read in order, as Apple Memories and GoPro Quik do, so
each clip row carries the time its file says it was captured: EXIF `DateTimeOriginal`
for a photo, the QuickTime `creationdate` (else `creation_time`) tag for a video.

**Times are wall-clock seconds, not instants.** A camera writes the local time it showed
and (for EXIF) no zone, so every source here is reduced to the same thing — the time on
the wall clock, read as if it were UTC — which makes a photo and a video from one phone
comparable. A video that only carries a UTC `creation_time` is the exception and is
compared as is (off by the zone offset from the photos beside it); the `source` returned
beside the time says which tag it came from so a caller can tell.

**Absent is not zero.** A file with no tag, a tag that is not a date, or one before
[`MIN_PLAUSIBLE_YEAR`](#muvid.footage.capture_time.MIN_PLAUSIBLE_YEAR) (cameras without a clock write 1904 or 1970) gives `None` —
never a made-up time. Reading is best effort and must never fail an upload.

### Module Attributes

| [`MIN_PLAUSIBLE_YEAR`](#muvid.footage.capture_time.MIN_PLAUSIBLE_YEAR)   | A capture time earlier than this year is a camera with no clock set, not a date.   |
|-----------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`PROBE_TIMEOUT_S`](#muvid.footage.capture_time.PROBE_TIMEOUT_S)      | Seconds ffprobe may spend on one file.                                             |
| [`EXIF_ORIGINAL`](#muvid.footage.capture_time.EXIF_ORIGINAL)        | `source` values of a returned time.                                                |
| [`EXIF_DATETIME`](#muvid.footage.capture_time.EXIF_DATETIME)        | `source` values of a returned time.                                                |

### Functions

| [`photo_capture_time`](#muvid.footage.capture_time.photo_capture_time)(image)   | `(time, source)` from an open PIL image's EXIF.                                   |
|------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`video_capture_time`](#muvid.footage.capture_time.video_capture_time)(path)    | `(time, source)` from a video's container tags (`ffprobe`).                       |
| [`wall_clock_seconds`](#muvid.footage.capture_time.wall_clock_seconds)(text)    | Seconds since 1970 of the wall-clock stamp in `text`; any zone suffix is ignored. |

### muvid.footage.capture_time.EXIF_DATETIME *= 'exif:DateTime'*

`source` values of a returned time.

### muvid.footage.capture_time.EXIF_ORIGINAL *= 'exif:DateTimeOriginal'*

`source` values of a returned time.

### muvid.footage.capture_time.MIN_PLAUSIBLE_YEAR *= 1990*

A capture time earlier than this year is a camera with no clock set, not a date.

### muvid.footage.capture_time.PROBE_TIMEOUT_S *= 20.0*

Seconds ffprobe may spend on one file.

### muvid.footage.capture_time.photo_capture_time(image)

`(time, source)` from an open PIL image’s EXIF.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### muvid.footage.capture_time.video_capture_time(path)

`(time, source)` from a video’s container tags (`ffprobe`).

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### muvid.footage.capture_time.wall_clock_seconds(text)

Seconds since 1970 of the wall-clock stamp in `text`; any zone suffix is ignored.

```pycon
>>> wall_clock_seconds("2024:06:01 14:03:22")
1717250602.0
>>> wall_clock_seconds("2024-06-01T14:03:22-0700") == wall_clock_seconds("2024:06:01 14:03:22")
True
>>> wall_clock_seconds("0000:00:00 00:00:00") is None, wall_clock_seconds("nope") is None
(True, True)
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]
