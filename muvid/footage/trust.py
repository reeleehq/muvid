"""The trust tiers selection ranks footage by — one ordered table (muvid#255).

Selection prefers trusted footage before it looks at any metric: a clip the aligner
does not vouch for (muvid#88), then a stretch the measured spans do not confirm
(muvid#16 slice 2). Each tier is a **preference, not a filter** — where only footage of
a lower tier covers a moment it is still chosen, and what happens to it is decided
downstream and out loud (:func:`muvid.footage.edl.exclude_unvouched`,
:func:`muvid.footage.edl.validate_edl`).

Both strategy families read this table, so a third tier (a person's "do not use this
stretch", say) is one row:

- the alignment-only built-ins (:mod:`muvid.footage.strategy`) keep, per elementary
  interval, the covering clips of the best tier membership (:func:`prefer_trusted`) and
  cut the interval grid at every tier edge (:func:`tier_edges`);
- ``weighted`` (:mod:`muvid.footage.select_score`) charges each tier's ``penalty`` per
  second on the composite it integrates.

**The tiers are ORDERED and the penalties must keep them so**: each penalty exceeds the
sum of the ones below it plus the composite's whole ``[0, 1]`` range, so the DP never
takes a lower tier over a higher one on any metric (the #16 slice-2 review measured the
failure with equal penalties). :func:`penalties_are_ordered` states the rule and a test
pins it. The penalties are not config fields, so a caller passing ``config=`` cannot
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
#: The composite's range, which every penalty gap must exceed.
COMPOSITE_RANGE = 1.0
#: How close to a stretch's edge a moment still counts as inside it (seconds).
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


#: Highest tier first. ``unvouched``: the aligner does not vouch for the clip's offset at
#: all (muvid#88). ``unverified``: its measured spans do not confirm the placement there
#: (muvid#16 slice 2) — raised from 2.0 to 3.0 for ``unvouched`` to make room for it.
TRUST_TIERS: "tuple[TrustTier, ...]" = (
    TrustTier("unvouched", _unvouched, penalty=3.0),
    TrustTier("unverified", selection_unverified_stretches, penalty=1.5),
)


def penalties_are_ordered(tiers: Sequence[TrustTier] = TRUST_TIERS) -> bool:
    """Whether each tier's penalty exceeds the sum of the lower ones plus
    :data:`COMPOSITE_RANGE` — the ordering the module docstring requires.

    >>> penalties_are_ordered()
    True
    >>> penalties_are_ordered((TrustTier("a", _unvouched, 2.0), TrustTier("b", _unvouched, 1.5)))
    False
    """
    return all(
        t.penalty > sum(lower.penalty for lower in tiers[i + 1 :]) + COMPOSITE_RANGE
        for i, t in enumerate(tiers)
    )


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
    """The covering clips of the best tier membership at ``mid`` — lexicographically:
    clear of the highest tier first, then of the next. A clip with no measurement is in
    no tier (no measurement is not evidence against it). Never empty when ``covering``
    is not: where only distrusted footage covers, it is returned."""
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
