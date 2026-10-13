# muvid.lyrics

Lyrics — transcription and markdown round-trip.

Two surfaces for the user:

1. `transcribe(audio_path)` — calls `mixing.transcript.transcribe`
   (ElevenLabs Scribe) and writes the raw word-timestamped JSON to
   `lyrics/transcript.json`. This is the *seed*; the user is expected
   to correct it.
2. `write_lyrics_md` / `parse_lyrics_md` — the canonical, editable
   form. A simple markdown with `[section]` headers, one line per
   sung line, and an optional `// <seconds>` end-of-line anchor.

The alignment module consumes both: it reads `lyrics.md` for the
*text* the user committed to, and `transcript.json` for the *timing*
to splice in.

### Functions

| [`indentation_varies`](#muvid.lyrics.indentation_varies)(indents)                | True when lyric lines are indented differently: a shape a parse would lose.          |
|---------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`layout_dropped`](#muvid.lyrics.layout_dropped)(md)                         | What the default parse flattens, as data: `None` for ordinary lyrics.                |
| [`line_indents`](#muvid.lyrics.line_indents)(md)                           | The leading whitespace of each lyric line, aligned with `parse_lyrics_md(md).lines`. |
| [`lyrics_from_transcript`](#muvid.lyrics.lyrics_from_transcript)(transcript)         | Build a default LyricsDoc from a transcription response.                             |
| [`parse_lyrics_md`](#muvid.lyrics.parse_lyrics_md)(md, \*[, preserve_indent]) | Parse the user-editable lyrics markdown.                                             |
| `read_lyrics_md`(path, \*[, preserve_indent])                                               |                                                                                      |
| `read_transcript`(path)                                                                     |                                                                                      |
| [`render_lyrics_md`](#muvid.lyrics.render_lyrics_md)(doc)                      | Inverse of `parse_lyrics_md`.                                                        |
| [`transcribe`](#muvid.lyrics.transcribe)(audio_path, \*[, api_key, ...]) | Run ElevenLabs Scribe on the audio and (optionally) write the JSON.                  |
| [`words_from_transcript`](#muvid.lyrics.words_from_transcript)(transcript)          | Normalize Scribe's word entries: `[{text, start, end, confidence}, ...]`.            |
| `write_lyrics_md`(path, doc)                                                                |                                                                                      |

### Classes

| [`LyricLine`](#muvid.lyrics.LyricLine)(\*, text, line_index[, ...])         | One line of lyric text, optionally with a known start time.   |
|-------------------------------------------------------------------------------------------------|---------------------------------------------------------------|
| [`LyricSection`](#muvid.lyrics.LyricSection)(\*, label[, title, start_s, ...]) | A user-tagged section in the lyrics markdown.                 |
| [`LyricsDoc`](#muvid.lyrics.LyricsDoc)(\*, sections)                        | Full parsed view of the user's lyrics markdown.               |

### Exceptions

| [`ShapedLyricsWarning`](#muvid.lyrics.ShapedLyricsWarning)   | Lyric lines are indented differently, and the parse is about to drop it.   |
|------------------------------------------------------------------------|----------------------------------------------------------------------------|

### *class* muvid.lyrics.LyricLine(, text, line_index, section_label='', start_s=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One line of lyric text, optionally with a known start time.

### *class* muvid.lyrics.LyricSection(, label, title='', start_s=None, end_s=None, lines=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A user-tagged section in the lyrics markdown.

Times are *optional* — if not present, alignment is computed from
transcripts; if present, they override.

### *class* muvid.lyrics.LyricsDoc(, sections)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Full parsed view of the user’s lyrics markdown.

### *exception* muvid.lyrics.ShapedLyricsWarning

Bases: [`UserWarning`](https://docs.python.org/3/builtins/exceptions.html#UserWarning)

Lyric lines are indented differently, and the parse is about to drop it.

A lyrics file whose lines carry *differing* leading whitespace is almost
always a drawn layout (a concrete poem, an *Il pleut*), and the default
parse strips that whitespace — so the shape is gone before any archetype
sees it (muvid#109). This is the signal that it happened. Uniform
indentation (every line indented alike) carries no shape and does not warn.

### muvid.lyrics.indentation_varies(indents)

True when lyric lines are indented differently: a shape a parse would lose.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

```pycon
>>> indentation_varies(["", "  "]), indentation_varies(["  ", "  "])
(True, False)
```

### muvid.lyrics.layout_dropped(md)

What the default parse flattens, as data: `None` for ordinary lyrics.

The same test as [`ShapedLyricsWarning`](#muvid.lyrics.ShapedLyricsWarning), for a caller that cannot see
a Python warning (an MCP reply, a render’s meta; muvid#165). Does not warn.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> layout_dropped("one\ntwo\n")
>>> layout_dropped("one\n  two\n    three\n")
{'lines': 3, 'indentations': 3}
```

### muvid.lyrics.line_indents(md)

The leading whitespace of each lyric line, aligned with `parse_lyrics_md(md).lines`.

Reads the shape the default parse strips, without changing the parse.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

```pycon
>>> line_indents("[v]\none\n  two\n(aside)\n\tthree\n")
('', '  ', '\t')
```

### muvid.lyrics.lyrics_from_transcript(transcript)

Build a default LyricsDoc from a transcription response.

Heuristic: split lines on punctuation (`. ? !`) or on long pauses
(>0.6 s gap between consecutive words). One `[transcribed]` section
holds everything; the user is expected to re-tag with real sections.

* **Return type:**
  [`LyricsDoc`](#muvid.lyrics.LyricsDoc)

### muvid.lyrics.parse_lyrics_md(md, , preserve_indent=False)

Parse the user-editable lyrics markdown.

Format:

```default
[section_label] optional title
line of lyric            // 12.5
another line

[next section]
...
```

Empty lines are separators between sections. `(instrumental)` or
any line starting with `(` and ending with `)` is treated as a
non-lyric placeholder (no LyricLine emitted).

Leading whitespace is stripped by default, and the result for every
existing input is unchanged by that default (pinned by a golden test). When
the lines are indented *differently* from one another — a drawn layout —
stripping destroys the shape, so a [`ShapedLyricsWarning`](#muvid.lyrics.ShapedLyricsWarning) says so.
`preserve_indent=True` keeps each line’s leading whitespace in
`LyricLine.text` instead (trailing whitespace and the `//` anchor are
still removed), which [`render_lyrics_md()`](#muvid.lyrics.render_lyrics_md) writes back verbatim and
which anything displaying that text (an alignment’s line text, say) then
carries. No
lyric-video archetype honours indentation yet; the word tokeniser skips
whitespace, so alignment is the same either way. [`line_indents()`](#muvid.lyrics.line_indents)
reads the indentation without changing the parse.

* **Return type:**
  [`LyricsDoc`](#muvid.lyrics.LyricsDoc)

```pycon
>>> md = "[v]\nIl pleut\n  des voix\n"
>>> [L.text for L in parse_lyrics_md(md, preserve_indent=True).lines]
['Il pleut', '  des voix']
```

### muvid.lyrics.render_lyrics_md(doc)

Inverse of `parse_lyrics_md`. Stable round-trip.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### muvid.lyrics.transcribe(audio_path, , api_key=None, out_path=None, cache=True)

Run ElevenLabs Scribe on the audio and (optionally) write the JSON.

Returns the raw response dict (which contains `words: [...]` with
per-word `text`, `start`, `end`, `confidence`).

The on-disk Scribe cache (in `mixing.transcript`) is enabled by
default, so re-running on the same audio is free. Pass
`cache=False` to force a fresh round-trip.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### muvid.lyrics.words_from_transcript(transcript)

Normalize Scribe’s word entries: `[{text, start, end, confidence}, ...]`.

Filters out non-word events (Scribe surfaces `(laughs)` etc. with
`type` ≠ `word`) and ones missing timing. `confidence` is
pass-through; absent → `None`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]
