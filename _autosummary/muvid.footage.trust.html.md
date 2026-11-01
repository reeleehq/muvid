# muvid.footage.trust

The trust tiers selection ranks footage by — one ordered table (muvid#255).

Selection prefers trusted footage before it looks at any metric: a clip the aligner
does not vouch for (muvid#88), then a stretch the measured spans do not confirm
(muvid#16 slice 2). Each tier is a **preference, not a filter** — where only footage of
a lower tier covers a moment it is still chosen, and what happens to it is decided
downstream and out loud ([`muvid.footage.edl.exclude_unvouched()`](muvid.footage.edl.html.md#muvid.footage.edl.exclude_unvouched),
[`muvid.footage.edl.validate_edl()`](muvid.footage.edl.html.md#muvid.footage.edl.validate_edl)).

Both strategy families read this table, so a third tier STEERS selection with one row:

- the alignment-only built-ins ([`muvid.footage.strategy`](muvid.footage.strategy.html.md#module-muvid.footage.strategy)) keep, per elementary
  interval, the covering clips of the best tier membership ([`prefer_trusted()`](#muvid.footage.trust.prefer_trusted)) and
  cut the interval grid at every tier edge ([`tier_edges()`](#muvid.footage.trust.tier_edges));
- `weighted` ([`muvid.footage.select_score`](muvid.footage.select_score.html.md#module-muvid.footage.select_score)) charges each tier’s `penalty` per
  second on the composite it integrates.

Steering is not the whole of a tier, and the table does not pretend it is: what is
REPORTED about distrusted footage — [`muvid.footage.edl.exclude_unvouched()`](muvid.footage.edl.html.md#muvid.footage.edl.exclude_unvouched), the
coverage report’s `only_weak_footage`, the reply `warnings` — still reads
`reliable` and [`selection_unverified_stretches()`](muvid.footage.edl.html.md#muvid.footage.edl.selection_unverified_stretches) by name, so a
new row must be taught there too, or it steers silently. And a tier is a PREFERENCE the
DP can pay its way past: a person’s “never use this stretch” is a filter, not a row here.

**The tiers are ORDERED and the penalties must keep them so**: each penalty exceeds the
sum of the ones below it plus the composite’s whole `[0, 1]` range, so the DP never
takes a lower tier over a higher one on any metric (the #16 slice-2 review measured the
failure with equal penalties); a test pins it over the table. The penalties are not config fields, so a caller passing `config=` cannot
tune the preference away.

Stdlib only: the alignment-only strategies keep `import muvid.footage` numpy-free.

### Module Attributes

| [`EVERYWHERE`](#muvid.footage.trust.EVERYWHERE)      | a tier that holds for a clip everywhere.                                                                                                         |
|------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| [`COMPOSITE_RANGE`](#muvid.footage.trust.COMPOSITE_RANGE) | The composite's range (`select_score._composite` normalises every metric to `[0, 1]` and weights sum to 1), which every penalty gap must exceed. |
| [`UNVOUCHED`](#muvid.footage.trust.UNVOUCHED)       | the aligner does not vouch for the clip's offset at all (muvid#88).                                                                              |
| [`UNVERIFIED`](#muvid.footage.trust.UNVERIFIED)      | its measured spans do not confirm the placement there (muvid#16 slice 2).                                                                        |
| [`TRUST_TIERS`](#muvid.footage.trust.TRUST_TIERS)     | the order IS the preference.                                                                                                                     |

### Functions

| [`membership`](#muvid.footage.trust.membership)(a, mid[, tiers])            | Which tiers clip `a` is in at song time `mid`, highest first.                                                                                                                                     |
|-----------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`prefer_trusted`](#muvid.footage.trust.prefer_trusted)(covering, mid[, tiers]) | Rank trust ahead of everything else, for ONE elementary interval: the covering clips of the best tier membership at `mid`, lexicographically — clear of the highest tier first, then of the next. |
| [`tier_edges`](#muvid.footage.trust.tier_edges)(alignments[, tiers])        | Every finite edge of every tier interval, sorted — where a preference can change.                                                                                                                 |

### Classes

| [`TrustTier`](#muvid.footage.trust.TrustTier)(name, intervals, penalty)   | One row: `intervals(a)` is where on the SONG timeline clip `a` is in this (distrusted) tier; `penalty` is the `weighted` charge per second there.   |
|----------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|

### muvid.footage.trust.COMPOSITE_RANGE *= 1.0*

The composite’s range (`select_score._composite` normalises every metric to
`[0, 1]` and weights sum to 1), which every penalty gap must exceed.

### muvid.footage.trust.EVERYWHERE *= (-inf, inf)*

a tier that holds for a clip everywhere.

* **Type:**
  The whole song timeline

### muvid.footage.trust.TRUST_TIERS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[TrustTier](#muvid.footage.trust.TrustTier), ...]* *= (TrustTier(name='unvouched', intervals=<function \_unvouched>, penalty=3.0), TrustTier(name='unverified', intervals=<function selection_unverified_stretches>, penalty=1.5))*

the order IS the preference.

* **Type:**
  Highest tier first

### *class* muvid.footage.trust.TrustTier(name, intervals, penalty)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One row: `intervals(a)` is where on the SONG timeline clip `a` is in this
(distrusted) tier; `penalty` is the `weighted` charge per second there.

### muvid.footage.trust.UNVERIFIED *= TrustTier(name='unverified', intervals=<function selection_unverified_stretches>, penalty=1.5)*

its measured spans do not confirm the placement there (muvid#16 slice
2). `unvouched` was raised from 2.0 to 3.0 to make room for it below.

* **Type:**
  `unverified`

### muvid.footage.trust.UNVOUCHED *= TrustTier(name='unvouched', intervals=<function \_unvouched>, penalty=3.0)*

the aligner does not vouch for the clip’s offset at all (muvid#88).

* **Type:**
  `unvouched`

### muvid.footage.trust.membership(a, mid, tiers=(TrustTier(name='unvouched', intervals=<function \_unvouched>, penalty=3.0), TrustTier(name='unverified', intervals=<function selection_unverified_stretches>, penalty=1.5)))

Which tiers clip `a` is in at song time `mid`, highest first.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### muvid.footage.trust.prefer_trusted(covering, mid, tiers=(TrustTier(name='unvouched', intervals=<function \_unvouched>, penalty=3.0), TrustTier(name='unverified', intervals=<function selection_unverified_stretches>, penalty=1.5)))

Rank trust ahead of everything else, for ONE elementary interval: the covering
clips of the best tier membership at `mid`, lexicographically — clear of the
highest tier first, then of the next. A clip with no measurement is in no tier (no
measurement is not evidence against it).

Trust is a **preference, not a filter**, and the distinction is the whole point.
Where a vouched clip covers the span, the unvouched ones are not considered — a
clip nobody vouches for should never win a span some other clip could have had, on
any metric. Where only distrusted footage covers, it is still returned, because a
strategy PROPOSES: dropping the only footage for a span here would put a second
trust check next to [`validate_edl()`](muvid.footage.edl.html.md#muvid.footage.edl.validate_edl) and remove a source
from the edit on the strength of a measurement — the two things `overlaps=False`
is carefully written not to do. What happens to that forced span is decided
downstream and out loud ([`exclude_unvouched()`](muvid.footage.edl.html.md#muvid.footage.edl.exclude_unvouched)).

Applied per elementary interval rather than to the alignment set, so a clip that is
the only cover for one span and one of several for the next is preferred away from
the second without losing the first. Order is kept.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`FootageAlignment`](muvid.footage.edl.html.md#muvid.footage.edl.FootageAlignment)]

### muvid.footage.trust.tier_edges(alignments, tiers=(TrustTier(name='unvouched', intervals=<function \_unvouched>, penalty=3.0), TrustTier(name='unverified', intervals=<function selection_unverified_stretches>, penalty=1.5)))

Every finite edge of every tier interval, sorted — where a preference can change.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]
