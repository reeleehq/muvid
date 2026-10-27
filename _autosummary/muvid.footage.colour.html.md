# muvid.footage.colour

The colour every assembled video is delivered in, and how a source’s colour is read.

muvid#195. The assembler’s per-cut `scale` converts every source to
[`DELIVERY_COLOR_SPACE`](#muvid.footage.colour.DELIVERY_COLOR_SPACE) at [`DELIVERY_COLOR_RANGE`](#muvid.footage.colour.DELIVERY_COLOR_RANGE), [`DELIVERY_TAG`](#muvid.footage.colour.DELIVERY_TAG)
says so on the frame, and the encode carries the same tags. That gives a look a
frame whose colour is a FACT, which [`muvid.footage.look.stylize()`](muvid.footage.look.html.md#muvid.footage.look.stylize) declares for
`looks` Rule 22 instead of assuming it (muvid#190).

Measured on ffmpeg 8.0.1 and 7.0.2, against the RGB original, decoded the way a
player reads a BT.709-tagged file: a BT.601 clip 24 -> 37 dB, a full-range JPEG
still 24 -> 41 dB, a PNG 24 -> 40 dB, a tagged BT.709 clip unchanged at 40 dB.

Two things the conversion cannot get right from the frame alone, which is why a
source is read here first ([`read_source_colour()`](#muvid.footage.colour.read_source_colour)):

- **An untagged source.** `scale` reads the frame’s matrix tag and swscale treats
  an unspecified one as BT.601, while players read untagged HD as BT.709. Measured:
  an untagged 1280x720 BT.709 clip went 41.6 -> 26.9 dB on both builds until the
  assembler told `scale` the matrix. An untagged YUV source that players call HD
  ([`is_hd()`](#muvid.footage.colour.is_hd)) is therefore converted FROM BT.709; an SD one keeps swscale’s
  BT.601, which is the SD convention.
- **An HDR source** (HLG or PQ transfer — iPhone footage records HLG by default).
  Only the YCbCr matrix and range are converted; BT.2020 primaries and an HDR
  transfer are not, so the delivered SDR picture looks washed out. Before muvid#195
  the part kept its HDR tags, which an HDR-aware player honoured; now it is tagged
  BT.709. That is not fixed here (tone mapping, muvid#201), so it is REPORTED: the
  assembler sends a finding naming each HDR clip.

Import-light (stdlib only at module top): the look compiler imports the constants.

### Module Attributes

| [`DELIVERY_COLOR_SPACE`](#muvid.footage.colour.DELIVERY_COLOR_SPACE)   | The delivery matrix — and the primaries and transfer it is tagged with.                                                                                                                                 |
|-------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`DELIVERY_COLOR_RANGE`](#muvid.footage.colour.DELIVERY_COLOR_RANGE)   | limited ("tv"), the range H.264 delivery is read in.                                                                                                                                                    |
| [`DELIVERY_TAG`](#muvid.footage.colour.DELIVERY_TAG)           | The frame-level tag the assembler places last in each part's chain, after the look (and on a gap's black).                                                                                              |
| [`HD_MIN_WIDTH`](#muvid.footage.colour.HD_MIN_WIDTH)           | Where players draw the line between SD (BT.601) and HD (BT.709) for an untagged source: at least this wide, OR taller than [`SD_MAX_HEIGHT`](#muvid.footage.colour.SD_MAX_HEIGHT) (mpv's rule). |
| [`SD_MAX_HEIGHT`](#muvid.footage.colour.SD_MAX_HEIGHT)          | The tallest SD frame (PAL, 576 lines).                                                                                                                                                                  |
| [`HDR_TRANSFERS`](#muvid.footage.colour.HDR_TRANSFERS)          | ffprobe's names for the transfers that make a source HDR (HLG, PQ).                                                                                                                                     |

### Functions

| [`read_source_colour`](#muvid.footage.colour.read_source_colour)(path, \*[, probe])   | The [`SourceColour`](#muvid.footage.colour.SourceColour) of the first video stream of `path`.   |
|------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------|
| [`is_hd`](#muvid.footage.colour.is_hd)(width, height)                    | Whether players read an untagged `width` x `height` source as HD (BT.709).                               |
| [`source_colour`](#muvid.footage.colour.source_colour)(stream)                   | A probed video stream's [`SourceColour`](#muvid.footage.colour.SourceColour).                   |

### Classes

| [`SourceColour`](#muvid.footage.colour.SourceColour)([in_matrix, hdr_transfer])   | What the assembler needs to know about one source's colour.   |
|--------------------------------------------------------------------------------------------|---------------------------------------------------------------|

### muvid.footage.colour.DELIVERY_COLOR_RANGE *= 'tv'*

limited (“tv”), the range H.264 delivery is read in.

* **Type:**
  The delivery range

### muvid.footage.colour.DELIVERY_COLOR_SPACE *= 'bt709'*

The delivery matrix — and the primaries and transfer it is tagged with. BT.709 is
what a player assumes for untagged HD and what phone video mostly is already.

### muvid.footage.colour.DELIVERY_TAG *= 'setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709'*

The frame-level tag the assembler places last in each part’s chain, after the
look (and on a gap’s black). On the FRAME, not only on the encoder: ffmpeg 8.0.1 takes
the stream’s colour description from the frames and ignores `-color_primaries`
/ `-color_trc` (measured: both came out `unknown` with the options alone).

### muvid.footage.colour.HDR_TRANSFERS *= frozenset({'arib-std-b67', 'smpte2084'})*

ffprobe’s names for the transfers that make a source HDR (HLG, PQ).

### muvid.footage.colour.HD_MIN_WIDTH *= 1280*

Where players draw the line between SD (BT.601) and HD (BT.709) for an untagged
source: at least this wide, OR taller than [`SD_MAX_HEIGHT`](#muvid.footage.colour.SD_MAX_HEIGHT) (mpv’s rule).
Width matters for letterboxed HD — an untagged 1280x536 BT.709 clip measured
26.9 dB under a height-only rule.

### muvid.footage.colour.SD_MAX_HEIGHT *= 576*

The tallest SD frame (PAL, 576 lines).

### *class* muvid.footage.colour.SourceColour(in_matrix=None, hdr_transfer=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What the assembler needs to know about one source’s colour.

#### hdr_transfer *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= None*

The source’s HDR transfer (`"arib-std-b67"`, `"smpte2084"`), else `None`.

#### in_matrix *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= None*

The matrix to give `scale` as `in_color_matrix`; `None` lets it read the
frame’s own tag (a tagged source, an RGB picture, an untagged SD one).

### muvid.footage.colour.is_hd(width, height)

Whether players read an untagged `width` x `height` source as HD (BT.709).

```pycon
>>> is_hd(1280, 536), is_hd(720, 1280), is_hd(720, 576), is_hd(960, 540)
(True, True, False, False)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### muvid.footage.colour.read_source_colour(path, , probe=None)

The [`SourceColour`](#muvid.footage.colour.SourceColour) of the first video stream of `path`.

A file ffprobe cannot read gets the default (`scale` reads the tag): the render
of that file is where an unreadable source is reported, not here.

* **Return type:**
  [`SourceColour`](#muvid.footage.colour.SourceColour)

### muvid.footage.colour.source_colour(stream)

A probed video stream’s [`SourceColour`](#muvid.footage.colour.SourceColour).

```pycon
>>> source_colour({"pix_fmt": "yuv420p", "width": 1920, "height": 1080})
SourceColour(in_matrix='bt709', hdr_transfer=None)
>>> source_colour({"pix_fmt": "yuv420p", "width": 1280, "height": 536})
SourceColour(in_matrix='bt709', hdr_transfer=None)
>>> source_colour({"pix_fmt": "yuv420p", "width": 640, "height": 480})  # SD
SourceColour(in_matrix=None, hdr_transfer=None)
>>> source_colour({"pix_fmt": "yuv420p", "height": 1080, "color_space": "smpte170m"})
SourceColour(in_matrix=None, hdr_transfer=None)
>>> source_colour({"pix_fmt": "rgb24", "height": 1080})  # RGB has no matrix
SourceColour(in_matrix=None, hdr_transfer=None)
>>> source_colour({"pix_fmt": "yuvj420p", "height": 1080})  # JFIF: BT.601
SourceColour(in_matrix=None, hdr_transfer=None)
>>> source_colour({"pix_fmt": "yuv420p10le", "height": 2160,
...                "color_space": "bt2020nc", "color_transfer": "arib-std-b67"})
SourceColour(in_matrix=None, hdr_transfer='arib-std-b67')
```

* **Return type:**
  [`SourceColour`](#muvid.footage.colour.SourceColour)
