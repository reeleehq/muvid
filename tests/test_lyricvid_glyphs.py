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
        ts = at if isinstance(at, list) else [at + 0.1 * i for i in range(len(w.glyphs))]
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


def _run_glyphs_cli(tmp_path, monkeypatch, capsys, **flags):
    """The ``glyphs`` verb end to end, with the model and the stem faked."""
    import json

    import numpy as np

    from muvid.lyricvid.__main__ import glyphs

    fine, coarse = _spilled_song()
    monkeypatch.setattr(ga, "_mms_weights", lambda **kw: tmp_path)
    monkeypatch.setattr(ga, "refine_glyphs", lambda tt, stem, **kw: fine)
    monkeypatch.setattr(
        ga, "stem_onsets", lambda vocals: np.array(_SPILL_ONSETS, dtype=float)
    )
    y = _stem((0.0, 15.0), duration=15.0)
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

    got = _run_glyphs_cli(tmp_path, monkeypatch, capsys)
    _GLYPHS_GOLDEN.write_text(
        json.dumps(got, ensure_ascii=False, indent=1) + "\n", "utf-8"
    )


def test_glyphs_default_output_is_pinned(tmp_path, monkeypatch, capsys):
    """The glyphs CLI with no new flags writes exactly what it wrote before
    muvid#155: a live pipeline renders from this file every day, so the
    spill repair and the overrides may only ever be opted into."""
    import json

    pytest.importorskip("numpy")
    got = _run_glyphs_cli(tmp_path, monkeypatch, capsys)
    assert got == json.loads(_GLYPHS_GOLDEN.read_text("utf-8"))


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
    assert basu.words[0].glyphs[0] == list(out.lines())[1].words[0].glyphs[0]
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
    assert list(fixed.words())[0].glyphs[-1].start == pytest.approx((lo + 2.0) / 2)
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

    got, recs = ga.apply_timing_overrides(out, fine, records, {"1": "fine"})

    assert list(got.lines())[1] == list(fine.lines())[1]
    assert list(got.lines())[0] == list(out.lines())[0]  # not overridden
    assert [(r["index"], r["why"], r["remedy"]) for r in recs] == [
        (1, "override", "fine")
    ]
    assert "disordered" in recs[0]["detail"]
    # ints work too, and no overrides is the identity
    assert ga.apply_timing_overrides(out, fine, records, {1: "fine"})[0] == got
    assert ga.apply_timing_overrides(out, fine, records, None) == (out, [])
    assert ga.apply_timing_overrides(out, fine, records, {}) == (out, [])


def test_an_override_restores_a_line_unsung_dropped(stem_of, onsets_at):
    """A person said it was sung, so it comes back, in its place."""
    fine, coarse = _intro_sung_once()
    onsets_at(1.0, 1.3, 1.6, 5.0, 5.1)
    stem = stem_of(_stem((0.9, 2.0), (5.0, 5.6), duration=8.0))
    out, records = ga.reconcile(fine, coarse, detectors=ga.stem_detectors(stem))
    assert len(list(out.lines())) == 2

    got, recs = ga.apply_timing_overrides(out, fine, records, {"1": "fine"})

    assert list(got.lines()) == [list(out.lines())[0], *list(fine.lines())[1:2], list(out.lines())[1]]
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
        ga.apply_timing_overrides(fine, fine, [], overrides)


def test_overrides_refuse_a_reconciled_timing_from_elsewhere():
    fine, _ = _four_lines()
    other, _ = _intro_sung_once()
    with pytest.raises(ValueError, match="does not come from"):
        ga.apply_timing_overrides(other, fine, [], {"0": "fine"})


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
    pinned = json.loads(_GLYPHS_GOLDEN.read_text("utf-8"))
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
