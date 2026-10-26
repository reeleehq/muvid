# muvid.lyricvid.glyph_align

Per-glyph timing: when was each written character sung? (muvid#142)

A word-level alignment says when `バカンス` was sung; a learner watching
katakana needs to see `バ`, `カ`, `ン` and `ス` light up one by one, each
at the moment its sound starts. This module refines any word-timed
[`TimedText`](muvid.lyricvid.timed_text.html.md#muvid.lyricvid.timed_text.TimedText) (from Suno’s own timestamps, an
enhanced LRC, a whisper match…) into one with measured
[`glyphs`](muvid.lyricvid.timed_text.html.md#muvid.lyricvid.timed_text.Word.glyphs).

How: each lyric line is cut out of the separated vocal stem, widened by
`margin_s` on both sides, and force-aligned with a CTC model (torchaudio’s
`MMS_FA`, trained on romanised speech in 1,000+ languages) against the line’s
romanisation, one romaji chunk per glyph, with a `<star>` token either side
to absorb breaths and ad-libs. Aligning per line, inside the coarse word
window, is what keeps one mis-sung line from dragging every later one.

Romanisation is a strategy slot (`romanize=`): [`romanize_kana()`](#muvid.lyricvid.glyph_align.romanize_kana) covers
katakana and hiragana, including `ー` (lengthens the previous vowel), `ッ`
(doubles the next consonant) and the small `ャュョァィゥェォ` combinations.
Another script needs another romaniser, nothing else.

Verification lives here too, because a timing nobody checked is a guess:
[`onset_report()`](#muvid.lyricvid.glyph_align.onset_report) measures how close glyph starts sit to acoustic onsets in
the vocal stem, against a random-jitter baseline, and [`word_agreement()`](#muvid.lyricvid.glyph_align.word_agreement)
lists the words where two timings disagree. [`reconcile()`](#muvid.lyricvid.glyph_align.reconcile) then acts on
what a list of [`Detector`](#muvid.lyricvid.glyph_align.Detector) s distrusts — each names words and a remedy
(`replace`: fall back to the vendor window; `drop`: it was never sung).
[`unsung()`](#muvid.lyricvid.glyph_align.unsung) is the one that drops: a line the aligner could not place over
which the vocal stem is silent (muvid#144).

Licensing — read before shipping anything: the `MMS_FA` weights are
**CC-BY-NC-4.0** and htdemucs (vocal separation) is CC-BY-NC too. So this is an
opt-in extra (`muvid[lyricvid-glyphs]`), never a default, never on the prod
connector, and it never downloads weights unless the caller says
`allow_download=True` (or `MUVID_ALLOW_WEIGHT_DOWNLOAD=1`).

### Module Attributes

| [`MARGIN_S`](#muvid.lyricvid.glyph_align.MARGIN_S)              | Seconds of audio kept either side of a line's coarse window.                                                                                          |
|------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`ONSET_TOL_S`](#muvid.lyricvid.glyph_align.ONSET_TOL_S)           | Onset tolerance for [`onset_report()`](#muvid.lyricvid.glyph_align.onset_report).                                                                  |
| [`DISAGREE_S`](#muvid.lyricvid.glyph_align.DISAGREE_S)            | Two timings of a word disagree when their starts differ by more than this.                                                                            |
| [`MIN_GLYPH_S`](#muvid.lyricvid.glyph_align.MIN_GLYPH_S)           | Two sounded glyphs whose STARTS are closer than this were squeezed together by the aligner, not sung (a mora takes ~0.1 s or more).                   |
| [`REMEDIES`](#muvid.lyricvid.glyph_align.REMEDIES)              | What [`reconcile()`](#muvid.lyricvid.glyph_align.reconcile) may do with a word a detector distrusts.                                            |
| [`UNSUNG_QUIET_DB`](#muvid.lyricvid.glyph_align.UNSUNG_QUIET_DB)       | a frame is quiet below this many dB under the stem's own loud level...                                                                                |
| [`UNSUNG_QUIET_SHARE`](#muvid.lyricvid.glyph_align.UNSUNG_QUIET_SHARE)    | ...and a line is unsung when at least this share of its window is quiet...                                                                            |
| [`UNSUNG_MIN_QUIET_S`](#muvid.lyricvid.glyph_align.UNSUNG_MIN_QUIET_S)    | ...in one unbroken stretch at least this long.                                                                                                        |
| [`LINE_GAP_S`](#muvid.lyricvid.glyph_align.LINE_GAP_S)            | a line whose last glyph starts within this many seconds of the next line's first glyph (or after it) overlaps it.                                     |
| [`UNSUNG_FRAME_S`](#muvid.lyricvid.glyph_align.UNSUNG_FRAME_S)        | Frame length for the stem's RMS level.                                                                                                                |
| [`UNSUNG_REF_PERCENTILE`](#muvid.lyricvid.glyph_align.UNSUNG_REF_PERCENTILE) | The stem's "loud level" is this percentile of its frame RMS, so the threshold follows the mix rather than an absolute dBFS a quieter stem would fail. |
| [`TIMING_OVERRIDES`](#muvid.lyricvid.glyph_align.TIMING_OVERRIDES)      | What a recorded per-song timing override may say about a line.                                                                                        |
| [`SPILL_MIN_STEP_S`](#muvid.lyricvid.glyph_align.SPILL_MIN_STEP_S)      | a moved glyph starts at least this long after the glyph before it (a mora takes ~0.1 s)...                                                            |
| [`SPILL_CLEAR_S`](#muvid.lyricvid.glyph_align.SPILL_CLEAR_S)         | ...an onset it moves to is at least this long before the next line...                                                                                 |
| [`SPILL_MIN_TAIL_S`](#muvid.lyricvid.glyph_align.SPILL_MIN_TAIL_S)      | ...and a word whose glyph moved ends no earlier than this after its last glyph's start (CTC spans are spiky; a 0 s word would never light).           |

### Functions

| [`apply_timing_overrides`](#muvid.lyricvid.glyph_align.apply_timing_overrides)(reconciled, fine, ...)      | Put recorded human judgements back over [`reconcile()`](#muvid.lyricvid.glyph_align.reconcile)'s result.      |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| [`check_timing_overrides`](#muvid.lyricvid.glyph_align.check_timing_overrides)(overrides, n_lines)         | Validate recorded timing overrides against a transcript of `n_lines`.                                               |
| [`default_detectors`](#muvid.lyricvid.glyph_align.default_detectors)(\*[, disagree_s, min_glyph_s])   | What [`reconcile()`](#muvid.lyricvid.glyph_align.reconcile) runs when given none: the two that need no audio. |
| [`disagrees`](#muvid.lyricvid.glyph_align.disagrees)(\*[, disagree_s])                        | Words whose fine start is more than `disagree_s` from the coarse one.                                               |
| [`disordered`](#muvid.lyricvid.glyph_align.disordered)(among, \*[, gap_s])                     | Lines that overlap, or whose glyphs run backwards, once `among` is applied.                                         |
| [`glyph_rows`](#muvid.lyricvid.glyph_align.glyph_rows)(tt)                                     | One flat record per glyph, for a table or a quick look.                                                             |
| [`lost`](#muvid.lyricvid.glyph_align.lost)(vocals, \*[, disagree_s, min_glyph_s, tol_s]) | Words the aligner could not place, as [`unsung()`](#muvid.lyricvid.glyph_align.unsung)'s `among`.          |
| [`misplaced`](#muvid.lyricvid.glyph_align.misplaced)(vocals, \*[, disagree_s, tol_s])         | Disagreeing words where the onsets side with the vendor.                                                            |
| [`onset_report`](#muvid.lyricvid.glyph_align.onset_report)(timed_text, vocals, \*[, tol_s, ...]) | How well glyph starts sit on acoustic onsets of the vocal stem.                                                     |
| [`reconcile`](#muvid.lyricvid.glyph_align.reconcile)(fine, coarse, \*[, disagree_s, ...])     | Distrust the fine timing where a detector says so; remedy it; say where.                                            |
| [`refine_glyphs`](#muvid.lyricvid.glyph_align.refine_glyphs)(timed_text, vocals, \*[, ...])       | Return `timed_text` with measured `Word.glyphs` on every word.                                                      |
| [`repair_spills`](#muvid.lyricvid.glyph_align.repair_spills)(tt, onsets, \*[, gap_s, ...])        | Pull a line's glyphs back off the NEXT line, where they aligned (muvid#155).                                        |
| [`romanize_hepburn`](#muvid.lyricvid.glyph_align.romanize_hepburn)(text)                             | Display romanisation (modified Hepburn) of kana text: what a learner reads.                                         |
| [`romanize_kana`](#muvid.lyricvid.glyph_align.romanize_kana)(word)                                | `(glyph, romaji)` per glyph, the romaji chunks concatenating to the word.                                           |
| [`squeezed`](#muvid.lyricvid.glyph_align.squeezed)(\*[, min_glyph_s])                        | Words with two sounded glyphs starting less than `min_glyph_s` apart.                                               |
| [`stem_detectors`](#muvid.lyricvid.glyph_align.stem_detectors)(vocals, \*[, disagree_s, ...])      | What to reconcile with when you have the vocal stem (muvid#150).                                                    |
| [`stem_onsets`](#muvid.lyricvid.glyph_align.stem_onsets)(vocals)                                | Acoustic onset times (seconds) of a vocal stem, as a numpy array.                                                   |
| [`unsung`](#muvid.lyricvid.glyph_align.unsung)(vocals, \*[, among, quiet_db, ...])         | Lines a vendor transcript lists but nobody sang.                                                                    |
| [`vocal_stem`](#muvid.lyricvid.glyph_align.vocal_stem)(audio, \*, out_dir[, allow_download])   | The song's separated vocal stem (Demucs), raising rather than degrading.                                            |
| [`word_agreement`](#muvid.lyricvid.glyph_align.word_agreement)(fine, coarse, \*[, disagree_s])     | Compare word starts (first glyph start when present) of two timings.                                                |

### Classes

| [`Detector`](#muvid.lyricvid.glyph_align.Detector)(\*, name, find[, remedy])   | Names the words of a fine timing not to trust, and what to do about them.   |
|---------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|

### muvid.lyricvid.glyph_align.DISAGREE_S *= 0.3*

Two timings of a word disagree when their starts differ by more than this.

### *class* muvid.lyricvid.glyph_align.Detector(, name, find, remedy='replace')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Names the words of a fine timing not to trust, and what to do about them.

`find(fine, coarse)` gets both timings (same word sequence) and returns
`{word_index: reason}`, indices into `list(fine.words())`. `remedy`
is one of [`REMEDIES`](#muvid.lyricvid.glyph_align.REMEDIES); when several detectors flag one word, `drop`
wins — a word nobody sang has no window worth falling back to.

### muvid.lyricvid.glyph_align.LINE_GAP_S *= 0.05*

a line whose last glyph starts within this many seconds
of the next line’s first glyph (or after it) overlaps it.

* **Type:**
  [`disordered()`](#muvid.lyricvid.glyph_align.disordered)

### muvid.lyricvid.glyph_align.MARGIN_S *= 0.5*

Seconds of audio kept either side of a line’s coarse window. Vendor word
times run late and miss leading consonants; too wide a window lets the
aligner wander into the neighbouring line.

### muvid.lyricvid.glyph_align.MIN_GLYPH_S *= 0.04*

Two sounded glyphs whose STARTS are closer than this were squeezed together
by the aligner, not sung (a mora takes ~0.1 s or more). Start-to-start, not
span length: CTC spans are spiky, so a perfectly sung `ン` can be 20 ms.

### muvid.lyricvid.glyph_align.ONSET_TOL_S *= 0.08*

Onset tolerance for [`onset_report()`](#muvid.lyricvid.glyph_align.onset_report).

### muvid.lyricvid.glyph_align.REMEDIES *= ('replace', 'drop')*

What [`reconcile()`](#muvid.lyricvid.glyph_align.reconcile) may do with a word a detector distrusts. `replace`:
fall back to the coarse window shifted by the measured bias, glyphs spread
evenly and marked unmeasured (the word was sung; the aligner could not place
it). `drop`: remove the word, and a line or section left empty (it was
never sung, so lighting it at ANY time is wrong).

### muvid.lyricvid.glyph_align.SPILL_CLEAR_S *= 0.1*

…an onset it moves to is at least this long before the next line…

### muvid.lyricvid.glyph_align.SPILL_MIN_STEP_S *= 0.08*

a moved glyph starts at least this long after the
glyph before it (a mora takes ~0.1 s)…

* **Type:**
  [`repair_spills()`](#muvid.lyricvid.glyph_align.repair_spills)

### muvid.lyricvid.glyph_align.SPILL_MIN_TAIL_S *= 0.05*

…and a word whose glyph moved ends no earlier than this after its last
glyph’s start (CTC spans are spiky; a 0 s word would never light).

### muvid.lyricvid.glyph_align.TIMING_OVERRIDES *= ('fine',)*

What a recorded per-song timing override may say about a line. `fine`:
the vendor window is junk and the aligner’s times are right, so the line
gets its fine timing back, whatever [`reconcile()`](#muvid.lyricvid.glyph_align.reconcile) did to it.

### muvid.lyricvid.glyph_align.UNSUNG_FRAME_S *= 0.05*

Frame length for the stem’s RMS level.

### muvid.lyricvid.glyph_align.UNSUNG_MIN_QUIET_S *= 1.0*

…in one unbroken stretch at least this long. A ghost repeat is a whole
line of silence (2 s on the measured song); a short sung line whose vendor
window is merely LATE lands on a quiet tail too, but a short one.

### muvid.lyricvid.glyph_align.UNSUNG_QUIET_DB *= -40.0*

a frame is
quiet below this many dB under the stem’s own loud level…

* **Type:**
  [`unsung()`](#muvid.lyricvid.glyph_align.unsung)’s thresholds, measured on a real song (muvid#144)

### muvid.lyricvid.glyph_align.UNSUNG_QUIET_SHARE *= 0.5*

…and a line is unsung when at least this share of its window is quiet…

### muvid.lyricvid.glyph_align.UNSUNG_REF_PERCENTILE *= 95.0*

The stem’s “loud level” is this percentile of its frame RMS, so the threshold
follows the mix rather than an absolute dBFS a quieter stem would fail.

### muvid.lyricvid.glyph_align.apply_timing_overrides(reconciled, fine, records, , overrides)

Put recorded human judgements back over [`reconcile()`](#muvid.lyricvid.glyph_align.reconcile)’s result.

`overrides` is per-song DATA, `{"<line index>": "fine"}` — the line’s
0-based position in the transcript `fine` was refined from (string keys,
as JSON writes them, or ints). It belongs in the song’s own spec beside
the lyrics, never in code: it says “on THIS song, this line’s vendor
window is junk and the aligner’s times sit on onsets” (muvid#150, used on
five songs). Each value is one of [`TIMING_OVERRIDES`](#muvid.lyricvid.glyph_align.TIMING_OVERRIDES).

`reconciled` and `records` are what `reconcile(fine, coarse, ...)`
returned; words are matched by position, so a line is restored exactly —
even one [`unsung()`](#muvid.lyricvid.glyph_align.unsung) dropped, since a person said it was sung. Only
the named line changes: a neighbour [`disordered()`](#muvid.lyricvid.glyph_align.disordered) flagged together
with it keeps its vendor window unless it is named too. `reconcile`’s
records still say what reconcile did; these say what undid it. Returns
the timing and one record per word whose timing changed (same keys as
[`reconcile()`](#muvid.lyricvid.glyph_align.reconcile)’s; `why` is `"override"`). Empty or `None`
`overrides` return `reconciled` unchanged.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`TimedText`](muvid.lyricvid.timed_text.html.md#muvid.lyricvid.timed_text.TimedText), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]]

### muvid.lyricvid.glyph_align.check_timing_overrides(overrides, n_lines)

Validate recorded timing overrides against a transcript of `n_lines`.

Returns `{line index: how}`. Refuses (`ValueError`) a key that is not
an integer line index (a bool or a fractional number included), one out of
range, two spellings of one line that disagree, and a value outside
[`TIMING_OVERRIDES`](#muvid.lyricvid.glyph_align.TIMING_OVERRIDES). Cheap, so a caller can run it BEFORE the
expensive alignment it is about to correct.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### muvid.lyricvid.glyph_align.default_detectors(, disagree_s=0.3, min_glyph_s=0.04)

What [`reconcile()`](#muvid.lyricvid.glyph_align.reconcile) runs when given none: the two that need no audio.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Detector`](#muvid.lyricvid.glyph_align.Detector), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### muvid.lyricvid.glyph_align.disagrees(, disagree_s=0.3)

Words whose fine start is more than `disagree_s` from the coarse one.

Remedy: `replace`.

* **Return type:**
  [`Detector`](#muvid.lyricvid.glyph_align.Detector)

### muvid.lyricvid.glyph_align.disordered(among, , gap_s=0.05)

Lines that overlap, or whose glyphs run backwards, once `among` is applied.

Seen on dense backing chants (muvid#150): the aligner loses the beat, and
after reconciling, a line’s last glyph starts after the next line’s first,
or glyphs inside one line go out of order. Neither timing can be right, and
the vendor windows at least keep the lines in order, so every word of such
a line (both lines, for an overlap) is flagged. Remedy: `replace`.

It judges the RESULT of reconciling with `among`, so it runs that
reconcile itself; pass it after the same detectors:

```default
dets = stem_detectors(stem)  # already ends with disordered(...)
```

* **Return type:**
  [`Detector`](#muvid.lyricvid.glyph_align.Detector)

### muvid.lyricvid.glyph_align.glyph_rows(tt)

One flat record per glyph, for a table or a quick look.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### muvid.lyricvid.glyph_align.lost(vocals, , disagree_s=0.3, min_glyph_s=0.04, tol_s=0.08)

Words the aligner could not place, as [`unsung()`](#muvid.lyricvid.glyph_align.unsung)’s `among`.

A word is lost when it is [`squeezed()`](#muvid.lyricvid.glyph_align.squeezed), or when it [`disagrees()`](#muvid.lyricvid.glyph_align.disagrees),
its fine start is off every onset, AND that start lies inside ANOTHER
line’s vendor window (bias-shifted): the aligner, finding nothing to put
it on, pushed it onto a neighbour. That is the unsung intro repeat of
muvid#150, whose first word disagreed instead of squeezing, so a
squeeze-only `among` never saw the whole line as flagged.

Each condition guards against deleting sung lyrics, because the remedy
this feeds is `drop`:

- A disagreeing word the aligner put ON an onset was sung somewhere.
- A word left in its OWN line’s neighbourhood can be one the vendor merely
  placed late, by more than the aligner’s search margin (`MARGIN_S`).
  Its window is then quiet, and without the third condition the line is
  deleted (review of muvid#154).

Remedy: `replace` (it only names words; [`unsung()`](#muvid.lyricvid.glyph_align.unsung) decides).

* **Return type:**
  [`Detector`](#muvid.lyricvid.glyph_align.Detector)

### muvid.lyricvid.glyph_align.misplaced(vocals, , disagree_s=0.3, tol_s=0.08)

Disagreeing words where the onsets side with the vendor. Remedy: `replace`.

[`disagrees()`](#muvid.lyricvid.glyph_align.disagrees) falls back to the vendor time whenever the two timings
differ, but on a song where the fine aligner is good the vendor is usually
the one that is wrong (muvid#150: seven words flagged, and every fine time
sat within ~60 ms of a stem onset while the vendor times were up to 10 s
off, one of them before the end of the previous line). So a word is
flagged only when its fine start is off every onset (`tol_s`) AND its
bias-shifted vendor start is on one: the evidence has to point at the
vendor, not just away from the aligner. Use it in place of
[`disagrees()`](#muvid.lyricvid.glyph_align.disagrees) when you have the stem (see [`stem_detectors()`](#muvid.lyricvid.glyph_align.stem_detectors)).

* **Return type:**
  [`Detector`](#muvid.lyricvid.glyph_align.Detector)

### muvid.lyricvid.glyph_align.onset_report(timed_text, vocals, , tol_s=0.08, seed=0, trials=20)

How well glyph starts sit on acoustic onsets of the vocal stem.

`near_onset` is the share of glyph starts within `tol_s` of a detected
onset; `random_baseline` is the same share after jittering every start
by up to ±0.5 s — the gap between the two is the evidence, since a dense
onset track makes any time look “near” something.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### muvid.lyricvid.glyph_align.reconcile(fine, coarse, , disagree_s=None, min_glyph_s=None, detectors=None)

Distrust the fine timing where a detector says so; remedy it; say where.

`detectors` defaults to [`default_detectors()`](#muvid.lyricvid.glyph_align.default_detectors) (`squeezed` and
`disagrees`, both `replace`; `disagree_s` and `min_glyph_s` tune
them, and are refused alongside explicit `detectors`, which they could
not reach). Add [`unsung()`](#muvid.lyricvid.glyph_align.unsung) when you have the vocal stem:

```default
reconcile(fine, coarse, detectors=(*default_detectors(), unsung(stem)))
```

`replace` puts a word back in its COARSE window, shifted by the median
offset between the two timings over the words no detector flagged (vendor
times run late; the bias is measured, not assumed), glyphs spread evenly
and marked `measured=False`. `drop` removes it, and any line or section
left empty. Returns the timing and one record per affected word: `why`
(the deciding detector), `detail`, `remedy`, `flagged_by` (every
detector that flagged it) and `used` (the start it got; `None` when
dropped).

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`TimedText`](muvid.lyricvid.timed_text.html.md#muvid.lyricvid.timed_text.TimedText), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]]

### muvid.lyricvid.glyph_align.refine_glyphs(timed_text, vocals, \*, romanize=<function romanize_kana>, margin_s=0.5, allow_download=False)

Return `timed_text` with measured `Word.glyphs` on every word.

`vocals` should be a separated vocal stem (see [`vocal_stem()`](#muvid.lyricvid.glyph_align.vocal_stem)): the
accompaniment confuses a CTC model far more than it confuses a listener.
The coarse word times are only used as per-line windows; the glyph times
replace nothing else. A line with nothing romanisable keeps evenly spread,
`measured=False` glyphs rather than invented precision.

* **Return type:**
  [`TimedText`](muvid.lyricvid.timed_text.html.md#muvid.lyricvid.timed_text.TimedText)

### muvid.lyricvid.glyph_align.repair_spills(tt, onsets, , gap_s=0.05, min_step_s=0.08, clear_s=0.1, min_tail_s=0.05)

Pull a line’s glyphs back off the NEXT line, where they aligned (muvid#155).

Seen on a real song: `ハット`’s `ト` aligned onto the next line’s `ト`.
It also follows from [`reconcile()`](#muvid.lyricvid.glyph_align.reconcile) itself: a line sent back to its
vendor window can end on a neighbour the aligner had right. A glyph (not
a line’s first) starting within `gap_s` of the next line’s first glyph,
or after it, has SPILLED. It moves to the first of `onsets` (the vocal
stem’s, see [`stem_onsets()`](#muvid.lyricvid.glyph_align.stem_onsets)) at least `min_step_s` after the glyph
before it and `clear_s` before the next line — or, with none there,
midway between that floor and `gap_s` before the next line, so it is
never left spilled — and is marked `measured=False`. Every glyph after
the first spilled one moves with it: they share that room in equal
slices, each taking the first onset in its own slice, so no glyph is
left on the next line for want of room an earlier one took.

Then, in that line only, nothing stays lit into the next line or over a
moved glyph: the glyph before a moved one ends no later than it starts, a
moved glyph ends by the next line, and each word spans its glyphs (from its
first glyph’s start, to its last glyph’s end or `min_tail_s` past its
start — CTC spans are spiky) and ends by the next line too. A glyph with
no room before the next line (the line itself already sits on it) is left
alone: moving it would put it before the glyph it follows, and a whole
line on its neighbour is [`disordered()`](#muvid.lyricvid.glyph_align.disordered)’s case, not a spill.

Run it on [`reconcile()`](#muvid.lyricvid.glyph_align.reconcile)’s result (and after
[`apply_timing_overrides()`](#muvid.lyricvid.glyph_align.apply_timing_overrides)). Returns the timing — the very object
passed in when nothing spilled — and one record per moved glyph: `text`,
`line`, `why` (`"spilled"`), `detail`, `remedy` (`"onset"` or
`"midpoint"`), `fine` (its start before) and `used` (its start now).

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`TimedText`](muvid.lyricvid.timed_text.html.md#muvid.lyricvid.timed_text.TimedText), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]]

### muvid.lyricvid.glyph_align.romanize_hepburn(text)

Display romanisation (modified Hepburn) of kana text: what a learner reads.

[`romanize_kana()`](#muvid.lyricvid.glyph_align.romanize_kana) is an ALIGNMENT romaniser — `ー` is silent there,
because it has no onset. Read on screen it needs a macron. Also `ン`
before a vowel or `y` takes an apostrophe, `ッ` before `ch` is `t`,
and glides keep their `w`/`y` (muvid#145).

```pycon
>>> romanize_hepburn("バス バス スタート")
'basu basu sutāto'
>>> romanize_hepburn("ハンバーガー")
'hanbāgā'
>>> romanize_hepburn("カップ マッチ シャツ")
'kappu matchi shatsu'
>>> romanize_hepburn("キンエン ウィンドウ")
"kin'en windou"
```

Anything that is not kana is KEPT, not dropped — kanji, digits, Latin, an
unknown kana — because a caption that silently loses a word looks right:

```pycon
>>> romanize_hepburn("東京 バス、スタート! Café")
'東京 basu, sutāto! Café'
```

Input is NFKC-normalised first, so half-width (`ﾊﾞｽ`) and decomposed
(`ハ` + combining `゙`) kana read as the composed glyphs. Hiragana long
vowels spelt with a second vowel (`とうきょう`) keep both letters: telling
`ou` the long vowel from `o``+``u` needs a dictionary.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### muvid.lyricvid.glyph_align.romanize_kana(word)

`(glyph, romaji)` per glyph, the romaji chunks concatenating to the word.

```pycon
>>> romanize_kana("バカンス")
[('バ', 'ba'), ('カ', 'ka'), ('ン', 'n'), ('ス', 'su')]
>>> romanize_kana("スーパー")
[('ス', 'su'), ('ー', ''), ('パ', 'pa'), ('ー', '')]
>>> romanize_kana("カップ")
[('カ', 'ka'), ('ッ', 'p'), ('プ', 'pu')]
>>> romanize_kana("シャツ")
[('シ', 'sh'), ('ャ', 'a'), ('ツ', 'tsu')]
>>> romanize_kana("キャンディー")
[('キ', 'k'), ('ャ', 'ya'), ('ン', 'n'), ('デ', 'd'), ('ィ', 'i'), ('ー', '')]
>>> romanize_kana("ok!")
[('o', 'o'), ('k', 'k'), ('!', '')]
```

A glyph with an empty chunk (`ー`, punctuation) has no onset of its own;
the aligner places it between its neighbours and marks it unmeasured.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### muvid.lyricvid.glyph_align.squeezed(, min_glyph_s=0.04)

Words with two sounded glyphs starting less than `min_glyph_s` apart.

CTC squeezing a word it could not hear into a few frames. Judged on
syllabic glyphs (kana/CJK: one mora each) only — letters of an alphabet are
legitimately ~30 ms apart — and only between neighbours in the same line
(lines are aligned in overlapping windows). Remedy: `replace`.

* **Return type:**
  [`Detector`](#muvid.lyricvid.glyph_align.Detector)

### muvid.lyricvid.glyph_align.stem_detectors(vocals, , disagree_s=0.3, min_glyph_s=0.04, tol_s=0.08, drop_unsung=True)

What to reconcile with when you have the vocal stem (muvid#150).

[`squeezed()`](#muvid.lyricvid.glyph_align.squeezed), [`misplaced()`](#muvid.lyricvid.glyph_align.misplaced) (in place of [`disagrees()`](#muvid.lyricvid.glyph_align.disagrees), which
trusts the vendor even when its time is impossible), [`unsung()`](#muvid.lyricvid.glyph_align.unsung) with
`among=`[`lost()`](#muvid.lyricvid.glyph_align.lost) (left out when `drop_unsung` is false), and
[`disordered()`](#muvid.lyricvid.glyph_align.disordered) over the rest. Measured on five songs, this reproduced
both hand fixes the first one needed.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Detector`](#muvid.lyricvid.glyph_align.Detector), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### muvid.lyricvid.glyph_align.stem_onsets(vocals)

Acoustic onset times (seconds) of a vocal stem, as a numpy array.

### muvid.lyricvid.glyph_align.unsung(vocals, , among=None, quiet_db=-40.0, quiet_share=0.5, min_quiet_s=1.0, frame_s=0.05)

Lines a vendor transcript lists but nobody sang. Remedy: `drop`.

A LINE is unsung when both hold: `among` (default [`squeezed()`](#muvid.lyricvid.glyph_align.squeezed))
distrusts every word in it — the aligner, searching the line’s window, found
nothing to put them on — and the vocal stem is quiet (`quiet_db` under its
own loud level) over at least `quiet_share` of the line’s coarse window,
including one unbroken quiet stretch of `min_quiet_s`. The window is
shifted by the vendor’s measured bias (median fine-minus-coarse start over
the words `among` trusts), and a window running past the end of the stem
is not judged at all.

Both, because neither instrument is enough alone. Measured on the song that
motivated this (muvid#144: a Suno transcript listing a repeated タン タン タン
at 36-38 s that the stem shows nobody sang), the stem alone puts a sung,
staccato ストップ ストップ at 0.63 quiet against the ghost’s 0.75 — vendor
windows run on into the silence after a word, so a quiet window is common —
while squeeze alone also flags a sung, fast スター ダンス (0.04 quiet).
Together they separate the ghost and nothing else.

What they do NOT separate unaided is one short sung line whose vendor
window is a second late: the aligner (searching ±\`\`MARGIN_S\`\`) misses it
and squeezes, and the window lands on the silence after it — measured on
the same song, the last line (フン) shifted +1 s was dropped. The unbroken
`min_quiet_s` is what refuses that case: a short window cannot hold a
second of silence, a ghost line is silence end to end.

The unit is the line, because a transcript repeats lines, and because the
first ghost word’s own window held the decaying tail of the previous held
note: sound, but not its sound. `among` is squeeze and not disagreement
on purpose — a line the vendor MISPLACED was sung somewhere else, and
dropping it would delete a sung line. With the stem, [`lost()`](#muvid.lyricvid.glyph_align.lost) widens
`among` only by disagreeing words that are off every onset AND sit in
another line’s window, which a misplaced-but-sung line does not produce
(see [`stem_detectors()`](#muvid.lyricvid.glyph_align.stem_detectors)).

* **Return type:**
  [`Detector`](#muvid.lyricvid.glyph_align.Detector)

### muvid.lyricvid.glyph_align.vocal_stem(audio, , out_dir, allow_download=False)

The song’s separated vocal stem (Demucs), raising rather than degrading.

Reuses the footage scorer’s separator; that one returns `None` on any
failure because lip-sync is optional there, but here no stem means no
trustworthy glyph times, so the absence is an error.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### muvid.lyricvid.glyph_align.word_agreement(fine, coarse, , disagree_s=0.3)

Compare word starts (first glyph start when present) of two timings.

The two must hold the same words in the same order (`fine` is normally
`refine_glyphs(coarse, ...)`). Returns summary statistics and the list
of words that disagree by more than `disagree_s` — the ones to look at.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]
