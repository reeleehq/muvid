"""A promo cut: chosen shots, in a chosen order, held for phrases of the music.

A music video cuts on the beat and lets the planner pick and reuse footage; a promo (a
class, a studio, a venue, an event: a "sizzle" or "brand film" in the trade) is edited
the other way round. An editor first pulls **selects** (the shots worth showing, each at
its best stretch) and orders them into an arc (hook, place, people, practice, details,
calm close), then lays them on the music so each shot is held long enough to be read
(two to six seconds, not one beat) and every change lands on a bar, preferably on a
phrase boundary, with the strongest musical moments taking the cuts and a dissolve
where the music changes section.

:func:`plan_promo` is that second half, pure: given the song's analysis, the shots in
order and how long each clip is, it places the boundaries by dynamic programming over the
song's bar lines (each shot's length near its target and inside its clip, phrase starts
and accented downbeats preferred) and returns ordinary free cuts (``EdlEntry`` with
``source_in``), so every gate, render and explanation applies unchanged. Choosing the
shots and their order is the caller's (a person, an agent reading contact sheets, or
later a content scorer), because it is the part that needs to know what is in them.

The numbers come from ``misc/docs/research/general/promo_video_editing_and_music.md``.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace
from typing import Callable, Mapping, Optional, Sequence

#: The hold a shot aims for when it names none (seconds). Promos of a calm practice sit
#: at an average shot length of about 3-4 s; a music video at 1-2.
DEFAULT_HOLD_S = float(os.environ.get("MUVID_PROMO_HOLD_S", "3.5"))
#: No shot shorter than this (it cannot be read) or longer than this (it stalls).
MIN_HOLD_S = float(os.environ.get("MUVID_PROMO_MIN_HOLD_S", "1.6"))
MAX_HOLD_S = float(os.environ.get("MUVID_PROMO_MAX_HOLD_S", "8.0"))
#: Bars per musical phrase: a change on a phrase start reads as "on the music".
PHRASE_BARS = int(os.environ.get("MUVID_PROMO_PHRASE_BARS", "4"))
#: Reward (in squared relative hold error) for a boundary on a phrase start, and per
#: unit of the downbeat's accent rank (``Analysis.cut_rank``).
PHRASE_BONUS = 0.25
ACCENT_BONUS = 0.15
#: Roles whose shots come in with a dissolve when they start on a phrase: the calm end
#: of a class (research rule 25: hard cuts by default, dissolves of half a beat to a beat
#: only in the calm and cool-down sections, only at phrase boundaries).
DISSOLVE_ROLES = frozenset({"calm", "cooldown", "savasana", "community", "close"})
#: A dissolve's length, in beats of the song (clamped to [0.4, 1.2] s).
DISSOLVE_BEATS = float(os.environ.get("MUVID_PROMO_DISSOLVE_BEATS", "1.0"))
#: Cuts land this much BEFORE their bar line: a cut one or two frames early reads as on
#: the beat (research rule 11). The first and last boundary never move.
CUT_LEAD_S = float(os.environ.get("MUVID_PROMO_CUT_LEAD_S", "0.033"))
#: The sound level of a shot's own audio when it names none (dB, research rules 18-20):
#: a soundbite (role ``soundbite``) or a nat-sound pop (role ``nat``) at full level,
#: every other shot a quiet bed of its room under the music.
FEATURE_SOUND_ROLES = frozenset({"soundbite", "nat"})
BED_SOUND_DB = float(os.environ.get("MUVID_PROMO_BED_SOUND_DB", "-8"))
#: Keep this much of each clip's head and tail unused when the planner picks the
#: in-point (phone clips start and end with the thumb on the button).
EDGE_S = 0.4


@dataclass(frozen=True)
class Shot:
    """One select: a clip to show, where in it, and how long it wants to be held.

    ``source_in`` ``None`` lets the planner choose the stretch; ``hold_s`` is the target
    length (``DEFAULT_HOLD_S`` when ``None``); ``min_s``/``max_s`` bound it (a soundbite
    sets ``min_s`` to the length of what is said). ``role`` is the caller's tag (``hook``,
    ``place``, ``instructor``, ``detail``, ``soundbite``, ``close`` ...), reported back,
    never interpreted here. ``transition`` forces how this shot comes IN: ``"cut"`` or
    ``"dissolve"``; ``""`` lets the music decide (a dissolve on a new section)."""

    clip_id: str
    source_in: Optional[float] = None
    hold_s: Optional[float] = None
    min_s: Optional[float] = None
    max_s: Optional[float] = None
    role: str = ""
    transition: str = ""
    sound_db: Optional[float] = None

    @property
    def sound_level(self) -> float:
        """This shot's own sound level (dB): its ``sound_db``, else full for a
        soundbite or nat pop, else :data:`BED_SOUND_DB`."""
        if self.sound_db is not None:
            return float(self.sound_db)
        return 0.0 if self.role.lower() in FEATURE_SOUND_ROLES else BED_SOUND_DB

    @property
    def may_dissolve(self) -> bool:
        """Whether this shot might come in with a dissolve (so its clip must hold the
        blend's lead before its in-point): forced, or a calm role."""
        return self.transition == "dissolve" or (
            not self.transition and self.role.lower() in DISSOLVE_ROLES
        )

    @classmethod
    def from_dict(cls, d: Mapping) -> "Shot":
        """From the wire: ``{"clip_id": ..., "source_in": ..., ...}``. Unknown keys and
        wrong types are refused with the field's name, so a misspelt or mistyped field
        is never silently dropped or crashed on."""
        known = set(cls.__dataclass_fields__)
        extra = set(d) - known
        if extra:
            raise ValueError(f"unknown shot field(s) {sorted(extra)}; known: {sorted(known)}")
        if not isinstance(d.get("clip_id"), str) or not d.get("clip_id"):
            raise ValueError("every shot needs a clip_id (a string)")
        for name in ("source_in", "hold_s", "min_s", "max_s", "sound_db"):
            v = d.get(name)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                raise ValueError(f"shot {d['clip_id']!r}: {name} must be a number, got {v!r}")
        for name in ("role", "transition"):
            if not isinstance(d.get(name, ""), str):
                raise ValueError(f"shot {d['clip_id']!r}: {name} must be a string")
        if d.get("transition", "") not in ("", "cut", "dissolve"):
            raise ValueError("transition must be '', 'cut' or 'dissolve'")
        for name in ("source_in", "hold_s", "min_s", "max_s"):
            v = d.get(name)
            if v is not None and v < 0:
                raise ValueError(f"shot {d['clip_id']!r}: {name} must not be negative")
        return cls(**dict(d))


@dataclass
class PromoPlan:
    """The cuts, and how they were placed (one row per shot)."""

    entries: list = field(default_factory=list)
    report: dict = field(default_factory=dict)


#: Spacing of the even grid a promo falls back to on a song with no beat at all (s).
FALLBACK_GRID_S = 0.5


def bar_lines(analysis, span: tuple[float, float]) -> list[tuple[float, int, float]]:
    """``(time, bar_index, accent)`` for every candidate boundary strictly inside
    ``span``: the downbeats (``bar_index`` counted from the song's first, so phrase
    membership is the song's own, not the window's); on a song with no downbeats (free
    time: an ambient bed, an alap) the beats, and with no beats an even
    :data:`FALLBACK_GRID_S` grid. Off the bars, no boundary is a phrase start."""
    beats = list(analysis.beats)
    rank = list(getattr(analysis, "cut_rank", ()) or ())
    accent = dict(zip((round(b, 4) for b in beats), rank)) if len(rank) == len(beats) else {}

    def inside(t):
        return span[0] + 1e-6 < t < span[1] - 1e-6

    downs = [(float(t), k) for k, t in enumerate(analysis.downbeats) if inside(t)]
    if downs:
        return [(t, k, float(accent.get(round(t, 4), 0.0))) for t, k in downs]
    no_phrase = -1  # off the bars: never a phrase start (_is_phrase)
    pool = [float(x) for x in beats if inside(x)]
    if not pool:
        n = int((span[1] - span[0]) / FALLBACK_GRID_S)
        pool = [span[0] + i * FALLBACK_GRID_S for i in range(1, n) if inside(span[0] + i * FALLBACK_GRID_S)]
    return [(t, no_phrase, float(accent.get(round(t, 4), 0.0))) for t in pool]


def _is_phrase(k: int, phrase_bars: int) -> bool:
    return k >= 0 and k % max(1, phrase_bars) == 0


def plan_promo(
    analysis,
    shots: Sequence[Shot],
    *,
    clip_durations: Mapping[str, Optional[float]],
    span: tuple[float, float],
    phrase_bars: int = PHRASE_BARS,
    dissolve_s: Optional[float] = None,
    cut_lead_s: float = CUT_LEAD_S,
    choose_in: Optional[Callable] = None,
    crop_of: Optional[Callable] = None,
) -> PromoPlan:
    """Lay ``shots`` (in order) over ``span`` of the song, one after another, every
    boundary on a bar line. Returns a :class:`PromoPlan` of free-cut ``EdlEntry`` s.

    ``clip_durations``: each clip's length (``None`` for a photo: any hold fits).
    ``choose_in(shot, start, end, room)`` picks an in-point within ``room`` (the legal
    in-points, :func:`muvid.footage.edl.in_point_bounds`, blends included) when
    ``shot.source_in`` is ``None`` (default: the middle of the room); ``crop_of(clip_id)`` is the cover crop
    for the canvas (default: none). Refused, with the reason, when the shots cannot fill
    the span within their bounds (too few, too many, or clips too short).

    >>> from muvid.montage.analysis import Analysis
    >>> a = Analysis(duration=20.0, tempo_bpm=120.0, beats=tuple(i * 0.5 for i in range(40)),
    ...              downbeats=tuple(float(i * 2) for i in range(10)))
    >>> p = plan_promo(a, [Shot("a"), Shot("b"), Shot("c", hold_s=6.0)],
    ...                clip_durations={"a": 30.0, "b": 30.0, "c": 30.0}, span=(0.0, 12.0),
    ...                cut_lead_s=0.0)
    >>> [(e.song_start, e.song_end, e.clip_id) for e in p.entries]
    [(0.0, 4.0, 'a'), (4.0, 8.0, 'b'), (8.0, 12.0, 'c')]
    """
    from muvid.footage.edl import (
        EdlEntry,
        Transition,
        blend_lead,
        blend_trail,
        in_point_bounds,
        still_in_point,
    )

    if not shots:
        raise ValueError("no shots to place")
    a, b = float(span[0]), float(span[1])
    if b <= a:
        raise ValueError(f"empty span {span}")
    lines = bar_lines(analysis, (a, b))
    times = [a] + [t for t, _, _ in lines] + [b]
    bonus = [0.0] + [
        (PHRASE_BONUS if _is_phrase(k, phrase_bars) else 0.0) + ACCENT_BONUS * acc
        for _, k, acc in lines
    ] + [0.0]
    n, m = len(shots), len(times)

    if dissolve_s is None:
        dissolve_s = min(1.2, max(0.4, DISSOLVE_BEATS * 60.0 / max(1e-6, analysis.tempo_bpm)))
    blend = Transition(duration_s=round(dissolve_s, 3), curve="fade") if dissolve_s > 0 else None
    lead = blend_lead(blend) if blend else 0.0
    trail = blend_trail(blend) if blend else 0.0

    def bounds(i: int, s: Shot) -> tuple[float, float, float]:
        target = s.hold_s or DEFAULT_HOLD_S
        lo = s.min_s if s.min_s is not None else min(MIN_HOLD_S, target)
        hi = s.max_s if s.max_s is not None else max(MAX_HOLD_S, target)
        dur = clip_durations.get(s.clip_id)
        if dur is not None:
            # what the clip must hold besides the shot: the next shot's blend reads past
            # its end, the frame lead can lengthen it, and (when the planner picks the
            # in-point) its own blend reads before it
            nxt = shots[i + 1] if i + 1 < len(shots) else None
            reads = (trail if nxt is not None and nxt.may_dissolve else 0.0) + cut_lead_s
            if s.source_in is not None:
                avail = dur - s.source_in - reads
            else:
                avail = dur - reads - (lead if i > 0 and s.may_dissolve else 0.0)
                if avail - 2 * EDGE_S >= lo:  # spare the edges when the clip can afford it
                    avail -= 2 * EDGE_S
            hi = min(hi, avail)
        if hi < lo:
            raise ValueError(
                f"shot {i + 1} ({s.clip_id!r}) cannot be held {lo:.1f} s: its clip has "
                f"{max(0.0, hi):.1f} s to give from its in-point; pick a longer clip, an "
                "earlier source_in, or lower min_s"
            )
        return lo, hi, target

    bnd = [bounds(i, s) for i, s in enumerate(shots)]
    inf = math.inf
    # cost[i][j]: best cost of placing shots 0..i-1 with shot i-1 ending at times[j]
    cost = [[inf] * m for _ in range(n + 1)]
    back = [[-1] * m for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(1, n + 1):
        lo, hi, target = bnd[i - 1]
        last = i == n
        for j in range(1, m):
            if last and j != m - 1:
                continue
            if not last and j == m - 1:
                continue
            best, arg = inf, -1
            for k in range(j - 1, -1, -1):
                length = times[j] - times[k]
                if length > hi + 1e-6:
                    break
                if length < lo - 1e-6 or cost[i - 1][k] == inf:
                    continue
                c = cost[i - 1][k] + ((length - target) / target) ** 2 - bonus[k]
                if c < best:
                    best, arg = c, k
            cost[i][j], back[i][j] = best, arg
    if cost[n][m - 1] == inf:
        total = sum(t for _, _, t in bnd)
        placed = max(i for i in range(n + 1) if any(c < inf for c in cost[i]))
        where = (
            f"; shots 1-{placed} fit, shot {placed + 1} ({shots[placed].clip_id!r}, "
            f"{bnd[placed][0]:.1f}-{bnd[placed][1]:.1f} s) cannot follow them on a bar line"
            if placed < n else "; the last shot cannot end where the window does"
        )
        fewest = sum(lo for lo, _, _ in bnd)
        most = sum(hi for _, hi, _ in bnd)
        advice = (
            "remove shots or lower min_s" if fewest > b - a else
            "add shots or raise max_s" if most < b - a else
            "relax hold_s/min_s/max_s (the bar lines leave no fit)"
        )
        raise ValueError(
            f"{n} shots cannot fill {b - a:.1f} s on this song's bar lines within their "
            f"holds (between {fewest:.1f} and {most:.1f} s together, aiming at "
            f"{total:.1f} s){where}; {advice}"
        )
    cuts, j = [], m - 1
    for i in range(n, 0, -1):
        k = back[i][j]
        cuts.append((times[k], times[j]))
        j = k
    cuts.reverse()

    if cut_lead_s > 0:  # anticipate: each inner boundary a frame or two early
        cuts = [
            (t0 - (cut_lead_s if i > 0 else 0.0), t1 - (cut_lead_s if i < len(cuts) - 1 else 0.0))
            for i, (t0, t1) in enumerate(cuts)
        ]
    # transitions first: an in-point's room depends on its own blend and the next one's
    transitions = []
    for i, (s, (t0, _)) in enumerate(zip(shots, cuts)):
        on_phrase = _on_phrase(t0 + (cut_lead_s if i > 0 else 0.0), lines, phrase_bars)
        calm = s.role.lower() in DISSOLVE_ROLES and on_phrase
        want = s.transition or ("dissolve" if calm else "cut")
        dissolve = i > 0 and want == "dissolve" and blend is not None
        if dissolve and s.source_in is not None and s.source_in < lead:
            dissolve = False  # the chosen in-point leaves no clip for the blend to read
        transitions.append(blend if dissolve else None)
    entries, rows = [], []
    for i, (s, (t0, t1)) in enumerate(zip(shots, cuts)):
        transition = transitions[i]
        nxt = transitions[i + 1] if i + 1 < len(transitions) else None
        draft = EdlEntry(song_start=round(t0, 4), song_end=round(t1, 4), clip_id=s.clip_id,
                         transition=transition)
        dur = clip_durations.get(s.clip_id)
        if s.source_in is not None:
            s_in = float(s.source_in)
        elif dur is None:  # a photo: the gate's own in-point
            s_in = still_in_point(draft)
        else:
            room = in_point_bounds(draft, clip_duration_s=dur, next_transition=nxt,
                                   edge_s=EDGE_S) or (0.0, max(0.0, dur - (t1 - t0)))
            s_in = float(choose_in(s, t0, t1, room)) if choose_in else (room[0] + room[1]) / 2
        entry = replace(
            draft,
            source_in=round(s_in, 4),
            crop=crop_of(s.clip_id) if crop_of else None,
            sound_db=s.sound_level,
        )
        entries.append(entry)
        rows.append({
            "clip_id": s.clip_id, "role": s.role, "song_start": entry.song_start,
            "song_end": entry.song_end, "hold_s": round(t1 - t0, 2),
            "source_in": entry.source_in, "transition": "dissolve" if transition else "cut",
            "sound_db": entry.sound_db,
        })
    lengths = [r["hold_s"] for r in rows]
    report = {
        "shots": rows,
        "average_shot_s": round(sum(lengths) / len(lengths), 2),
        "span": [round(a, 3), round(b, 3)],
        "on_phrase": sum(
            1 for t, _ in cuts[1:] if _on_phrase(t + cut_lead_s, lines, phrase_bars)
        ),
        "boundaries": len(cuts) - 1,
    }
    return PromoPlan(entries=entries, report=report)


def _on_phrase(t: float, lines, phrase_bars: int) -> bool:
    return any(abs(t - x) < 1e-3 and _is_phrase(k, phrase_bars) for x, k, _ in lines)


def ending_span(analysis, *, length_s: float, duration: float, phrase_bars: int = PHRASE_BARS) -> tuple[float, float]:
    """A window of about ``length_s`` that ENDS where the song does (its own ending, no
    fade) and starts on a phrase boundary (else a bar line) near ``duration - length_s``.
    The whole song when it is no longer than ``length_s``.

    >>> from muvid.montage.analysis import Analysis
    >>> a = Analysis(duration=100.0, tempo_bpm=120.0, beats=(), downbeats=tuple(float(i * 2) for i in range(50)))
    >>> ending_span(a, length_s=60.0, duration=100.0)
    (40.0, 100.0)
    """
    if length_s >= duration:
        return 0.0, float(duration)
    want = duration - length_s
    downs = [(float(t), k) for k, t in enumerate(analysis.downbeats)]
    phrase = [t for t, k in downs if k % max(1, phrase_bars) == 0]
    pool = phrase or [t for t, _ in downs] or [want]
    start = min(pool, key=lambda t: abs(t - want))
    return round(start, 4), float(duration)
