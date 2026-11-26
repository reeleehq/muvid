# muvid.aac

The AAC encoder’s priming, compensated (muvid#379, muvid#385).

Stdlib-only and import-free on purpose: the footage sound module, the visualizer
and the lyric renderers all need it, and none should load another’s package to get
it. `muvid.visualize.ffmpeg` and `muvid.footage.sound` re-export it.

### Module Attributes

| [`AAC_SAMPLE_RATE`](#muvid.aac.AAC_SAMPLE_RATE)     | The rate every muvid AAC delivery is encoded at (and so primes at).   |
|----------------------------------------------------------------------|-----------------------------------------------------------------------|
| [`AAC_PRIMING_SAMPLES`](#muvid.aac.AAC_PRIMING_SAMPLES) | Samples the AAC encoder prepends ("priming").                         |

### Functions

| [`aac_priming_filter`](#muvid.aac.aac_priming_filter)(\*[, priming_samples, ...])   | The `-af` links that put an AAC encode's sound back on its picture (muvid#379).   |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|

### muvid.aac.AAC_PRIMING_SAMPLES *= 1024*

Samples the AAC encoder prepends (“priming”). Without an edit list (muvid’s delivery
contract writes none) a player plays them, so the sound would land 21.3 ms late at
48 kHz; [`aac_priming_filter()`](#muvid.aac.aac_priming_filter) trims them off the input to compensate.

### muvid.aac.AAC_SAMPLE_RATE *= 48000*

The rate every muvid AAC delivery is encoded at (and so primes at).

### muvid.aac.aac_priming_filter(, priming_samples=1024, sample_rate=48000)

The `-af` links that put an AAC encode’s sound back on its picture (muvid#379).

The encoder prepends `priming_samples` of priming, and a file with no edit list
(the delivery contract) plays them, so every AAC pass lands the sound 21.3 ms
late at 48 kHz; measured with a click at 1.000 s, decoded at 1.021 s after one
pass and 1.043 s after two. Trimming as many samples off the INPUT cancels it,
and padding them back at the tail keeps the length. `aresample` comes first so
`start_sample` counts samples at the rate the encoder primes at, whatever rate
the input has. Append it LAST to a chain whose timeline is the delivered one (a
fade’s `st` is read before the trim). Every muvid AAC encode under
`-use_editlist 0` goes through it: the footage assembler and
[`muvid.footage.sound.mux_audio()`](muvid.footage.sound.html.md#muvid.footage.sound.mux_audio) (muvid#379), the visualizer and the
subgenres that share its encode (montage, choreo), and both lyric-video
renderers (muvid#385). `tests/test_aac_priming.py` checks every one.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
