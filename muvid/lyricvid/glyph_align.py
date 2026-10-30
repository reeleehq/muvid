"""Per-glyph timing: when was each written character sung? (muvid#142)

A word-level alignment says when ``バカンス`` was sung; a learner watching
katakana needs to see ``バ``, ``カ``, ``ン`` and ``ス`` light up one by one, each
at the moment its sound starts. This module refines any word-timed
:class:`~muvid.lyricvid.timed_text.TimedText` (from Suno's own timestamps, an
enhanced LRC, a whisper match...) into one with measured
:attr:`~muvid.lyricvid.timed_text.Word.glyphs`.

How: each lyric line is cut out of the separated vocal stem, widened by
``margin_s`` on both sides, and force-aligned with a CTC model (torchaudio's
``MMS_FA``, trained on romanised speech in 1,000+ languages) against the line's
romanisation, one romaji chunk per glyph, with a ``<star>`` token either side
to absorb breaths and ad-libs. Aligning per line, inside the coarse word
window, is what keeps one mis-sung line from dragging every later one.

Romanisation is a strategy slot (``romanize=``): :func:`romanize_kana` covers
katakana and hiragana, including ``ー`` (lengthens the previous vowel), ``ッ``
(doubles the next consonant) and the small ``ャュョァィゥェォ`` combinations.
Another script needs another romaniser, nothing else.

Verification lives here too, because a timing nobody checked is a guess:
:func:`onset_report` measures how close glyph starts sit to acoustic onsets in
the vocal stem, against a random-jitter baseline, and :func:`word_agreement`
lists the words where two timings disagree. :func:`reconcile` then acts on
what a list of :class:`Detector` s distrusts — each names words and a remedy
(``replace``: fall back to the vendor window; ``drop``: it was never sung).
:func:`unsung` drops a line the aligner could not place over which the vocal
stem is silent (muvid#144); :func:`silent_glyph` flags a word with one silent
sounded glyph inside a sung line (muvid#156).

Licensing — read before shipping anything: the ``MMS_FA`` weights are
**CC-BY-NC-4.0** and htdemucs (vocal separation) is CC-BY-NC too. So this is an
opt-in extra (``muvid[lyricvid-glyphs]``), never a default, never on the prod
connector, and it never downloads weights unless the caller says
``allow_download=True`` (or ``MUVID_ALLOW_WEIGHT_DOWNLOAD=1``).
"""

from __future__ import annotations

import math
import os
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from collections.abc import Collection
from typing import Any, Callable, Iterable, Mapping, Sequence

from muvid.lyricvid.timed_text import Glyph, Line, Section, Span, TimedText, Word

#: The sokuon, in both kana scripts: the closure of a geminate, silence by
#: definition.
_SOKUON = "ッっ"
#: Glyphs that carry no sound of their own: a lengthening mark and a sokuon.
_SOUNDLESS_GLYPHS = "ー" + _SOKUON


def _has_sound(g: Glyph) -> bool:
    """A glyph that makes a sound of its own: a letter or kana (Unicode
    category ``L*``), not ``ー``/``ッ``, and not punctuation, a digit or a space."""
    return (
        bool(g.text)
        and g.text not in _SOUNDLESS_GLYPHS
        and unicodedata.category(g.text[0]).startswith("L")
    )


#: Seconds of audio kept either side of a line's coarse window. Vendor word
#: times run late and miss leading consonants; too wide a window lets the
#: aligner wander into the neighbouring line.
MARGIN_S = float(os.environ.get("MUVID_GLYPH_MARGIN_S", "0.5"))
#: Onset tolerance for :func:`onset_report`.
ONSET_TOL_S = 0.08
#: Two timings of a word disagree when their starts differ by more than this.
DISAGREE_S = 0.3
#: Two sounded glyphs whose STARTS are closer than this were squeezed together
#: by the aligner, not sung (a mora takes ~0.1 s or more). Start-to-start, not
#: span length: CTC spans are spiky, so a perfectly sung ``ン`` can be 20 ms.
MIN_GLYPH_S = 0.04

Romanizer = Callable[[str], list[tuple[str, str]]]

# --------------------------------------------------------------------------
# romanisation (a strategy slot; kana is the default)
# --------------------------------------------------------------------------

_KANA_ROWS = {
    "": "アイウエオ",
    "k": "カキクケコ",
    "s": "サシスセソ",
    "t": "タチツテト",
    "n": "ナニヌネノ",
    "h": "ハヒフヘホ",
    "m": "マミムメモ",
    "y": "ヤ_ユ_ヨ",
    "r": "ラリルレロ",
    "w": "ワ___ヲ",
    "g": "ガギグゲゴ",
    "z": "ザジズゼゾ",
    "d": "ダヂヅデド",
    "b": "バビブベボ",
    "p": "パピプペポ",
}
_KANA: dict[str, str] = {
    k: c + v for c, row in _KANA_ROWS.items() for v, k in zip("aiueo", row) if k != "_"
}
_KANA.update(
    {
        "シ": "shi",
        "チ": "chi",
        "ツ": "tsu",
        "フ": "fu",
        "ジ": "ji",
        "ヂ": "ji",
        "ヅ": "zu",
        "ヲ": "o",
        "ン": "n",
        "ヴ": "vu",
    }
)
#: Small kana that modify the glyph before them.
_SMALL_Y = {"ャ": "ya", "ュ": "yu", "ョ": "yo"}
_SMALL_V = {"ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o"}
_PALATAL = {"shi": "sh", "chi": "ch", "ji": "j"}


def _to_katakana(ch: str) -> str:
    """Hiragana → katakana (same sound, codepoint + 0x60); anything else as is."""
    o = ord(ch)
    return chr(o + 0x60) if 0x3041 <= o <= 0x3096 else ch


def romanize_kana(word: str) -> list[tuple[str, str]]:
    """``(glyph, romaji)`` per glyph, the romaji chunks concatenating to the word.

    >>> romanize_kana("バカンス")
    [('バ', 'ba'), ('カ', 'ka'), ('ン', 'n'), ('ス', 'su')]
    >>> romanize_kana("スーパー")
    [('ス', 'su'), ('ー', ''), ('パ', 'pa'), ('ー', '')]
    >>> romanize_kana("カップ")
    [('カ', 'ka'), ('ッ', 'p'), ('プ', 'pu')]
    >>> romanize_kana("シャツ")
    [('シ', 'sh'), ('ャ', 'a'), ('ツ', 'tsu')]
    >>> romanize_kana("キャンディー")
    [('キ', 'k'), ('ャ', 'ya'), ('ン', 'n'), ('デ', 'd'), ('ィ', 'i'), ('ー', '')]
    >>> romanize_kana("ok!")
    [('o', 'o'), ('k', 'k'), ('!', '')]

    A glyph with an empty chunk (``ー``, punctuation) has no onset of its own;
    the aligner places it between its neighbours and marks it unmeasured.
    """
    kata = [_to_katakana(c) for c in word]
    out: list[tuple[str, str]] = []
    for i, (g, k) in enumerate(zip(word, kata)):
        nxt = kata[i + 1] if i + 1 < len(kata) else ""
        if k == "ー":
            # a held vowel has no onset of its own: an empty chunk, timed
            # between its neighbours by the aligner (a CTC model places a
            # repeated vowel at the END of the held note, not where it starts)
            out.append((g, ""))
        elif k == "ッ":
            # doubles the NEXT consonant; word-final (a glottal stop) has no
            # sound of its own to align
            follow = _KANA.get(nxt, "")
            out.append((g, follow[0] if follow else ""))
        elif k in _SMALL_Y or k in _SMALL_V:
            out.append((g, (_SMALL_Y | _SMALL_V)[k]))
        elif k in _KANA:
            r = _KANA[k]
            if nxt in _SMALL_Y:  # キャ: キ keeps its consonant, ャ carries "ya"
                if r in _PALATAL:
                    r = _PALATAL[r]
                    out.append((g, r))
                    # シャ = "sha": the small kana then carries only the vowel
                    # (`zip` reads `kata` lazily, so the next step sees this)
                    kata[i + 1] = "_V" + _SMALL_Y[nxt][-1]
                    continue
                r = r[:-1] if len(r) > 1 else r
            elif nxt in _SMALL_V:  # ファ, ティ: drop the base vowel
                r = r[:-1] if len(r) > 1 else r
            out.append((g, r))
        elif k.startswith("_V"):
            out.append((g, k[2:]))
        elif k.isascii() and k.isalpha():
            out.append((g, k.lower()))
        else:
            out.append((g, ""))
    return out


_MACRON = dict(zip("aiueo", "āīūēō"))
#: Glyph pairs Hepburn writes as one sound, where the per-glyph alignment
#: chunks would give two vowels or lose the glide (ウィ "ui", クァ "ka").
_HEPBURN_PAIRS = {
    "ウィ": "wi",
    "ウェ": "we",
    "ウォ": "wo",
    "イェ": "ye",
    "クァ": "kwa",
    "クィ": "kwi",
    "クェ": "kwe",
    "クォ": "kwo",
    "グァ": "gwa",
}
#: Japanese punctuation, written the Latin way.
_HEPBURN_PUNCT = str.maketrans(
    {
        "、": ", ",
        "。": ". ",
        "・": " ",
        "「": '"',
        "」": '"',
        "『": '"',
        "』": '"',
        "〜": "~",
    }
)


def _is_kana(ch: str) -> bool:
    return 0x3041 <= ord(ch) <= 0x3096 or 0x30A1 <= ord(ch) <= 0x30FA or ch == "ー"


def romanize_hepburn(text: str) -> str:
    """Display romanisation (modified Hepburn) of kana text: what a learner reads.

    :func:`romanize_kana` is an ALIGNMENT romaniser — ``ー`` is silent there,
    because it has no onset. Read on screen it needs a macron. Also ``ン``
    before a vowel or ``y`` takes an apostrophe, ``ッ`` before ``ch`` is ``t``,
    and glides keep their ``w``/``y`` (muvid#145).

    >>> romanize_hepburn("バス バス スタート")
    'basu basu sutāto'
    >>> romanize_hepburn("ハンバーガー")
    'hanbāgā'
    >>> romanize_hepburn("カップ マッチ シャツ")
    'kappu matchi shatsu'
    >>> romanize_hepburn("キンエン ウィンドウ")
    "kin'en windou"

    Anything that is not kana is KEPT, not dropped — kanji, digits, Latin, an
    unknown kana — because a caption that silently loses a word looks right:

    >>> romanize_hepburn("東京 バス、スタート! Café")
    '東京 basu, sutāto! Café'

    Input is NFKC-normalised first, so half-width (``ﾊﾞｽ``) and decomposed
    (``ハ`` + combining ``゙``) kana read as the composed glyphs. Hiragana long
    vowels spelt with a second vowel (``とうきょう``) keep both letters: telling
    ``ou`` the long vowel from ``o``+``u`` needs a dictionary.
    """
    text = unicodedata.normalize("NFKC", text)
    out, run = [], ""
    for ch in text + "\0":
        if _is_kana(ch):
            run += ch
            continue
        if run:
            out.append(_hepburn_kana(run))
            run = ""
        if ch != "\0":
            out.append(ch.translate(_HEPBURN_PUNCT))
    return re.sub(r" +([,.!?])", r"\1", re.sub(r"\s+", " ", "".join(out))).strip()


def _hepburn_kana(run: str) -> str:
    chunks = romanize_kana(run)
    out, prev, i = "", "", 0
    while i < len(chunks):
        g, r = chunks[i]
        k = _to_katakana(g)
        pair = k + _to_katakana(chunks[i + 1][0]) if i + 1 < len(chunks) else ""
        if pair in _HEPBURN_PAIRS:
            r, i = _HEPBURN_PAIRS[pair], i + 1
        if k == "ー":
            if out and out[-1] in _MACRON:
                out = out[:-1] + _MACRON[out[-1]]
        elif not r and k not in "ッ":  # a kana this romaniser does not know: keep it
            out += g
        else:
            if k == "ッ" and r == "c":  # ッチ: "tch", not "cch"
                r = "t"
            if prev == "ン" and r[:1] in ("a", "i", "u", "e", "o", "y"):
                out += "'"
            out += r
        prev, i = k, i + 1
    return out


# --------------------------------------------------------------------------
# alignment
# --------------------------------------------------------------------------


def _mms_weights(*, allow_download: bool) -> Path:
    """Where the MMS_FA weights are cached, refusing to fetch them unasked.

    Cheap: checks the file, builds nothing. The CLI calls it before separating
    the vocals, so a missing licence decision fails in a second, not after
    minutes of separation.
    """
    import torch
    import torchaudio

    bundle = torchaudio.pipelines.MMS_FA
    cached = Path(torch.hub.get_dir()) / "checkpoints" / Path(bundle._path).name
    allow = allow_download or os.environ.get("MUVID_ALLOW_WEIGHT_DOWNLOAD") == "1"
    if not cached.exists() and not allow:
        raise RuntimeError(
            "The MMS_FA weights (CC-BY-NC-4.0, ~1.2 GB) are not cached and muvid "
            "never downloads weights unasked. Pass allow_download=True or set "
            "MUVID_ALLOW_WEIGHT_DOWNLOAD=1 — after checking the licence fits "
            "your use."
        )
    return cached


def _load_mms(*, allow_download: bool):
    """The MMS_FA model + dictionary, refusing to fetch weights unasked.

    When the weights are already cached, the model is built on the meta
    device and the checkpoint is memory-mapped into it, so the 1.2 GB of
    weights are file-backed pages the kernel can evict. torchaudio's own path
    builds a randomly initialised model and then copies a loaded state dict
    into it: about 2 GB of anonymous memory, which caused a global OOM on a
    3.8 GB server (muvid#150). Same weights, same model (measured: identical
    glyph times on a full song). If torchaudio's internals have moved, it
    falls back to the copying path rather than failing.
    """
    import torchaudio

    cached = _mms_weights(allow_download=allow_download)
    bundle = torchaudio.pipelines.MMS_FA
    if not cached.exists():  # allowed: fetch to disk first, so it can be mapped
        import torch

        cached.parent.mkdir(parents=True, exist_ok=True)
        torch.hub.download_url_to_file(_MMS_URL_BASE + bundle._path, str(cached))
    model = _mmap_model(bundle, cached)
    if model is None:
        model = bundle.get_model(with_star=True)
    return bundle, model, bundle.get_dict()


#: Where torchaudio fetches its pipeline weights from (``utils._get_state_dict``).
_MMS_URL_BASE = "https://download.pytorch.org/torchaudio/models/"


def _mmap_model(bundle, checkpoint: Path):
    """``bundle.get_model(with_star=True)`` with the weights memory-mapped.

    Rebuilds torchaudio's ``Wav2Vec2FABundle.get_model`` from its parts rather
    than swapping its module functions, so nothing global changes: two threads
    can load at once, and another bundle loaded meanwhile gets its own weights.
    Returns ``None`` (use the copying path) when those parts are not where
    torchaudio 2.x keeps them, and warns, because that path is the one that
    ran a 3.8 GB server out of memory.
    """
    import warnings

    import torch

    try:
        from torchaudio.pipelines._wav2vec2 import utils as u

        build, remove_aux, extend = u._get_model, u._remove_aux_axes, u._extend_model
        model_type, params = bundle._model_type, bundle._params
        aux, normalize = bundle._remove_aux_axis, bundle._normalize_waveform
    except (ImportError, AttributeError) as e:
        warnings.warn(
            f"muvid: cannot memory-map the MMS_FA weights ({e!r}); loading them "
            "the copying way, which needs ~2 GB of free memory",
            RuntimeWarning,
            stacklevel=3,
        )
        return None

    with torch.device("meta"):
        model = build(model_type, params)
    state = torch.load(checkpoint, mmap=True, weights_only=True, map_location="cpu")
    if aux:
        remove_aux(state, aux)
    model.load_state_dict(state, assign=True)
    model = extend(
        model, normalize_waveform=normalize, apply_log_softmax=True, append_star=True
    )
    # a tensor left on the meta device would fail only at inference
    if any(t.is_meta for t in (*model.parameters(), *model.buffers())):
        warnings.warn(
            "muvid: the memory-mapped MMS_FA model is incomplete; loading the "
            "weights the copying way, which needs ~2 GB of free memory",
            RuntimeWarning,
            stacklevel=3,
        )
        return None
    return model.eval()


def _read_mono(path: Path | str, sample_rate: int):
    import soundfile as sf
    import torch
    import torchaudio

    a, sr = sf.read(str(path), dtype="float32", always_2d=True)
    wav = torch.from_numpy(a.mean(1)).unsqueeze(0)
    return torchaudio.functional.resample(wav, sr, sample_rate)


def _interpolated(word: Word, chunks: Sequence[tuple[str, str]]) -> tuple[Glyph, ...]:
    """Glyphs spread evenly over the word: honest ``measured=False`` fallback."""
    n = max(1, len(chunks))
    step = (word.end - word.start) / n
    return tuple(
        Glyph(
            text=g,
            start=word.start + i * step,
            end=word.start + (i + 1) * step,
            measured=False,
        )
        for i, (g, _) in enumerate(chunks)
    )


def _align_line(
    line: Line, *, wav, sr: int, model, dic, romanize: Romanizer, margin_s: float
) -> Line:
    import torch
    import torchaudio.functional as F

    t0 = max(0.0, line.start - margin_s)
    t1 = line.end + margin_s
    seg = wav[:, int(t0 * sr) : int(t1 * sr)]
    chunks = [romanize(w.text) for w in line.words]
    letters = [c for ws in chunks for _, r in ws for c in r if c in dic]
    if not letters or seg.shape[1] < sr // 10:
        return replace(
            line,
            words=tuple(
                replace(w, glyphs=_interpolated(w, ch))
                for w, ch in zip(line.words, chunks)
            ),
        )
    with torch.inference_mode():
        emission, _ = model(seg)
    star = dic["*"]
    targets = torch.tensor(
        [[star] + [dic[c] for c in letters] + [star]], dtype=torch.int32
    )
    try:
        ali, scores = F.forced_align(emission, targets, blank=0)
    except RuntimeError:  # window too short for the targets: no honest answer
        return replace(
            line,
            words=tuple(
                replace(w, glyphs=_interpolated(w, ch))
                for w, ch in zip(line.words, chunks)
            ),
        )
    spans = [s for s in F.merge_tokens(ali[0], scores[0].exp()) if s.token != star]
    ratio = seg.shape[1] / emission.shape[1] / sr
    k = 0
    words = []
    for w, ws in zip(line.words, chunks):
        glyphs = []
        for g, r in ws:
            n = sum(1 for c in r if c in dic)
            if n == 0:  # no onset of its own: placed by _place_silent below
                glyphs.append(
                    Glyph(text=g, start=float("nan"), end=float("nan"), measured=False)
                )
                continue
            sp = spans[k : k + n]
            k += n
            glyphs.append(
                Glyph(
                    text=g,
                    start=round(t0 + sp[0].start * ratio, 3),
                    end=round(t0 + sp[-1].end * ratio, 3),
                )
            )
        words.append(replace(w, glyphs=tuple(glyphs)))
    return _place_silent(replace(line, words=tuple(words)))


def _place_silent(line: Line) -> Line:
    """Time glyphs without an onset (``ー``, punctuation) between their neighbours.

    Midway from the previous sounded glyph's start to the next one's (a held
    vowel is the second half of its syllable); at a line's end, half the
    previous glyph's span past its start. ``measured=False`` either way.
    """
    flat = [g for w in line.words for g in w.glyphs]
    times: list[tuple[float, float]] = []
    for i, g in enumerate(flat):
        if g.start == g.start:  # not NaN
            times.append((g.start, g.end))
            continue
        prev = next(
            (times[j] for j in range(i - 1, -1, -1) if flat[j].measured),
            (line.start, line.start),
        )
        nxt = next(
            (
                flat[j].start
                for j in range(i + 1, len(flat))
                if flat[j].start == flat[j].start
            ),
            None,
        )
        at = (
            (prev[0] + nxt) / 2
            if nxt is not None
            else min(line.end, prev[0] + max(0.05, (prev[1] - prev[0]) / 2))
        )
        times.append((at, at))
    it = iter(times)
    return replace(
        line,
        words=tuple(
            replace(
                w,
                glyphs=tuple(
                    g
                    if g.measured
                    else replace(g, start=round(t[0], 3), end=round(t[1], 3))
                    for g, t in ((g, next(it)) for g in w.glyphs)
                ),
            )
            for w in line.words
        ),
    )


def refine_glyphs(
    timed_text: TimedText,
    vocals: Path | str,
    *,
    romanize: Romanizer = romanize_kana,
    margin_s: float = MARGIN_S,
    allow_download: bool = False,
) -> TimedText:
    """Return ``timed_text`` with measured :attr:`Word.glyphs` on every word.

    ``vocals`` should be a separated vocal stem (see :func:`vocal_stem`): the
    accompaniment confuses a CTC model far more than it confuses a listener.
    The coarse word times are only used as per-line windows; the glyph times
    replace nothing else. A line with nothing romanisable keeps evenly spread,
    ``measured=False`` glyphs rather than invented precision.
    """
    bundle, model, dic = _load_mms(allow_download=allow_download)
    sr = bundle.sample_rate
    wav = _read_mono(vocals, sr)
    return replace(
        timed_text,
        sections=tuple(
            replace(
                s,
                lines=tuple(
                    _align_line(
                        ln,
                        wav=wav,
                        sr=sr,
                        model=model,
                        dic=dic,
                        romanize=romanize,
                        margin_s=margin_s,
                    )
                    for ln in s.lines
                ),
            )
            for s in timed_text.sections
        ),
        source=f"{timed_text.source}+glyph_align",
    )


def vocal_stem(
    audio: Path | str, *, out_dir: Path | str, allow_download: bool = False
) -> Path:
    """The song's separated vocal stem (Demucs), raising rather than degrading.

    Reuses the footage scorer's separator; that one returns ``None`` on any
    failure because lip-sync is optional there, but here no stem means no
    trustworthy glyph times, so the absence is an error.
    """
    from muvid.footage.scoring.lipsync import separate_master_vocals

    if not (allow_download or os.environ.get("MUVID_ALLOW_WEIGHT_DOWNLOAD") == "1"):
        # Demucs fetches its (CC-BY-NC) weights on first use, and offers no
        # cheap "is it cached?" probe: the caller must say yes, or hand us a stem.
        raise RuntimeError(
            "Vocal separation may download the htdemucs weights (CC-BY-NC). "
            "Pass allow_download=True (CLI: --allow-download) or supply a vocal "
            "stem yourself (CLI: --vocals)."
        )
    out = separate_master_vocals(str(audio), out_dir=str(out_dir))
    if out is None:
        raise RuntimeError(
            "Vocal separation failed or Demucs is missing "
            "(pip install 'muvid[lyricvid-glyphs]')."
        )
    return out


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------


def _glyph_starts(tt: TimedText) -> list[float]:
    return [
        g.start
        for w in tt.words()
        for g in w.glyphs
        if g.measured
        and g.sung  # an unsung glyph sits off every onset by definition
        and g.end > g.start
        and unicodedata.category(g.text)[0] == "L"
        and g.text not in _SOUNDLESS_GLYPHS
    ]


def onset_report(
    timed_text: TimedText,
    vocals: Path | str,
    *,
    tol_s: float = ONSET_TOL_S,
    seed: int = 0,
    trials: int = 20,
) -> dict[str, Any]:
    """How well glyph starts sit on acoustic onsets of the vocal stem.

    ``near_onset`` is the share of glyph starts within ``tol_s`` of a detected
    onset; ``random_baseline`` is the same share after jittering every start
    by up to ±0.5 s — the gap between the two is the evidence, since a dense
    onset track makes any time look "near" something.
    """
    import numpy as np

    onsets = stem_onsets(vocals)
    starts = np.array(_glyph_starts(timed_text))
    if not len(starts) or not len(onsets):
        return {"n_glyphs": int(len(starts)), "n_onsets": int(len(onsets))}

    def share(ts) -> float:
        return float(np.mean([np.min(np.abs(onsets - t)) <= tol_s for t in ts]))

    dist = np.array([np.min(np.abs(onsets - t)) for t in starts])
    rng = np.random.default_rng(seed)
    base = np.mean(
        [share(starts + rng.uniform(-0.5, 0.5, len(starts))) for _ in range(trials)]
    )
    return {
        "n_glyphs": int(len(starts)),
        "n_onsets": int(len(onsets)),
        "near_onset": round(share(starts), 3),
        "random_baseline": round(float(base), 3),
        "median_onset_distance_ms": round(float(np.median(dist)) * 1000),
        "tol_ms": round(tol_s * 1000),
    }


def word_agreement(
    fine: TimedText, coarse: TimedText, *, disagree_s: float = DISAGREE_S
) -> dict[str, Any]:
    """Compare word starts (first glyph start when present) of two timings.

    The two must hold the same words in the same order (``fine`` is normally
    ``refine_glyphs(coarse, ...)``). Returns summary statistics and the list
    of words that disagree by more than ``disagree_s`` — the ones to look at.
    """
    import numpy as np

    def start(w: Word) -> float:
        return w.glyphs[0].start if w.glyphs else w.start

    a, b = list(fine.words()), list(coarse.words())
    if [w.text for w in a] != [w.text for w in b]:
        raise ValueError("word_agreement needs the same word sequence in both timings")
    d = np.array([start(x) - start(y) for x, y in zip(a, b)])
    bad = [
        {
            "index": i,
            "text": x.text,
            "fine": round(start(x), 3),
            "coarse": round(start(y), 3),
        }
        for i, (x, y, dd) in enumerate(zip(a, b, d))
        if abs(dd) > disagree_s
    ]
    return {
        "n_words": len(a),
        "median_abs_diff_ms": round(float(np.median(np.abs(d))) * 1000),
        "median_signed_diff_ms": round(float(np.median(d)) * 1000),
        "disagree_s": disagree_s,
        "disagreements": bad,
    }


# --------------------------------------------------------------------------
# reconciliation: detectors name the words to distrust, remedies fix them
# --------------------------------------------------------------------------

#: :func:`unsung`'s thresholds, measured on a real song (muvid#144): a frame is
#: quiet below this many dB under the stem's own loud level...
UNSUNG_QUIET_DB = -40.0
#: ...and a line is unsung when at least this share of its window is quiet...
UNSUNG_QUIET_SHARE = 0.5
#: ...in one unbroken stretch at least this long. A ghost repeat is a whole
#: line of silence (2 s on the measured song); a short sung line whose vendor
#: window is merely LATE lands on a quiet tail too, but a short one.
UNSUNG_MIN_QUIET_S = 1.0
#: :func:`disordered`: a line whose last glyph starts within this many seconds
#: of the next line's first glyph (or after it) overlaps it.
LINE_GAP_S = 0.05
#: Frame length for the stem's RMS level.
UNSUNG_FRAME_S = 0.05
#: The stem's "loud level" is this percentile of its frame RMS, so the threshold
#: follows the mix rather than an absolute dBFS a quieter stem would fail.
UNSUNG_REF_PERCENTILE = 95.0
#: :func:`silent_glyph`'s thresholds, measured on 21 songs (muvid#156): a glyph
#: window is silent when its PEAK is under this many dB below the stem's loud
#: level...
SILENT_GLYPH_PEAK_DB = -25.0
#: ...AND its MEDIAN is under this. Both: a sung glyph's window often runs into
#: a gap or a devoiced tail (low median, high peak), and a quiet tail can sit
#: next to an attack (high peak). (The median never exceeds the peak, so once the
#: peak is under its bound this only rejects windows uniformly near the threshold.)
SILENT_GLYPH_MEDIAN_DB = -28.0
#: A glyph's window runs to the next sounded glyph's start, clamped to this
#: range (seconds): a glyph is never judged on less than a couple of frames,
#: nor on the held note after it.
SILENT_GLYPH_WINDOW_S = (0.06, 0.4)
#: Frame length for :func:`silent_glyph`'s levels (finer than the line-level 50 ms).
SILENT_GLYPH_FRAME_S = 0.01
#: :func:`with_spans` (muvid#149). A glyph's sound is taken to run at most this
#: long (seconds) when nothing ends it sooner.
GLYPH_SPAN_MAX_S = 0.6
#: Seconds searched around a labelled onset for the cut to the previous
#: glyph: (before, after).
SPAN_SEARCH_S = (0.18, 0.08)
#: A frame is silent below this many dB under the stem's loud level (the
#: consumer-side re-cut this is ported from used -40 re the LOUDEST frame; ours
#: is re the 95th percentile, see :data:`UNSUNG_REF_PERCENTILE`, so it is
#: slightly stricter)...
SPAN_SILENCE_DB = -40.0
#: ...and a dip is a valley when it sits this far under both neighbouring
#: syllables, its flat bottom being the frames within ``SPAN_VALLEY_FLAT_DB``
#: of its minimum.
SPAN_VALLEY_DB = 8.0
SPAN_VALLEY_FLAT_DB = 1.0
#: Frame length for the levels the cuts are read from.
SPAN_FRAME_S = 0.01
#: A stem whose loud level is below this RMS (-120 dBFS) holds no singing at all.
_SILENT_RMS = 1e-6


@dataclass(frozen=True, slots=True, kw_only=True)
class Detector:
    """Names the words of a fine timing not to trust, and what to do about them.

    ``find(fine, coarse)`` gets both timings (same word sequence) and returns
    ``{word_index: reason}``, indices into ``list(fine.words())``. ``remedy``
    is one of :data:`REMEDIES`; when several detectors flag one word, the
    remedy with the lowest rank wins: ``drop`` — a word nobody sang has no
    window worth falling back to — then ``replace``, then ``mute``.
    """

    name: str
    find: Callable[[TimedText, TimedText], Mapping[int, str]]
    remedy: str = "replace"
    #: ``mute`` acts on single glyphs, so it needs to say which: ``glyphs(fine,
    #: coarse)`` returns ``{word_index: {glyph_index, ...}}`` (indices into the
    #: word's ``glyphs``), and ``find`` still names the words (muvid#175).
    glyphs: Callable[[TimedText, TimedText], Mapping[int, Collection[int]]] | None = (
        None
    )

    def __post_init__(self) -> None:
        if self.remedy not in REMEDIES:
            raise ValueError(f"remedy must be one of {REMEDIES}, not {self.remedy!r}")
        if self.remedy == "mute" and self.glyphs is None:
            raise ValueError("a 'mute' detector must say which glyphs (glyphs=)")


def _word_start(w: Word) -> float:
    return w.glyphs[0].start if w.glyphs else w.start


def squeezed(*, min_glyph_s: float = MIN_GLYPH_S) -> Detector:
    """Words with two sounded glyphs starting less than ``min_glyph_s`` apart.

    CTC squeezing a word it could not hear into a few frames. Judged on
    syllabic glyphs (kana/CJK: one mora each) only — letters of an alphabet are
    legitimately ~30 ms apart — and only between neighbours in the same line
    (lines are aligned in overlapping windows). Remedy: ``replace``.
    """

    def find(fine: TimedText, coarse: TimedText) -> dict[int, str]:
        out: dict[int, str] = {}
        w_idx = 0
        for ln in fine.lines():
            sounded = []
            for w in ln.words:
                sounded += [
                    (w_idx, g.start)
                    for g in w.glyphs
                    if g.measured
                    and _has_sound(g)
                    and unicodedata.east_asian_width(g.text[0]) in "WF"
                ]
                w_idx += 1
            for (wa, t), (wb, u) in zip(sounded, sounded[1:]):
                if 0 <= u - t < min_glyph_s:
                    why = f"two glyphs start {round((u - t) * 1000)} ms apart"
                    out.setdefault(wa, why)
                    out.setdefault(wb, why)
        return out

    return Detector(name="squeezed", find=find)


def disagrees(*, disagree_s: float = DISAGREE_S) -> Detector:
    """Words whose fine start is more than ``disagree_s`` from the coarse one.

    Remedy: ``replace``.
    """

    def find(fine: TimedText, coarse: TimedText) -> dict[int, str]:
        diffs = (
            _word_start(x) - _word_start(y)
            for x, y in zip(fine.words(), coarse.words())
        )
        return {
            i: f"starts {d:+.2f} s from the coarse timing"
            for i, d in enumerate(diffs)
            if abs(d) > disagree_s
        }

    return Detector(name="disagrees", find=find)


def default_detectors(
    *, disagree_s: float = DISAGREE_S, min_glyph_s: float = MIN_GLYPH_S
) -> tuple[Detector, ...]:
    """What :func:`reconcile` runs when given none: the two that need no audio."""
    return (squeezed(min_glyph_s=min_glyph_s), disagrees(disagree_s=disagree_s))


def _read_stem(vocals: Path | str):
    """``(mono samples, sample rate)`` of a stem file."""
    import soundfile as sf

    y, sr = sf.read(str(vocals), dtype="float32", always_2d=True)
    return y.mean(1), sr


def _frame_levels_db(vocals: Path | str, *, frame_s: float):
    """Per-frame RMS of the stem, in dB relative to its own loud level."""
    import numpy as np

    y, sr = _read_stem(vocals)
    hop = max(1, int(round(frame_s * sr)))
    n = len(y) // hop
    rms = np.sqrt(np.mean(y[: n * hop].reshape(n, hop) ** 2, axis=1))
    ref = float(np.percentile(rms, UNSUNG_REF_PERCENTILE)) if n else 0.0
    if ref < _SILENT_RMS:
        # no loud level to be quiet against (a digitally silent stem, or the
        # wrong file): read every frame as NOT quiet — the safe direction for a
        # remedy that deletes words
        return np.zeros(n)
    return 20 * np.log10(np.maximum(rms, 1e-12) / ref)


def unsung(
    vocals: Path | str,
    *,
    among: Detector | None = None,
    quiet_db: float = UNSUNG_QUIET_DB,
    quiet_share: float = UNSUNG_QUIET_SHARE,
    min_quiet_s: float = UNSUNG_MIN_QUIET_S,
    frame_s: float = UNSUNG_FRAME_S,
) -> Detector:
    """Lines a vendor transcript lists but nobody sang. Remedy: ``drop``.

    A LINE is unsung when both hold: ``among`` (default :func:`squeezed`)
    distrusts every word in it — the aligner, searching the line's window, found
    nothing to put them on — and the vocal stem is quiet (``quiet_db`` under its
    own loud level) over at least ``quiet_share`` of the line's coarse window,
    including one unbroken quiet stretch of ``min_quiet_s``. The window is
    shifted by the vendor's measured bias (median fine-minus-coarse start over
    the words ``among`` trusts), and a window running past the end of the stem
    is not judged at all.

    Both, because neither instrument is enough alone. Measured on the song that
    motivated this (muvid#144: a Suno transcript listing a repeated タン タン タン
    at 36-38 s that the stem shows nobody sang), the stem alone puts a sung,
    staccato ストップ ストップ at 0.63 quiet against the ghost's 0.75 — vendor
    windows run on into the silence after a word, so a quiet window is common —
    while squeeze alone also flags a sung, fast スター ダンス (0.04 quiet).
    Together they separate the ghost and nothing else.

    What they do NOT separate unaided is one short sung line whose vendor
    window is a second late: the aligner (searching ±``MARGIN_S``) misses it
    and squeezes, and the window lands on the silence after it — measured on
    the same song, the last line (フン) shifted +1 s was dropped. The unbroken
    ``min_quiet_s`` is what refuses that case: a short window cannot hold a
    second of silence, a ghost line is silence end to end.

    The unit is the line, because a transcript repeats lines, and because the
    first ghost word's own window held the decaying tail of the previous held
    note: sound, but not its sound. ``among`` is squeeze and not disagreement
    on purpose — a line the vendor MISPLACED was sung somewhere else, and
    dropping it would delete a sung line. With the stem, :func:`lost` widens
    ``among`` only by disagreeing words that are off every onset AND sit in
    another line's window, which a misplaced-but-sung line does not produce
    (see :func:`stem_detectors`).
    """
    among = among or squeezed()

    def find(fine: TimedText, coarse: TimedText) -> dict[int, str]:
        import numpy as np

        flagged = among.find(fine, coarse)
        fw, cw = list(fine.words()), list(coarse.words())
        if len(fw) != len(cw):
            raise ValueError("unsung needs the same word sequence in both timings")
        trusted = [
            _word_start(x) - _word_start(y)
            for k, (x, y) in enumerate(zip(fw, cw))
            if k not in flagged
        ]
        bias = float(np.median(trusted)) if trusted else 0.0
        level = None
        out: dict[int, str] = {}
        i = 0
        for ln in fine.lines():
            idx = range(i, i + len(ln.words))
            i += len(ln.words)
            if not idx or any(k not in flagged for k in idx):
                continue
            if level is None:  # read the stem only when there is a candidate
                level = _frame_levels_db(vocals, frame_s=frame_s)
            a = max(0, int(round((min(cw[k].start for k in idx) + bias) / frame_s)))
            b = max(a + 1, int(round((max(cw[k].end for k in idx) + bias) / frame_s)))
            if b > len(level):  # past the stem's end: nothing to judge it by
                continue
            quiet = level[a:b] < quiet_db
            share = float(np.mean(quiet))
            run_s = _longest_run(quiet) * frame_s
            if share >= quiet_share and run_s >= min_quiet_s:
                why = (
                    f"line {ln.text!r}: every word {among.name}, and the stem is "
                    f"quiet over {share:.0%} of its window ({run_s:.1f} s unbroken)"
                )
                out.update({k: why for k in idx})
        return out

    return Detector(name="unsung", find=find, remedy="drop")


def silent_glyph(
    vocals: Path | str,
    *,
    peak_db: float = SILENT_GLYPH_PEAK_DB,
    median_db: float = SILENT_GLYPH_MEDIAN_DB,
    window_s: tuple[float, float] = SILENT_GLYPH_WINDOW_S,
    frame_s: float = SILENT_GLYPH_FRAME_S,
    remedy: str = "drop",
) -> Detector:
    """Words with a sounded glyph whose own window is silent in the stem (muvid#156).

    :func:`squeezed` sees glyph starts too close together and :func:`unsung`
    sees whole quiet lines; neither sees ONE silent mora inside a sung line.
    That happens when the transcript lists ハッカー and the singer sang ハッ
    (CTC must still place カ, and puts it in the ッ gap: ``measured=True``, 61 ms,
    30-40 dB under the singing), and when an unmeasured glyph keeps a vendor
    fallback time that lands in a gap. A consumer that plays per-glyph clips
    plays silence or a click for these.

    A glyph's window runs from its start to the next sounded glyph's start
    (``ー`` and ``ッ`` make no sound of their own and are neither judged nor
    ends), clamped to ``window_s``; its levels are dB under the stem's loud
    level. It is silent when its peak is under ``peak_db`` AND its median under
    ``median_db``. Measured on 21 songs this flagged 13 words in 8, each checked
    against the stem envelope; sung-but-devoiced glyphs (デス ス) stay above.
    A window running past the stem's end, or a digitally silent stem, is not
    judged (the safe direction for a remedy that deletes words).

    Remedy: ``drop`` at WORD level by default (a per-glyph consumer, such as one
    playing a clip per kana, wants the word out of its timing); ``mute`` marks
    only the silent glyphs ``sung=False`` and keeps the rest of the word and its
    times (a lyric video keeps ``ハッ`` of ``ハッカー``); ``replace`` falls back to
    the vendor window. ``drop`` deletes sung text in a lyric video and outranks
    ``replace``, so it also turns a recoverable squeezed word into a deletion:
    opt-in, NOT part of :func:`stem_detectors`. Only wide (kana, CJK) glyphs are judged; words
    without glyphs are not judged and do not end a neighbour's window.
    """
    lo, hi = window_s
    if frame_s <= 0 or not 0 < lo <= hi:
        raise ValueError(
            "silent_glyph needs frame_s > 0 and 0 < window_s[0] <= window_s[1]"
        )
    levels: list = []  # the stem is read once per detector, on first use

    def judged(g: Glyph) -> bool:
        # syllabic scripts only: the thresholds were measured on kana, and CTC
        # places an alphabet's letters in gaps all the time (as `squeezed` does)
        return _has_sound(g) and unicodedata.east_asian_width(g.text[0]) in "WF"

    def scan(fine: TimedText) -> dict[int, dict[int, str]]:
        """``{word index: {glyph index: reason}}`` for every silent sounded glyph."""
        import numpy as np

        # (word index, glyph index, glyph) for every glyph that makes a sound
        sounded = [
            (k, gi, g)
            for k, w in enumerate(fine.words())
            for gi, g in enumerate(w.glyphs)
            if judged(g)
        ]
        if not sounded:
            return {}
        if not levels:
            levels.append(_frame_levels_db(vocals, frame_s=frame_s))
        level = levels[0]
        out: dict[int, dict[int, str]] = {}
        for n, (k, gi, g) in enumerate(sounded):
            nxt = sounded[n + 1][2].start if n + 1 < len(sounded) else g.start + hi
            end = min(max(nxt, g.start + lo), g.start + hi)
            a = max(0, int(g.start / frame_s))
            b = max(int(end / frame_s), a + 1)
            if b > len(level):  # past the stem's end: nothing to judge by
                continue
            w = level[a:b]
            peak, med = float(w.max()), float(np.median(w))
            if peak < peak_db and med < median_db:
                out.setdefault(k, {})[gi] = (
                    f"glyph {g.text!r} at {g.start:.2f} s: silent in the stem "
                    f"(peak {peak:.0f} dB, median {med:.0f} dB)"
                )
        return out

    def find(fine: TimedText, coarse: TimedText) -> dict[int, str]:
        return {k: next(iter(hits.values())) for k, hits in scan(fine).items()}

    def glyphs(fine: TimedText, coarse: TimedText) -> dict[int, set[int]]:
        return {k: set(hits) for k, hits in scan(fine).items()}

    return Detector(name="silent_glyph", find=find, remedy=remedy, glyphs=glyphs)


def stem_onsets(vocals: Path | str):
    """Acoustic onset times (seconds) of a vocal stem, as a numpy array."""
    import librosa

    y, sr = _read_stem(vocals)
    return librosa.onset.onset_detect(y=y, sr=sr, units="time")


def _onset_test(vocals: Path | str, tol_s: float) -> Callable[[float], bool]:
    """``near(t)``: is ``t`` within ``tol_s`` of an onset? Reads the stem once,
    on first use, so a detector that never needs it costs nothing."""
    import numpy as np

    onsets = None

    def near(t: float) -> bool:
        nonlocal onsets
        if onsets is None:
            onsets = np.asarray(stem_onsets(vocals), dtype=float)
        return bool(onsets.size) and float(np.min(np.abs(onsets - t))) <= tol_s

    return near


def _start_bias(fine: TimedText, coarse: TimedText) -> float:
    """Median fine-minus-coarse word start: how late the vendor runs."""
    import numpy as np

    d = [_word_start(x) - _word_start(y) for x, y in zip(fine.words(), coarse.words())]
    return float(np.median(d)) if d else 0.0


def misplaced(
    vocals: Path | str,
    *,
    disagree_s: float = DISAGREE_S,
    tol_s: float = ONSET_TOL_S,
) -> Detector:
    """Disagreeing words where the onsets side with the vendor. Remedy: ``replace``.

    :func:`disagrees` falls back to the vendor time whenever the two timings
    differ, but on a song where the fine aligner is good the vendor is usually
    the one that is wrong (muvid#150: seven words flagged, and every fine time
    sat within ~60 ms of a stem onset while the vendor times were up to 10 s
    off, one of them before the end of the previous line). So a word is
    flagged only when its fine start is off every onset (``tol_s``) AND its
    bias-shifted vendor start is on one: the evidence has to point at the
    vendor, not just away from the aligner. Use it in place of
    :func:`disagrees` when you have the stem (see :func:`stem_detectors`).
    """

    near = _onset_test(vocals, tol_s)

    def find(fine: TimedText, coarse: TimedText) -> dict[int, str]:
        bias = _start_bias(fine, coarse)
        out: dict[int, str] = {}
        for i, (x, y) in enumerate(zip(fine.words(), coarse.words())):
            f0, c0 = _word_start(x), _word_start(y) + bias
            if abs(f0 - c0) > disagree_s and not near(f0) and near(c0):
                out[i] = (
                    f"fine start {f0:.2f} s is off every onset; vendor {c0:.2f} s is on one"
                )
        return out

    return Detector(name="misplaced", find=find)


def lost(
    vocals: Path | str,
    *,
    disagree_s: float = DISAGREE_S,
    min_glyph_s: float = MIN_GLYPH_S,
    tol_s: float = ONSET_TOL_S,
) -> Detector:
    """Words the aligner could not place, as :func:`unsung`'s ``among``.

    A word is lost when it is :func:`squeezed`, or when it :func:`disagrees`,
    its fine start is off every onset, AND that start lies inside ANOTHER
    line's vendor window (bias-shifted): the aligner, finding nothing to put
    it on, pushed it onto a neighbour. That is the unsung intro repeat of
    muvid#150, whose first word disagreed instead of squeezing, so a
    squeeze-only ``among`` never saw the whole line as flagged.

    Each condition guards against deleting sung lyrics, because the remedy
    this feeds is ``drop``:

    - A disagreeing word the aligner put ON an onset was sung somewhere.
    - A word left in its OWN line's neighbourhood can be one the vendor merely
      placed late, by more than the aligner's search margin (``MARGIN_S``).
      Its window is then quiet, and without the third condition the line is
      deleted (review of muvid#154).

    Remedy: ``replace`` (it only names words; :func:`unsung` decides).
    """
    sq, dis = squeezed(min_glyph_s=min_glyph_s), disagrees(disagree_s=disagree_s)
    near = _onset_test(vocals, tol_s)

    def find(fine: TimedText, coarse: TimedText) -> dict[int, str]:
        fw = list(fine.words())
        bias = _start_bias(fine, coarse)
        windows, line_of, k = [], {}, 0
        for li, ln in enumerate(coarse.lines()):
            windows.append((ln.words[0].start + bias, ln.words[-1].end + bias))
            for _ in ln.words:
                line_of[k] = li
                k += 1

        def in_another_line(i: int) -> bool:
            t = _word_start(fw[i])
            return any(
                a <= t < b for j, (a, b) in enumerate(windows) if j != line_of[i]
            )

        out = {
            i: f"{why}, off every onset, inside another line's window"
            for i, why in dis.find(fine, coarse).items()
            if not near(_word_start(fw[i])) and in_another_line(i)
        }
        out.update(sq.find(fine, coarse))
        return out

    return Detector(name="lost", find=find)


def _line_starts(ln: Line) -> list[float]:
    return [g.start for w in ln.words for g in w.glyphs] or [w.start for w in ln.words]


def disordered(
    among: Sequence[Detector],
    *,
    gap_s: float = LINE_GAP_S,
) -> Detector:
    """Lines that overlap, or whose glyphs run backwards, once ``among`` is applied.

    Seen on dense backing chants (muvid#150): the aligner loses the beat, and
    after reconciling, a line's last glyph starts after the next line's first,
    or glyphs inside one line go out of order. Neither timing can be right, and
    the vendor windows at least keep the lines in order, so every word of such
    a line (both lines, for an overlap) is flagged. Remedy: ``replace``.

    It judges the RESULT of reconciling with ``among``, so it runs that
    reconcile itself; pass it after the same detectors::

        dets = stem_detectors(stem)  # already ends with disordered(...)
    """
    among = tuple(among)

    def find(fine: TimedText, coarse: TimedText) -> dict[int, str]:
        tt, records = reconcile(fine, coarse, detectors=among)
        dropped = {r["index"] for r in records if r["remedy"] == "drop"}
        keep = [k for k in range(len(list(fine.words()))) if k not in dropped]
        lines = list(tt.lines())
        spans, k = [], 0
        for ln in lines:
            spans.append([keep[j] for j in range(k, k + len(ln.words))])
            k += len(ln.words)
        out: dict[int, str] = {}
        for ln, span in zip(lines, spans):
            st = _line_starts(ln)
            if any(b < a - 1e-3 for a, b in zip(st, st[1:])):
                out.update({j: f"line {ln.text!r}: glyphs out of order" for j in span})
        for (a, sa), (b, sb) in zip(zip(lines, spans), zip(lines[1:], spans[1:])):
            if max(_line_starts(a)) >= min(_line_starts(b)) - gap_s:
                why = f"lines {a.text!r} and {b.text!r} overlap"
                out.update({j: why for j in (*sa, *sb)})
        return out

    return Detector(name="disordered", find=find)


def stem_detectors(
    vocals: Path | str,
    *,
    disagree_s: float = DISAGREE_S,
    min_glyph_s: float = MIN_GLYPH_S,
    tol_s: float = ONSET_TOL_S,
    drop_unsung: bool = True,
    silent_glyph_remedy: str | None = None,
) -> tuple[Detector, ...]:
    """What to reconcile with when you have the vocal stem (muvid#150).

    :func:`squeezed`, :func:`misplaced` (in place of :func:`disagrees`, which
    trusts the vendor even when its time is impossible), :func:`unsung` with
    ``among=``:func:`lost` (left out when ``drop_unsung`` is false), and
    :func:`disordered` over the rest. :func:`silent_glyph` joins them, with the
    given remedy, only when ``silent_glyph_remedy`` is set (default: not run;
    its ``drop`` deletes sung text, so it stays opt-in, muvid#177). Measured on five songs, this reproduced
    both hand fixes the first one needed.
    """
    first: tuple[Detector, ...] = (
        squeezed(min_glyph_s=min_glyph_s),
        misplaced(vocals, disagree_s=disagree_s, tol_s=tol_s),
    )
    if drop_unsung:
        among = lost(
            vocals, disagree_s=disagree_s, min_glyph_s=min_glyph_s, tol_s=tol_s
        )
        first = (*first, unsung(vocals, among=among))
    if silent_glyph_remedy is not None:
        first = (*first, silent_glyph(vocals, remedy=silent_glyph_remedy))
    return (*first, disordered(first))


def _longest_run(mask) -> int:
    """Length of the longest run of ``True`` in a boolean sequence."""
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


@dataclass(frozen=True, slots=True)
class _Remedy:
    """One row of ``_REMEDY_TABLE``. ``rank``: when several detectors flag one
    word the lowest decides. ``apply(word, coarse_word, *, bias, glyphs)``
    returns the word to keep (``None``: gone) and the fields it adds to the
    word's record (``used``, and ``glyphs`` for ``mute``)."""

    rank: int
    apply: Callable[..., tuple[Word | None, dict[str, Any]]]


def _apply_drop(w, c, *, bias, glyphs):
    return None, {}  # gone: no window is right for a word nobody sang


def _apply_replace(w, c, *, bias, glyphs):
    shifted = replace(
        c, start=c.start + bias, end=c.end + bias, measured=False, glyphs=()
    )
    spread = _interpolated(
        shifted, [(g.text, "") for g in w.glyphs] or [(ch, "") for ch in w.text]
    )
    kept = replace(
        w, start=shifted.start, end=shifted.end, measured=False, glyphs=spread
    )
    return kept, {"used": round(shifted.start, 3)}


def _apply_mute(w, c, *, bias, glyphs):
    kept = replace(
        w,
        glyphs=tuple(
            replace(g, sung=False) if i in glyphs else g for i, g in enumerate(w.glyphs)
        ),
    )
    return kept, {"used": round(_word_start(w), 3), "glyphs": sorted(glyphs)}


#: What :func:`reconcile` may do with a word a detector distrusts. ``replace``:
#: fall back to the coarse window shifted by the measured bias, glyphs spread
#: evenly and marked unmeasured (the word was sung; the aligner could not place
#: it). ``drop``: remove the word, and a line or section left empty (it was
#: never sung, so lighting it at ANY time is wrong). ``mute``: keep the word and
#: its times, mark only the glyphs the detector names ``sung=False``. A new
#: remedy is one row: rank AND behaviour together, so it can never be read as an
#: old one (a remedy falling through to ``drop`` would delete words).
_REMEDY_TABLE = {
    "drop": _Remedy(0, _apply_drop),
    "replace": _Remedy(1, _apply_replace),
    "mute": _Remedy(2, _apply_mute),
}
REMEDIES = tuple(_REMEDY_TABLE)


def reconcile(
    fine: TimedText,
    coarse: TimedText,
    *,
    disagree_s: float | None = None,
    min_glyph_s: float | None = None,
    detectors: Sequence[Detector] | None = None,
) -> tuple[TimedText, list[dict[str, Any]]]:
    """Distrust the fine timing where a detector says so; remedy it; say where.

    ``detectors`` defaults to :func:`default_detectors` (``squeezed`` and
    ``disagrees``, both ``replace``; ``disagree_s`` and ``min_glyph_s`` tune
    them, and are refused alongside explicit ``detectors``, which they could
    not reach). Add :func:`unsung` when you have the vocal stem::

        reconcile(fine, coarse, detectors=(*default_detectors(), unsung(stem)))

    ``replace`` puts a word back in its COARSE window, shifted by the median
    offset between the two timings over the words no detector flagged (vendor
    times run late; the bias is measured, not assumed), glyphs spread evenly
    and marked ``measured=False``. ``drop`` removes it, and any line or section
    left empty. Returns the timing and one record per affected word: ``why``
    (the deciding detector), ``detail``, ``remedy``, ``flagged_by`` (every
    detector that flagged it) and ``used`` (the start it got; ``None`` when
    dropped). ``mute`` (see :func:`silent_glyph`) keeps the word and its times
    and sets ``sung=False`` on the glyphs the detector names (the record lists
    their indices as ``glyphs``); it ranks below ``replace``, so a word another
    detector distrusts is re-timed and its silence verdict, measured on the
    distrusted time, is not kept. A ``ー`` after a muted glyph keeps ``sung=True``
    (it is never judged); and a ``fine`` timing override restores the line whole,
    ``sung`` included.
    """
    import numpy as np

    a, b = list(fine.words()), list(coarse.words())
    if [w.text for w in a] != [w.text for w in b]:
        raise ValueError("reconcile needs the same word sequence in both timings")
    if detectors is None:
        detectors = default_detectors(
            disagree_s=DISAGREE_S if disagree_s is None else disagree_s,
            min_glyph_s=MIN_GLYPH_S if min_glyph_s is None else min_glyph_s,
        )
    elif disagree_s is not None or min_glyph_s is not None:
        raise ValueError(
            "disagree_s/min_glyph_s tune the DEFAULT detectors; with "
            "detectors=, pass them to default_detectors(...) instead"
        )
    flags: dict[int, list[tuple[Detector, str]]] = {}
    muted: dict[int, set[int]] = {}  # word index -> glyph indices, asked once each
    for d in detectors:
        found = d.find(fine, coarse)
        for k, why in found.items():
            flags.setdefault(k, []).append((d, why))
        if d.remedy == "mute":
            named = d.glyphs(fine, coarse)
            for k in {*found, *named}:
                idx = set(named.get(k, ()))
                n = len(a[k].glyphs) if 0 <= k < len(a) else 0
                if not idx or not idx <= set(range(n)):
                    raise ValueError(
                        f"detector {d.name!r} flagged word {k} for 'mute' but its "
                        f"glyphs() named {sorted(idx)} of {n} glyphs"
                    )
                muted.setdefault(k, set()).update(idx)
    # the bias is measured over words whose fine time is trusted; a muted word's
    # times are (only its sung-ness is in doubt), a replaced or dropped one's not
    good = [
        _word_start(x) - _word_start(y)
        for k, (x, y) in enumerate(zip(a, b))
        if all(d.remedy == "mute" for d, _ in flags.get(k, ()))
    ]
    bias = float(np.median(good)) if good else 0.0

    records, k = [], 0
    sections = []
    for sec in fine.sections:
        lines = []
        for ln in sec.lines:
            words = []
            for w in ln.words:
                fl = flags.get(k)
                if fl:
                    d, why = min(fl, key=lambda f: _REMEDY_TABLE[f[0].remedy].rank)
                    rec = {
                        "index": k,
                        "text": w.text,
                        "fine": round(_word_start(w), 3),
                        "why": d.name,
                        "detail": why,
                        "remedy": d.remedy,
                        "flagged_by": [x.name for x, _ in fl],
                        "used": None,
                    }
                    kept, fields = _REMEDY_TABLE[d.remedy].apply(
                        w, b[k], bias=bias, glyphs=muted.get(k, set())
                    )
                    rec.update(fields)
                    if kept is not None:
                        words.append(kept)
                    records.append(rec)
                else:
                    words.append(w)
                k += 1
            if words:
                lines.append(replace(ln, words=tuple(words)))
        if lines:
            sections.append(replace(sec, lines=tuple(lines)))
    out = replace(fine, sections=tuple(sections))
    # a word moved, removed or muted changes its NEIGHBOURS' spans too
    return (_without_spans(out) if records else out), records


# --------------------------------------------------------------------------
# post-passes over the reconciled timing (muvid#155) — both opt-in
# --------------------------------------------------------------------------

#: What a recorded per-song timing override may say about a line. ``fine``:
#: the vendor window is junk and the aligner's times are right, so the line
#: gets its fine timing back, whatever :func:`reconcile` did to it.
TIMING_OVERRIDES = ("fine",)
#: :func:`repair_spills`: a moved glyph starts at least this long after the
#: glyph before it (a mora takes ~0.1 s)...
SPILL_MIN_STEP_S = 0.08
#: ...an onset it moves to is at least this long before the next line...
SPILL_CLEAR_S = 0.1
#: ...and a word whose glyph moved ends no earlier than this after its last
#: glyph's start (CTC spans are spiky; a 0 s word would never light).
SPILL_MIN_TAIL_S = 0.05


def _rebuilt(tt: TimedText, lines: Iterable[Line]) -> TimedText:
    """``tt`` with its lines replaced, in order, by ``lines`` (same count)."""
    it = iter(lines)
    return replace(
        tt,
        sections=tuple(
            replace(sec, lines=tuple(next(it) for _ in sec.lines))
            for sec in tt.sections
        ),
    )


def _map_glyphs(tt: TimedText, fn: Callable[[int, Glyph], Glyph]) -> TimedText:
    """``tt`` with every glyph replaced by ``fn(i, glyph)``, ``i`` its index in
    reading order (lines, then words, then glyphs)."""
    n = iter(range(sum(len(w.glyphs) for w in tt.words())))

    def word(w: Word) -> Word:
        return replace(w, glyphs=tuple(fn(next(n), g) for g in w.glyphs))

    return _rebuilt(
        tt, (replace(ln, words=tuple(map(word, ln.words))) for ln in tt.lines())
    )


def _without_spans(tt: TimedText) -> TimedText:
    """``tt`` with every :attr:`Glyph.span` cleared (``tt`` itself if none is set).

    The one invalidation: a span is cut against its NEIGHBOURS' onsets, so any
    pass that moves, removes or mutes a glyph clears them all, and
    :func:`with_spans` runs last.
    """
    if not any(g.span is not None for w in tt.words() for g in w.glyphs):
        return tt
    return _map_glyphs(tt, lambda i, g: replace(g, span=None))


def check_timing_overrides(
    overrides: Mapping[str | int, str] | None, n_lines: int
) -> dict[int, str]:
    """Validate recorded timing overrides against a transcript of ``n_lines``.

    Returns ``{line index: how}``. Refuses (``ValueError``) a key that is not
    an integer line index (a bool or a fractional number included), one out of
    range, two spellings of one line that disagree, and a value outside
    :data:`TIMING_OVERRIDES` (given bare, or as ``{"how": ..., "reason": ...}``
    so the judgement's reason is recorded beside it). Cheap, so a caller can
    run it BEFORE the expensive alignment it is about to correct.
    """
    chosen: dict[int, str] = {}
    for key, how in (overrides or {}).items():
        if isinstance(
            how, Mapping
        ):  # {"how": "fine", "reason": "..."}: reason is a note
            how = how.get("how")
        if isinstance(key, bool) or (isinstance(key, float) and not key.is_integer()):
            li = None
        else:
            try:
                li = int(key)
            except (TypeError, ValueError):
                li = None
        if li is None:
            raise ValueError(f"timing_overrides key {key!r} is not a line index")
        if not 0 <= li < n_lines:
            raise ValueError(
                f"timing_overrides line {li} is out of range: the transcript "
                f"has {n_lines} lines (0-based)"
            )
        if how not in TIMING_OVERRIDES:
            raise ValueError(
                f"timing_overrides[{key!r}] must be one of {TIMING_OVERRIDES}, "
                f"not {how!r}"
            )
        if chosen.get(li, how) != how:
            raise ValueError(f"timing_overrides gives line {li} two values")
        chosen[li] = how
    return chosen


def apply_timing_overrides(
    reconciled: TimedText,
    fine: TimedText,
    records: Sequence[Mapping[str, Any]],
    *,
    overrides: Mapping[str | int, str] | None,
) -> tuple[TimedText, list[dict[str, Any]]]:
    """Put recorded human judgements back over :func:`reconcile`'s result.

    ``overrides`` is per-song DATA, ``{"<line index>": "fine"}`` — the line's
    0-based position in the transcript ``fine`` was refined from (string keys,
    as JSON writes them, or ints). It belongs in the song's own spec beside
    the lyrics, never in code: it says "on THIS song, this line's vendor
    window is junk and the aligner's times sit on onsets" (muvid#150, used on
    five songs). Each value is one of :data:`TIMING_OVERRIDES`.

    ``reconciled`` and ``records`` are what ``reconcile(fine, coarse, ...)``
    returned; words are matched by position, so a line is restored exactly —
    even one :func:`unsung` dropped, since a person said it was sung. Only
    the named line changes: a neighbour :func:`disordered` flagged together
    with it keeps its vendor window unless it is named too. ``reconcile``'s
    records still say what reconcile did; these say what undid it. Returns
    the timing and one record per word whose timing changed (same keys as
    :func:`reconcile`'s; ``why`` is ``"override"``). Empty or ``None``
    ``overrides`` return ``reconciled`` unchanged.
    """
    if not overrides:
        return reconciled, []
    fine_lines = list(fine.lines())
    chosen = check_timing_overrides(overrides, len(fine_lines))

    by_index = {r["index"]: r for r in records}
    dropped = {k for k, r in by_index.items() if r["remedy"] == "drop"}
    fw, rw = list(fine.words()), iter(reconciled.words())
    kept: dict[int, Word] = {}
    for k, w in enumerate(fw):
        if k in dropped:
            continue
        got = next(rw, None)
        if got is None or got.text != w.text:
            raise ValueError(
                "reconciled does not come from fine and records: pass what "
                "reconcile(fine, ...) returned"
            )
        kept[k] = got
    if next(rw, None) is not None:
        raise ValueError("reconciled has more words than fine minus its drops")

    out: list[dict[str, Any]] = []
    lines: list[Line] = []
    k = 0
    for li, ln in enumerate(fine_lines):
        span = range(k, k + len(ln.words))
        k += len(ln.words)
        if li in chosen:
            for j in span:
                if j in by_index:  # reconcile changed it; the override undoes that
                    prev = by_index[j]
                    out.append(
                        {
                            "index": j,
                            "text": fw[j].text,
                            "fine": round(_word_start(fw[j]), 3),
                            "why": "override",
                            "detail": f"timing_overrides[{li}] = {chosen[li]!r}, "
                            f"undoing {prev['why']} ({prev['remedy']})",
                            "remedy": chosen[li],
                            "flagged_by": list(prev.get("flagged_by", ())),
                            "used": round(_word_start(fw[j]), 3),
                        }
                    )
            lines.append(ln)
        else:
            lines.append(replace(ln, words=tuple(kept[j] for j in span if j in kept)))
    restored = _rebuilt(fine, lines)
    result = replace(
        reconciled,
        sections=tuple(
            replace(sec, lines=tuple(ln for ln in sec.lines if ln.words))
            for sec in restored.sections
            if any(ln.words for ln in sec.lines)
        ),
    )
    return (_without_spans(result) if result != reconciled else result), out


def repair_spills(
    tt: TimedText,
    onsets: Sequence[float] | None,
    *,
    gap_s: float = LINE_GAP_S,
    min_step_s: float = SPILL_MIN_STEP_S,
    clear_s: float = SPILL_CLEAR_S,
    min_tail_s: float = SPILL_MIN_TAIL_S,
) -> tuple[TimedText, list[dict[str, Any]]]:
    """Pull a line's glyphs back off the NEXT line, where they aligned (muvid#155).

    Seen on a real song: ``ハット``'s ``ト`` aligned onto the next line's ``ト``.
    It also follows from :func:`reconcile` itself: a line sent back to its
    vendor window can end on a neighbour the aligner had right. A glyph (not
    a line's first) starting within ``gap_s`` of the next line's first glyph,
    or after it, has SPILLED. It moves to the first of ``onsets`` (the vocal
    stem's, see :func:`stem_onsets`) at least ``min_step_s`` after the glyph
    before it and ``clear_s`` before the next line — or, with none there,
    midway between that floor and ``gap_s`` before the next line, so it is
    never left spilled — and is marked ``measured=False``. Every glyph after
    the first spilled one moves with it: they share that room in equal
    slices, each taking the first onset in its own slice, so no glyph is
    left on the next line for want of room an earlier one took.

    Then, in that line only, nothing stays lit into the next line or over a
    moved glyph: the glyph before a moved one ends no later than it starts, a
    moved glyph ends by the next line, and each word spans its glyphs (from its
    first glyph's start, to its last glyph's end or ``min_tail_s`` past its
    start — CTC spans are spiky) and ends by the next line too. A glyph with
    no room before the next line (the line itself already sits on it) is left
    alone: moving it would put it before the glyph it follows, and a whole
    line on its neighbour is :func:`disordered`'s case, not a spill.

    Run it on :func:`reconcile`'s result (and after
    :func:`apply_timing_overrides`). Returns the timing — the very object
    passed in when nothing spilled — and one record per moved glyph: ``text``,
    ``line``, ``why`` (``"spilled"``), ``detail``, ``remedy`` (``"onset"`` or
    ``"midpoint"``), ``fine`` (its start before) and ``used`` (its start now).
    """
    ons = sorted(float(t) for t in (onsets if onsets is not None else ()))
    src = list(tt.lines())
    out: list[dict[str, Any]] = []
    fixed: list[Line] = []
    for ln, nxt in zip(src, [*src[1:], None]):
        flat = [g for w in ln.words for g in w.glyphs]
        if nxt is None or not nxt.words or len(flat) < 2:
            fixed.append(ln)
            continue
        t_next = min(_line_starts(nxt))
        hi = t_next - gap_s  # a glyph at or past this has spilled
        first = next((i for i in range(1, len(flat)) if flat[i].start >= hi), None)
        lo = None if first is None else flat[first - 1].start + min_step_s
        if first is None or lo >= hi:  # nothing spilled, or no room to move it
            fixed.append(ln)
            continue
        # Everything from the first spilled glyph on is read after it, so it
        # all moves, each into its own slice of [lo, hi): placed one at a time,
        # a glyph could use up the room the ones after it need (review of #157).
        tail = range(first, len(flat))
        width = (hi - lo) / len(tail)
        for j, i in enumerate(tail):
            a, b = lo + j * width, lo + (j + 1) * width
            g = flat[i]
            cand = [t for t in ons if a <= t < b and t <= t_next - clear_s]
            new = cand[0] if cand else (a + b) / 2
            out.append(
                {
                    "text": g.text,
                    "line": ln.text,
                    "why": "spilled",
                    "detail": f"starts {g.start:.2f} s, within {gap_s:.2f} s of "
                    f"the next line's {t_next:.2f} s or past it",
                    "remedy": "onset" if cand else "midpoint",
                    "fine": round(g.start, 3),
                    "used": round(new, 3),
                }
            )
            flat[i] = replace(g, start=new, measured=False)
        # in this line, nothing lit over the glyph after it, nor into the
        # next line — an EARLIER glyph's long span included (review of #157)
        for i in range(len(flat)):
            g = flat[i]
            stop = flat[i + 1].start if i + 1 < len(flat) else t_next
            flat[i] = replace(g, end=max(g.start, min(g.end, stop)))
        it = iter(flat)
        words = []
        for w in ln.words:
            gs = tuple(next(it) for _ in w.glyphs)
            if gs:
                start = min(w.start, gs[0].start)
                last = max(gs[-1].end, gs[-1].start + min_tail_s)
                end = max(start, gs[-1].end, min(w.end, last, t_next))
                w = replace(w, start=start, end=end, glyphs=gs)
            words.append(w)
        fixed.append(replace(ln, words=tuple(words)))
    return (_without_spans(_rebuilt(tt, fixed)), out) if out else (tt, out)


@dataclass(frozen=True, slots=True, kw_only=True)
class _SpanThresholds:
    """The level thresholds :func:`with_spans` cuts by (dB under the loud level)."""

    silence_db: float
    valley_db: float
    flat_db: float


@dataclass(frozen=True, slots=True, kw_only=True)
class _SearchWindow:
    """The frames searched for the cut before the onset ``t`` (round-to-nearest
    frame indices into ``level``): ``a`` to ``limit`` inclusive; a silence may
    be walked back down to ``floor``, and sound must return by ``limit``."""

    level: Any
    t: float
    a: int
    limit: int
    floor: int
    frame_s: float


def _search_window(
    level, t: float, floor_t: float, *, search_s: tuple[float, float], frame_s: float
) -> _SearchWindow | None:
    """The window around the onset ``t``, never before ``floor_t``; None when
    it holds fewer than three frames (no cut can be read from it)."""
    floor = max(round(floor_t / frame_s), 0)
    a = max(round((t - search_s[0]) / frame_s), floor)
    limit = min(round((t + search_s[1]) / frame_s), len(level) - 1)
    if limit - a + 1 < 3:
        return None
    return _SearchWindow(
        level=level, t=t, a=a, limit=limit, floor=floor, frame_s=frame_s
    )


def _silence_cut(win: _SearchWindow, th: _SpanThresholds):
    """``(end, begin, "silence")`` at the window's first quiet run, else None.

    The previous sound ends where the quiet run BEGAN (walked back below the
    window down to its floor: a silence can start before the search does), and
    the next starts where the sound returns — or at its own onset, when it does
    not return by the window's end.
    """
    lv, quiet_db = win.level, th.silence_db
    quiet = lv[win.a : win.limit + 1] < quiet_db
    if not quiet.any():
        return None
    q0 = win.a + int(quiet.argmax())
    while q0 - 1 >= win.floor and lv[q0 - 1] < quiet_db:
        q0 -= 1
    q1 = q0
    while q1 < win.limit and lv[q1 + 1] < quiet_db:
        q1 += 1
    end = q0 * win.frame_s
    begin = (q1 + 1) * win.frame_s if q1 < win.limit else win.t
    return end, max(begin, end), "silence"


def _valley_cut(win: _SearchWindow, th: _SpanThresholds):
    """``(at, at, "valley")`` at the flat bottom of a dip ``valley_db`` under the
    loudest frame on BOTH sides, cut where the bottom begins (in kana the
    consonant belongs to the NEXT mora); else None."""
    w = win.level[win.a : win.limit + 1]
    m = int(w.argmin())
    if not 0 < m < len(w) - 1:
        return None
    if min(w[:m].max(), w[m + 1 :].max()) - w[m] < th.valley_db:
        return None
    flat = m
    while flat > 0 and w[flat - 1] <= w[m] + th.flat_db:
        flat -= 1
    at = (win.a + flat) * win.frame_s
    return at, at, "valley"


#: The cuts :func:`with_spans` tries at a boundary, in order; the first that
#: finds one wins. Without either, the boundary is ``legato`` (or ``next``
#: before a sokuon).
_CUTS = (_silence_cut, _valley_cut)


def with_spans(
    tt: TimedText,
    *,
    vocals: Path | str | None = None,
    max_span_s: float = GLYPH_SPAN_MAX_S,
    search_s: tuple[float, float] = SPAN_SEARCH_S,
    silence_db: float = SPAN_SILENCE_DB,
    valley_db: float = SPAN_VALLEY_DB,
    flat_db: float = SPAN_VALLEY_FLAT_DB,
    frame_s: float = SPAN_FRAME_S,
) -> TimedText:
    """Give every sung glyph a ``span``: where its sound runs (muvid#149).

    A glyph's ``end`` is nominal (20-140 ms after its onset), so a consumer that
    plays or wipes per glyph needs this. Each :class:`~muvid.lyricvid.timed_text.Span`
    runs from the glyph's onset to the next sung glyph's onset, capped at
    ``max_span_s`` after the glyph's ``start``; its ``cut`` says how that
    trailing boundary was decided. ``ー`` extends the glyph before it (it is no
    boundary and has no span); ``ッ`` ends it (its sokuon is silence) and has no
    span; punctuation, a glyph with ``sung=False`` and one with no finite
    ``start`` have none either and are no boundary.

    With ``vocals`` (the separated vocal stem; none is needed) each boundary is
    refined from the stem's levels, searched from ``search_s[0]`` before the
    next onset to ``search_s[1]`` after it, never before the glyph's own span
    start: ``silence`` (the previous span ends where the sound died and the next
    starts where it returns, or at its own onset if it does not return within
    the search), ``valley`` (cut at the flat bottom of a dip between the
    syllables) or ``legato`` (no clean cut: the onset, flagged as such). Before a
    ``ッ`` a silence or valley is used the same way, else ``next``. Without a
    stem every boundary is ``next``. Any end clamped at ``max_span_s`` is
    ``cap``. A span may start later than ``start`` (after a silence); ``start``
    is not moved. Spans never overlap, and times are rounded to the ms. A burst
    (a spectral-flux attack) is not detected: those boundaries read as
    ``legato``.

    Run it LAST, after :func:`reconcile`, :func:`apply_timing_overrides` and
    :func:`repair_spills`: it recomputes every span from scratch (running it
    twice changes nothing), and each of those passes clears EVERY span when it
    changes anything, since a span depends on its neighbours.
    """
    if max_span_s <= 0 or frame_s <= 0:
        raise ValueError("with_spans needs max_span_s > 0 and frame_s > 0")
    level = _frame_levels_db(vocals, frame_s=frame_s) if vocals is not None else None
    th = _SpanThresholds(silence_db=silence_db, valley_db=valley_db, flat_db=flat_db)
    # a cut never lands further past an onset than a span may run
    search = (search_s[0], min(search_s[1], max_span_s))

    flat = [g for ln in tt.lines() for w in ln.words for g in w.glyphs]

    def spanned(g: Glyph) -> bool:
        return g.sung and _has_sound(g) and math.isfinite(g.start)

    def sokuon(g: Glyph) -> bool:  # ends the sound before it: the closure is silence
        return g.sung and bool(g.text) and g.text in _SOKUON and math.isfinite(g.start)

    # (flat index, onset) of every glyph that has a span or ends one, in order
    marks = [(i, g.start) for i, g in enumerate(flat) if spanned(g) or sokuon(g)]
    spans: dict[int, Span] = {}
    begin: dict[int, float] = {}  # a glyph's span start, when a cut moved it
    last_end = -math.inf  # spans never overlap, whatever sits between two glyphs
    for (i, _), nxt in zip(marks, [*marks[1:], None]):
        g = flat[i]
        if not spanned(g):
            continue
        s0 = max(begin.get(i, g.start), last_end)
        cap = g.start + max_span_s
        if nxt is None or nxt[1] >= cap:
            spans[i] = Span(round(s0, 3), round(max(cap, s0), 3), "cap")
            last_end = max(cap, s0)
            continue
        j, t = nxt
        end, nxt_begin, how = t, t, "next"
        if level is not None:
            win = _search_window(
                level, t, max(s0, g.start) + frame_s, search_s=search, frame_s=frame_s
            )
            found = win and next(filter(None, (cut(win, th) for cut in _CUTS)), None)
            if found:
                end, nxt_begin, how = found
            elif spanned(flat[j]):
                how = "legato"
        if end > cap:
            end, how = cap, "cap"
        end = max(end, s0)
        spans[i] = Span(round(s0, 3), round(end, 3), how)
        last_end = end
        if spanned(flat[j]):
            begin[j] = max(nxt_begin, end)

    return _map_glyphs(tt, lambda i, g: replace(g, span=spans.get(i)))


def glyph_rows(tt: TimedText) -> Iterable[dict[str, Any]]:
    """One flat record per glyph, for a table or a quick look."""
    for li, ln in enumerate(tt.lines()):
        for wi, w in enumerate(ln.words):
            for g in w.glyphs:
                yield {
                    "line": li,
                    "word": wi,
                    "text": g.text,
                    "start": g.start,
                    "end": g.end,
                    "measured": g.measured,
                    "sung": g.sung,
                    "span": g.span and (g.span.start, g.span.end),
                    "cut": g.span and g.span.cut,
                }
