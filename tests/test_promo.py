"""Tests for the promo cut (:mod:`muvid.footage.promo`, ``service.propose_promo``) and the
clips'-own-sound render (:mod:`muvid.footage.sound`, ``render(sound="song_and_clips")``).

The planner tests are pure. The service tests reuse the declared-offset project of
``test_footage_service`` (no ffmpeg; the song's analysis is given). The sound tests encode
tiny synthetic clips and are marked ``needs_ffmpeg``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from muvid.footage.promo import Shot, ending_span, plan_promo
from muvid.montage.analysis import Analysis

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg + ffprobe")


def _song(duration=40.0, bar=2.0, sections=()):
    n = int(duration / 0.5)
    return Analysis(
        duration=duration,
        tempo_bpm=120.0,
        beats=tuple(i * 0.5 for i in range(n)),
        downbeats=tuple(float(i * bar) for i in range(int(duration / bar))),
        sections=tuple(sections),
    )


# -- the planner ------------------------------------------------------------------


def test_every_boundary_is_a_bar_line_and_holds_follow_their_targets():
    a = _song()
    shots = [Shot("a", hold_s=2.0), Shot("b", hold_s=6.0), Shot("c", hold_s=4.0)]
    p = plan_promo(a, shots, clip_durations={"a": 30, "b": 30, "c": 30}, span=(0.0, 12.0),
                   cut_lead_s=0.0)
    spans = [(e.song_start, e.song_end) for e in p.entries]
    assert spans == [(0.0, 2.0), (2.0, 8.0), (8.0, 12.0)]
    assert all(t in a.downbeats or t == 12.0 for _, t in spans)
    assert p.report["average_shot_s"] == 4.0


def test_a_shot_is_never_longer_than_its_clip():
    p = plan_promo(_song(), [Shot("short", hold_s=8.0), Shot("long")],
                   clip_durations={"short": 3.0, "long": 60.0}, span=(0.0, 8.0))
    first = p.entries[0]
    assert first.song_end - first.song_start <= 3.0


def test_a_given_in_point_is_kept_and_bounds_the_hold():
    p = plan_promo(_song(), [Shot("a", source_in=7.0), Shot("b")],
                   clip_durations={"a": 10.0, "b": 60.0}, span=(0.0, 8.0))
    assert p.entries[0].source_in == 7.0 or p.entries[0].song_end <= 3.0
    assert p.entries[0].song_end - p.entries[0].song_start <= 3.0


def test_phrase_starts_are_preferred_over_other_bars():
    # bars every 2 s, phrases (4 bars) every 8 s: a 16 s window with two 8 s-ish shots
    p = plan_promo(_song(), [Shot("a", hold_s=7.0), Shot("b", hold_s=9.0)],
                   clip_durations={"a": 60, "b": 60}, span=(0.0, 16.0), cut_lead_s=0.0)
    assert p.entries[0].song_end == 8.0  # the phrase start, not the 7 s target's bar
    assert p.report["on_phrase"] == 1


def test_hard_cuts_by_default_and_a_dissolve_into_a_calm_shot_on_a_phrase():
    a = _song()
    durs = {"a": 60, "b": 60, "c": 60}
    p = plan_promo(a, [Shot("a", hold_s=8.0), Shot("b", hold_s=8.0, role="flow"),
                       Shot("c", hold_s=8.0, role="calm")], clip_durations=durs, span=(0.0, 24.0))
    assert [e.transition is not None for e in p.entries] == [False, False, True]
    assert abs(p.entries[2].transition.duration_s - 0.5) < 1e-9  # one beat at 120 BPM
    forced = plan_promo(a, [Shot("a", hold_s=8.0), Shot("b", hold_s=8.0, transition="dissolve"),
                            Shot("c", hold_s=8.0, role="calm", transition="cut")],
                        clip_durations=durs, span=(0.0, 24.0))
    assert [e.transition is not None for e in forced.entries] == [False, True, False]
    first = plan_promo(a, [Shot("a", role="calm", transition="dissolve"), Shot("b")],
                       clip_durations=durs, span=(0.0, 8.0))
    assert first.entries[0].transition is None


def test_inner_cuts_come_a_frame_early_and_the_ends_stay_put():
    p = plan_promo(_song(), [Shot("a", hold_s=4.0), Shot("b", hold_s=4.0)],
                   clip_durations={"a": 60, "b": 60}, span=(0.0, 8.0))
    assert p.entries[0].song_start == 0.0 and p.entries[-1].song_end == 8.0
    assert p.entries[0].song_end == p.entries[1].song_start == 3.967


def test_too_many_shots_for_the_window_is_refused_with_the_reason():
    with pytest.raises(ValueError, match="cannot fill"):
        plan_promo(_song(), [Shot(c) for c in "abcdefgh"],
                   clip_durations=dict.fromkeys("abcdefgh", 60.0), span=(0.0, 6.0))


def test_shot_from_dict_refuses_unknown_fields():
    with pytest.raises(ValueError, match="unknown shot field"):
        Shot.from_dict({"clip_id": "a", "hold": 3})
    with pytest.raises(ValueError, match="transition"):
        Shot.from_dict({"clip_id": "a", "transition": "wipe"})


def test_ending_span_ends_with_the_song_and_starts_on_a_phrase():
    a = _song(duration=100.0)
    start, end = ending_span(a, length_s=60.0, duration=100.0)
    assert end == 100.0 and start == 40.0
    assert ending_span(a, length_s=200.0, duration=100.0) == (0.0, 100.0)


# -- the service op ----------------------------------------------------------------


@pytest.fixture
def fp(tmp_path, monkeypatch):
    pytest.importorskip("nw")
    from muvid.footage import service
    from muvid.footage.workspace import FootageWorkspace

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "data"))
    proj = FootageWorkspace.for_email("u@x.com").create_project("p")
    song = tmp_path / "song.wav"
    song.write_bytes(b"RIFF-song")
    service.set_song(proj, path=str(song), duration_s=30.0)
    for cid in ("A", "B", "C"):
        clip = tmp_path / f"{cid}.mp4"
        clip.write_bytes(f"clip-{cid}".encode())
        service.add_clip(proj, path=str(clip), clip_id=cid, duration_s=20.0)
    monkeypatch.setattr(service, "song_analysis", lambda fp: _song(duration=30.0))
    monkeypatch.setattr(service, "_activity_envelope", lambda fp, src: None)
    import muvid.footage.music_cut as mc

    monkeypatch.setattr(mc, "display_size", lambda path: None)
    return proj


def test_propose_promo_saves_an_edit_of_the_chosen_shots_in_order(fp):
    from muvid.footage import service

    out = service.propose_promo(
        fp,
        shots=[{"clip_id": "B", "role": "hook"}, {"clip_id": "A"}, {"clip_id": "C", "role": "close"}],
        length_s=12.0,
        name="Promo",
    )
    cuts = [e for e in out["edl"] if e["clip_id"]]
    assert [c["clip_id"] for c in cuts] == ["B", "A", "C"]
    assert out["span"] == [16.0, 30.0]  # ends with the song, starts on the nearest phrase
    assert all(c.get("source_in") is not None for c in cuts)
    assert out["promo"]["shots"][0]["role"] == "hook"
    assert service.get_edit(fp, edit_id=out["edit_id"])["how_made"] == "promo cut"


def test_propose_promo_refuses_unknown_clips_and_bad_shots(fp):
    from muvid.footage import service
    from muvid.footage.errors import FootageError

    with pytest.raises(FootageError, match="unknown clip"):
        service.propose_promo(fp, shots=[{"clip_id": "Z"}])
    with pytest.raises(FootageError, match="bad shot"):
        service.propose_promo(fp, shots=[{"clip_id": "A", "colour": "red"}])
    with pytest.raises(FootageError, match="non-empty"):
        service.propose_promo(fp, shots=[])


def test_render_with_the_clips_sound_records_its_stems(fp, monkeypatch):
    import muvid.footage.assemble as A
    import muvid.visualize as V
    from muvid.footage import service
    from muvid.footage.errors import FootageError

    def fake_assemble(cuts, song, out, canvas, on_note=None, **kw):
        Path(out).write_bytes(b"video")
        return Path(out)

    monkeypatch.setattr(A, "assemble_music_video", fake_assemble)
    monkeypatch.setattr(V, "verify_video", lambda *a, **k: [])
    monkeypatch.setattr(V, "failures", lambda c: [])
    monkeypatch.setattr(V, "report", lambda c: "ok")
    seen = {}

    def fake_stems(fp_, render_dir, video, cuts, **kw):
        seen["cuts"] = [c.clip_id for c in cuts]
        stems = {k: str(render_dir / f"{k}.wav")
                 for k in ("music", "dialogue", "nat", "clips", "mix", "no_music")}
        return stems, {"duck_db": -12.0}

    monkeypatch.setattr(service, "_with_clip_sound", fake_stems)
    out = service.propose_promo(fp, shots=[{"clip_id": "A"}, {"clip_id": "B"}], length_s=8.0)
    plain = service.render(fp, edit_id=out["edit_id"])
    assert "stems" not in plain and "sound" not in plain
    meta = service.render(fp, edit_id=out["edit_id"], sound="song_and_clips")
    assert meta["sound"] == "song_and_clips"
    assert set(meta["stems"]) == {"music", "dialogue", "nat", "clips", "mix", "no_music"}
    assert all(not Path(v).is_absolute() for v in meta["stems"].values())
    assert seen["cuts"] == ["A", "B"] and meta["mix"] == {"duck_db": -12.0}
    with pytest.raises(FootageError, match="sound must be one of"):
        service.render(fp, edit_id=out["edit_id"], sound="karaoke")


# -- the sound itself (real ffmpeg) --------------------------------------------------


def _clip(path: Path, *, seconds: float, freq: int, audio: bool = True) -> Path:
    args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
            f"color=c=gray:s=64x112:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
                 "-c:a", "aac", "-shortest"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(args, check=True)
    return path


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip())


@needs_ffmpeg
def test_the_clips_sound_track_is_the_cuts_sound_in_order_and_exactly_as_long(tmp_path):
    from muvid.footage.edl import AssemblyCut
    from muvid.footage.sound import clip_sound_track, mix_under

    a = _clip(tmp_path / "a.mp4", seconds=4, freq=440)
    mute = _clip(tmp_path / "m.mp4", seconds=4, freq=0, audio=False)
    still = tmp_path / "s.jpg"
    still.write_bytes(b"")
    cuts = [
        AssemblyCut(10.0, 11.5, "a", 1.0, str(a)),
        AssemblyCut(11.5, 12.5, "m", 0.0, str(mute)),
        AssemblyCut(12.5, 13.0, "s", 0.0, str(still)),
        AssemblyCut(13.0, 14.0, "", 0.0, ""),
        AssemblyCut(14.0, 16.0, "a", 3.5, str(a)),  # runs past the clip's end: padded
    ]
    out = clip_sound_track(cuts, tmp_path / "clips.wav")
    assert abs(_duration(out) - 6.0) < 0.01

    import numpy as np
    import soundfile as sf

    x, sr = sf.read(str(out))
    x = np.abs(x).mean(axis=1)
    loud = lambda t0, t1: float(x[int(t0 * sr):int(t1 * sr)].mean())  # noqa: E731
    assert loud(0.2, 1.3) > 0.05  # the tone
    assert loud(1.6, 3.9) < 1e-4  # no audio stream, a photo, a gap: silence
    music = tmp_path / "music.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=220:duration=6", "-ar", "48000", "-ac", "2", str(music)],
                   check=True)
    silent = tmp_path / "silent.wav"
    sf.write(str(silent), np.zeros((6 * 48000, 2)), 48000)
    params = mix_under(music, out, silent, tmp_path / "mix.wav", clips_out=tmp_path / "c2.wav")
    assert abs(_duration(tmp_path / "mix.wav") - 6.0) < 0.02
    assert params["limiter_gain_db"] <= 0 and params["duck_db"] <= 0
    y, _ = sf.read(str(tmp_path / "mix.wav"))
    assert np.abs(y).max() <= 10 ** (-1 / 20) + 1e-3  # limited to -1 dBFS


def test_soundbites_play_at_full_level_and_other_shots_as_a_bed():
    from muvid.footage.promo import BED_SOUND_DB  # noqa: F401 (read below)

    p = plan_promo(_song(), [Shot("a", role="soundbite"), Shot("b", role="flow"),
                             Shot("c", sound_db=-6.0)],
                   clip_durations=dict.fromkeys("abc", 60.0), span=(0.0, 12.0))
    assert [e.sound_db for e in p.entries] == [0.0, BED_SOUND_DB, -6.0]


def test_a_cuts_sound_level_round_trips_and_is_bounded():
    pytest.importorskip("nw")
    from muvid.footage.edl import _as_entry
    from muvid.footage.service import edl_json

    e = _as_entry({"song_start": 0.0, "song_end": 2.0, "clip_id": "a", "sound_db": -14})
    assert e.sound_db == -14.0 and edl_json(e)["sound_db"] == -14.0
    assert "sound_db" not in edl_json(_as_entry({"song_start": 0, "song_end": 1, "clip_id": "a"}))
    with pytest.raises(ValueError, match="sound_db"):
        _as_entry({"song_start": 0.0, "song_end": 2.0, "clip_id": "a", "sound_db": 40})
    with pytest.raises(ValueError, match="sound_db"):
        _as_entry({"song_start": 0.0, "song_end": 2.0, "clip_id": "a", "sound_db": "loud"})


def test_the_lacing_bridge_carries_a_cuts_sound_level():
    pytest.importorskip("lacing")
    from muvid.footage import lacing_bridge as lb
    from muvid.footage.edl import _as_entry

    e = _as_entry({"song_start": 0.0, "song_end": 2.0, "clip_id": "a", "source_in": 1.0,
                   "sound_db": -14})
    anns = lb.edl_annotations([e], song_asset_id="s", attributed_to="t")
    back = lb.edl_from_annotations(anns) if hasattr(lb, "edl_from_annotations") else None
    assert any(getattr(a, "body", {}).get("sound_db") == -14.0 for a in anns)
    if back is not None:
        assert back[0]["sound_db"] == -14.0


@needs_ffmpeg
def test_a_cuts_sound_level_is_applied_to_its_stretch_of_the_track(tmp_path):
    import numpy as np
    import soundfile as sf

    from muvid.footage.edl import AssemblyCut
    from muvid.footage.sound import clip_sound_track

    a = _clip(tmp_path / "a.mp4", seconds=4, freq=440)
    cuts = [AssemblyCut(0.0, 1.5, "a", 0.0, str(a)),
            AssemblyCut(1.5, 3.0, "a", 1.5, str(a), sound_db=-20.0)]
    x, sr = sf.read(str(clip_sound_track(cuts, tmp_path / "c.wav")))
    x = np.abs(x).mean(axis=1)
    full, bed = x[int(0.3 * sr):int(1.2 * sr)].mean(), x[int(1.8 * sr):int(2.7 * sr)].mean()
    assert abs(20 * np.log10(bed / full) + 20.0) < 1.0


def test_propose_promo_accepts_the_whole_song_as_a_span_and_refuses_a_negative_length(fp):
    from muvid.footage import service
    from muvid.footage.errors import FootageError

    out = service.propose_promo(fp, shots=[{"clip_id": c} for c in "ABCAB"] * 2,
                                span=[0.0, 30.0])
    assert out["span"] == [0.0, 30.0]
    with pytest.raises(FootageError, match="length_s must be positive"):
        service.propose_promo(fp, shots=[{"clip_id": "A"}], length_s=-5)
    with pytest.raises(FootageError, match="hold_s must be a number"):
        service.propose_promo(fp, shots=[{"clip_id": "A", "hold_s": "3"}])


def test_a_song_with_no_bar_lines_falls_back_to_its_beats_then_an_even_grid():
    free = Analysis(duration=20.0, tempo_bpm=60.0, beats=(), downbeats=())
    p = plan_promo(free, [Shot("a"), Shot("b"), Shot("c")],
                   clip_durations=dict.fromkeys("abc", 60.0), span=(0.0, 10.5))
    assert len(p.entries) == 3 and p.entries[-1].song_end == 10.5


def test_a_clip_too_short_for_its_shot_is_named():
    with pytest.raises(ValueError, match="shot 2 \\('tiny'\\)"):
        plan_promo(_song(), [Shot("a"), Shot("tiny", min_s=3.0)],
                   clip_durations={"a": 60.0, "tiny": 1.0}, span=(0.0, 8.0))


def test_a_dissolve_never_reads_clip_the_in_point_does_not_have():
    from muvid.footage.edl import in_point_bounds

    durs = {"a": 60.0, "b": 60.0, "c": 9.5}
    p = plan_promo(_song(), [Shot("a", hold_s=8.0), Shot("b", hold_s=8.0, source_in=0.0, role="calm"),
                             Shot("c", hold_s=8.0, role="calm")],
                   clip_durations=durs, span=(0.0, 24.0))
    assert p.entries[1].transition is None  # an in-point of 0 leaves nothing for the blend
    for e, nxt in zip(p.entries, p.entries[1:] + [None]):
        room = in_point_bounds(e, clip_duration_s=durs[e.clip_id],
                               next_transition=nxt.transition if nxt else None)
        assert room is not None and room[0] - 1e-6 <= e.source_in <= room[1] + 1e-6


@needs_ffmpeg
def test_muxed_sound_lands_on_its_frame_despite_aac_priming(tmp_path):
    import numpy as np
    import soundfile as sf

    from muvid.footage.sound import mux_audio

    sr = 48000
    x = np.zeros((sr * 3, 2))
    x[sr: sr + 48] = 0.9  # a click at exactly 1.000 s
    sf.write(str(tmp_path / "click.wav"), x, sr)
    video = _clip(tmp_path / "v.mp4", seconds=3, freq=0, audio=False)
    mux_audio(video, tmp_path / "click.wav", tmp_path / "out.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp_path / "out.mp4"),
                    str(tmp_path / "back.wav")], check=True)
    y, sr2 = sf.read(str(tmp_path / "back.wav"))
    at = int(np.argmax(np.abs(y).mean(axis=1))) / sr2
    assert abs(at - 1.0) < 0.003, at


@needs_ffmpeg
def test_a_clip_whose_audio_starts_late_is_padded_not_pulled_early(tmp_path):
    import numpy as np
    import soundfile as sf

    from muvid.footage.edl import AssemblyCut
    from muvid.footage.sound import clip_sound_track

    late = tmp_path / "late.mp4"  # picture from 0, a tone whose stream starts at 0.5 s
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=64x112:d=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2.5", "-filter_complex",
                    "[1:a]adelay=500|500[a]", "-map", "0:v", "-map", "[a]", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(late)], check=True)
    out = clip_sound_track([AssemblyCut(0.0, 2.0, "late", 0.0, str(late))], tmp_path / "c.wav")
    y, sr = sf.read(str(out))
    y = np.abs(y).mean(axis=1)
    assert y[int(0.05 * sr):int(0.4 * sr)].mean() < 1e-3 < y[int(0.7 * sr):int(1.5 * sr)].mean()


def test_a_synced_clip_stays_silent_unless_its_cut_names_a_level():
    from muvid.footage.edl import AssemblyCut
    from muvid.footage.sound import silent_unless_set

    cuts = [AssemblyCut(0, 1, "song_rec", 0, "x.mp4"), AssemblyCut(1, 2, "song_rec", 0, "x.mp4", sound_db=-6.0),
            AssemblyCut(2, 3, "broll", 0, "y.mp4")]
    out = silent_unless_set(cuts, {"song_rec"})
    assert [c.sound_db for c in out] == [-60.0, -6.0, None]


@needs_ffmpeg
def test_speech_is_raised_and_the_music_ducked_under_it_but_not_under_the_room(tmp_path):
    """The flaw this guards: a room-tone bed keyed the ducker, holding the music 12 dB
    down for the whole video, while a quiet phone voice stayed under the ducked music."""
    import numpy as np
    import soundfile as sf

    from muvid.footage.sound import mix_under

    sr = 48000
    t = np.arange(6 * sr) / sr
    music = 0.3 * np.sin(2 * np.pi * 220 * t)                       # about -13 dBFS
    voice = np.zeros_like(t)
    voice[2 * sr:4 * sr] = 0.02 * np.sin(2 * np.pi * 600 * t[2 * sr:4 * sr])  # -37 dBFS, 2-4 s
    voice[2 * sr:4 * sr] += 0.0005 * np.random.default_rng(0).standard_normal(2 * sr)
    room = 0.003 * np.random.default_rng(1).standard_normal(len(t))  # a room bed, all along
    room[2 * sr:4 * sr] = 0
    for name, x in (("m", music), ("d", voice), ("n", room)):
        sf.write(str(tmp_path / f"{name}.wav"), np.stack([x, x], 1), sr)
    p = mix_under(tmp_path / "m.wav", tmp_path / "d.wav", tmp_path / "n.wav", tmp_path / "x.wav")
    y, _ = sf.read(str(tmp_path / "x.wav"))
    y = y.mean(axis=1)

    def db(a, b):
        return 20 * np.log10(np.sqrt(np.mean(y[int(a * sr):int(b * sr)] ** 2)))

    music_alone = 20 * np.log10(np.sqrt(np.mean(music ** 2)))
    assert abs(db(0.5, 1.5) - music_alone) < 1.0            # no duck under the room alone
    assert p["dialogue_gain_db"] > 10 and p["duck_db"] <= -8  # speech raised, music down
    assert p["speech_dbfs"] + p["dialogue_gain_db"] - (p["music_under_speech_dbfs"] + p["duck_db"]) >= 11.5
