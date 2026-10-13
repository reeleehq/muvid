# muvid.lyricvid.pictures

Pictures for a lyric video: a mosaic that builds up as its words are sung (muvid#151).

A learner’s lyric video wants a picture of what is being sung. This layer places
small pictures around the lyrics. Each one appears when its word is first sung,
so a mosaic builds up through the song, and it **bounces** (a quick enlarge and
back) every time the word is sung again. The lyrics stay readable because no
tile, even at the top of its bounce, enters the text block.

Four steps, each its own function so a caller can replace one:

1. [`text_block()`](#muvid.lyricvid.pictures.text_block) finds where the lyrics are drawn: the union of
   non-background pixels over frames of the finished lyric render.
2. [`mosaic_cells()`](#muvid.lyricvid.pictures.mosaic_cells) lays out cells in the bands above and below it.
3. [`plan_tiles()`](#muvid.lyricvid.pictures.plan_tiles) times each picture from the sung word times
   ([`word_times()`](#muvid.lyricvid.pictures.word_times)): it appears just before the first time its word is
   sung, and bounces on every sung occurrence.
4. [`render()`](#muvid.lyricvid.pictures.render) composites the tiles onto the lyric render in one ffmpeg
   pass. Pictures are fitted inside their cell, never cropped, so a CC BY-SA
   picture is shown unmodified; the bounce is a per-frame `scale`.

Rights travel with each [`Picture`](#muvid.lyricvid.pictures.Picture) (its `credit`), and [`credits()`](#muvid.lyricvid.pictures.credits)
lists the credit of every tile actually shown, in order of appearance, so the
end card cannot forget one.

Needs `ffmpeg`/`ffprobe` on PATH and nothing beyond muvid’s core
dependencies (numpy).

### Functions

| [`bounce_expr`](#muvid.lyricvid.pictures.bounce_expr)(beats, bounce)                    | An ffmpeg expression of `t`: 1 at rest, `1 + scale` at the peak of each pop.      |
|------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`credits`](#muvid.lyricvid.pictures.credits)(tiles)                                | The credit line of every shown picture, in order of appearance, without repeats.  |
| [`frame_size`](#muvid.lyricvid.pictures.frame_size)(video)                             | `(width, height)` of `video`'s frames: the `size` to plan cells for.              |
| [`mosaic_cells`](#muvid.lyricvid.pictures.mosaic_cells)(n, block, \*[, size, gap, ...])  | `n` cells in one row above and one row below the text block, centre-out.          |
| [`plan_tiles`](#muvid.lyricvid.pictures.plan_tiles)(pictures, times, cells, \*[, ...]) | Place each sung picture in a cell, in order of its word's first sung time.        |
| [`render`](#muvid.lyricvid.pictures.render)(video, tiles, out, \*[, bounce, ...])  | Composite `tiles` onto `video` in one ffmpeg pass; audio is copied.               |
| [`text_block`](#muvid.lyricvid.pictures.text_block)(video, \*, background[, ...])      | Where the lyrics are drawn: the box around every non-background pixel of `video`. |
| [`unsung_pictures`](#muvid.lyricvid.pictures.unsung_pictures)(pictures, times)              | The words that have a picture but are never sung (so the picture is never shown). |
| [`word_times`](#muvid.lyricvid.pictures.word_times)(timed_text)                        | Every sung start of every word, from a `TimedText.to_dict()` (or its JSON file).  |

### Classes

| [`Bounce`](#muvid.lyricvid.pictures.Bounce)([scale, duration, lead])     | A quick enlarge and back, timed to a sung word.                         |
|--------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`Picture`](#muvid.lyricvid.pictures.Picture)(word, path[, credit])       | A picture for one sung word, with the credit line its licence requires. |
| [`Tile`](#muvid.lyricvid.pictures.Tile)(picture, box, appear[, beats]) | A picture placed in a cell, with when it appears and when it bounces.   |

### *class* muvid.lyricvid.pictures.Bounce(scale=0.18, duration=0.32, lead=0.04)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A quick enlarge and back, timed to a sung word.

`scale` is the extra size at the peak (0.18 is 18 % larger), `duration`
the length of the whole pop in seconds, and `lead` how long before the
sung onset it starts, so the peak lands on the syllable.

### *class* muvid.lyricvid.pictures.Picture(word, path, credit=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A picture for one sung word, with the credit line its licence requires.

### *class* muvid.lyricvid.pictures.Tile(picture, box, appear, beats=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A picture placed in a cell, with when it appears and when it bounces.

### muvid.lyricvid.pictures.bounce_expr(beats, bounce)

An ffmpeg expression of `t`: 1 at rest, `1 + scale` at the peak of each pop.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### muvid.lyricvid.pictures.credits(tiles)

The credit line of every shown picture, in order of appearance, without repeats.

Raises when a shown picture has no credit: a dropped attribution is a licence
failure nobody downstream can see.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### muvid.lyricvid.pictures.frame_size(video)

`(width, height)` of `video`’s frames: the `size` to plan cells for.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)]

### muvid.lyricvid.pictures.mosaic_cells(n, block, , size=(1920, 1080), gap=24, aspect=1.3333333333333333, top=0.04, bottom=0.95, min_band=120, width=0.94)

`n` cells in one row above and one row below the text block, centre-out.

Bands thinner than `min_band` pixels are skipped. The first cells returned
are the most central, so a short list of pictures sits near the lyrics.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)]]

### muvid.lyricvid.pictures.plan_tiles(pictures, times, cells, , lead=0.15, bounce=Bounce(scale=0.18, duration=0.32, lead=0.04))

Place each sung picture in a cell, in order of its word’s first sung time.

A picture whose word is never sung is left out (see [`unsung_pictures()`](#muvid.lyricvid.pictures.unsung_pictures)).
With a `bounce`, each picture shrinks inside its cell by the bounce’s peak,
so at full size it still fits the cell, and the cells already keep clear of
the text.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Tile`](#muvid.lyricvid.pictures.Tile)]

### muvid.lyricvid.pictures.render(video, tiles, out, , bounce=Bounce(scale=0.18, duration=0.32, lead=0.04), fade_in=0.35, border=None, border_px=3, crf=18)

Composite `tiles` onto `video` in one ffmpeg pass; audio is copied.

Each picture is fitted inside its tile box (never cropped), framed by a
`border` of `border_px` when given, fades in at `appear` and pops on
each of its `beats` when `bounce` is set.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### muvid.lyricvid.pictures.text_block(video, , background, threshold=40, fps=1.0, downscale=4, margin=40)

Where the lyrics are drawn: the box around every non-background pixel of `video`.

Frames are sampled at `fps` and shrunk by `downscale` for speed; a pixel
is ink when its summed RGB distance from `background` exceeds `threshold`.
`margin` pixels are added on every side. Raises when nothing is drawn.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)]

### muvid.lyricvid.pictures.unsung_pictures(pictures, times)

The words that have a picture but are never sung (so the picture is never shown).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### muvid.lyricvid.pictures.word_times(timed_text)

Every sung start of every word, from a `TimedText.to_dict()` (or its JSON file).

A word’s time is its first glyph’s start when glyph times exist (the measured
onset), else the word’s own start.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]]
