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
  Converting only the YCbCr matrix and range leaves BT.2020 primaries and an HDR
  transfer behind, so the delivered SDR picture is washed out (measured: 10.0 dB
  against the SDR original). So it is TONE MAPPED (muvid#201, [`tonemap_chain()`](#muvid.footage.colour.tonemap_chain)):
  to linear light with [`HDR_REFERENCE_WHITE_NITS`](#muvid.footage.colour.HDR_REFERENCE_WHITE_NITS) as SDR white, to BT.709
  primaries, [`TONEMAP`](#muvid.footage.colour.TONEMAP) with `TONEMAP_PARAM`, then BT.709 limited — 24.7 dB
  on the same clip. A build without `zscale` / `tonemap` cannot, and the assembler
  then reports each HDR clip it delivers washed out.

Import-light (stdlib only at module top): the look compiler imports the constants.

### Module Attributes

| [`DELIVERY_COLOR_SPACE`](#muvid.footage.colour.DELIVERY_COLOR_SPACE)     | The delivery matrix — and the primaries and transfer it is tagged with.                                                                                                                                 |
|---------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`DELIVERY_COLOR_RANGE`](#muvid.footage.colour.DELIVERY_COLOR_RANGE)     | limited ("tv"), the range H.264 delivery is read in.                                                                                                                                                    |
| [`DELIVERY_TAG`](#muvid.footage.colour.DELIVERY_TAG)             | The frame-level tag the assembler places last in each part's chain, after the look (and on a gap's black).                                                                                              |
| [`HD_MIN_WIDTH`](#muvid.footage.colour.HD_MIN_WIDTH)             | Where players draw the line between SD (BT.601) and HD (BT.709) for an untagged source: at least this wide, OR taller than [`SD_MAX_HEIGHT`](#muvid.footage.colour.SD_MAX_HEIGHT) (mpv's rule). |
| [`SD_MAX_HEIGHT`](#muvid.footage.colour.SD_MAX_HEIGHT)            | The tallest SD frame (PAL, 576 lines).                                                                                                                                                                  |
| [`HDR_TRANSFERS`](#muvid.footage.colour.HDR_TRANSFERS)            | ffprobe's names for the transfers that make a source HDR (HLG, PQ).                                                                                                                                     |
| [`HDR_REFERENCE_WHITE_NITS`](#muvid.footage.colour.HDR_REFERENCE_WHITE_NITS) | BT.2408's reference white, where an HLG camera puts diffuse white.                                                                                                                                      |
| [`TONEMAP`](#muvid.footage.colour.TONEMAP)                  | The `tonemap` curve for the highlights above SDR white.                                                                                                                                                 |

### Functions

| [`can_tonemap`](#muvid.footage.colour.can_tonemap)()                         | Whether this ffmpeg has the filters [`tonemap_chain()`](#muvid.footage.colour.tonemap_chain) needs.                                             |
|----------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`tonemap_chain`](#muvid.footage.colour.tonemap_chain)([fill])                 | HDR -> the SDR delivery colour, for a frame already at the canvas size (float frames at the source's 4K would cost 100 MB each), ending in 8-bit 4:2:0. |
| [`read_source_colour`](#muvid.footage.colour.read_source_colour)(path, \*[, probe]) | The [`SourceColour`](#muvid.footage.colour.SourceColour) of the first video stream of `path`.                                                  |
| [`is_hd`](#muvid.footage.colour.is_hd)(width, height)                  | Whether players read an untagged `width` x `height` source as HD (BT.709).                                                                              |
| [`source_colour`](#muvid.footage.colour.source_colour)(stream)                 | A probed video stream's [`SourceColour`](#muvid.footage.colour.SourceColour).                                                                  |

### Classes

| [`SourceColour`](#muvid.footage.colour.SourceColour)([in_matrix, hdr_transfer, hdr_fill])   | What the assembler needs to know about one source's colour.   |
|------------------------------------------------------------------------------------------------------|---------------------------------------------------------------|

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

### muvid.footage.colour.HDR_REFERENCE_WHITE_NITS *= 203*

BT.2408’s reference white, where an
HLG camera puts diffuse white.

* **Type:**
  The HDR luminance (nits) that becomes SDR white

### muvid.footage.colour.HDR_TRANSFERS *= frozenset({'arib-std-b67', 'smpte2084'})*

ffprobe’s names for the transfers that make a source HDR (HLG, PQ).

### muvid.footage.colour.HD_MIN_WIDTH *= 1280*

Where players draw the line between SD (BT.601) and HD (BT.709) for an untagged
source: at least this wide, OR taller than [`SD_MAX_HEIGHT`](#muvid.footage.colour.SD_MAX_HEIGHT) (mpv’s rule).
Width matters for letterboxed HD — an untagged 1280x536 BT.709 clip measured
26.9 dB under a height-only rule.

### muvid.footage.colour.SD_MAX_HEIGHT *= 576*

The tallest SD frame (PAL, 576 lines).

### *class* muvid.footage.colour.SourceColour(in_matrix=None, hdr_transfer=None, hdr_fill=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What the assembler needs to know about one source’s colour.

#### hdr_fill *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)], ...]* *= ()*

For an HDR source, the colour tags it does NOT carry, filled with the HDR
standard’s own (BT.2020) — `{"color_primaries": "bt2020"}` — because `zscale`
refuses to convert from a colour it is not told (the #201 review: “no path between
colorspaces” on an HLG clip with untagged primaries, which rendered before).

#### hdr_transfer *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= None*

The source’s HDR transfer (`"arib-std-b67"`, `"smpte2084"`), else `None`.

#### in_matrix *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= None*

The matrix to give `scale` as `in_color_matrix`; `None` lets it read the
frame’s own tag (a tagged source, an RGB picture, an untagged SD one).

### muvid.footage.colour.TONEMAP *= 'mobius'*

The `tonemap` curve for the highlights above SDR white. `mobius` is the identity
up to `TONEMAP_PARAM` and rolls off smoothly above it. Measured on an HLG clip
of an SDR original, decoded as BT.709 (no highlight above white): `clip` 25.2 dB,
`mobius` 0.85 24.7, 0.7 23.1, `reinhard` 15.8, `hable` 11.3. On an HLG clip of
eight bands from signal 0.60 to 0.95 (0.75 is reference white), the #201 review:
`clip` sends 56% of the pixels to Y >= 235 and keeps no detail in the four bands
above white; `mobius` 0.85 sends 6% there and keeps 6/2/1/0/1 code values in the
top five; `mobius` 0.5 sends none but costs 8 codes at signal 0.70.

### muvid.footage.colour.can_tonemap()

Whether this ffmpeg has the filters [`tonemap_chain()`](#muvid.footage.colour.tonemap_chain) needs.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

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
SourceColour(in_matrix='bt709', hdr_transfer=None, hdr_fill=())
>>> source_colour({"pix_fmt": "yuv420p", "width": 1280, "height": 536})
SourceColour(in_matrix='bt709', hdr_transfer=None, hdr_fill=())
>>> source_colour({"pix_fmt": "yuv420p", "width": 640, "height": 480})  # SD
SourceColour(in_matrix=None, hdr_transfer=None, hdr_fill=())
>>> source_colour({"pix_fmt": "yuv420p", "height": 1080, "color_space": "smpte170m"})
SourceColour(in_matrix=None, hdr_transfer=None, hdr_fill=())
>>> source_colour({"pix_fmt": "rgb24", "height": 1080})  # RGB has no matrix
SourceColour(in_matrix=None, hdr_transfer=None, hdr_fill=())
>>> source_colour({"pix_fmt": "yuvj420p", "height": 1080})  # JFIF: BT.601
SourceColour(in_matrix=None, hdr_transfer=None, hdr_fill=())
>>> source_colour({"pix_fmt": "yuv420p10le", "height": 2160,
...                "color_space": "bt2020nc", "color_transfer": "arib-std-b67"})
SourceColour(in_matrix=None, hdr_transfer='arib-std-b67', hdr_fill=(('color_primaries', 'bt2020'),))
>>> source_colour({"pix_fmt": "yuv420p10le", "height": 2160,
...                "color_transfer": "arib-std-b67"}).hdr_fill
(('color_primaries', 'bt2020'), ('colorspace', 'bt2020nc'))
```

* **Return type:**
  [`SourceColour`](#muvid.footage.colour.SourceColour)

### muvid.footage.colour.tonemap_chain(fill=())

HDR -> the SDR delivery colour, for a frame already at the canvas size (float
frames at the source’s 4K would cost 100 MB each), ending in 8-bit 4:2:0. `fill`
names the colour tags the source left out ([`SourceColour.hdr_fill`](#muvid.footage.colour.SourceColour.hdr_fill)).

```pycon
>>> tonemap_chain().split(",")[0]
'zscale=t=linear:npl=203'
>>> tonemap_chain((("color_primaries", "bt2020"),)).split(",")[0]
'setparams=color_primaries=bt2020'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
