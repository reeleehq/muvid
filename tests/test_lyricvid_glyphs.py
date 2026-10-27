"""Per-glyph timing and the glyph_pages archetype (muvid#142). No torch needed."""

from pathlib import Path

import pytest

from muvid.lyricvid import glyph_align as ga
from muvid.lyricvid import spec as S
from muvid.lyricvid.scene import compile_scene, Canvas
from muvid.lyricvid.timed_text import Glyph, Line, Word, from_dict, from_word_records


def _tt():
    recs = [
        {"text": "バス", "start": 1.0, "end": 1.5, "section": "Verse"},
        {"text": "ドア", "start": 1.6, "end": 2.0, "line_end": True},
        {"text": "メロン", "start": 3.0, "end": 3.6, "line_end": True},
        {"text": "パン", "start": 6.0, "end": 6.5, "line_end": True},
    ]
    return from_word_records(recs, duration=8.0)


def _with_glyphs(tt):
    from dataclasses import replace

    def g(w):
        n = len(w.text)
        step = (w.end - w.start) / n
        return tuple(
            Glyph(text=c, start=w.start + i * step, end=w.start + (i + 1) * step)
            for i, c in enumerate(w.text)
        )

    return replace(
        tt,
        sections=tuple(
            replace(
                s,
                lines=tuple(
                    replace(l, words=tuple(replace(w, glyphs=g(w)) for w in l.words))
                    for l in s.lines
                ),
            )
            for s in tt.sections
        ),
    )


def test_word_records_keep_vendor_line_breaks_and_sections():
    tt = _tt()
    assert [l.text for l in tt.lines()] == ["バス ドア", "メロン", "パン"]
    assert tt.sections[0].label == "Verse"


def test_glyphs_round_trip_through_dict():
    tt = _with_glyphs(_tt())
    assert from_dict(tt.to_dict()) == tt


def _treatment(**params):
    return {
        "scenes": [
            {
                "applies_to": ["*"],
                "archetype": "glyph_pages",
                "params": {"lines_on_screen": 2, "emphasis": "ハスン", **params},
            }
        ],
        "direction": {
            "palette": {
                "bg": "#000000",
                "fg": "#ffffff",
                "accent": "#ffff00",
                "dim": "#808080",
            }
        },
    }


def test_glyph_pages_ignite_each_glyph_at_its_time_with_emphasis_classes():
    tt = _with_glyphs(_tt())
    sc = compile_scene(
        S.coerce(_treatment())[0], tt, canvas=Canvas(width=1920, height=1080)
    )
    ink = [c for c in sc.cues if c.layer == 1]
    glyphs = [g for w in tt.words() for g in w.glyphs]
    assert sorted(c.t_in for c in ink) == pytest.approx(sorted(g.start for g in glyphs))
    by = {c.text: c.colour for c in ink}
    assert by["バ"] == "#ffff00"  # folds onto ハ: a target
    assert by["ス"] == "#ffff00"
    assert by["ド"] != "#ffff00"  # not a target: milder highlight
    ghosts = {c.text: c.colour for c in sc.cues if c.layer == 0}
    assert ghosts["バ"] == "#808080" and ghosts["ド"] != "#808080"


def test_glyph_pages_page_turns_before_the_next_page_is_sung():
    tt = _with_glyphs(_tt())
    sc = compile_scene(
        S.coerce(_treatment())[0], tt, canvas=Canvas(width=1920, height=1080)
    )
    pages = {}
    for c in sc.cues:
        pages.setdefault(c.extra["page"], []).append(c)
    first_ink_p1 = min(c.t_in for c in pages[1] if c.layer == 1)
    p0_gone = max(c.t_out for c in pages[0] if c.layer == 1)
    p1_shown = min(c.t_in for c in pages[1] if c.layer == 0)
    assert p0_gone < first_ink_p1 and p1_shown < first_ink_p1


def test_glyph_pages_without_glyphs_spreads_and_marks_unmeasured():
    sc = compile_scene(
        S.coerce(_treatment())[0], _tt(), canvas=Canvas(width=1920, height=1080)
    )
    assert sc.cues and all(c.extra["measured"] is False for c in sc.cues)


def test_place_silent_puts_long_vowel_between_neighbours():
    nan = float("nan")
    w = Word(
        text="スーパ",
        start=1.0,
        end=2.0,
        glyphs=(
            Glyph(text="ス", start=1.0, end=1.1),
            Glyph(text="ー", start=nan, end=nan, measured=False),
            Glyph(text="パ", start=1.6, end=1.7),
        ),
    )
    out = ga._place_silent(Line(words=(w,)))
    g = out.words[0].glyphs[1]
    assert g.start == pytest.approx(1.3) and g.measured is False


def test_reconcile_replaces_squeezed_and_disagreeing_words():
    coarse = _tt()
    fine = _with_glyphs(coarse)
    from dataclasses import replace

    words = list(fine.words())
    # squeeze メロン into 30 ms
    bad = replace(
        words[2],
        glyphs=tuple(
            replace(g, start=3.0 + i * 0.01, end=3.0 + i * 0.01 + 0.01)
            for i, g in enumerate(words[2].glyphs)
        ),
    )
    fine = replace(
        fine,
        sections=tuple(
            replace(
                s,
                lines=tuple(
                    replace(
                        l,
                        words=tuple(bad if w.text == "メロン" else w for w in l.words),
                    )
                    for l in s.lines
                ),
            )
            for s in fine.sections
        ),
    )
    out, replaced = ga.reconcile(fine, coarse)
    assert [r["text"] for r in replaced] == ["メロン"]
    assert all(
        not g.measured for w in out.words() if w.text == "メロン" for g in w.glyphs
    )


def test_weights_never_downloaded_unasked(monkeypatch, tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("torchaudio")
    monkeypatch.setattr(torch.hub, "get_dir", lambda: str(tmp_path))
    monkeypatch.delenv("MUVID_ALLOW_WEIGHT_DOWNLOAD", raising=False)
    with pytest.raises(RuntimeError, match="never downloads"):
        ga._load_mms(allow_download=False)


def test_reconcile_does_not_flag_alphabet_letters():
    w = Word(
        text="love",
        start=1.0,
        end=1.4,
        glyphs=tuple(
            Glyph(text=c, start=1.0 + i * 0.02, end=1.0 + i * 0.02 + 0.02)
            for i, c in enumerate("love")
        ),
    )
    from muvid.lyricvid.timed_text import Section, TimedText

    fine = TimedText(
        sections=(Section(label="*", lines=(Line(words=(w,)),)),), duration=3.0
    )
    coarse = TimedText(
        sections=(Section(label="*", lines=(Line(words=(replace_glyphs(w),)),)),),
        duration=3.0,
    )
    _, replaced = ga.reconcile(fine, coarse)
    assert replaced == []


def replace_glyphs(w):
    from dataclasses import replace

    return replace(w, glyphs=())


def test_glyph_pages_skips_empty_pages_and_previews_next_page():
    recs = [
        {"text": "カス", "start": 1.0, "end": 2.6, "line_end": True},
        {"text": "タト", "start": 2.5, "end": 3.0, "line_end": True},
    ]
    tt = _with_glyphs(from_word_records(recs, duration=5.0))
    sc = compile_scene(
        S.coerce(_treatment(lines_on_screen=1))[0],
        tt,
        canvas=Canvas(width=1920, height=1080),
    )
    ta_ghost = [c for c in sc.cues if c.text == "タ" and c.layer == 0][0]
    assert ta_ghost.t_out - ta_ghost.t_in >= 0.2  # seen grey before it is sung


def test_romanize_word_final_sokuon_is_silent():
    assert ga.romanize_kana("カッ") == [("カ", "ka"), ("ッ", "")]


# --------------------------------------------------------------------------
# reconcile's detector seam, and the unsung detector (muvid#144)
# --------------------------------------------------------------------------

_SR = 8000


def _song_with_a_ghost_line():
    """Four lines: sung; a vendor-listed repeat nobody sang; sung but squeezed
    by the aligner; sung staccato with a long silence after it (not squeezed)."""
    recs = [
        {"text": "カス", "start": 1.0, "end": 2.0, "line_end": True},
        {"text": "タン", "start": 3.0, "end": 4.0},
        {"text": "タン", "start": 4.0, "end": 5.0, "line_end": True},
        {"text": "スター", "start": 6.0, "end": 7.0, "line_end": True},
        {"text": "ストップ", "start": 8.0, "end": 10.0, "line_end": True},
    ]
    coarse = from_word_records(recs, duration=11.0)
    fine = _with_glyphs(coarse)

    def squeeze(w):
        from dataclasses import replace

        t = w.start + 0.6  # crammed together, later than the vendor said
        return replace(
            w,
            glyphs=tuple(
                replace(g, start=t + i * 0.01, end=t + i * 0.01 + 0.01)
                for i, g in enumerate(w.glyphs)
            ),
        )

    from dataclasses import replace

    fine = replace(
        fine,
        sections=tuple(
            replace(
                s,
                lines=tuple(
                    replace(
                        l,
                        words=tuple(
                            squeeze(w) if w.text in ("タン", "スター") else w
                            for w in l.words
                        ),
                    )
                    for l in s.lines
                ),
            )
            for s in fine.sections
        ),
    )
    return fine, coarse


def _stem(*spans, duration=11.0):
    np = pytest.importorskip("numpy")
    t = np.arange(int(duration * _SR)) / _SR
    y = np.zeros_like(t, dtype="float32")
    for a, b in spans:
        m = (t >= a) & (t < b)
        y[m] = 0.5 * np.sin(2 * np.pi * 220 * t[m])
    return y


@pytest.fixture
def stem_of(monkeypatch):
    def use(y):
        monkeypatch.setattr(ga, "_read_stem", lambda vocals: (y, _SR))
        return "vocals.wav"

    return use


def test_unsung_drops_the_silent_squeezed_line_and_nothing_else(stem_of):
    fine, coarse = _song_with_a_ghost_line()
    stem = stem_of(_stem((1.0, 2.0), (6.0, 7.0), (8.0, 8.3)))
    out, records = ga.reconcile(
        fine, coarse, detectors=(*ga.default_detectors(), ga.unsung(stem))
    )
    assert [l.text for l in out.lines()] == ["カス", "スター", "ストップ"]
    by = {(r["index"], r["text"]): r for r in records}
    assert {k for k, r in by.items() if r["remedy"] == "drop"} == {
        (1, "タン"),
        (2, "タン"),
    }
    assert all(
        r["why"] == "unsung" and r["used"] is None
        for r in records
        if r["remedy"] == "drop"
    )
    # squeezed but SUNG: falls back to its vendor window, it is not deleted
    star = by[(3, "スター")]
    assert star["remedy"] == "replace" and star["why"] == "squeezed"
    # a quiet window alone is not evidence: ストップ is untouched
    assert all(r["text"] != "ストップ" for r in records)


def test_unsung_needs_the_aligner_to_have_failed_too(stem_of):
    """A silent stem over a line the aligner placed fine drops nothing."""
    fine, coarse = _song_with_a_ghost_line()
    fine = _with_glyphs(coarse)  # nothing squeezed
    stem = stem_of(_stem((1.0, 2.0)))  # every later line is quiet
    _, records = ga.reconcile(
        fine, coarse, detectors=(*ga.default_detectors(), ga.unsung(stem))
    )
    assert records == []


def test_unsung_ignores_a_digitally_silent_stem(stem_of):
    """No loud level to be quiet against: never a reason to delete words."""
    fine, coarse = _song_with_a_ghost_line()
    stem = stem_of(_stem())
    _, records = ga.reconcile(
        fine, coarse, detectors=(*ga.default_detectors(), ga.unsung(stem))
    )
    assert all(r["remedy"] == "replace" for r in records)


def test_default_reconcile_still_replaces_the_ghost_line():
    """Without a stem, the behaviour before muvid#144 is unchanged."""
    fine, coarse = _song_with_a_ghost_line()
    out, records = ga.reconcile(fine, coarse)
    assert [l.text for l in out.lines()] == [l.text for l in coarse.lines()]
    assert {r["text"] for r in records} == {"タン", "スター"}
    assert all(r["remedy"] == "replace" for r in records)


def test_a_custom_detector_plugs_in_and_drop_beats_replace():
    fine, coarse = _song_with_a_ghost_line()
    first = ga.Detector(name="first", find=lambda f, c: {0: "test"}, remedy="drop")
    also = ga.Detector(name="also", find=lambda f, c: {0: "test"})
    out, records = ga.reconcile(fine, coarse, detectors=(also, first))
    assert [l.text for l in out.lines()][0] == "タン タン"  # line 0 left empty: gone
    assert records == [
        {
            "index": 0,
            "text": "カス",
            "fine": 1.0,
            "why": "first",
            "detail": "test",
            "remedy": "drop",
            "flagged_by": ["also", "first"],
            "used": None,
        }
    ]


def test_an_unknown_remedy_is_refused():
    with pytest.raises(ValueError, match="remedy"):
        ga.Detector(name="x", find=lambda f, c: {}, remedy="mark")


def test_read_stem_reads_a_real_file(tmp_path):
    sf = pytest.importorskip("soundfile")
    y = _stem((0.0, 0.5), duration=1.0)
    sf.write(tmp_path / "v.wav", y, _SR)
    got, sr = ga._read_stem(tmp_path / "v.wav")
    assert sr == _SR and len(got) == len(y)


def _one_squeezed_line(text, start, end, duration):
    coarse = from_word_records(
        [{"text": text, "start": start, "end": end, "line_end": True}],
        duration=duration,
    )
    from dataclasses import replace

    fine = _with_glyphs(coarse)
    fine = replace(
        fine,
        sections=tuple(
            replace(
                s,
                lines=tuple(
                    replace(
                        l,
                        words=tuple(
                            replace(
                                w,
                                glyphs=tuple(
                                    replace(
                                        g,
                                        start=start + i * 0.01,
                                        end=start + i * 0.01 + 0.01,
                                    )
                                    for i, g in enumerate(w.glyphs)
                                ),
                            )
                            for w in l.words
                        ),
                    )
                    for l in s.lines
                ),
            )
            for s in fine.sections
        ),
    )
    return fine, coarse


def test_a_short_sung_line_whose_vendor_window_is_late_is_not_dropped(stem_of):
    """Review of muvid#144: sung at 7.0-7.3 s, the vendor says 8.0-8.3 s — the
    aligner misses it AND the window is quiet, but no second of silence fits."""
    fine, coarse = _one_squeezed_line("フン", 8.0, 8.3, duration=11.0)
    stem = stem_of(_stem((1.0, 2.0), (7.0, 7.3)))
    _, records = ga.reconcile(
        fine, coarse, detectors=(*ga.default_detectors(), ga.unsung(stem))
    )
    assert [r["remedy"] for r in records] == ["replace"]


def test_a_line_past_the_end_of_the_stem_is_not_judged(stem_of):
    fine, coarse = _one_squeezed_line("タン", 20.0, 22.0, duration=30.0)
    stem = stem_of(_stem((1.0, 2.0), duration=11.0))  # ends at 11 s, quiet tail
    _, records = ga.reconcile(
        fine, coarse, detectors=(*ga.default_detectors(), ga.unsung(stem))
    )
    assert all(r["remedy"] == "replace" for r in records)


def test_default_thresholds_are_refused_alongside_explicit_detectors():
    fine, coarse = _song_with_a_ghost_line()
    with pytest.raises(ValueError, match="default_detectors"):
        ga.reconcile(fine, coarse, disagree_s=1.0, detectors=ga.default_detectors())


# --------------------------------------------------------------------------
# onset-aware reconciliation (muvid#150)
# --------------------------------------------------------------------------


def _place(tt, starts):
    """Put word ``k``'s glyphs at ``starts[k]`` (a list, one per glyph, or a
    single start spread 0.1 s apart), leaving other words alone."""
    from dataclasses import replace

    k = -1

    def move(w):
        nonlocal k
        k += 1
        if k not in starts:
            return w
        at = starts[k]
        ts = (
            at if isinstance(at, list) else [at + 0.1 * i for i in range(len(w.glyphs))]
        )
        return replace(
            w,
            glyphs=tuple(
                replace(g, start=t, end=t + 0.08) for g, t in zip(w.glyphs, ts)
            ),
        )

    return replace(
        tt,
        sections=tuple(
            replace(
                s,
                lines=tuple(
                    replace(l, words=tuple(move(w) for w in l.words)) for l in s.lines
                ),
            )
            for s in tt.sections
        ),
    )


@pytest.fixture
def onsets_at(monkeypatch):
    np = pytest.importorskip("numpy")

    def use(*ts):
        monkeypatch.setattr(ga, "stem_onsets", lambda vocals: np.array(ts, dtype=float))

    return use


def _four_lines():
    recs = [
        {"text": "カス", "start": 1.0, "end": 2.0, "line_end": True},
        {"text": "バス", "start": 3.0, "end": 4.0, "line_end": True},
        {"text": "ドア", "start": 6.0, "end": 7.0, "line_end": True},
        {"text": "メロン", "start": 9.0, "end": 10.0, "line_end": True},
        # two more the aligner agrees on, so the vendor's bias is measured on
        # a majority, as on a real song
        {"text": "パン", "start": 11.0, "end": 12.0, "line_end": True},
        {"text": "ネコ", "start": 13.0, "end": 14.0, "line_end": True},
    ]
    coarse = from_word_records(recs, duration=15.0)
    return _with_glyphs(coarse), coarse


def test_misplaced_keeps_an_onset_backed_fine_time_the_vendor_contradicts(
    stem_of, onsets_at
):
    """The muvid#150 table: バス's fine time sits on an onset and the vendor's
    does not, so the fine time stays; ドア's is the other way round."""
    fine, coarse = _four_lines()
    fine = _place(fine, {0: 1.0, 1: 3.6, 2: 6.7, 3: 9.0})
    onsets_at(1.0, 3.6, 6.0, 9.0, 11.0, 13.0)
    stem = stem_of(_stem((0.0, 15.0), duration=15.0))

    out, records = ga.reconcile(fine, coarse, detectors=ga.stem_detectors(stem))

    assert {r["text"]: r["why"] for r in records} == {"ドア": "misplaced"}
    starts = {w.text: w.glyphs[0].start for w in out.words()}
    assert starts["バス"] == pytest.approx(3.6)
    assert starts["ドア"] == pytest.approx(6.0)
    # negative control: the old default distrusts both and takes the vendor's
    _, old = ga.reconcile(fine, coarse)
    assert {r["text"] for r in old} == {"バス", "ドア"}


def _intro_sung_once():
    """``カ ト ハ`` listed twice by the vendor, sung once; the aligner pushed the
    repeat's first word into the next line's window (off any onset) and
    squeezed the other two."""
    recs = [
        {"text": "カ", "start": 1.0, "end": 1.3},
        {"text": "ト", "start": 1.3, "end": 1.6},
        {"text": "ハ", "start": 1.6, "end": 1.9, "line_end": True},
        {"text": "カ", "start": 2.5, "end": 2.9},
        {"text": "ト", "start": 2.9, "end": 3.3},
        {"text": "ハ", "start": 3.3, "end": 3.8, "line_end": True},
        {"text": "バス", "start": 5.0, "end": 5.6, "line_end": True},
    ]
    coarse = from_word_records(recs, duration=8.0)
    fine = _place(
        _with_glyphs(coarse),
        {0: 1.0, 1: 1.3, 2: 1.6, 3: 5.25, 4: 3.0, 5: 3.01, 6: 5.0},
    )
    return fine, coarse


def test_unsung_catches_a_repeat_whose_first_word_disagrees_instead_of_squeezing(
    stem_of, onsets_at
):
    fine, coarse = _intro_sung_once()
    onsets_at(1.0, 1.3, 1.6, 5.0, 5.1)
    stem = stem_of(_stem((0.9, 2.0), (5.0, 5.6), duration=8.0))

    out, records = ga.reconcile(fine, coarse, detectors=ga.stem_detectors(stem))

    assert [l.text for l in out.lines()] == [
        l.text for i, l in enumerate(coarse.lines()) if i != 1
    ]
    assert sorted(r["index"] for r in records if r["remedy"] == "drop") == [3, 4, 5]
    # negative control: squeeze-only `among` misses it, so the ghost stays
    _, old = ga.reconcile(
        fine, coarse, detectors=(*ga.default_detectors(), ga.unsung(stem))
    )
    assert not [r for r in old if r["remedy"] == "drop"]


def test_lost_never_counts_a_disagreeing_word_on_an_onset(stem_of, onsets_at):
    """A disagreeing word the aligner put on an onset was sung somewhere, so
    its line is never dropped, however quiet the vendor's window is."""
    fine, coarse = _intro_sung_once()
    onsets_at(1.0, 1.3, 1.6, 5.0, 5.25)  # the pushed カ now sits on an onset
    stem = stem_of(_stem((0.9, 2.0), (5.0, 5.6), duration=8.0))

    _, records = ga.reconcile(fine, coarse, detectors=ga.stem_detectors(stem))

    assert not [r for r in records if r["remedy"] == "drop"]


def test_disordered_sends_overlapping_and_backwards_lines_to_the_vendor(
    stem_of, onsets_at
):
    fine, coarse = _four_lines()
    # カス aligned onto バス's time (both on onsets, so nothing else objects),
    # and ドア's glyphs run backwards
    fine = _place(fine, {0: 3.1, 1: 3.05, 2: [6.4, 6.2], 3: 9.0})
    onsets_at(3.05, 3.1, 3.15, 6.2, 6.4, 9.0, 11.0, 13.0)
    stem = stem_of(_stem((0.0, 15.0), duration=15.0))

    out, records = ga.reconcile(fine, coarse, detectors=ga.stem_detectors(stem))

    assert {r["text"]: r["why"] for r in records} == {
        "カス": "disordered",
        "バス": "disordered",
        "ドア": "disordered",
    }
    starts = [l.words[0].glyphs[0].start for l in out.lines()]
    assert starts == sorted(starts)
    # negative control: without it the overlap survives
    first = ga.stem_detectors(stem)[:-1]
    kept, _ = ga.reconcile(fine, coarse, detectors=first)
    ln = list(kept.lines())
    assert ln[0].words[-1].glyphs[-1].start >= ln[1].words[0].glyphs[0].start


def test_keep_unsung_leaves_the_drop_out(stem_of, onsets_at):
    fine, coarse = _intro_sung_once()
    onsets_at(1.0, 1.3, 1.6, 5.0, 5.1)
    stem = stem_of(_stem((0.9, 2.0), (5.0, 5.6), duration=8.0))

    dets = ga.stem_detectors(stem, drop_unsung=False)

    assert "unsung" not in [d.name for d in dets]
    _, records = ga.reconcile(fine, coarse, detectors=dets)
    assert not [r for r in records if r["remedy"] == "drop"]


def test_the_weight_check_builds_nothing(monkeypatch, tmp_path):
    """The CLI's refuse-early check must not build the 1.2 GB model: it used
    to, and then refine_glyphs built it again (muvid#150)."""
    torch = pytest.importorskip("torch")
    pytest.importorskip("torchaudio")
    import torchaudio

    monkeypatch.setattr(torch.hub, "get_dir", lambda: str(tmp_path))
    ckpt = tmp_path / "checkpoints" / Path(torchaudio.pipelines.MMS_FA._path).name
    ckpt.parent.mkdir()
    ckpt.write_bytes(b"")
    monkeypatch.setattr(
        type(torchaudio.pipelines.MMS_FA),
        "get_model",
        lambda *a, **k: pytest.fail("the check built the model"),
    )
    assert ga._mms_weights(allow_download=False) == ckpt


def test_a_sung_line_the_vendor_placed_late_is_never_dropped(stem_of, onsets_at):
    """Review of muvid#154: ドア was sung at 4.5-5.4 s, the vendor says
    6.0-8.5 s, beyond the aligner's search margin, so its fine time disagrees
    and sits off every onset, and its window is quiet. It is in no other
    line's window, so it is not lost, and its line is never deleted."""
    recs = [
        {"text": "カス", "start": 1.0, "end": 2.0, "line_end": True},
        {"text": "ドア", "start": 6.0, "end": 8.5, "line_end": True},
        {"text": "パン", "start": 9.0, "end": 10.0, "line_end": True},
        {"text": "ネコ", "start": 11.0, "end": 12.0, "line_end": True},
    ]
    coarse = from_word_records(recs, duration=13.0)
    fine = _place(_with_glyphs(coarse), {0: 1.0, 1: 5.6, 2: 9.0, 3: 11.0})
    onsets_at(1.0, 4.5, 4.9, 9.0, 11.0)
    stem = stem_of(_stem((0.9, 2.1), (4.5, 5.4), (8.9, 12.2), duration=13.0))

    _, records = ga.reconcile(fine, coarse, detectors=ga.stem_detectors(stem))

    assert not [r for r in records if r["remedy"] == "drop"]


def test_disordered_maps_indices_across_a_dropped_line(stem_of, onsets_at):
    """The result ``disordered`` judges has the ghost line dropped, so its
    word positions are not the fine timing's; the flags must land on the
    right words anyway (an identity mapping passes the simpler test)."""
    fine, coarse = _intro_sung_once()
    fine = _place(fine, {6: 1.65})  # バス aligned onto line 0's tail, on an onset
    onsets_at(1.0, 1.3, 1.6, 1.65, 5.0)
    stem = stem_of(_stem((0.9, 2.0), (5.0, 5.6), duration=8.0))

    _, records = ga.reconcile(fine, coarse, detectors=ga.stem_detectors(stem))

    by = {r["index"]: (r["why"], r["remedy"]) for r in records}
    assert {k for k, v in by.items() if v[1] == "drop"} == {3, 4, 5}
    assert {k for k, v in by.items() if v[0] == "disordered"} == {0, 1, 2, 6}


def _tiny_mms(tmp_path):
    """A real MMS_FA-shaped wav2vec2, small enough for CI, saved to disk."""
    import copy

    torch = pytest.importorskip("torch")
    torchaudio = pytest.importorskip("torchaudio")
    from torchaudio.pipelines._wav2vec2 import utils as u

    params = copy.deepcopy(torchaudio.pipelines.MMS_FA._params)
    params.update(
        encoder_embed_dim=16,
        encoder_projection_dropout=0.0,
        encoder_pos_conv_kernel=4,
        encoder_pos_conv_groups=2,
        encoder_num_layers=1,
        encoder_num_heads=2,
        encoder_ff_interm_features=16,
        extractor_conv_layer_config=[(8, 10, 5), (8, 3, 2)],
    )
    bundle = copy.copy(torchaudio.pipelines.MMS_FA)
    bundle._params, bundle._remove_aux_axis = params, None
    ref = u._get_model(bundle._model_type, params)
    ckpt = tmp_path / "tiny.pt"
    torch.save(ref.state_dict(), ckpt)
    ref = u._extend_model(
        ref,
        normalize_waveform=bundle._normalize_waveform,
        apply_log_softmax=True,
        append_star=True,
    ).eval()
    return bundle, ckpt, ref


def test_the_mapped_model_is_the_model(tmp_path):
    """Same outputs as torchaudio's own build, nothing left on the meta
    device, and nothing global changed (two threads may load at once)."""
    torch = pytest.importorskip("torch")
    from torchaudio.pipelines._wav2vec2 import utils as u

    bundle, ckpt, ref = _tiny_mms(tmp_path)
    before = (u._get_model, u._get_state_dict)

    model = ga._mmap_model(bundle, ckpt)

    assert model is not None
    assert not any(t.is_meta for t in model.parameters())
    x = torch.randn(1, 4000)
    with torch.inference_mode():
        assert float((model(x)[0] - ref(x)[0]).abs().max()) == 0.0
    assert (u._get_model, u._get_state_dict) == before


def test_mmap_loading_falls_back_loudly_when_torchaudio_internals_moved(
    monkeypatch, tmp_path
):
    pytest.importorskip("torchaudio")
    from torchaudio.pipelines._wav2vec2 import utils as u

    monkeypatch.delattr(u, "_extend_model")
    with pytest.warns(RuntimeWarning, match="2 GB"):
        assert ga._mmap_model(object(), tmp_path / "model.pt") is None


# --------------------------------------------------------------------------
# the default output is pinned (muvid#155): the repairs below are opt-in
# --------------------------------------------------------------------------

_GLYPHS_GOLDEN = Path(__file__).parent / "data" / "glyphs_default_golden.json"


def _spilled_song():
    """カス aligned onto バス (both sent back to the vendor); the vendor's バス
    then ends on ドア's first glyph, which the aligner had right: a spill."""
    fine, coarse = _four_lines()
    return _place(fine, {0: 3.1, 1: 3.05, 2: 3.5, 3: 9.0}), coarse


_SPILL_ONSETS = (3.05, 3.1, 3.15, 3.5, 3.6, 9.0, 11.0, 13.0)

_BIASED = {
    0: [0.8, 2.75],  # ends exactly LINE_GAP_S before バス: an overlap
    1: [2.8, 3.3],
    2: [5.8, 8.7],  # 0.1 s before メロン: not one
    3: [8.8, 8.85, 8.9],  # 0.05 s apart: not squeezed at MIN_GLYPH_S
    4: [10.8, 11.3],
    5: [12.8, 13.3],
}


def _biased_song():
    """The vendor runs 0.2 s late everywhere, so the measured bias is not 0."""
    fine, coarse = _four_lines()
    return _place(fine, _BIASED), coarse


#: The fixtures the default output is pinned on: (song, onsets, sung spans,
#: duration). Between them they reach a spill, a dropped ghost line, a
#: non-zero bias, both sides of LINE_GAP_S and of MIN_GLYPH_S.
_PINNED_SONGS = {
    "spill": (_spilled_song, _SPILL_ONSETS, ((0.0, 15.0),), 15.0),
    "ghost": (
        _intro_sung_once,
        (1.0, 1.3, 1.6, 5.0, 5.1),
        ((0.9, 2.0), (5.0, 5.6)),
        8.0,
    ),
    "biased": (
        _biased_song,
        tuple(t for ts in _BIASED.values() for t in ts),
        ((0.0, 15.0),),
        15.0,
    ),
}


def _run_glyphs_cli(tmp_path, monkeypatch, capsys, *, song="spill", **flags):
    """The ``glyphs`` verb end to end, with the model and the stem faked."""
    import json

    import numpy as np

    from muvid.lyricvid.__main__ import glyphs

    make, onsets, spans, duration = _PINNED_SONGS[song]
    fine, coarse = make()
    monkeypatch.setattr(ga, "_mms_weights", lambda **kw: tmp_path)
    monkeypatch.setattr(ga, "refine_glyphs", lambda tt, stem, **kw: fine)
    monkeypatch.setattr(ga, "stem_onsets", lambda vocals: np.array(onsets, dtype=float))
    y = _stem(*spans, duration=duration)
    monkeypatch.setattr(ga, "_read_stem", lambda vocals: (y, _SR))
    timing = tmp_path / "timing.json"
    timing.write_text(json.dumps(coarse.to_dict(), ensure_ascii=False), "utf-8")
    out = tmp_path / "out.json"
    capsys.readouterr()
    glyphs("song.wav", str(timing), str(out), vocals="vocals.wav", **flags)
    report = json.loads(capsys.readouterr().out)
    report["output"] = "out.json"  # a tmp path; everything else is pinned
    return {"timing": json.loads(out.read_text("utf-8")), "report": report}


def _refresh_glyphs_golden(tmp_path, monkeypatch, capsys):  # pragma: no cover
    """Re-record the golden. Only on purpose: it is what the default IS."""
    import json

    got = {
        name: _run_glyphs_cli(tmp_path, monkeypatch, capsys, song=name)
        for name in _PINNED_SONGS
    }
    _GLYPHS_GOLDEN.write_text(
        json.dumps(got, ensure_ascii=False, indent=1) + "\n", "utf-8"
    )


@pytest.mark.parametrize("song", sorted(_PINNED_SONGS))
def test_glyphs_default_output_is_pinned(song, tmp_path, monkeypatch, capsys):
    """The glyphs CLI with no new flags writes exactly what it wrote before
    muvid#155: a live pipeline renders from this file every day, so the
    spill repair and the overrides may only ever be opted into. The golden
    was recorded from the code BEFORE that change; re-record it only on
    purpose (``_refresh_glyphs_golden``)."""
    import json

    pytest.importorskip("numpy")
    got = _run_glyphs_cli(tmp_path, monkeypatch, capsys, song=song)
    assert got == json.loads(_GLYPHS_GOLDEN.read_text("utf-8"))[song]


def test_repair_spills_moves_a_glyph_off_the_next_line_onto_an_onset(
    stem_of, onsets_at
):
    fine, coarse = _spilled_song()
    onsets_at(*_SPILL_ONSETS)
    stem = stem_of(_stem((0.0, 15.0), duration=15.0))
    out, _ = ga.reconcile(fine, coarse, detectors=ga.stem_detectors(stem))

    fixed, records = ga.repair_spills(out, _SPILL_ONSETS)

    assert [(r["text"], r["line"], r["remedy"], r["used"]) for r in records] == [
        ("ス", "バス", "onset", 3.1)
    ]
    basu = list(fixed.lines())[1]
    su = basu.words[0].glyphs[-1]
    assert (su.start, su.measured) == (pytest.approx(3.1), False)
    assert su.end <= 3.5 and basu.words[0].end <= 3.5
    ba, was = basu.words[0].glyphs[0], list(out.lines())[1].words[0].glyphs[0]
    assert ba.start == was.start  # the first glyph never moves...
    assert (was.end, ba.end) == (pytest.approx(3.5), pytest.approx(3.1))  # ...but
    # it no longer stays lit over the glyph moved in after it
    # every other line is untouched
    others = [l for i, l in enumerate(fixed.lines()) if i != 1]
    assert others == [l for i, l in enumerate(out.lines()) if i != 1]
    # negative control: that is the spill the default leaves in place
    assert list(out.lines())[1].words[0].glyphs[-1].start >= 3.5 - ga.LINE_GAP_S


def test_repair_spills_falls_back_to_the_midpoint_and_never_moves_a_first_glyph():
    recs = [
        {"text": "ハット", "start": 1.0, "end": 2.0, "line_end": True},
        {"text": "トマト", "start": 2.0, "end": 3.0, "line_end": True},
    ]
    tt = _place(
        _with_glyphs(from_word_records(recs, duration=4.0)),
        {0: [1.0, 1.4, 2.0], 1: 2.0},  # ハット's ト sits on トマト's ト
    )

    fixed, records = ga.repair_spills(tt, None)

    assert [(r["text"], r["remedy"]) for r in records] == [("ト", "midpoint")]
    lo = 1.4 + ga.SPILL_MIN_STEP_S
    hi = 2.0 - ga.LINE_GAP_S  # never left inside the gap it was flagged for
    assert list(fixed.words())[0].glyphs[-1].start == pytest.approx((lo + hi) / 2)
    # a line that STARTS on the next one is disordered's business, not this
    # ...and one with no room left is not moved before the glyph it follows
    first = _place(tt, {0: [2.0, 2.1, 2.2]})
    assert ga.repair_spills(first, None) == (first, [])
    # nothing spilled: the very same object back, no records
    clean = _place(tt, {0: [1.0, 1.4, 1.7]})
    assert ga.repair_spills(clean, (1.5,)) == (clean, [])


def test_timing_overrides_give_a_line_its_fine_times_back(stem_of, onsets_at):
    fine, coarse = _spilled_song()
    onsets_at(*_SPILL_ONSETS)
    stem = stem_of(_stem((0.0, 15.0), duration=15.0))
    out, records = ga.reconcile(fine, coarse, detectors=ga.stem_detectors(stem))

    got, recs = ga.apply_timing_overrides(out, fine, records, overrides={"1": "fine"})

    assert list(got.lines())[1] == list(fine.lines())[1]
    assert list(got.lines())[0] == list(out.lines())[0]  # not overridden
    assert [(r["index"], r["why"], r["remedy"]) for r in recs] == [
        (1, "override", "fine")
    ]
    assert "disordered" in recs[0]["detail"]
    # ints work too, and no overrides is the identity
    assert (
        ga.apply_timing_overrides(out, fine, records, overrides={1: "fine"})[0] == got
    )
    assert ga.apply_timing_overrides(out, fine, records, overrides=None) == (out, [])
    assert ga.apply_timing_overrides(out, fine, records, overrides={}) == (out, [])


def test_an_override_restores_a_line_unsung_dropped(stem_of, onsets_at):
    """A person said it was sung, so it comes back, in its place."""
    fine, coarse = _intro_sung_once()
    onsets_at(1.0, 1.3, 1.6, 5.0, 5.1)
    stem = stem_of(_stem((0.9, 2.0), (5.0, 5.6), duration=8.0))
    out, records = ga.reconcile(fine, coarse, detectors=ga.stem_detectors(stem))
    assert len(list(out.lines())) == 2

    got, recs = ga.apply_timing_overrides(out, fine, records, overrides={"1": "fine"})

    assert list(got.lines()) == [
        list(out.lines())[0],
        *list(fine.lines())[1:2],
        list(out.lines())[1],
    ]
    assert sorted(r["index"] for r in recs) == [3, 4, 5]


@pytest.mark.parametrize(
    "overrides, msg",
    [
        ({"x": "fine"}, "not a line index"),
        ({"9": "fine"}, "out of range"),
        ({"-1": "fine"}, "out of range"),
        ({"0": "vendor"}, "must be one of"),
    ],
)
def test_bad_timing_overrides_are_refused(overrides, msg):
    fine, coarse = _four_lines()
    with pytest.raises(ValueError, match=msg):
        ga.apply_timing_overrides(fine, fine, [], overrides=overrides)


def test_overrides_refuse_a_reconciled_timing_from_elsewhere():
    fine, _ = _four_lines()
    other, _ = _intro_sung_once()
    with pytest.raises(ValueError, match="does not come from"):
        ga.apply_timing_overrides(other, fine, [], overrides={"0": "fine"})


def test_glyphs_cli_opts_in_to_both_repairs(tmp_path, monkeypatch, capsys):
    import json

    pytest.importorskip("numpy")
    spec = tmp_path / "song.json"
    spec.write_text(json.dumps({"title": "x", "timing_overrides": {"0": "fine"}}))

    got = _run_glyphs_cli(
        tmp_path, monkeypatch, capsys, timing_overrides=str(spec), repair_spills=True
    )

    rep = got["report"]["repaired"]
    assert [(r["why"], r["text"]) for r in rep] == [
        ("override", "カス"),
        ("spilled", "ス"),
    ]
    pinned = json.loads(_GLYPHS_GOLDEN.read_text("utf-8"))["spill"]
    assert got["report"]["reconciled"] == pinned["report"]["reconciled"]
    assert got["timing"] != pinned["timing"]
    # each flag alone, inline JSON too
    only = _run_glyphs_cli(
        tmp_path, monkeypatch, capsys, timing_overrides='{"0": "fine"}'
    )
    assert [r["why"] for r in only["report"]["repaired"]] == ["override"]


def test_glyphs_cli_refuses_overrides_without_reconciling(
    tmp_path, monkeypatch, capsys
):
    pytest.importorskip("numpy")
    with pytest.raises(SystemExit, match="nothing to undo"):
        _run_glyphs_cli(
            tmp_path,
            monkeypatch,
            capsys,
            timing_overrides='{"0": "fine"}',
            no_reconcile=True,
        )


def test_repair_spills_clamps_the_whole_word_and_never_moves_a_glyph_later():
    """Review of muvid#157: a word whose first glyph moved kept its vendor
    start and end, past the next line; and a glyph just inside the gap was
    moved LATER and still reported repaired."""
    recs = [
        {"text": "ハ", "start": 1.0, "end": 1.5},
        {"text": "ト", "start": 2.3, "end": 2.3, "line_end": True},
        {"text": "マ", "start": 2.0, "end": 3.0, "line_end": True},
    ]
    tt = _place(
        _with_glyphs(from_word_records(recs, duration=4.0)), {0: 1.0, 1: 2.3, 2: 2.0}
    )

    fixed, records = ga.repair_spills(tt, None)

    to = list(fixed.words())[1]
    assert len(records) == 1
    assert to.start == to.glyphs[0].start < 2.0 - ga.LINE_GAP_S
    assert to.start <= to.end <= 2.0
    # [1.0, 1.9, 1.96] before 2.0: ト has no room (1.9 + a mora is already in
    # the gap), so it is left alone rather than moved later and called fixed
    hatto = [{"text": "ハット", "start": 1.0, "end": 2.0, "line_end": True}, recs[2]]
    late = _place(
        _with_glyphs(from_word_records(hatto, duration=4.0)),
        {0: [1.0, 1.9, 1.96], 1: 2.0},
    )
    assert ga.repair_spills(late, None) == (late, [])


@pytest.mark.parametrize(
    "value, expected",
    [
        ('{"1": "fine"}', {"1": "fine"}),
        ('{"title": "x", "timing_overrides": {"1": "fine"}}', {"1": "fine"}),
        ('{"title": "x", "lyrics": "y"}', {}),  # a spec with none recorded
        ('{"title": "x", "mp3": "a.mp3"}', {}),  # digits in a spec key (#159 review)
        ('{"title": "x", "id3": {}}', {}),
        ('{"title": "x", "h1": "Hat"}', {}),
        ('{"title": "x", "timing_overrides": null}', {}),
        ("{}", {}),
    ],
)
def test_timing_overrides_arg_reads_a_mapping_or_a_song_spec(value, expected, tmp_path):
    from muvid.lyricvid.__main__ import _timing_overrides_arg

    assert _timing_overrides_arg(value) == expected
    f = tmp_path / "spec.json"
    f.write_text(value)
    assert _timing_overrides_arg(str(f)) == expected


@pytest.mark.parametrize(
    "value, msg",
    [
        ('{"1": "fine", "x2": "fien"}', "not a line index"),  # never dropped
        ('{"x": "fine"}', "not a line index"),
        ('{"x1": "fien"}', "not a line index"),  # bad key AND bad value (muvid#159)
        ("[1]", "JSON object"),
        ('{"timing_overrides": []}', "JSON object"),
        ("song.jsn", "neither a file nor JSON"),
    ],
)
def test_a_mistyped_overrides_value_is_refused_not_dropped(value, msg, tmp_path):
    """Review of muvid#157: a typo beside a valid entry used to read as a
    song spec with no overrides, silently dropping the valid one too."""
    from muvid.lyricvid.__main__ import _timing_overrides_arg

    with pytest.raises((SystemExit, ValueError), match=msg):
        ga.check_timing_overrides(_timing_overrides_arg(value), 4)


def test_repair_spills_shares_the_room_between_every_spilled_glyph():
    """Review of muvid#157: placed one at a time, the first moved glyph took
    the room the next needed, which stayed on the next line."""
    recs = [
        {"text": "ハット", "start": 1.0, "end": 1.9},
        {"text": "ト", "start": 2.1, "end": 2.1, "line_end": True},
        {"text": "マ", "start": 2.0, "end": 3.0, "line_end": True},
    ]
    tt = _place(
        _with_glyphs(from_word_records(recs, duration=4.0)),
        {0: [1.0, 1.82, 1.97], 1: 2.2, 2: 2.0},
    )

    fixed, records = ga.repair_spills(tt, None)

    first = list(fixed.lines())[0]
    gl = [g for w in first.words for g in w.glyphs]
    hi = 2.0 - ga.LINE_GAP_S
    assert [r["text"] for r in records] == ["ト", "ト"]
    assert all(g.start < hi for g in gl)
    assert all(a.start < b.start and a.end <= b.start for a, b in zip(gl, gl[1:]))
    for w in first.words:
        assert w.start <= w.glyphs[0].start and w.glyphs[-1].end <= w.end <= 2.0


def test_repair_spills_never_leaves_a_glyph_spilled_or_out_of_order():
    """A small fuzz over random lines: every repaired line ends up clear of
    the next one, in order, with no end before its start."""
    import random

    rng = random.Random(155)
    for _ in range(500):
        n = rng.randint(2, 5)
        starts = sorted(round(rng.uniform(0.5, 2.6), 2) for _ in range(n))
        recs = [{"text": "カ" * n, "start": 0.5, "end": 2.0, "line_end": True}]
        recs.append({"text": "マ", "start": 2.0, "end": 3.0, "line_end": True})
        tt = _place(
            _with_glyphs(from_word_records(recs, duration=4.0)), {0: starts, 1: 2.0}
        )
        ons = sorted(rng.uniform(0.5, 2.0) for _ in range(rng.randint(0, 4)))
        fixed, records = ga.repair_spills(tt, ons)
        if not records:
            continue
        gl = [g for w in list(fixed.lines())[0].words for g in w.glyphs]
        assert all(g.start < 2.0 - ga.LINE_GAP_S for g in gl[1:]), starts
        # in order wherever this pass moved a glyph (the input's own order is not its business)
        assert all(a.start < b.start for a, b in zip(gl, gl[1:]) if not b.measured), (
            starts
        )
        assert all(g.start <= g.end for g in gl), starts
        assert all(r["used"] < r["fine"] for r in records), starts
        for w in list(fixed.lines())[0].words:
            assert w.start <= w.end <= 2.0, starts


@pytest.mark.parametrize("key", [True, 1.5, "1.0"])
def test_a_line_index_must_be_an_integer(key):
    with pytest.raises(ValueError, match="not a line index"):
        ga.check_timing_overrides({key: "fine"}, 4)


def test_glyphs_cli_refuses_a_bad_override_before_aligning(tmp_path, monkeypatch):
    """The refusal must come before the weights, the stem and the model."""
    import json

    from muvid.lyricvid.__main__ import glyphs

    _, coarse = _four_lines()
    timing = tmp_path / "timing.json"
    timing.write_text(json.dumps(coarse.to_dict(), ensure_ascii=False), "utf-8")
    monkeypatch.setattr(
        ga, "_mms_weights", lambda **kw: pytest.fail("reached the model first")
    )
    for bad, msg in (('{"99": "fine"}', "out of range"), ('{"0": "vendor"}', "one of")):
        with pytest.raises(SystemExit, match=msg):
            glyphs(
                "song.wav", str(timing), str(tmp_path / "o.json"), timing_overrides=bad
            )


def test_repair_spills_clamps_an_earlier_glyph_lit_into_the_next_line():
    """Third review pass on muvid#157: only the glyphs from the spill on were
    clamped, so ハ (1.0-2.5) stayed lit into the next line at 2.0."""
    from dataclasses import replace

    recs = [
        {"text": "ハ", "start": 1.0, "end": 2.5},
        {"text": "ット", "start": 1.5, "end": 2.0, "line_end": True},
        {"text": "マ", "start": 2.0, "end": 3.0, "line_end": True},
    ]
    tt = _place(
        _with_glyphs(from_word_records(recs, duration=4.0)),
        {1: [1.5, 1.97], 2: 2.0},
    )
    ha = list(tt.words())[0]
    tt = _rebuilt_first_word(
        tt, replace(ha, glyphs=(replace(ha.glyphs[0], start=1.0, end=2.5),))
    )

    fixed, records = ga.repair_spills(tt, None)

    assert [r["text"] for r in records] == ["ト"]
    for w in list(fixed.lines())[0].words:
        assert w.end <= 2.0 and all(g.end <= 2.0 for g in w.glyphs)


def _rebuilt_first_word(tt, word):
    from dataclasses import replace

    sec = tt.sections[0]
    ln = sec.lines[0]
    ln = replace(ln, words=(word, *ln.words[1:]))
    return replace(
        tt, sections=(replace(sec, lines=(ln, *sec.lines[1:])), *tt.sections[1:])
    )


# ---------------------------------------------------------------------------
# silent_glyph: one silent mora inside a sung line (muvid#156)
# ---------------------------------------------------------------------------


def _timed_words(*words):
    """``words``: ``(text, [(glyph, start), ...])``; one line, glyph ends at the next start."""
    from dataclasses import replace

    out = []
    for text, gl in words:
        starts = [s for _, s in gl]
        glyphs = tuple(
            Glyph(text=c, start=s, end=(starts[i + 1] if i + 1 < len(gl) else s + 0.1))
            for i, (c, s) in enumerate(gl)
        )
        out.append(
            {"text": text, "start": starts[0], "end": glyphs[-1].end, "glyphs": glyphs}
        )
    recs = [{"text": w["text"], "start": w["start"], "end": w["end"]} for w in out]
    recs[-1]["line_end"] = True
    tt = from_word_records(recs, duration=8.0)
    it = iter(out)
    return replace(
        tt,
        sections=tuple(
            replace(
                s,
                lines=tuple(
                    replace(
                        l,
                        words=tuple(
                            replace(w, glyphs=next(it)["glyphs"]) for w in l.words
                        ),
                    )
                    for l in s.lines
                ),
            )
            for s in tt.sections
        ),
    )


def _elided_song():
    # ハッカー sung as ハッ: カ (1.3) and ー (1.4) fall in silence; サンプル is sung
    return _timed_words(
        ("ハッカー", [("ハ", 1.0), ("ッ", 1.15), ("カ", 1.3), ("ー", 1.4)]),
        ("サン", [("サ", 3.0), ("ン", 3.2)]),
    )


def test_silent_glyph_flags_the_elided_mora_and_not_the_sung_ones(stem_of):
    fine = _elided_song()
    stem = stem_of(_stem((1.0, 1.25), (3.0, 3.5)))
    found = ga.silent_glyph(stem).find(fine, fine)
    assert list(found) == [0] and "'カ'" in found[0]


def test_silent_glyph_drops_the_word_by_default_and_can_replace(stem_of):
    fine = _elided_song()
    stem = stem_of(_stem((1.0, 1.25), (3.0, 3.5)))
    out, records = ga.reconcile(fine, fine, detectors=(ga.silent_glyph(stem),))
    assert [w.text for w in out.words()] == ["サン"]
    assert records[0]["why"] == "silent_glyph" and records[0]["remedy"] == "drop"
    out, records = ga.reconcile(
        fine, fine, detectors=(ga.silent_glyph(stem, remedy="replace"),)
    )
    assert [w.text for w in out.words()] == ["ハッカー", "サン"]


def test_silent_glyph_wants_both_peak_and_median_quiet(stem_of):
    """A quiet tail next to an attack (high peak) is not silence."""
    fine = _elided_song()
    # the singing resumes 50 ms into カ's 0.4 s window: peak is loud, median quiet
    stem = stem_of(_stem((1.0, 1.25), (1.35, 1.4), (3.0, 3.5)))
    assert ga.silent_glyph(stem).find(fine, fine) == {}


def test_silent_glyph_ignores_soundless_glyphs_and_a_silent_stem(stem_of):
    fine = _timed_words(("ハー", [("ハ", 1.0), ("ー", 1.3)]), ("ス", [("ス", 3.0)]))
    stem = stem_of(_stem((1.0, 1.25), (3.0, 3.5)))
    assert ga.silent_glyph(stem).find(fine, fine) == {}  # ー is never judged
    stem = stem_of(_stem())
    assert ga.silent_glyph(stem).find(_elided_song(), _elided_song()) == {}


def test_silent_glyph_does_not_judge_past_the_end_of_the_stem(stem_of):
    fine = _timed_words(("ハ", [("ハ", 10.9)]))
    stem = stem_of(_stem((1.0, 2.0), duration=11.0))
    assert ga.silent_glyph(stem).find(fine, fine) == {}


def test_silent_glyph_refuses_an_unknown_remedy():
    with pytest.raises(ValueError):
        ga.silent_glyph("x", remedy="wipe")


def _stem_amps(*spans, duration=11.0):
    """Like ``_stem`` but each span is ``(a, b, amplitude)``."""
    np = pytest.importorskip("numpy")
    t = np.arange(int(duration * _SR)) / _SR
    y = np.zeros_like(t, dtype="float32")
    for a, b, amp in spans:
        m = (t >= a) & (t < b)
        y[m] = amp * np.sin(2 * np.pi * 220 * t[m])
    return y


def _db_amp(db):
    """Amplitude of a 0.5-amplitude loud level's sine, ``db`` below it."""
    return 0.5 * 10 ** (db / 20)


@pytest.mark.parametrize(
    "db, flagged",
    [(-20, False), (-26.5, False), (-30, True), (-60, True)],
)
def test_silent_glyph_thresholds_sit_where_they_were_measured(stem_of, db, flagged):
    """-26.5 dB: peak is under -25 but the median is not under -28; both are needed."""
    fine = _elided_song()
    stem = stem_of(
        _stem_amps((0.0, 1.25, 0.5), (1.25, 2.9, _db_amp(db)), (3.0, 3.5, 0.5))
    )
    found = ga.silent_glyph(stem).find(fine, fine)
    assert (0 in found) is flagged


def test_silent_glyph_window_is_clamped_to_the_next_glyph_and_to_the_cap(stem_of):
    fine = _timed_words(
        ("カ", [("カ", 1.0)]), ("サ", [("サ", 1.01)]), ("ス", [("ス", 5.0)])
    )
    # カ's window is floored at 0.06 s though サ starts 10 ms on: sound at 1.05
    # is inside it, so カ is not silent
    stem = stem_of(_stem_amps((0.0, 0.9, 0.5), (1.04, 1.07, 0.5), (5.0, 5.5, 0.5)))
    assert 0 not in ga.silent_glyph(stem).find(fine, fine)
    # ス's window is capped at 0.4 s: singing resuming 0.45 s later is out of it
    stem = stem_of(_stem_amps((0.0, 0.9, 0.5), (5.45, 6.0, 0.5)))
    assert 2 in ga.silent_glyph(stem).find(fine, fine)


def test_silent_glyph_geminate_closure_in_either_script_is_not_judged(stem_of):
    fine = _timed_words(("きって", [("き", 1.0), ("っ", 1.15), ("て", 1.3)]))
    stem = stem_of(_stem((1.0, 1.15), (1.3, 1.5)))
    assert ga.silent_glyph(stem).find(fine, fine) == {}


def test_silent_glyph_judges_only_wide_scripts(stem_of):
    fine = _timed_words(("cat", [("c", 1.0), ("a", 1.1), ("t", 1.2)]))
    stem = stem_of(_stem((1.0, 1.15)))
    assert ga.silent_glyph(stem).find(fine, fine) == {}


def test_silent_glyph_survives_a_glyph_before_zero(stem_of):
    fine = _timed_words(("カ", [("カ", -0.05)]), ("サ", [("サ", 3.0)]))
    stem = stem_of(_stem((3.0, 4.0)))
    assert 0 in ga.silent_glyph(stem).find(fine, fine)  # silent, and no crash


def test_silent_glyph_reads_the_stem_once(monkeypatch, stem_of):
    stem = stem_of(_stem((1.0, 1.25), (3.0, 3.5)))
    reads = []
    real = ga._read_stem
    monkeypatch.setattr(ga, "_read_stem", lambda v: reads.append(v) or real(v))
    det, fine = ga.silent_glyph(stem), _elided_song()
    det.find(fine, fine)
    det.find(fine, fine)
    assert len(reads) == 1


@pytest.mark.parametrize("kw", [{"frame_s": 0}, {"window_s": (0.4, 0.06)}])
def test_silent_glyph_refuses_nonsense_config(kw):
    with pytest.raises(ValueError):
        ga.silent_glyph("x", **kw)


def test_silent_glyph_window_never_runs_to_a_distant_next_glyph(stem_of):
    """カ's window ends 0.4 s on, not at ス 4 s later; sound at 1.6 s is outside it."""
    fine = _timed_words(("カ", [("カ", 1.0)]), ("ス", [("ス", 5.0)]))
    stem = stem_of(_stem_amps((0.0, 0.9, 0.5), (1.6, 2.0, 0.5), (5.0, 5.5, 0.5)))
    assert 0 in ga.silent_glyph(stem).find(fine, fine)


def test_silent_glyph_a_loud_blip_in_a_quiet_window_is_not_silence(stem_of):
    """Peak -20 dB (above -25) over an otherwise -40 dB window: an attack, not a gap."""
    fine = _elided_song()
    stem = stem_of(
        _stem_amps(
            (0.0, 1.25, 0.5),
            (1.25, 2.9, _db_amp(-40)),
            (1.35, 1.40, _db_amp(-20)),
            (3.0, 3.5, 0.5),
        )
    )
    assert ga.silent_glyph(stem).find(fine, fine) == {}


# ---------------------------------------------------------------------------
# the per-glyph 'mute' remedy and Glyph.sung (muvid#175)
# ---------------------------------------------------------------------------


def _glyph_dicts(d):
    return [
        g
        for s in d["sections"]
        for l in s["lines"]
        for w in l["words"]
        for g in w.get("glyphs", ())
    ]


def test_mute_marks_only_the_silent_glyph_and_keeps_the_word(stem_of):
    fine = _elided_song()
    stem = stem_of(_stem((1.0, 1.25), (3.0, 3.5)))
    out, records = ga.reconcile(
        fine, fine, detectors=(ga.silent_glyph(stem, remedy="mute"),)
    )
    word = next(iter(out.words()))
    assert word.text == "ハッカー" and word.start == next(iter(fine.words())).start
    assert [(g.text, g.sung) for g in word.glyphs] == [
        ("ハ", True),
        ("ッ", True),
        ("カ", False),
        ("ー", True),
    ]
    assert [g.start for g in word.glyphs] == [1.0, 1.15, 1.3, 1.4]  # times untouched
    assert [g.sung for g in list(out.words())[1].glyphs] == [True, True]
    assert records[0]["remedy"] == "mute" and records[0]["glyphs"] == [2]


def test_mute_loses_to_replace(stem_of):
    fine = _elided_song()
    stem = stem_of(_stem((1.0, 1.25), (3.0, 3.5)))
    always = ga.Detector(name="always", find=lambda f, c: {0: "x"}, remedy="replace")
    out, records = ga.reconcile(
        fine, fine, detectors=(ga.silent_glyph(stem, remedy="mute"), always)
    )
    assert records[0]["remedy"] == "replace"
    assert all(g.sung for g in next(iter(out.words())).glyphs)


def test_a_mute_detector_must_say_which_glyphs():
    with pytest.raises(ValueError, match="glyphs="):
        ga.Detector(name="m", find=lambda f, c: {}, remedy="mute")


def test_sung_false_round_trips_and_is_omitted_when_true(stem_of):
    fine = _elided_song()
    assert all("sung" not in g for g in _glyph_dicts(fine.to_dict()))
    stem = stem_of(_stem((1.0, 1.25), (3.0, 3.5)))
    muted, _ = ga.reconcile(
        fine, fine, detectors=(ga.silent_glyph(stem, remedy="mute"),)
    )
    d = muted.to_dict()
    assert [g["text"] for g in _glyph_dicts(d) if g.get("sung") is False] == ["カ"]
    assert from_dict(d) == muted


def _two_words_two_silences():
    # word 0: カ (1.3) silent; word 1: two silent glyphs, ス (3.0) and ト (3.2) ; word 2 sung
    return _timed_words(
        ("ハッカー", [("ハ", 1.0), ("ッ", 1.15), ("カ", 1.3), ("ー", 1.4)]),
        ("スト", [("ス", 3.0), ("ト", 3.2)]),
        ("サン", [("サ", 5.0), ("ン", 5.2)]),
    )


def test_mute_handles_several_words_and_several_glyphs_per_word(stem_of):
    fine = _two_words_two_silences()
    stem = stem_of(_stem((1.0, 1.25), (5.0, 5.5), (7.0, 8.0)))
    out, records = ga.reconcile(
        fine, fine, detectors=(ga.silent_glyph(stem, remedy="mute"),)
    )
    ws = list(out.words())
    assert [[g.sung for g in w.glyphs] for w in ws] == [
        [True, True, False, True],
        [False, False],
        [True, True],
    ]
    assert [(r["index"], r["glyphs"], r["used"]) for r in records] == [
        (0, [2], 1.0),
        (1, [0, 1], 3.0),
    ]


def test_drop_beats_mute_on_the_same_word(stem_of):
    fine = _elided_song()
    stem = stem_of(_stem((1.0, 1.25), (3.0, 3.5)))
    dropper = ga.Detector(name="d", find=lambda f, c: {0: "x"}, remedy="drop")
    out, records = ga.reconcile(
        fine, fine, detectors=(ga.silent_glyph(stem, remedy="mute"), dropper)
    )
    assert [w.text for w in out.words()] == ["サン"]
    assert records[0]["remedy"] == "drop"
    assert records[0]["flagged_by"] == ["silent_glyph", "d"]


@pytest.mark.parametrize("named", [{}, {0: {99}}])
def test_a_mute_detector_that_disagrees_with_its_own_find_is_refused(named):
    fine = _elided_song()
    bad = ga.Detector(
        name="bad", find=lambda f, c: {0: "x"}, remedy="mute", glyphs=lambda f, c: named
    )
    with pytest.raises(ValueError, match="flagged word 0"):
        ga.reconcile(fine, fine, detectors=(bad,))


def test_a_muted_word_still_counts_toward_the_bias_a_replaced_word_gets(stem_of):
    """Muting keeps a word's time, so it is evidence of the vendor's offset."""
    fine = _elided_song()
    # coarse is fine shifted -0.2 s: bias = fine - coarse = +0.2
    from dataclasses import replace as _r

    def shift(tt, dt):
        return _r(
            tt,
            sections=tuple(
                _r(
                    s,
                    lines=tuple(
                        _r(
                            l,
                            words=tuple(
                                _r(w, start=w.start + dt, end=w.end + dt, glyphs=())
                                for w in l.words
                            ),
                        )
                        for l in s.lines
                    ),
                )
                for s in tt.sections
            ),
        )

    coarse = shift(fine, -0.2)
    stem = stem_of(_stem((1.0, 1.25), (3.0, 3.5)))
    replace_second = ga.Detector(name="r", find=lambda f, c: {1: "x"}, remedy="replace")
    out, _ = ga.reconcile(
        fine,
        coarse,
        detectors=(ga.silent_glyph(stem, remedy="mute"), replace_second),
    )
    assert list(out.words())[1].start == pytest.approx(3.0)  # coarse 2.8 + bias 0.2


def test_glyph_rows_always_carry_sung(stem_of):
    fine = _elided_song()
    stem = stem_of(_stem((1.0, 1.25), (3.0, 3.5)))
    out, _ = ga.reconcile(fine, fine, detectors=(ga.silent_glyph(stem, remedy="mute"),))
    rows = list(ga.glyph_rows(out))
    assert all("sung" in r for r in rows)
    assert [r["text"] for r in rows if not r["sung"]] == ["カ"]


# ---------------------------------------------------------------------------
# with_spans: where a glyph's sound runs (muvid#149)
# ---------------------------------------------------------------------------


def _spans(tt):
    return [
        (
            g.text,
            g.span and (round(g.span.start, 2), round(g.span.end, 2)),
            g.span and g.span.cut,
        )
        for g in (g for w in tt.words() for g in w.glyphs)
    ]


def test_spans_without_a_stem_run_to_the_next_onset_capped():
    fine = _timed_words(
        ("ハーカッ", [("ハ", 1.0), ("ー", 1.2), ("カ", 1.5), ("ッ", 1.8)]),
        ("トス", [("ト", 2.0), ("ス", 3.0)]),
    )
    got = _spans(ga.with_spans(fine))
    assert got == [
        ("ハ", (1.0, 1.5), "next"),  # ー extends it, it is no boundary
        ("ー", None, None),
        ("カ", (1.5, 1.8), "next"),  # ッ is silence: it ends カ
        ("ッ", None, None),
        ("ト", (2.0, 2.6), "cap"),  # the next onset is 1 s away: capped at 0.6 s
        ("ス", (3.0, 3.6), "cap"),
    ]


def test_spans_skip_unsung_and_unplaced_glyphs():
    from dataclasses import replace

    fine = _timed_words(("カスタ", [("カ", 1.0), ("ス", 1.2), ("タ", 1.4)]))
    w = next(iter(fine.words()))
    muted = replace(
        w, glyphs=(w.glyphs[0], replace(w.glyphs[1], sung=False), w.glyphs[2])
    )
    tt = ga._rebuilt(fine, [replace(next(iter(fine.lines())), words=(muted,))])
    got = _spans(ga.with_spans(tt))
    assert got[0] == ("カ", (1.0, 1.4), "next")  # the muted ス is not a boundary
    assert got[1] == ("ス", None, None)


def _two_glyphs(second_at):
    return _timed_words(("カス", [("カ", 1.0), ("ス", second_at)]))


def test_spans_cut_at_a_silence(stem_of):
    stem = stem_of(_stem((1.0, 1.28), (1.34, 1.6), (3.0, 4.0)))
    got = _spans(ga.with_spans(_two_glyphs(1.32), vocals=stem))
    (_, ka, kcut), (_, su, scut) = got
    assert kcut == "silence" and ka[0] == 1.0 and ka[1] == pytest.approx(1.28, abs=0.02)
    assert su[0] == pytest.approx(1.34, abs=0.02)  # the next starts where sound returns
    assert ka[1] <= su[0]


def test_spans_cut_at_the_flat_bottom_of_a_valley(stem_of):
    # a -12 dB dip (not silent) between two syllables, from 1.30 to 1.40
    stem = stem_of(
        _stem_amps(
            (1.0, 1.3, 0.5), (1.3, 1.4, _db_amp(-12)), (1.4, 2.0, 0.5), (3.0, 4.0, 0.5)
        )
    )
    got = _spans(ga.with_spans(_two_glyphs(1.38), vocals=stem))
    assert got[0][2] == "valley" and got[0][1][1] == pytest.approx(1.30, abs=0.02)
    assert got[1][1][0] == got[0][1][1]  # one cut, shared


def test_spans_flag_a_legato_boundary_and_keep_the_onset(stem_of):
    stem = stem_of(_stem((1.0, 2.0), (3.0, 4.0)))
    got = _spans(ga.with_spans(_two_glyphs(1.5), vocals=stem))
    assert got[0] == ("カ", (1.0, 1.5), "legato")
    assert got[1][1][0] == 1.5


def test_spans_are_idempotent_never_overlap_and_round_trip(stem_of):
    stem = stem_of(_stem((1.0, 1.28), (1.34, 1.6), (3.0, 4.0)))
    once = ga.with_spans(_two_glyphs(1.32), vocals=stem)
    assert ga.with_spans(once, vocals=stem) == once
    assert from_dict(once.to_dict()) == once
    gl = [g for w in once.words() for g in w.glyphs]
    assert gl[0].span.end <= gl[1].span.start
    # absent spans are absent from the file
    assert all("span" not in g for g in _glyph_dicts(_two_glyphs(1.32).to_dict()))


def test_spans_survive_a_digitally_silent_stem(stem_of):
    stem = stem_of(_stem())
    got = _spans(ga.with_spans(_two_glyphs(1.5), vocals=stem))
    assert got[0][2] == "legato"


def test_mute_clears_every_span_since_neighbours_depend_on_it(stem_of):
    fine = ga.with_spans(_elided_song())
    stem = stem_of(_stem((1.0, 1.25), (3.0, 3.5)))
    out, _ = ga.reconcile(fine, fine, detectors=(ga.silent_glyph(stem, remedy="mute"),))
    ka = [g for w in out.words() for g in w.glyphs if g.text == "カ"][0]
    assert ka.sung is False
    # ハ's span ran to カ's onset, which is no longer a boundary: none is stale
    assert all(g.span is None for w in out.words() for g in w.glyphs)
    # reconcile changing nothing keeps them (and the same object)
    same, recs = ga.reconcile(fine, fine, detectors=())
    assert recs == [] and same == fine


def test_repair_spills_clears_every_span():
    recs = [
        {"text": "ハット", "start": 1.0, "end": 2.0, "line_end": True},
        {"text": "トマト", "start": 2.0, "end": 3.0, "line_end": True},
    ]
    tt = _place(
        _with_glyphs(from_word_records(recs, duration=4.0)),
        {0: [1.0, 1.4, 2.0], 1: 2.0},  # ハット's ト sits on トマト's ト
    )
    spanned = ga.with_spans(tt)
    assert any(g.span for w in spanned.words() for g in w.glyphs)
    fixed, records = ga.repair_spills(spanned, None)
    assert records
    assert all(g.span is None for w in fixed.words() for g in w.glyphs)


def test_with_spans_refuses_nonsense_config():
    with pytest.raises(ValueError):
        ga.with_spans(_elided_song(), max_span_s=0)


def test_glyphs_cli_spans_flag(tmp_path, monkeypatch, capsys):
    got = _run_glyphs_cli(tmp_path, monkeypatch, capsys, spans=True)
    gl = _glyph_dicts(got["timing"])
    assert gl and all("span" in g for g in gl if g["text"] not in "ーッっ")
    assert set(got["report"]["spans"]) & {"silence", "valley", "legato"}
    assert sum(got["report"]["spans"].values()) == sum("span" in g for g in gl)
    plain = _run_glyphs_cli(tmp_path, monkeypatch, capsys)
    assert not any("span" in g for g in _glyph_dicts(plain["timing"]))
    assert "spans" not in plain["report"]


def test_a_silence_over_the_whole_search_never_makes_a_negative_span(stem_of):
    """B1/B3 of the #149 review: sound 1.0-1.2 then nothing until 2.4."""
    stem = stem_of(_stem((1.0, 1.2), (2.4, 3.0)))
    fine = _timed_words(("カスタ", [("カ", 1.0), ("ス", 1.3), ("タ", 2.5)]))
    got = _spans(ga.with_spans(fine, vocals=stem))
    assert got == [
        ("カ", (1.0, 1.2), "silence"),  # ends where the sound died, before the window
        ("ス", (1.3, 1.9), "cap"),  # sound never returned: it starts at its onset
        ("タ", (2.5, 3.1), "cap"),
    ]
    # a silence that began well before the search window still ends カ there
    got = _spans(
        ga.with_spans(
            _two_glyphs(1.5), vocals=stem_of(_stem((1.0, 1.2), (1.5, 2.0), (4.0, 6.0)))
        )
    )
    assert got[0] == ("カ", (1.0, 1.2), "silence") and got[1][1][0] == 1.5


def test_a_silence_before_the_onset_is_searched_further_back_than_after(stem_of):
    # the gap sits 0.10-0.14 s before ス: inside search_s[0], outside search_s[1]
    stem = stem_of(_stem((1.0, 1.36), (1.40, 2.0)))
    got = _spans(ga.with_spans(_two_glyphs(1.5), vocals=stem))
    assert got[0] == ("カ", (1.0, 1.36), "silence")
    assert got[1][1][0] == pytest.approx(1.40)


@pytest.mark.parametrize("gap_db, cut", [(-30, "valley"), (-50, "silence")])
def test_span_silence_threshold_sits_at_minus_40(stem_of, gap_db, cut):
    stem = stem_of(
        _stem_amps((1.0, 1.3, 0.5), (1.3, 1.4, _db_amp(gap_db)), (1.4, 2.0, 0.5))
    )
    assert _spans(ga.with_spans(_two_glyphs(1.38), vocals=stem))[0][2] == cut


@pytest.mark.parametrize("dip_db, cut", [(-5, "legato"), (-12, "valley")])
def test_span_valley_threshold_sits_at_8_db(stem_of, dip_db, cut):
    stem = stem_of(
        _stem_amps((1.0, 1.3, 0.5), (1.3, 1.4, _db_amp(dip_db)), (1.4, 2.0, 0.5))
    )
    assert _spans(ga.with_spans(_two_glyphs(1.38), vocals=stem))[0][2] == cut


def test_spans_skip_a_glyph_with_no_start_and_punctuation():
    from dataclasses import replace

    fine = _timed_words(
        ("カス、タ", [("カ", 1.0), ("ス", 1.2), ("、", 1.3), ("タ", 1.4)])
    )
    w = next(iter(fine.words()))
    nan = replace(w.glyphs[1], start=float("nan"))
    tt = ga._rebuilt(
        fine,
        [
            replace(
                next(iter(fine.lines())),
                words=(replace(w, glyphs=(w.glyphs[0], nan, *w.glyphs[2:])),),
            )
        ],
    )
    assert _spans(ga.with_spans(tt)) == [
        ("カ", (1.0, 1.4), "next"),  # neither the unplaced ス nor 、 is a boundary
        ("ス", None, None),
        ("、", None, None),
        ("タ", (1.4, 2.0), "cap"),
    ]


def test_a_sokuon_boundary_is_cut_from_the_stem_too(stem_of):
    fine = _timed_words(("カップ", [("カ", 1.0), ("ッ", 1.3), ("プ", 1.5)]))
    got = _spans(ga.with_spans(fine, vocals=stem_of(_stem((1.0, 1.25), (1.5, 2.0)))))
    assert got[0] == ("カ", (1.0, 1.25), "silence") and got[1] == ("ッ", None, None)
    assert got[2][1][0] == 1.5  # a sokuon moves no span start
    # no cut in the stem: the sokuon's onset, as without one
    got = _spans(ga.with_spans(fine, vocals=stem_of(_stem((1.0, 2.0)))))
    assert got[0] == ("カ", (1.0, 1.3), "next")


def test_span_property_never_negative_overlapping_or_over_the_cap(stem_of):
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(149)
    frame = ga.SPAN_FRAME_S
    for _ in range(60):
        starts = np.sort(rng.uniform(0.2, 3.5, rng.integers(2, 12)))
        segs = []
        for a in np.sort(rng.uniform(0, 4, rng.integers(0, 8))):
            segs.append(
                (a, a + rng.uniform(0.02, 0.6), rng.choice([0.5, 0.15, 0.05, 0.005]))
            )
        # some of the glyphs are sokuon, which carry no span but sit between two
        chars = rng.choice(["カ", "カ", "ッ"], len(starts))
        max_s = float(rng.choice([0.05, 0.2, ga.GLYPH_SPAN_MAX_S]))
        fine = _timed_words(
            (
                "".join(chars),
                [(str(c), float(t)) for c, t in zip(chars, starts)],
            )
        )
        out = ga.with_spans(
            fine, vocals=stem_of(_stem_amps(*segs, duration=4.5)), max_span_s=max_s
        )
        gl = [g for w in out.words() for g in w.glyphs if g.span]
        for g in gl:
            assert g.span.start <= g.span.end
            assert g.span.end <= g.start + max_s + frame
        for a, b in zip(gl, gl[1:]):
            assert a.span.end <= b.span.start


def test_glyph_rows_carry_span_and_cut():
    rows = list(ga.glyph_rows(ga.with_spans(_two_glyphs(1.3))))
    assert [(r["span"], r["cut"]) for r in rows] == [
        ((1.0, 1.3), "next"),
        ((1.3, 1.9), "cap"),
    ]
    assert list(ga.glyph_rows(_two_glyphs(1.3)))[0]["cut"] is None


@pytest.mark.parametrize(
    "span, cut",
    [([2.0, 1.0], "next"), ([1.0, 2.0], "bogus"), ("x", "next"), ([1.0, 2.0], None)],
)
def test_from_dict_refuses_an_invalid_span(span, cut):
    d = _two_glyphs(1.3).to_dict()
    _glyph_dicts(d)[0].update(span=span, cut=cut)
    with pytest.raises(ValueError, match="span"):
        from_dict(d)


def test_span_is_a_checked_value():
    from muvid.lyricvid.timed_text import Span

    with pytest.raises(ValueError):
        Span(2.0, 1.0, "next")
    with pytest.raises(ValueError):
        Span(1.0, float("nan"), "next")


def test_a_sokuon_between_two_glyphs_never_makes_their_spans_overlap(stem_of):
    """Review of #149: カ's silence cut can land past ッ, onto プ's own onset."""
    fine = _timed_words(("カップ", [("カ", 1.0), ("ッ", 1.3), ("プ", 1.33)]))
    got = _spans(
        ga.with_spans(fine, vocals=stem_of(_stem((1.0, 1.35), (1.6, 2.0), (3.0, 4.0))))
    )
    assert got[0][1][1] <= got[2][1][0]


def test_a_next_onset_just_inside_the_cap_is_the_boundary_not_the_cap(stem_of):
    stem = stem_of(_stem((1.0, 2.0), (3.0, 4.0)))
    at_cap = _timed_words(("カス", [("カ", 1.0), ("ス", 1.6)]))
    assert _spans(ga.with_spans(at_cap, vocals=stem))[0][2] == "cap"  # >= the cap
    inside = _timed_words(("カス", [("カ", 1.0), ("ス", 1.57)]))
    assert _spans(ga.with_spans(inside, vocals=stem))[0][2] == "legato"
    # a tiny max_span_s caps everything, and never goes negative or raises
    got = _spans(ga.with_spans(inside, vocals=stem, max_span_s=0.05))
    assert got[0] == ("カ", (1.0, 1.05), "cap")


@pytest.mark.parametrize("gap_db, cut", [(-38, "valley"), (-42, "silence")])
def test_span_silence_threshold_is_tight(stem_of, gap_db, cut):
    stem = stem_of(
        _stem_amps((1.0, 1.3, 0.5), (1.3, 1.4, _db_amp(gap_db)), (1.4, 2.0, 0.5))
    )
    assert _spans(ga.with_spans(_two_glyphs(1.38), vocals=stem))[0][2] == cut


@pytest.mark.parametrize("dip_db, cut", [(-7, "legato"), (-9, "valley")])
def test_span_valley_threshold_is_tight(stem_of, dip_db, cut):
    stem = stem_of(
        _stem_amps((1.0, 1.3, 0.5), (1.3, 1.4, _db_amp(dip_db)), (1.4, 2.0, 0.5))
    )
    assert _spans(ga.with_spans(_two_glyphs(1.38), vocals=stem))[0][2] == cut


def test_a_valley_must_be_deep_under_both_neighbours(stem_of):
    """-12 dB under the left syllable but only -4 under the right one: no valley."""
    stem = stem_of(
        _stem_amps(
            (1.0, 1.3, 0.5),
            (1.3, 1.4, _db_amp(-12)),
            (1.4, 2.0, _db_amp(-8)),
            (3.0, 4.0, 0.5),
        )
    )
    assert _spans(ga.with_spans(_two_glyphs(1.38), vocals=stem))[0][2] == "legato"


def test_timing_overrides_clear_the_spans_they_invalidate(stem_of, onsets_at):
    fine, coarse = _spilled_song()
    onsets_at(*_SPILL_ONSETS)
    stem = stem_of(_stem((0.0, 15.0), duration=15.0))
    out, records = ga.reconcile(fine, coarse, detectors=ga.stem_detectors(stem))
    out = ga.with_spans(out)
    assert any(g.span for w in out.words() for g in w.glyphs)
    got, _ = ga.apply_timing_overrides(out, fine, records, overrides={"1": "fine"})
    assert all(g.span is None for w in got.words() for g in w.glyphs)


# ---------------------------------------------------------------------------
# consuming Glyph.sung (muvid#177)
# ---------------------------------------------------------------------------


def _unsung_second_glyph():
    from dataclasses import replace

    tt = _with_glyphs(_tt())
    w = next(iter(tt.words()))
    gs = list(w.glyphs)
    gs[1] = replace(gs[1], sung=False, start=gs[1].start + 0.3, end=gs[1].end + 0.3)
    return tt, w.text, w.glyphs[0].start, tuple(gs)


def test_glyph_pages_light_an_unsung_glyph_with_its_predecessor():
    from dataclasses import replace

    tt, text, first_start, gs = _unsung_second_glyph()
    first = next(iter(tt.words()))
    tt = replace(
        tt,
        sections=tuple(
            replace(
                s,
                lines=tuple(
                    replace(
                        l,
                        words=tuple(
                            replace(w, glyphs=gs) if w is first else w for w in l.words
                        ),
                    )
                    for l in s.lines
                ),
            )
            for s in tt.sections
        ),
    )
    sc = compile_scene(
        S.coerce(_treatment())[0], tt, canvas=Canvas(width=1920, height=1080)
    )
    ink = {c.text: c for c in sc.cues if c.layer == 1}
    assert text[1] in ink  # still lit, so the written word completes
    assert ink[text[1]].t_in == pytest.approx(ink[text[0]].t_in)


def test_onset_report_ignores_unsung_glyphs():
    tt, _, _, gs = _unsung_second_glyph()
    from dataclasses import replace

    first = next(iter(tt.words()))
    muted = replace(
        tt,
        sections=tuple(
            replace(
                s,
                lines=tuple(
                    replace(
                        l,
                        words=tuple(
                            replace(w, glyphs=gs) if w is first else w for w in l.words
                        ),
                    )
                    for l in s.lines
                ),
            )
            for s in tt.sections
        ),
    )
    assert len(ga._glyph_starts(muted)) == len(ga._glyph_starts(tt)) - 1


def test_from_dict_refuses_a_string_for_a_boolean():
    d = _with_glyphs(_tt()).to_dict()
    d["sections"][0]["lines"][0]["words"][0]["glyphs"][0]["sung"] = "false"
    with pytest.raises(ValueError, match="'sung' must be true or false"):
        from_dict(d)


def test_stem_detectors_run_silent_glyph_only_when_asked(stem_of):
    stem = stem_of(_stem((1.0, 1.25), (3.0, 3.5)))
    assert "silent_glyph" not in [d.name for d in ga.stem_detectors(stem)]
    dets = ga.stem_detectors(stem, silent_glyph_remedy="mute")
    sg = [d for d in dets if d.name == "silent_glyph"]
    assert [d.remedy for d in sg] == ["mute"]
    assert dets[-1].name == "disordered"  # still judges the result of the rest


def test_an_unsung_glyph_with_a_stray_time_does_not_move_a_page_turn():
    from dataclasses import replace

    tt = _with_glyphs(_tt())
    # the LAST glyph of the first word is unsung, with a time inside page 2
    tt = ga._map_glyphs(
        tt,
        lambda i, g: replace(g, sung=False, start=7.0, end=7.1) if i == 1 else g,
    )
    base = compile_scene(
        S.coerce(_treatment(lines_on_screen=1))[0],
        _with_glyphs(_tt()),
        canvas=Canvas(width=1920, height=1080),
    )
    sc = compile_scene(
        S.coerce(_treatment(lines_on_screen=1))[0],
        tt,
        canvas=Canvas(width=1920, height=1080),
    )
    turns = lambda s: sorted({round(c.t_out, 3) for c in s.cues if c.layer == 1})
    assert turns(sc) == turns(base)


@pytest.mark.parametrize(
    "value, msg",
    [
        ('{"x": "fien"}', "not a line index"),  # the issue's own case
        ('{"x": "fin", "y": "fine"}', "not a line index"),
        ('{"title": "x", "timing_override": {"1": "fine"}}', "did you mean"),
        ('{"title": "x", "Timing-Overrides": {"1": "fine"}}', "did you mean"),
        ('{"title": "x", "timingoverides": {"1": "fine"}}', "did you mean"),
    ],
)
def test_a_misspelt_overrides_key_or_value_is_refused_muvid_162(value, msg):
    """muvid#162: with no song-spec schema, a near-miss of the key or of every value
    was read as a spec recording none, and nothing was applied in silence."""
    from muvid.lyricvid.__main__ import _timing_overrides_arg

    with pytest.raises((SystemExit, ValueError), match=msg):
        ga.check_timing_overrides(_timing_overrides_arg(value), 4)


@pytest.mark.parametrize(
    "value",
    [
        '{"title": "x", "lyrics": "y"}',
        '{"title": "Fine day", "lyrics": "one"}',  # "one" is two edits from "fine"
        '{"title": "x", "timings": {}}',  # far from the key
    ],
)
def test_a_spec_recording_none_is_said_not_silent_muvid_162(value, capsys):
    from muvid.lyricvid.__main__ import _timing_overrides_arg

    assert _timing_overrides_arg(value) == {}
    err = capsys.readouterr().err
    assert "recording no timing_overrides" in err and "title" in err


def test_no_flag_and_a_recorded_none_stay_silent(capsys):
    """The default path is unaffected: no flag, an empty object, or a spec that says
    `timing_overrides: null` apply nothing and say nothing."""
    from muvid.lyricvid.__main__ import _timing_overrides_arg

    for value in ("", "{}", '{"title": "x", "timing_overrides": null}'):
        assert _timing_overrides_arg(value) == {}
    assert capsys.readouterr().err == ""
