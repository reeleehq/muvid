"""The lyric-video production as named stages, and the settings section muvid owns.

A runner (a separate package: it composes muvid, arioso, mixing, illustration,
tituli and yb, none of which muvid imports; muvid#158) needs two things from muvid
and nothing else:

* **Stages** — :func:`lyric_stages` returns the steps muvid owns as a ``{name: Stage}``
  mapping: ``stem``, ``glyphs``, ``render``, ``pictures`` and ``captions``. A
  :class:`Stage` is a *manifest* (name, what it reads, what it writes, whether it
  costs money or memory) whose ``run`` is a ``"module:function"`` string imported
  lazily, the same shape as :class:`muvid.subgenres.Subgenre`: listing the stages
  imports no rendering code. Each function takes paths and primitives and returns a
  report ``dict`` (or the output path); they are the functions the CLI calls, with
  no new behaviour. Third parties and the runner find them through the entry-point
  group :data:`ENTRY_POINT_GROUP` (``muvid.lyric_stages.v1``), muvid's own included.
* **Settings** — :class:`LyricProductionSettings` is the part of a song spec muvid
  reads, with :data:`LYRIC_PRODUCTION_SCHEMA` its JSON Schema. A runner mounts it as
  the ``muvid`` section of its ``spec.json`` and hands it to muvid through one
  ``settings`` argument. Timing overrides accept the bare ``"fine"`` and the
  recorded form ``{"how": "fine", "reason": "..."}``.

This module is stdlib-only at import time.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

#: Entry-point group a stage manifest is registered under (muvid's own included).
ENTRY_POINT_GROUP = "muvid.lyric_stages.v1"
API_VERSION = 1

#: How much memory a stage needs, so a runner can run the heavy one alone under a cap.
MEMORY_CLASSES = ("light", "heavy")


# -- stage manifests ---------------------------------------------------------------


@dataclass(frozen=True)
class Stage:
    """One named step of a lyric-video production: a manifest, not a function."""

    name: str
    summary: str
    run: str  # "module:function", imported lazily by :meth:`resolve`
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    #: ``"light"`` or ``"heavy"`` (the aligner and the separator are heavy).
    memory: str = "light"
    #: True when the stage spends money or fetches licensed weights.
    costed: bool = False
    api_version: int = API_VERSION

    def __post_init__(self):
        if self.memory not in MEMORY_CLASSES:
            raise ValueError(f"memory must be one of {MEMORY_CLASSES}, got {self.memory!r}")
        if ":" not in self.run:
            raise ValueError(f"run must be 'module:function', got {self.run!r}")

    def resolve(self) -> Callable[..., Any]:
        """Import and return the stage's function."""
        module, _, func = self.run.partition(":")
        return getattr(import_module(module), func)

    def __call__(self, *args, **kwargs):
        return self.resolve()(*args, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


STEM = Stage(
    "stem",
    "Separate the song's vocal stem (Demucs; fetches CC-BY-NC weights on first use).",
    "muvid.lyricvid.glyph_align:vocal_stem",
    inputs=("audio",),
    outputs=("vocals",),
    memory="heavy",
    costed=True,
)
GLYPHS = Stage(
    "glyphs",
    "Refine word timings to per-glyph times and reconcile them against the stem.",
    "muvid.lyricvid.stages:run_glyphs",
    inputs=("audio", "timing", "vocals"),
    outputs=("glyph_timing",),
    memory="heavy",
)
RENDER = Stage(
    "render",
    "Render the lyric video from audio, timing and a treatment.",
    "muvid.lyricvid.tools:render_lyric_video",
    inputs=("audio", "glyph_timing", "treatment"),
    outputs=("video",),
)
PICTURES = Stage(
    "pictures",
    "Composite a mosaic of per-word pictures onto the rendered video.",
    "muvid.lyricvid.stages:run_pictures",
    inputs=("video", "glyph_timing", "pictures"),
    outputs=("video_with_pictures",),
)
CAPTIONS = Stage(
    "captions",
    "Write one caption file per language from a saved timing.",
    "muvid.lyricvid.tools:export_captions",
    inputs=("glyph_timing", "captions"),
    outputs=("caption_files",),
)

#: Execution order of muvid's own stages.
_OWN = (STEM, GLYPHS, RENDER, PICTURES, CAPTIONS)


def lyric_stages(*, include_plugins: bool = True) -> dict[str, Stage]:
    """The stages available, ``{name: Stage}``, muvid's own first and in order.

    Plugins registered under :data:`ENTRY_POINT_GROUP` are added after them; a plugin
    naming an existing stage is skipped (muvid's own wins). A plugin that fails to
    load is skipped rather than taking the catalogue down.
    """
    stages = {s.name: s for s in _OWN}
    if include_plugins:
        from importlib.metadata import entry_points

        for ep in entry_points(group=ENTRY_POINT_GROUP):
            try:
                stage = ep.load()
            except Exception:  # one broken plugin must not empty the catalogue
                continue
            if isinstance(stage, Stage):
                stages.setdefault(stage.name, stage)
    return stages


# -- stage functions (the same ones the CLI calls) ----------------------------------


def run_glyphs(
    audio: str,
    timing: str,
    output: str,
    *,
    vocals: str = "",
    workdir: str = "",
    allow_download: bool = False,
    no_reconcile: bool = False,
    keep_unsung: bool = False,
    silent_glyph: str = "",
    overrides: Optional[Mapping[str, Any]] = None,
    repair_spills: bool = False,
    spans: bool = False,
) -> dict[str, Any]:
    """Refine word TIMING (TimedText JSON) to per-glyph times; write OUTPUT JSON.

    Returns the report (onsets, agreement, reconciled, and the opt-in ``repaired`` and
    ``spans``). ``overrides`` (``None``: not asked for) is the already-parsed ``{"<line index>": "fine"}``
    mapping; see :func:`LyricProductionSettings.timing_override_values`.
    """
    import tempfile

    from muvid.lyricvid import glyph_align as ga
    from muvid.lyricvid.timed_text import from_dict

    supplied = overrides is not None  # even ``{}`` opts in to the ``repaired`` report
    overrides = dict(overrides or {})
    coarse = from_dict(json.loads(Path(timing).read_text(encoding="utf-8")))
    stem = (
        Path(vocals)
        if vocals
        else ga.vocal_stem(
            audio,
            out_dir=workdir or tempfile.mkdtemp(prefix="muvid-glyphs-"),
            allow_download=allow_download,
        )
    )
    fine = ga.refine_glyphs(coarse, stem, allow_download=allow_download)
    agreement = ga.word_agreement(fine, coarse)
    replaced: list = []
    repaired: list = []
    if not no_reconcile:
        detectors = ga.stem_detectors(
            stem,
            drop_unsung=not keep_unsung,
            silent_glyph_remedy=silent_glyph or None,
        )
        refined = fine
        fine, replaced = ga.reconcile(refined, coarse, detectors=detectors)
        fine, repaired = ga.apply_timing_overrides(
            fine, refined, replaced, overrides=overrides
        )
    if repair_spills:
        fine, spilled = ga.repair_spills(fine, ga.stem_onsets(stem))
        repaired = [*repaired, *spilled]
    if spans:
        fine = ga.with_spans(fine, vocals=stem)
    Path(output).write_text(
        json.dumps(fine.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    report: dict[str, Any] = {
        "output": output,
        "vocals": str(stem),
        "onsets": ga.onset_report(fine, stem),
        "agreement": agreement,
        "reconciled": replaced,
    }
    if supplied or repair_spills:  # opt-in only: the default is unchanged
        report["repaired"] = repaired
    if spans:  # how many boundaries each cut decided (opt-in, as above)
        cuts = [g.span.cut for w in fine.words() for g in w.glyphs if g.span]
        report["spans"] = {c: cuts.count(c) for c in sorted(set(cuts))}
    return report


def run_pictures(
    video: str,
    timing: str,
    pictures: list[Mapping[str, Any]],
    output: str,
    *,
    block: tuple[int, int, int, int] = (0, 0, 0, 0),
    bounce: bool = True,
    border: Optional[str] = None,
) -> dict[str, Any]:
    """Composite PICTURES (``[{"word", "path", "credit"?}]``) onto VIDEO at OUTPUT.

    Each picture appears when its word is first sung and pops on each later one.
    ``block`` is the text block's ``(x, y, w, h)`` the mosaic keeps clear of. Words
    never sung are listed under ``unsung`` and left out.
    """
    from muvid.lyricvid import pictures as pic

    pics = [pic.Picture(p["word"], p["path"], p.get("credit")) for p in pictures]
    times = pic.word_times(timing)
    bounce_ = pic.Bounce() if bounce else None
    cells = pic.mosaic_cells(len(pics), block, size=pic.frame_size(video))
    tiles = pic.plan_tiles(pics, times, cells, bounce=bounce_)
    out = pic.render(video, tiles, output, bounce=bounce_, border=border)
    return {
        "output": str(out),
        "placed": len(tiles),
        "unsung": pic.unsung_pictures(pics, times),
        "credits": pic.credits(tiles),
    }


# -- the settings section muvid owns ------------------------------------------------

_HOW = ("fine",)  # the override values glyph_align accepts


def _how(value: Any) -> Any:
    """An override as the aligner reads it: ``{"how": h, "reason": r}`` becomes ``h``."""
    return value["how"] if isinstance(value, Mapping) else value


@dataclass(frozen=True)
class LyricProductionSettings:
    """What muvid reads from a song spec (the ``muvid`` section of a runner's spec)."""

    #: Which take of the song (a runner's judgement point); ``None`` until chosen.
    take: Optional[str] = None
    keep_unsung: bool = False
    repair_spills: bool = False
    #: ``{"<line index>": "fine" | {"how": "fine", "reason": "..."}}``.
    timing_overrides: Mapping[str, Any] = field(default_factory=dict)
    #: A treatment (archetype choice and parameters), as ``validate_treatment`` takes.
    treatment: Optional[Mapping[str, Any]] = None
    #: Words to emphasise, in the treatment's vocabulary.
    emphasis: tuple[str, ...] = ()
    #: ``{language tag: transform name | {line text: caption}}``.
    captions: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Optional[Mapping[str, Any]]) -> "LyricProductionSettings":
        """Build from a spec section, refusing unknown keys (a typo must not be silent)."""
        data = dict(data or {})
        known = set(cls.__dataclass_fields__)
        if unknown := sorted(set(data) - known):
            raise ValueError(
                f"unknown muvid settings {unknown}; known: {sorted(known)}"
            )
        if "emphasis" in data:
            data["emphasis"] = tuple(data["emphasis"] or ())
        for key in ("timing_overrides", "captions"):
            if data.get(key) is None:
                data.pop(key, None)
        return cls(**data)

    def timing_override_values(self) -> dict[str, Any]:
        """``timing_overrides`` with each ``{"how", "reason"}`` collapsed to its ``how``."""
        return {k: _how(v) for k, v in self.timing_overrides.items()}

    def timing_override_reasons(self) -> dict[str, str]:
        """The recorded reason per overridden line (only those that gave one)."""
        return {
            k: v["reason"]
            for k, v in self.timing_overrides.items()
            if isinstance(v, Mapping) and v.get("reason")
        }


LYRIC_PRODUCTION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "muvid lyric production settings",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "take": {"type": ["string", "null"]},
        "keep_unsung": {"type": "boolean", "default": False},
        "repair_spills": {"type": "boolean", "default": False},
        "timing_overrides": {
            "type": "object",
            "additionalProperties": {
                "oneOf": [
                    {"enum": list(_HOW)},
                    {
                        "type": "object",
                        "required": ["how"],
                        "additionalProperties": False,
                        "properties": {
                            "how": {"enum": list(_HOW)},
                            "reason": {"type": "string"},
                        },
                    },
                ]
            },
        },
        "treatment": {"type": ["object", "null"]},
        "emphasis": {"type": "array", "items": {"type": "string"}},
        "captions": {"type": "object"},
    },
}


def settings_schema() -> dict[str, Any]:
    """The JSON Schema of :class:`LyricProductionSettings` (a copy)."""
    return json.loads(json.dumps(LYRIC_PRODUCTION_SCHEMA))
