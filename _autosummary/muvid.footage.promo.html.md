# muvid.footage.promo

A promo cut: chosen shots, in a chosen order, held for phrases of the music.

A music video cuts on the beat and lets the planner pick and reuse footage; a promo (a
class, a studio, a venue, an event: a “sizzle” or “brand film” in the trade) is edited
the other way round. An editor first pulls **selects** (the shots worth showing, each at
its best stretch) and orders them into an arc (hook, place, people, practice, details,
calm close), then lays them on the music so each shot is held long enough to be read
(two to six seconds, not one beat) and every change lands on a bar, preferably on a
phrase boundary, with the strongest musical moments taking the cuts and a dissolve
where the music changes section.

[`plan_promo()`](#muvid.footage.promo.plan_promo) is that second half, pure: given the song’s analysis, the shots in
order and how long each clip is, it places the boundaries by dynamic programming over the
song’s bar lines (each shot’s length near its target and inside its clip, phrase starts
and accented downbeats preferred) and returns ordinary free cuts (`EdlEntry` with
`source_in`), so every gate, render and explanation applies unchanged. Choosing the
shots and their order is the caller’s (a person, an agent reading contact sheets, or
later a content scorer), because it is the part that needs to know what is in them.

The numbers come from `misc/docs/research/general/promo_video_editing_and_music.md`.

### Module Attributes

| [`DEFAULT_HOLD_S`](#muvid.footage.promo.DEFAULT_HOLD_S)      | The hold a shot aims for when it names none (seconds).                                                                                                                                                                       |
|----------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`MIN_HOLD_S`](#muvid.footage.promo.MIN_HOLD_S)          | No shot shorter than this (it cannot be read) or longer than this (it stalls).                                                                                                                                               |
| [`PHRASE_BARS`](#muvid.footage.promo.PHRASE_BARS)         | a change on a phrase start reads as "on the music".                                                                                                                                                                          |
| [`PHRASE_BONUS`](#muvid.footage.promo.PHRASE_BONUS)        | Reward (in squared relative hold error) for a boundary on a phrase start, and per unit of the downbeat's accent rank (`Analysis.cut_rank`).                                                                                  |
| [`DISSOLVE_ROLES`](#muvid.footage.promo.DISSOLVE_ROLES)      | the calm end of a class (research rule 25: hard cuts by default, dissolves of half a beat to a beat only in the calm and cool-down sections, only at phrase boundaries).                                                     |
| [`DISSOLVE_BEATS`](#muvid.footage.promo.DISSOLVE_BEATS)      | A dissolve's length, in beats of the song (clamped to [0.4, 1.2] s).                                                                                                                                                         |
| [`CUT_LEAD_S`](#muvid.footage.promo.CUT_LEAD_S)          | a cut one or two frames early reads as on the beat (research rule 11).                                                                                                                                                       |
| [`FEATURE_SOUND_ROLES`](#muvid.footage.promo.FEATURE_SOUND_ROLES) | The sound level of a shot's own audio when it names none (dB, research rules 18-20): a soundbite (role `soundbite`) or a nat-sound pop (role `nat`) at full level, every other shot a quiet bed of its room under the music. |
| [`EDGE_S`](#muvid.footage.promo.EDGE_S)              | Keep this much of each clip's head and tail unused when the planner picks the in-point (phone clips start and end with the thumb on the button).                                                                             |
| [`FALLBACK_GRID_S`](#muvid.footage.promo.FALLBACK_GRID_S)     | Spacing of the even grid a promo falls back to on a song with no beat at all (s).                                                                                                                                            |

### Functions

| [`bar_lines`](#muvid.footage.promo.bar_lines)(analysis, span)                     | `(time, bar_index, accent)` for every candidate boundary strictly inside `span`: the downbeats (`bar_index` counted from the song's first, so phrase membership is the song's own, not the window's); on a song with no downbeats (free time: an ambient bed, an alap) the beats, and with no beats an even [`FALLBACK_GRID_S`](#muvid.footage.promo.FALLBACK_GRID_S) grid.   |
|------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`ending_span`](#muvid.footage.promo.ending_span)(analysis, \*, length_s, duration) | A window of about `length_s` that ENDS where the song does (its own ending, no fade) and starts on a phrase boundary (else a bar line) near `duration - length_s`.                                                                                                                                                                                                                   |
| [`plan_promo`](#muvid.footage.promo.plan_promo)(analysis, shots, \*, ...[, ...])   | Lay `shots` (in order) over `span` of the song, one after another, every boundary on a bar line.                                                                                                                                                                                                                                                                                     |

### Classes

| [`PromoPlan`](#muvid.footage.promo.PromoPlan)([entries, report])                   | The cuts, and how they were placed (one row per shot).                     |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| [`Shot`](#muvid.footage.promo.Shot)(clip_id[, source_in, hold_s, min_s, ...]) | One select: a clip to show, where in it, and how long it wants to be held. |

### muvid.footage.promo.CUT_LEAD_S *= 0.033*

a cut one or two frames early reads as on
the beat (research rule 11). The first and last boundary never move.

* **Type:**
  Cuts land this much BEFORE their bar line

### muvid.footage.promo.DEFAULT_HOLD_S *= 3.5*

The hold a shot aims for when it names none (seconds). Promos of a calm practice sit
at an average shot length of about 3-4 s; a music video at 1-2.

### muvid.footage.promo.DISSOLVE_BEATS *= 1.0*

A dissolve’s length, in beats of the song (clamped to [0.4, 1.2] s).

### muvid.footage.promo.DISSOLVE_ROLES *= frozenset({'calm', 'close', 'community', 'cooldown', 'savasana'})*

the calm end
of a class (research rule 25: hard cuts by default, dissolves of half a beat to a beat
only in the calm and cool-down sections, only at phrase boundaries).

* **Type:**
  Roles whose shots come in with a dissolve when they start on a phrase

### muvid.footage.promo.EDGE_S *= 0.4*

Keep this much of each clip’s head and tail unused when the planner picks the
in-point (phone clips start and end with the thumb on the button).

### muvid.footage.promo.FALLBACK_GRID_S *= 0.5*

Spacing of the even grid a promo falls back to on a song with no beat at all (s).

### muvid.footage.promo.FEATURE_SOUND_ROLES *= frozenset({'nat', 'soundbite'})*

The sound level of a shot’s own audio when it names none (dB, research rules 18-20):
a soundbite (role `soundbite`) or a nat-sound pop (role `nat`) at full level,
every other shot a quiet bed of its room under the music.

### muvid.footage.promo.MIN_HOLD_S *= 1.6*

No shot shorter than this (it cannot be read) or longer than this (it stalls).

### muvid.footage.promo.PHRASE_BARS *= 4*

a change on a phrase start reads as “on the music”.

* **Type:**
  Bars per musical phrase

### muvid.footage.promo.PHRASE_BONUS *= 0.25*

Reward (in squared relative hold error) for a boundary on a phrase start, and per
unit of the downbeat’s accent rank (`Analysis.cut_rank`).

### *class* muvid.footage.promo.PromoPlan(entries=list(), report=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The cuts, and how they were placed (one row per shot).

### *class* muvid.footage.promo.Shot(clip_id, source_in=None, hold_s=None, min_s=None, max_s=None, role='', transition='', sound_db=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One select: a clip to show, where in it, and how long it wants to be held.

`source_in` `None` lets the planner choose the stretch; `hold_s` is the target
length (`DEFAULT_HOLD_S` when `None`); `min_s`/`max_s` bound it (a soundbite
sets `min_s` to the length of what is said). `role` is the caller’s tag (`hook`,
`place`, `instructor`, `detail`, `soundbite`, `close` …), reported back,
never interpreted here. `transition` forces how this shot comes IN: `"cut"` or
`"dissolve"`; `""` lets the music decide (a dissolve on a new section).

#### *classmethod* from_dict(d)

From the wire: `{"clip_id": ..., "source_in": ..., ...}`. Unknown keys and
wrong types are refused with the field’s name, so a misspelt or mistyped field
is never silently dropped or crashed on.

* **Return type:**
  [`Shot`](#muvid.footage.promo.Shot)

#### *property* may_dissolve *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Whether this shot might come in with a dissolve (so its clip must hold the
blend’s lead before its in-point): forced, or a calm role.

#### *property* sound_level *: [float](https://docs.python.org/3/builtins/functions.html#float)*

its `sound_db`, else full for a
soundbite or nat pop, else `BED_SOUND_DB`.

* **Type:**
  This shot’s own sound level (dB)

### muvid.footage.promo.bar_lines(analysis, span)

`(time, bar_index, accent)` for every candidate boundary strictly inside
`span`: the downbeats (`bar_index` counted from the song’s first, so phrase
membership is the song’s own, not the window’s); on a song with no downbeats (free
time: an ambient bed, an alap) the beats, and with no beats an even
[`FALLBACK_GRID_S`](#muvid.footage.promo.FALLBACK_GRID_S) grid. Off the bars, no boundary is a phrase start.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

### muvid.footage.promo.ending_span(analysis, , length_s, duration, phrase_bars=4)

A window of about `length_s` that ENDS where the song does (its own ending, no
fade) and starts on a phrase boundary (else a bar line) near `duration - length_s`.
The whole song when it is no longer than `length_s`.

```pycon
>>> from muvid.montage.analysis import Analysis
>>> a = Analysis(duration=100.0, tempo_bpm=120.0, beats=(), downbeats=tuple(float(i * 2) for i in range(50)))
>>> ending_span(a, length_s=60.0, duration=100.0)
(40.0, 100.0)
```

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]

### muvid.footage.promo.plan_promo(analysis, shots, , clip_durations, span, phrase_bars=4, dissolve_s=None, cut_lead_s=0.033, choose_in=None, crop_of=None)

Lay `shots` (in order) over `span` of the song, one after another, every
boundary on a bar line. Returns a [`PromoPlan`](#muvid.footage.promo.PromoPlan) of free-cut `EdlEntry` s.

`clip_durations`: each clip’s length (`None` for a photo: any hold fits).
`choose_in(shot, start, end, room)` picks an in-point within `room` (the legal
in-points, [`muvid.footage.edl.in_point_bounds()`](muvid.footage.edl.html.md#muvid.footage.edl.in_point_bounds), blends included) when
`shot.source_in` is `None` (default: the middle of the room); `crop_of(clip_id)` is the cover crop
for the canvas (default: none). Refused, with the reason, when the shots cannot fill
the span within their bounds (too few, too many, or clips too short).

```pycon
>>> from muvid.montage.analysis import Analysis
>>> a = Analysis(duration=20.0, tempo_bpm=120.0, beats=tuple(i * 0.5 for i in range(40)),
...              downbeats=tuple(float(i * 2) for i in range(10)))
>>> p = plan_promo(a, [Shot("a"), Shot("b"), Shot("c", hold_s=6.0)],
...                clip_durations={"a": 30.0, "b": 30.0, "c": 30.0}, span=(0.0, 12.0),
...                cut_lead_s=0.0)
>>> [(e.song_start, e.song_end, e.clip_id) for e in p.entries]
[(0.0, 4.0, 'a'), (4.0, 8.0, 'b'), (8.0, 12.0, 'c')]
```

* **Return type:**
  [`PromoPlan`](#muvid.footage.promo.PromoPlan)
