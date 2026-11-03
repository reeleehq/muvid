# muvid.footage.fflex

ffmpeg’s filtergraph text, read the way ffmpeg reads it — the ONE lexer (muvid#278).

Every consumer of a look fragment (the gate in [`muvid.footage.edl`](muvid.footage.edl.html.md#module-muvid.footage.edl), the LUT
binding in [`muvid.footage.luts`](muvid.footage.luts.html.md#module-muvid.footage.luts)) reads it through this module, because two readers
that disagree about what a fragment says is exactly the failure the gate exists to
prevent. It used to be private helpers in `edl` that `luts` imported by their
underscored names.

**The contract: ffmpeg resolves a filter’s argument text at TWO levels.**

1. The graph parser (`av_get_token` over the whole chain) splits links on the commas
   it reads as separators and resolves ONE level of escapes (a backslash escapes the
   next character) and single quotes (copied literally) — [`significant()`](#muvid.footage.fflex.significant),
   [`split_significant()`](#muvid.footage.fflex.split_significant) (`sep=","`), [`links()`](#muvid.footage.fflex.links), [`filter_names()`](#muvid.footage.fflex.filter_names).
2. The option parser then splits that resolved text on `:` and resolves a SECOND
   level per value — [`options()`](#muvid.footage.fflex.options) does level 1 first and returns option-level
   text; a caller reading a value passes it through [`unquote()`](#muvid.footage.fflex.unquote), which is level 2.

Reading one level where ffmpeg reads two let a graph-escaped colon through as part of
one value while ffmpeg read it as a separator (the muvid#252 review). An unclosed
fragment (an open quote, a dangling backslash) is a [`FilterSyntaxError`](#muvid.footage.fflex.FilterSyntaxError), not a
character to refuse: it would swallow the text a caller splices after it.

Pure and stdlib-only. `looks.ffmpeg` owns the opposite direction
(`escape_filter_value`) and a comma splitter (`split_filters`); whether it should
own this parse too is reeleehq/looks#68.

### Functions

| [`significant`](#muvid.footage.fflex.significant)(s)            | Yield `(index, char)` for each character ffmpeg reads as SYNTAX.         |
|----------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [`unquote`](#muvid.footage.fflex.unquote)(s)                | `s` as ffmpeg's tokenizer resolves it — escapes applied, quotes removed. |
| [`first_unescaped`](#muvid.footage.fflex.first_unescaped)(s, chars) | The first character of `chars` in `s` that ffmpeg would read as syntax.  |
| [`strip_unescaped`](#muvid.footage.fflex.strip_unescaped)(s)        | Trim whitespace from the ends — but only whitespace ffmpeg would trim.   |
| [`split_significant`](#muvid.footage.fflex.split_significant)(s, sep) | `s` split on the `sep` characters ffmpeg reads as SEPARATORS.            |
| [`links`](#muvid.footage.fflex.links)(look)               | Each link of the chain as `(filter name, argument string)`.              |
| [`filter_names`](#muvid.footage.fflex.filter_names)(look)        | The filter each link of the chain names, as ffmpeg will resolve it.      |
| [`options`](#muvid.footage.fflex.options)(args, positional) | One link's arguments as `{option name: value}`, ffmpeg's way.            |

### Exceptions

| [`FilterSyntaxError`](#muvid.footage.fflex.FilterSyntaxError)(char)   | A look fragment that is not lexically CLOSED.   |
|----------------------------------------------------------------------------|-------------------------------------------------|

### *exception* muvid.footage.fflex.FilterSyntaxError(char)

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A look fragment that is not lexically CLOSED. Carries the open character.

### muvid.footage.fflex.filter_names(look)

The filter each link of the chain names, as ffmpeg will resolve it.

Splits on the commas ffmpeg reads as separators (not on the ones inside a
quoted expression), then takes each link’s name token — everything before its
first significant `=`, minus a `@instance` label — and resolves it through
[`unquote()`](#muvid.footage.fflex.unquote).

Only **unescaped** whitespace is trimmed, because that is the only kind
ffmpeg trims: `hue =s=0` works (rc=0), while `\ hue=s=0` names the
filter *space-h-u-e* and fails with “No such filter: ‘ hue’” (rc=8). Both
measured. A plain `.strip()` here resolved the second to `hue` and
accepted it — harmless, since ffmpeg then refused it, but it also meant the
gate and the binary disagreed about what a fragment says, which is the one
thing a gate must not do.

```pycon
>>> filter_names("scale=2,hue=s=0")
['scale', 'hue']
>>> filter_names("crop=x='min(a,b)':y=0,zoompan=d=1")
['crop', 'zoompan']
>>> filter_names(r"\m\e\t\a\d\a\t\a=mode=print")
['metadata']
>>> filter_names("hue@grade=s=0")
['hue']
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### muvid.footage.fflex.first_unescaped(s, chars)

The first character of `chars` in `s` that ffmpeg would read as syntax.

```pycon
>>> first_unescaped("scale=2,hue=s=0", "[];") is None
True
>>> first_unescaped("[0:v]scale=2", "[];")
'['
>>> first_unescaped(r"lut3d=file=a\[b\].cube", "[];") is None
True
>>> first_unescaped("lut3d=file='a[b].cube'", "[];") is None
True
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### muvid.footage.fflex.links(look)

Each link of the chain as `(filter name, argument string)`.

```pycon
>>> links("scale=2,hue=s=0")
[('scale', '2'), ('hue', 's=0')]
>>> links("null")
[('null', '')]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### muvid.footage.fflex.options(args, positional)

One link’s arguments as `{option name: value}`, ffmpeg’s way.

`args` is the link’s text as it sits in the filtergraph, and ffmpeg reads it
at TWO levels: the graph parser (`av_get_token` over the whole argument
string) resolves one level of escapes and quotes, and only THEN does the option
parser split on `:` and resolve a second level per value. So the graph level
is resolved here first, and each returned value is the OPTION-level text — what
`av_get_token` will unescape once more (callers that read a value
[`unquote()`](#muvid.footage.fflex.unquote) it, which is that second level). Splitting the graph-level
text instead let a graph-escaped colon through as one value while ffmpeg read
it as a separator: `lut3d=interp=nearest\:file=/elsewhere.cube` passed the
gate as `{interp: ...}` and loaded a cube from outside the LUT folder, and
`pad=w=1920:h=1080:color=black\:aspect=1/30` reached `pad`’s `aspect`
past the geometry gate (both measured on ffmpeg 9.0.1 and 6.1.6; muvid#252
review).

Two rules taken from libavfilter’s `process_options` rather than from
intuition, and both change the answer:

- an argument with no `=` is POSITIONAL, filling the next slot of
  `positional` (the option list in declaration order, aliases collapsed);
- **positional slots stop being offered after the first named argument**, so
  a bare argument after a `key=value` one goes to `overflow` and is
  REFUSED rather than read as a later slot. \*\*Not because ffmpeg agrees —
  because the two builds this fleet runs do not agree with each other:\*\*

  | fragment           | ffmpeg 9.0.1   | ffmpeg 6.1.6   |
  |--------------------|----------------|----------------|
  | `scale=w=100:8000` | rc=234         | **100x8000**   |
  | `scale=w=8000:100` | rc=234         | **8000x100**   |
  | `scale=100:h=8000` | 100x8000       | 100x8000       |

  9.0.1 discards the remaining shorthand (“No option name near ‘8000’”); 6.1.6
  fills the next slot. A gate that picked either reading would be wrong on the
  other binary, and on 6.1.6 it would be wrong in the dangerous direction —
  reading `scale=w=8000:100` as `{w: 100}` accepts a fragment that renders
  8000 px wide. So this is a hole where it is dropped, not merely an
  over-refusal: without the rule the trailing bare argument refills slot 0 and
  **overwrites** the named `w`.

Later assignments win, as `av_opt_set` does.

Returns `(options, overflow)`. `overflow` is one `(value, after_named)`
per positional argument that found no slot — **reported rather than dropped**,
which is the half the first pass got wrong. `positional` stops at the slots
muvid classifies (see `edl._LOOK_GEOMETRY_FILTERS`), so a bare argument past
the end is not a triviality: `pad`’s `aspect` is its seventh slot, and
`pad=1920:1080:0:0:black:init:1/30` reaches it without naming it. Silently
dropping slot 7 is what let that fragment through.

An EMPTY argument string declares nothing, which is a case rather than a
triviality: `scale` and `pad` with no arguments at all are legal ffmpeg
(rc=0, frame unchanged — measured), and reading their absent `w` as the
empty string made the gate refuse a fragment the binary accepts. Note this is
the whole list being empty; an empty value *within* a list (`scale=:100`)
is left alone, because ffmpeg refuses that too (“Cannot parse expression for
width: ‘’”, rc=234) and the gate agreeing is the point.

```pycon
>>> options("8000:8000", ("w", "h"))
({'w': '8000', 'h': '8000'}, [])
>>> options("w=8000:h=8000", ("w", "h"))
({'w': '8000', 'h': '8000'}, [])
>>> options("1:0:0:1:640x360:25", ("zoom", "x", "y", "d", "s", "fps"))[0]["s"]
'640x360'
>>> options("", ("w", "h"))
({}, [])
>>> options("64:48:0:0:black", ("w", "h", "x", "y"))[1]
[('black', False)]
>>> options("w=100:8000", ("w", "h"))
({'w': '100'}, [('8000', True)])
>>> options(r"interp=nearest\:file=/x.cube", ("file",))[0]
{'interp': 'nearest', 'file': '/x.cube'}
>>> options("enable='between(t,0,1)'", ("file",))[0]
{'enable': 'between(t,0,1)'}
>>> options(r"enable=between(t\,0\,1)", ("file",))[0]
{'enable': 'between(t,0,1)'}
```

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]]]

### muvid.footage.fflex.significant(s)

Yield `(index, char)` for each character ffmpeg reads as SYNTAX.

Models both of ffmpeg’s escape mechanisms, because modelling only one is a
silent hole: `av_get_token` treats `\` as escaping the next character
**and** copies everything between single quotes literally — inside quotes a
backslash is an ordinary character and a terminator is swallowed. So
`crop=x='min(a,b)'` is ONE filter, not two, and a check that walks only
backslashes splits it in the middle.

* **Raises:**
  [**FilterSyntaxError**](#muvid.footage.fflex.FilterSyntaxError) – if the fragment ends inside a quote, or on a dangling
      backslash. Neither is a character to refuse — it is the fragment
      failing to be CLOSED, which is exactly what “one chain spliceable by
      comma” requires: an open quote swallows the `,format=yuv420p[a];[1:`
      the transition site appends, and a trailing backslash escapes the
      splice’s own comma. Both render fine alone and restructure the graph
      beside a transition (measured: ffmpeg exits 234 with
      `No option name near 'v]scale=...'`).

Yields every character whose syntactic role ffmpeg will honour — i.e. all of
them except the ones an escape or a quoted run hides:

```pycon
>>> "".join(c for _, c in significant("scale=2,hue=s=0"))
'scale=2,hue=s=0'
>>> "".join(c for _, c in significant(r"lut3d=file=a\[b\].cube"))
'lut3d=file=ab.cube'
>>> "".join(c for _, c in significant("crop=x='min(a,b)'"))
'crop=x='
```

### muvid.footage.fflex.split_significant(s, sep)

`s` split on the `sep` characters ffmpeg reads as SEPARATORS.

The one splitter for both of a filter chain’s levels — `,` between links,
`:` between one link’s arguments — so a quoted expression survives both.
Written once rather than twice because the second copy is where the two stop
agreeing about what a fragment says.

```pycon
>>> split_significant("scale=2,hue=s=0", ",")
['scale=2', 'hue=s=0']
>>> split_significant("w='min(iw,2)':h=100", ":")
["w='min(iw,2)'", 'h=100']
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### muvid.footage.fflex.strip_unescaped(s)

Trim whitespace from the ends — but only whitespace ffmpeg would trim.

A plain `.strip()` here removed an ESCAPED space and left the backslash
that escaped it, so `hue\ =s=0` became `hue\` and the lexer raised
`FilterSyntaxError("\\")` from outside the caller’s try/except: a lexically
closed look refused with a message that was a single backslash, reaching an
MCP caller as the whole explanation.

```pycon
>>> strip_unescaped("  hue  ")
'hue'
>>> strip_unescaped(r"hue\ ")
'hue\\ '
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### muvid.footage.fflex.unquote(s)

`s` as ffmpeg’s tokenizer resolves it — escapes applied, quotes removed.

Needed for the *name* half of [`filter_names()`](#muvid.footage.fflex.filter_names), and its role is to
**widen** what the allowlist accepts, not to secure it. An earlier version of
this docstring had that backwards — it claimed a raw-text compare “would be
bypassed” by `'metadata'` or `\m\e\t\a\d\a\t\a`. Measured, it is not:
against an ALLOWLIST a raw compare fails **closed**, because neither spelling
is a member either. What a raw compare loses is the legitimate direction —
`h\ue=s=0` resolves to the allowed `hue` and would be refused.

| spelling                     | raw compare   | with `unquote`   |
|------------------------------|---------------|------------------|
| `metadata=mode=print:file=…` | refused       | refused          |
| `\m\e\t\a\d\a\t\a=…`         | refused       | refused          |
| `h\ue=s=0`  (legitimate)     | **refused**   | accepted         |

The security comes from [`muvid.footage.edl.LOOK_FILTERS`](muvid.footage.edl.html.md#muvid.footage.edl.LOOK_FILTERS) being a closed set. Stating that
correctly matters: a reader who believes this function is the guard could
“simplify” by dropping the allowlist and keeping the normalisation, which is
the one edit that would reopen the hole.

```pycon
>>> unquote(r"h\ue")
'hue'
>>> unquote("'hue'")
'hue'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
