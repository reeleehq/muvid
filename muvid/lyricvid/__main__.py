"""muvid lyric-video CLI — ``cw`` dispatch over the SSOT verbs.

Every verb here is the same function the MCP tools, the shipped skill and a
production frontend call; this module only adapts them to a terminal. Run
``python -m muvid.lyricvid --help``.
"""

from __future__ import annotations

import json as _json

from muvid.lyricvid import tools as _tools


def _emit(obj) -> None:
    print(_json.dumps(obj, indent=2, default=str))


def subgenres() -> None:
    """List every installed subgenre, without importing any renderer."""
    _emit(_tools.catalog())


def vocabulary() -> None:
    """Print the closed vocabularies a treatment may draw on."""
    _emit(_tools.vocabulary())


def schema() -> None:
    """Print the JSON Schema for a treatment spec."""
    _emit(_tools.treatment_schema())


def analyze(
    audio: str,
    *,
    lyrics: str = "",
    subtitles: str = "",
    project: str = "",
    aligner: str = "",
) -> None:
    """Measure AUDIO's words and report the structure a director needs."""
    _emit(
        _tools.analyze_song(
            audio,
            lyrics=lyrics or None,
            subtitles=subtitles or None,
            project=project or None,
            aligner=aligner or None,
        )
    )


def propose(
    audio: str,
    *,
    lyrics: str = "",
    subtitles: str = "",
    project: str = "",
    n: int = 3,
    title: str = "",
    reference_image: str = "",
    use_llm: bool = False,
    model: str = "",
) -> None:
    """Propose N ranked treatments for AUDIO. No AI and no cost unless --use-llm."""
    _emit(
        _tools.propose_treatments(
            audio,
            lyrics=lyrics or None,
            subtitles=subtitles or None,
            project=project or None,
            n=n,
            title=title,
            reference_image=reference_image or None,
            use_llm=use_llm,
            model=model or None,
        )
    )


def validate(treatment: str) -> None:
    """Validate a treatment JSON file (or a JSON string), and report repairs."""
    from pathlib import Path

    _emit(_tools.validate_treatment(_treatment_arg(treatment)))


def _treatment_arg(value: str) -> str:
    """A path to a JSON file, or inline JSON. Inline first: a long JSON string
    handed to ``Path(...).exists()`` raises ENAMETOOLONG rather than False."""
    from pathlib import Path

    stripped = value.strip()
    if stripped.startswith("{"):
        return stripped
    p = Path(value)
    try:
        if p.exists():
            return p.read_text(encoding="utf-8")
    except OSError:
        pass
    return value


def render(
    audio: str,
    output: str,
    *,
    lyrics: str = "",
    subtitles: str = "",
    project: str = "",
    timed_text: str = "",
    treatment: str = "",
    renderer: str = "auto",
    title: str = "",
    persona: str = "",
    aligner: str = "",
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    workdir: str = "",
    captions: str = "",
) -> None:
    """Render a lyric video from AUDIO to OUTPUT.

    --captions also writes caption tracks beside it: see the `captions` verb.
    """
    treat = _json.loads(_treatment_arg(treatment)) if treatment else None
    _emit(
        _tools.render_lyric_video(
            audio,
            output,
            lyrics=lyrics or None,
            subtitles=subtitles or None,
            project=project or None,
            timed_text=timed_text or None,
            treatment=treat,
            renderer=renderer,
            title=title,
            persona=persona or None,
            aligner=aligner or None,
            width=width,
            height=height,
            fps=fps,
            workdir=workdir or None,
            captions=_caption_tracks_arg(captions) if captions else None,
        )
    )


def _caption_tracks_arg(value: str) -> dict:
    """``{language: transform}`` from inline JSON or a JSON file; a transform
    that names an existing ``.json`` file is replaced by the mapping it holds."""
    from pathlib import Path

    from muvid.lyricvid.captions import CAPTION_TRANSFORMS

    tracks = _json.loads(_treatment_arg(value))
    return {
        lang: _json.loads(Path(t).read_text(encoding="utf-8"))
        if isinstance(t, str) and t not in CAPTION_TRANSFORMS and Path(t).is_file()
        else t
        for lang, t in tracks.items()
    }


def captions(
    timing: str,
    output_dir: str,
    tracks: str,
    *,
    offset_s: float = 0.0,
    stem: str = "captions",
    fmt: str = "srt",
) -> None:
    """Write one caption file per language for TIMING (TimedText JSON) to OUTPUT_DIR.

    TRACKS is JSON, inline or a file: '{"ja-Latn": "hepburn", "en": "en.json"}'.
    Each value is a named transform (hepburn, original), a {line text: caption}
    mapping, or a path to a JSON file holding one. A mapping must cover every
    sung line (map a line to "" to omit it). --offset-s shifts every caption,
    e.g. by a title card prepended to the video (muvid#145).
    """
    _emit(
        _tools.export_captions(
            timing,
            output_dir,
            _caption_tracks_arg(tracks),
            offset_s=offset_s,
            stem=stem,
            fmt=fmt,
        )
    )


def glyphs(
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
    timing_overrides: str = "",
    repair_spills: bool = False,
    spans: bool = False,
) -> None:
    """Refine word TIMING (TimedText JSON) to per-glyph times; write OUTPUT JSON.

    Separates the vocals first unless --vocals is given. Prints the onset and
    agreement reports: read them before trusting the result (muvid#142).
    Lines the transcript lists but the stem shows nobody sang are DROPPED and
    listed under ``reconciled`` with ``remedy: drop`` (muvid#144);
    --silent-glyph {drop,mute,replace} also flags a word holding one sounded
    glyph that is silent in the stem (muvid#156) and applies that remedy; off
    by default, since ``drop`` deletes sung text (muvid#177).
    --keep-unsung falls back to their vendor windows instead. Words whose fine time is off every onset while
    the vendor's is on one, and lines left overlapping or out of order, go
    back to their vendor windows (muvid#150); --no-reconcile skips all of it.

    Two opt-in post-passes (muvid#155); without them the output is unchanged.
    --timing-overrides takes the song's recorded judgements, ``{"<line index>":
    "fine"}``, as a JSON file (or a song spec holding a ``timing_overrides``
    key) or inline JSON, and gives those lines the aligner's times back.
    --repair-spills pulls glyphs that aligned onto the NEXT line back onto a
    stem onset before it. Both are listed under ``repaired``.

    --spans (muvid#149) runs last and gives every sung glyph a ``span`` and a
    ``cut``: where its sound runs (a glyph's ``end`` is only the aligner's
    nominal token end), cut from the vocal stem at silences and dips; the
    report then counts the cuts under ``spans``.
    """
    import tempfile
    from pathlib import Path

    from muvid.lyricvid import glyph_align as ga
    from muvid.lyricvid.timed_text import from_dict

    coarse = from_dict(_json.loads(Path(timing).read_text(encoding="utf-8")))
    overrides = _timing_overrides_arg(timing_overrides)
    if overrides and no_reconcile:
        raise SystemExit(
            "--timing-overrides undoes what reconciling did to a line; with "
            "--no-reconcile there is nothing to undo"
        )
    try:  # refuse a bad override BEFORE separating and aligning, not after
        ga.check_timing_overrides(overrides, len(list(coarse.lines())))
    except ValueError as e:
        raise SystemExit(f"--timing-overrides: {e}") from None
    if silent_glyph and silent_glyph not in ga.REMEDIES:
        raise SystemExit(
            f"--silent-glyph must be one of {', '.join(ga.REMEDIES)}, not {silent_glyph!r}"
        )
    if silent_glyph and no_reconcile:
        raise SystemExit(
            "--silent-glyph is a reconcile detector; --no-reconcile skips it"
        )
    ga._mms_weights(
        allow_download=allow_download
    )  # refuse BEFORE separating, not after
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
        _json.dumps(fine.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    report = {
        "output": output,
        "vocals": str(stem),
        "onsets": ga.onset_report(fine, stem),
        "agreement": agreement,
        "reconciled": replaced,
    }
    if timing_overrides or repair_spills:  # opt-in only: the default is unchanged
        report["repaired"] = repaired
    if spans:  # how many boundaries each cut decided (opt-in, as above)
        cuts = [g.span.cut for w in fine.words() for g in w.glyphs if g.span]
        report["spans"] = {c: cuts.count(c) for c in sorted(set(cuts))}
    _emit(report)


def _timing_overrides_arg(value: str) -> dict:
    """``--timing-overrides``: a JSON file or inline JSON. Empty means none.

    The JSON is either a song spec, whose ``timing_overrides`` key holds the
    mapping (null: none recorded), or the mapping itself — read as one as soon as
    any key looks like a line index or any value is an override, or when EVERY
    entry is a string value under a key containing a digit (a typo such as
    ``{"x1": "fien"}``), so a typo in it is refused by the check rather than
    dropped with the valid entries beside it. ``{}`` is an empty mapping.

    Anything else is REFUSED (muvid#162): with no song-spec schema to check field
    names against, a JSON without the key cannot be told from a misspelt one —
    ``{"title": "x", "timing_override": {...}}``, or ``{"x": "fien"}`` — and reading
    either as "none recorded" applied nothing in silence. The flag is opt-in, so a
    spec that records none says so with ``"timing_overrides": null``.
    """
    from pathlib import Path

    from muvid.lyricvid.glyph_align import TIMING_OVERRIDES

    if not value:
        return {}
    path = Path(value)
    try:
        obj = _json.loads(path.read_text("utf-8") if path.is_file() else value)
    except ValueError:
        raise SystemExit(
            f"--timing-overrides {value!r} is neither a file nor JSON"
        ) from None
    if not isinstance(obj, dict):
        raise SystemExit("--timing-overrides must be a JSON object")
    if "timing_overrides" in obj:
        found = obj["timing_overrides"]
        if found is None:
            return {}
        if not isinstance(found, dict):
            raise SystemExit("timing_overrides must be a JSON object")
        return found
    looks_like_overrides = (
        any(str(k).strip().isdigit() for k in obj)
        or any(isinstance(v, str) and v in TIMING_OVERRIDES for v in obj.values())
        or (  # every entry shaped like "<something with a digit>": "<string>"
            bool(obj)
            and all(
                isinstance(v, str) and any(c.isdigit() for c in str(k))
                for k, v in obj.items()
            )
        )
    )
    if looks_like_overrides or not obj:
        return obj
    raise SystemExit(
        "--timing-overrides: this JSON is neither a timing-overrides mapping "
        '({"<line index>": "fine"}) nor a song spec with a "timing_overrides" key '
        f"(its keys: {', '.join(map(str, obj))}) — check that key's spelling, or, "
        'to record none, give the spec "timing_overrides": null'
    )


_FUNCS = [
    subgenres,
    vocabulary,
    schema,
    analyze,
    propose,
    validate,
    render,
    captions,
    glyphs,
]


def main() -> int:
    import cw

    return cw.dispatch(_FUNCS)


if __name__ == "__main__":
    raise SystemExit(main())
