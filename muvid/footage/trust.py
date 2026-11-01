"""The trust tiers selection ranks footage by — one ordered table (muvid#255).

Selection prefers trusted footage before it looks at any metric: a clip the aligner
does not vouch for (muvid#88), then a stretch the measured spans do not confirm
(muvid#16 slice 2). Each tier is a **preference, not a filter** — where only footage of
a lower tier covers a moment it is still chosen, and what happens to it is decided
downstream and out loud (:func:`muvid.footage.edl.exclude_unvouched`,
:func:`muvid.footage.edl.validate_edl`).

Both strategy families read this table, so a third tier STEERS selection with one row:

- the alignment-only built-ins (:mod:`muvid.footage.strategy`) keep, per elementary
  interval, the covering clips of the best tier membership (:func:`prefer_trusted`) and
  cut the interval grid at every tier edge (:func:`tier_edges`);
- ``weighted`` (:mod:`muvid.footage.select_score`) charges each tier's ``penalty`` per
  second on the composite it integrates.

Steering is not the whole of a tier, and the table does not pretend it is: what is
REPORTED about distrusted footage — :func:`muvid.footage.edl.exclude_unvouched`, the
coverage report's ``only_weak_footage``, the reply ``warnings`` — still reads
``reliable`` and :func:`~muvid.footage.edl.selection_unverified_stretches` by name, so a
new row must be taught there too, or it steers silently. And a tier is a PREFERENCE the
DP can pay its way past: a person's "never use this stretch" is a filter, not a row here.

**The tiers are ORDERED and the penalties must keep them so**: each penalty exceeds the
sum of the ones below it plus the composite's whole ``[0, 1]`` range, so the DP never
takes a lower tier over a higher one on any metric (the #16 slice-2 review measured the
failure with equal penalties); a test pins it over the table. The penalties are not config fields, so a caller passing ``config=`` cannot
tune the preference away.

Stdlib only: the alignment-only strategies keep ``import muvid.footage`` numpy-free.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

from muvid.footage.edl import FootageAlignment, selection_unverified_stretches

#: The whole song timeline: a tier that holds for a clip everywhere.
EVERYWHERE = (-math.inf, math.inf)
#: The composite's range (``select_score._composite`` normalises every metric to
#: ``[0, 1]`` and weights sum to 1), which every penalty gap must exceed.
COMPOSITE_RANGE = 1.0
#: How close to a stretch's edge a moment still counts as inside it (seconds). Far
#: tighter than ``edl._EPS`` (1 ms, a cut-boundary tolerance) on purpose: it is the old
#: ``_prefer_confirmed``'s test, kept bit for bit, applied to interval MIDPOINTS.
_EDGE_EPS = 1e-6


@dataclass(frozen=True)
class TrustTier:
    """One row: ``intervals(a)`` is where on the SONG timeline clip ``a`` is in this
    (distrusted) tier; ``penalty`` is the ``weighted`` charge per second there."""

    name: str
    intervals: Callable[[FootageAlignment], "list[tuple[float, float]]"]
    penalty: float


def _unvouched(a: FootageAlignment) -> "list[tuple[float, float]]":
    return [] if a.reliable else [EVERYWHERE]


#: ``unvouched``: the aligner does not vouch for the clip's offset at all (muvid#88).
UNVOUCHED = TrustTier("unvouched", _unvouched, penalty=3.0)
#: ``unverified``: its measured spans do not confirm the placement there (muvid#16 slice
#: 2). ``unvouched`` was raised from 2.0 to 3.0 to make room for it below.
UNVERIFIED = TrustTier("unverified", selection_unverified_stretches, penalty=1.5)
#: Highest tier first: the order IS the preference.
TRUST_TIERS: "tuple[TrustTier, ...]" = (UNVOUCHED, UNVERIFIED)


def membership(
    a: FootageAlignment, mid: float, tiers: Sequence[TrustTier] = TRUST_TIERS
) -> "tuple[bool, ...]":
    """Which tiers clip ``a`` is in at song time ``mid``, highest first."""
    return tuple(
        any(s - _EDGE_EPS <= mid < e + _EDGE_EPS for s, e in t.intervals(a))
        for t in tiers
    )


def prefer_trusted(
    covering: "list[FootageAlignment]",
    mid: float,
    tiers: Sequence[TrustTier] = TRUST_TIERS,
) -> "list[FootageAlignment]":
    """Rank trust ahead of everything else, for ONE elementary interval: the covering
    clips of the best tier membership at ``mid``, lexicographically — clear of the
    highest tier first, then of the next. A clip with no measurement is in no tier (no
    measurement is not evidence against it).

    Trust is a **preference, not a filter**, and the distinction is the whole point.
    Where a vouched clip covers the span, the unvouched ones are not considered — a
    clip nobody vouches for should never win a span some other clip could have had, on
    any metric. Where only distrusted footage covers, it is still returned, because a
    strategy PROPOSES: dropping the only footage for a span here would put a second
    trust check next to :func:`~muvid.footage.edl.validate_edl` and remove a source
    from the edit on the strength of a measurement — the two things ``overlaps=False``
    is carefully written not to do. What happens to that forced span is decided
    downstream and out loud (:func:`~muvid.footage.edl.exclude_unvouched`).

    Applied per elementary interval rather than to the alignment set, so a clip that is
    the only cover for one span and one of several for the next is preferred away from
    the second without losing the first. Order is kept.
    """
    if not covering:
        return covering
    ranks = [membership(a, mid, tiers) for a in covering]
    best = min(ranks)
    return [a for a, r in zip(covering, ranks) if r == best]


def tier_edges(
    alignments: Sequence[FootageAlignment], tiers: Sequence[TrustTier] = TRUST_TIERS
) -> "list[float]":
    """Every finite edge of every tier interval, sorted — where a preference can change."""
    return sorted(
        x
        for t in tiers
        for a in alignments
        for st in t.intervals(a)
        for x in st
        if math.isfinite(x)
    )
