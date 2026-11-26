"""The clips' own sound under the song — and the song kept removable.

A music video's audio is the clean song and nothing else (the assembler mutes every clip).
A promo, a recap or a class video is different: the picture is cut to the music, but the
people in it talk, breathe and laugh, and that sound ("production sound", "nat sound") is
part of what sells it. Editors keep it on its own track under a music bed and duck the
music when someone speaks; and because the music is the part most often replaced (a
licence, a client's taste, a better track found later), they deliver it as **stems** —
the music, the production sound, and the mix — rather than one baked track.

This module is that, for a rendered footage edit:

- :func:`song_stem` is the music as the render plays it (cut to the edit's window, faded
  at its tail when the window ends early), taken from the song itself, not decoded back
  out of the render (each AAC pass shifts audio by the encoder's priming).
- :func:`clip_sound_track` builds the production-sound stem from the same cuts the
  picture was rendered from: each video cut contributes its own audio for exactly its span
  (from its in-point, on the clip's own clock: an audio stream that starts after its
  video is padded, not pulled early) at its own level (``EdlEntry.sound_db``), with a
  short fade at each edge so a cut does not click; a photo, a gap, a retimed cut (slow
  motion has no sync sound) or a clip with no audio stream is silence. Its length is the
  render's, sample for sample.
- the clips' sound is split in two stems by each cut's level: **dialogue** (the cuts
  meant to be heard: soundbites, nat pops) and **nat** (the room under every other
  shot). :func:`mix_under` raises the dialogue toward a speech level, ducks the music
  under it alone (``mixing.audio.duck_audio``, the fleet's one ducker) by as much as
  puts the speech :data:`SPEECH_OVER_MUSIC_DB` over the music, lays the nat sound in as a
  bed, and limits the sum to :data:`PEAK_DBFS`.
- :func:`mux_audio` puts one audio track on a picture, compensating the AAC encoder's
  priming so the sound lands on the frame it was cut to.

The render op (:func:`muvid.footage.service.render`, ``sound="song_and_clips"``) is
their one caller and records the stems and the mix parameters beside ``final.mp4``.
Research behind the numbers: ``misc/docs/research/general/promo_video_editing_and_music.md``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Sequence

#: Sample rate and channel count of every stem — the delivery contract's (aac 48 kHz 2ch).
SAMPLE_RATE = 48_000
CHANNELS = 2
#: Fade at each edge of a cut's sound, so a hard cut in the picture is not a click in the
#: sound. Short enough to keep a word that starts on the cut intelligible.
EDGE_FADE_S = float(os.environ.get("MUVID_SOUND_EDGE_FADE_S", "0.04"))
#: The level of a cut's own sound when its edit entry names none (``sound_db`` ``None``).
DEFAULT_CLIP_SOUND_DB = float(os.environ.get("MUVID_SOUND_DEFAULT_CLIP_DB", "0"))
#: A cut whose own sound is at least this loud (dB, its ``sound_db``) is DIALOGUE: what
#: the people in it say is meant to be heard (a soundbite, a nat-sound pop). Quieter cuts
#: are NAT sound: the room as a bed under the music. ``None`` (the default level, 0 dB)
#: is dialogue, so a render whose cuts name no level ducks on all of them, as before.
DIALOGUE_MIN_DB = float(os.environ.get("MUVID_SOUND_DIALOGUE_MIN_DB", "-6"))
#: Dialogue is raised (never lowered) toward this speech level (dBFS, median RMS of its
#: active frames) — a phone held across a room records a voice at -35..-30 dBFS — by at
#: most :data:`MAX_DIALOGUE_GAIN_DB`.
SPEECH_TARGET_DBFS = float(os.environ.get("MUVID_SOUND_SPEECH_TARGET_DBFS", "-20"))
MAX_DIALOGUE_GAIN_DB = 18.0
#: Speech sits at least this far over the music under it (dB; research rule 17: speech
#: 12-15 LU over the music, at least 10). The duck is sized to reach it, between
#: :data:`DUCK_DB` (the least it ducks) and :data:`MAX_DUCK_DB` (the most).
SPEECH_OVER_MUSIC_DB = float(os.environ.get("MUVID_SOUND_SPEECH_OVER_MUSIC_DB", "12"))
DUCK_DB = float(os.environ.get("MUVID_SOUND_DUCK_DB", "-8"))
MAX_DUCK_DB = -30.0
#: Inside the dialogue stem (only the cuts meant to be heard), a frame louder than this
#: (dBFS) is speech for the ducker: the whole of a soundbite, its pauses included, holds
#: the music down. Silence (the other cuts) is far below it.
DIALOGUE_ACTIVE_DBFS = float(os.environ.get("MUVID_SOUND_DIALOGUE_ACTIVE_DBFS", "-55"))
#: The speech level of the dialogue: this percentile of its active frames' RMS (dB), high
#: enough that the pauses between words do not drag it down.
SPEECH_PERCENTILE = 75.0
#: The mix's sample peak never exceeds this (dBFS): headroom for the AAC encode, the
#: research's -1 dBTP delivery rule approximated on samples.
PEAK_DBFS = -1.0
#: Samples the AAC encoder prepends ("priming"). Without an edit list (muvid's delivery
#: contract writes none) a player plays them, so the sound would land 21.3 ms late at
#: 48 kHz; :func:`aac_priming_filter` trims them off the input to compensate.
AAC_PRIMING_SAMPLES = 1024


def aac_priming_filter(
    *,
    priming_samples: int = AAC_PRIMING_SAMPLES,
    sample_rate: int = SAMPLE_RATE,
) -> str:
    """The ``-af`` links that put an AAC encode's sound back on its picture (muvid#379).

    The encoder prepends ``priming_samples`` of priming, and a file with no edit list
    (the delivery contract) plays them, so every AAC pass lands the sound 21.3 ms
    late at 48 kHz; measured with a click at 1.000 s, decoded at 1.021 s after one
    pass and 1.043 s after two. Trimming as many samples off the INPUT cancels it,
    and padding them back at the tail keeps the length. ``aresample`` comes first so
    ``start_sample`` counts samples at the rate the encoder primes at, whatever rate
    the input has. Append it LAST to a chain whose timeline is the delivered one (a
    fade's ``st`` is read before the trim). Every FOOTAGE AAC encode goes through
    it: :func:`mux_audio` and :func:`muvid.footage.assemble._audio_args`. The
    visualizer and the lyric-video renderers do not yet (muvid#385)."""
    return (
        f"aresample={sample_rate},"
        f"atrim=start_sample={priming_samples},"
        f"apad=pad_len={priming_samples}"
    )


_STILL_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}


def _has_audio(path: str, cache: dict) -> bool:
    if path not in cache:
        from muvid.visualize.ffmpeg import probe

        try:
            streams = probe(path).get("streams", [])
        except Exception:  # an unreadable source is silent here; the picture says why
            streams = []
        cache[path] = any(s.get("codec_type") == "audio" for s in streams)
    return cache[path]


def _sounding(cut, cache: dict) -> bool:
    """Whether this cut contributes its own sound (else it is silence)."""
    path = getattr(cut, "clip_path", "") or ""
    if not getattr(cut, "clip_id", "") or not path:
        return False  # a gap
    if Path(path).suffix.lower() in _STILL_SUFFIXES:
        return False
    if abs(float(getattr(cut, "rate", 1.0) or 1.0) - 1.0) > 1e-6:
        return False  # retimed: its sound would be pitched or stretched — keep it out
    return _has_audio(path, cache)


def song_stem(
    song_path,
    out_path,
    *,
    start_s: float,
    duration_s: float,
    fade_out_s: float = 0.0,
    sample_rate: int = SAMPLE_RATE,
) -> Path:
    """The music stem: ``duration_s`` of the song from ``start_s`` (wav), faded out over
    its last ``fade_out_s`` seconds — the same window and fade the render applies."""
    from muvid.visualize.ffmpeg import run_ffmpeg

    out = Path(out_path)
    af = [f"aresample={sample_rate}", "apad", f"atrim=0:{duration_s:.6f}"]
    if fade_out_s > 0:
        af.append(
            f"afade=t=out:st={max(0.0, duration_s - fade_out_s):.6f}:d={fade_out_s:.6f}"
        )
    head = ["-ss", f"{start_s:.6f}"] if start_s > 1e-3 else []
    run_ffmpeg(
        [
            *head,
            "-i",
            str(song_path),
            "-map",
            "0:a:0",
            "-af",
            ",".join(af),
            "-ac",
            str(CHANNELS),
            "-c:a",
            "pcm_s16le",
            str(out),
        ]
    )
    return out


def clip_sound_track(
    cuts: Sequence,
    out_path,
    *,
    edge_fade_s: float = EDGE_FADE_S,
    default_db: float = DEFAULT_CLIP_SOUND_DB,
    sample_rate: int = SAMPLE_RATE,
    keep=None,
) -> Path:
    """Write the production-sound stem of ``cuts`` (``AssemblyCut``-like: ``song_start``,
    ``song_end``, ``clip_id``, ``clip_in``, ``clip_path``, ``rate``, ``sound_db``) to
    ``out_path`` (wav).

    The stem starts at ``cuts[0].song_start`` and is exactly as long as the cuts span: each
    sounding cut is its clip's audio from ``clip_in`` for the cut's duration at its
    ``sound_db`` (``default_db`` when ``None``), padded with silence where the clip's
    audio starts late or runs out; every other cut is silence, and so is every cut
    ``keep(cut, level)`` rejects (how the dialogue and nat stems are split).

    >>> clip_sound_track([], "x.wav")
    Traceback (most recent call last):
    ...
    ValueError: no cuts
    """
    from muvid.visualize.ffmpeg import require_ffmpeg, run_ffmpeg

    if not cuts:
        raise ValueError("no cuts")
    require_ffmpeg("ffmpeg")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cache: dict = {}
    inputs: list[str] = []
    chains: list[str] = []
    labels: list[str] = []
    fmt = f"aformat=sample_rates={sample_rate}:channel_layouts=stereo"
    n_in = 0
    for i, c in enumerate(cuts):
        dur = float(c.song_end) - float(c.song_start)
        if dur <= 0:
            continue
        level = getattr(c, "sound_db", None)
        level = default_db if level is None else float(level)
        if _sounding(c, cache) and (keep is None or keep(c, level)):
            inputs += ["-ss", f"{max(0.0, float(c.clip_in)):.6f}", "-t", f"{dur:.6f}"]
            inputs += ["-i", str(c.clip_path)]
            fade = min(edge_fade_s, dur / 4)
            # first_pts=0 + async: an audio stream that starts after the seek point is
            # padded with silence at its head instead of being pulled early.
            chains.append(
                f"[{n_in}:a:0]{fmt},aresample=async=1:first_pts=0,"
                f"apad=whole_dur={dur:.6f},atrim=0:{dur:.6f},asetpts=PTS-STARTPTS,"
                f"volume={level:.2f}dB,afade=t=in:d={fade:.4f},"
                f"afade=t=out:st={dur - fade:.6f}:d={fade:.4f}[s{i}]"
            )
            n_in += 1
        else:
            chains.append(
                f"anullsrc=r={sample_rate}:cl=stereo,atrim=0:{dur:.6f},"
                f"asetpts=PTS-STARTPTS[s{i}]"
            )
        labels.append(f"[s{i}]")
    graph = ";".join(chains) + f";{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]"
    run_ffmpeg(
        [
            *inputs,
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            "-ar",
            str(sample_rate),
            "-ac",
            str(CHANNELS),
            "-c:a",
            "pcm_s16le",
            str(out),
        ]
    )
    return out


def is_dialogue(cut, level: float) -> bool:
    """A cut whose sound is meant to be heard (at or over :data:`DIALOGUE_MIN_DB`)."""
    return level >= DIALOGUE_MIN_DB


def is_nat(cut, level: float) -> bool:
    return not is_dialogue(cut, level)


def _frame_db(x, sr: int, frame_s: float = 0.02):
    """Per-frame RMS level (dBFS) of a mono signal."""
    import numpy as np

    n = max(1, int(frame_s * sr))
    k = len(x) // n
    if k == 0:
        return np.zeros(0)
    rms = np.sqrt((x[: k * n].reshape(k, n) ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-6))


def _active(level, *, threshold_dbfs: float):
    """Frames of a stem louder than ``threshold_dbfs``."""
    return level > threshold_dbfs


def read_wav(path):
    """``(samples, rate)`` of a PCM wav: float in [-1, 1], shape ``(n, channels)``.
    Stdlib ``wave`` + numpy, so the stems need no audio library beyond ffmpeg."""
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as w:
        rate, ch, width, n = (
            w.getframerate(),
            w.getnchannels(),
            w.getsampwidth(),
            w.getnframes(),
        )
        raw = w.readframes(n)
    if width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    elif width == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    else:
        raise ValueError(f"{path}: {8 * width}-bit wav is not read here")
    return x.reshape(-1, ch), rate


def write_wav(path, samples, rate: int) -> None:
    """Write float samples (``(n, channels)`` or ``(n,)``, clipped to [-1, 1]) as 16-bit
    PCM wav."""
    import wave

    import numpy as np

    x = np.asarray(samples, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    pcm = np.round(np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())


_read = read_wav


def mix_under(
    music,
    dialogue,
    nat,
    out_path,
    *,
    clips_out=None,
    speech_target_dbfs: float = SPEECH_TARGET_DBFS,
    speech_over_music_db: float = SPEECH_OVER_MUSIC_DB,
    duck_db: float = DUCK_DB,
    max_duck_db: float = MAX_DUCK_DB,
    active_dbfs: float = DIALOGUE_ACTIVE_DBFS,
    peak_dbfs: float = PEAK_DBFS,
) -> dict:
    """Mix ``music`` over the clips' sound, split as ``dialogue`` and ``nat`` (wav
    stems of equal length), into ``out_path``:

    - the dialogue is raised toward ``speech_target_dbfs`` (never lowered), and the music
      ducked under it (``mixing.audio.duck_audio``, keyed on the dialogue alone) by as much
      as puts the speech ``speech_over_music_db`` over the music, between ``duck_db`` and
      ``max_duck_db``;
    - the nat sound (the room under the other shots) is laid in as it is, never ducking
      anything;
    - all of it summed in floating point and scaled down (never up) so the peak stays
      at or under ``peak_dbfs``.

    ``clips_out`` (optional) receives the clips' sound as mixed (dialogue at its gain +
    nat): with the ducked music it sums to the mix. Returns the parameters that made it
    (dialogue gain, duck depth, speech and music levels, the limiter's gain)."""
    import numpy as np
    from mixing.audio import duck_audio

    m, sr = _read(music)
    d, sr_d = _read(dialogue)
    n_, sr_n = _read(nat)
    if not sr == sr_d == sr_n:
        raise ValueError(f"stems differ in sample rate ({sr}, {sr_d}, {sr_n})")

    def fit(x):
        x = x[: len(m)]
        return np.pad(x, ((0, len(m) - len(x)), (0, 0))) if len(x) < len(m) else x

    d, n_ = fit(d), fit(n_)
    d_level = _frame_db(d.mean(axis=1), sr)
    active = _active(d_level, threshold_dbfs=active_dbfs)
    threshold = active_dbfs
    params = {
        "dialogue_gain_db": 0.0,
        "duck_db": 0.0,
        "threshold_db": round(threshold, 2),
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    bed = m
    gain = 1.0
    if active.any():
        speech = float(np.percentile(d_level[active], SPEECH_PERCENTILE))
        g_db = float(np.clip(speech_target_dbfs - speech, 0.0, MAX_DIALOGUE_GAIN_DB))
        m_level = _frame_db(m.mean(axis=1), sr)[: len(d_level)]
        music_there = (
            float(np.median(m_level[active[: len(m_level)]])) if len(m_level) else -80.0
        )
        want = (speech + g_db) - speech_over_music_db - music_there
        depth = float(np.clip(min(duck_db, want), max_duck_db, 0.0))
        ducked = out.with_name(f".{out.stem}.ducked.wav")
        try:
            duck_audio(
                str(music),
                str(dialogue),
                duck_db=depth,
                threshold_db=threshold,
                output=str(ducked),
            )
            bed, _ = _read(ducked)
            bed = fit(bed)
        finally:
            ducked.unlink(missing_ok=True)
        gain = 10 ** (g_db / 20)
        params.update(
            dialogue_gain_db=round(g_db, 2),
            duck_db=round(depth, 2),
            speech_dbfs=round(speech, 2),
            music_under_speech_dbfs=round(music_there, 2),
        )
    clips = d * gain + n_
    mix = bed + clips
    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    limit = 10 ** (peak_dbfs / 20)
    scale = min(1.0, limit / peak) if peak > 0 else 1.0
    write_wav(out, mix * scale, sr)
    if clips_out is not None:
        write_wav(clips_out, clips, sr)
    params["limiter_gain_db"] = round(20 * np.log10(scale), 2)
    return params


def mux_audio(
    video,
    audio,
    out_path,
    *,
    bitrate: str = "192k",
    priming_samples: int = AAC_PRIMING_SAMPLES,
) -> Path:
    """``video``'s picture (stream-copied) with ``audio`` as its one audio track (aac),
    at the video's length; the encoder's priming is trimmed off the input (and the tail
    padded back), so the sound is where it was on the picture."""
    from muvid.visualize.ffmpeg import run_ffmpeg

    out = Path(out_path)
    af = aac_priming_filter(priming_samples=priming_samples)
    run_ffmpeg(
        [
            "-i",
            str(video),
            "-i",
            str(audio),
            "-map",
            "0:v",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-af",
            af,
            "-c:a",
            "aac",
            "-b:a",
            bitrate,
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "-shortest",
            "-use_editlist",
            "0",
            "-movflags",
            # keeps the copied video starting at 0 (muvid#384); without it the
            # B-frame delay is a start offset and -shortest drops the last frames
            "+faststart+negative_cts_offsets",
            str(out),
        ]
    )
    return out


def mix_params(*, default_db: float = DEFAULT_CLIP_SOUND_DB, **measured) -> dict:
    """What a ``song_and_clips`` render records about its mix, so a later change of these
    defaults is visible against an old render (and a re-render can reproduce it)."""
    return {
        "default_clip_db": default_db,
        "dialogue_min_db": DIALOGUE_MIN_DB,
        "speech_target_dbfs": SPEECH_TARGET_DBFS,
        "speech_over_music_db": SPEECH_OVER_MUSIC_DB,
        "edge_fade_s": EDGE_FADE_S,
        "peak_dbfs": PEAK_DBFS,
        **measured,
    }


def silent_unless_set(cuts, mute: "set[str]", *, level: Optional[float] = -60.0):
    """``cuts`` with every cut of a ``mute`` clip that names no ``sound_db`` set to
    ``level`` — the clips whose own audio is a recording of the song (a music video's
    synced footage), which under the master would double it."""
    from dataclasses import replace

    return [
        replace(c, sound_db=level)
        if c.clip_id in mute and getattr(c, "sound_db", None) is None
        else c
        for c in cuts
    ]
