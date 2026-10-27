"""``verify_video``'s loudness meter (muvid#219): ``mixing.loudness.file_loudness``,
metered as it streams, in place of ffmpeg's ``loudnorm`` analysis pass."""

import subprocess

import pytest

from tests.ffmpeg_support import needs_ffmpeg
from muvid.visualize.ffmpeg import Loudness, measure_loudness
from muvid.visualize.verify import measure_integrated_lufs, verify_video


def _tone(tmp_path, *, channels, name="tone.m4a", seconds=6):
    out = tmp_path / name
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i"]
        + [f"sine=frequency=440:duration={seconds}:sample_rate=48000,volume=0.3"]
        + ["-ac", str(channels), "-c:a", "aac", str(out)],
        check=True,
    )
    return out


@needs_ffmpeg
@pytest.mark.parametrize("channels", [1, 2])
def test_the_streaming_meter_agrees_with_loudnorm(tmp_path, channels):
    tone = _tone(tmp_path, channels=channels)
    want = float(measure_loudness(tone).measured["input_i"])
    assert measure_integrated_lufs(tone) == pytest.approx(want, abs=0.2)


def _video(tmp_path, *, volume=1.0):
    video = tmp_path / f"v{volume}.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=640x360:d=2",
        ]
        + [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration=2:sample_rate=48000,volume={volume}",
        ]
        + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2"]
        + ["-shortest", str(video)],
        check=True,
    )
    return video


def _loudness_check(checks):
    (check,) = [c for c in checks if c.name == "loudness"]
    return check


@needs_ffmpeg
def test_verify_video_measures_with_the_meter_it_is_given_against_its_target(tmp_path):
    video = _video(tmp_path)
    seen = []

    def meter(media):
        seen.append(media)
        return -16.2

    target = Loudness(integrated=-16.0)
    ok = _loudness_check(
        verify_video(video, check_loudness=True, loudness=target, loudness_meter=meter)
    )
    assert ok.ok and seen == [video] and "target -16.0" in ok.detail
    # against the default target (-14) the same reading is 2.2 LU off: refused
    assert not _loudness_check(
        verify_video(video, check_loudness=True, loudness_meter=meter)
    ).ok


@needs_ffmpeg
def test_the_default_meter_reads_the_file(tmp_path):
    loud, quiet = _video(tmp_path, volume=1.0), _video(tmp_path, volume=0.1)
    a = float(
        _loudness_check(verify_video(loud, check_loudness=True)).detail.split()[0]
    )
    b = float(
        _loudness_check(verify_video(quiet, check_loudness=True)).detail.split()[0]
    )
    assert a - b == pytest.approx(20.0, abs=0.5)  # 20 dB quieter, read as such


def test_the_default_meter_is_the_streaming_one():
    import inspect

    default = inspect.signature(verify_video).parameters["loudness_meter"].default
    assert default is measure_integrated_lufs


@needs_ffmpeg
def test_a_meter_failure_is_a_traceback_not_a_quiet_fallback(tmp_path, monkeypatch):
    import mixing.loudness

    def broken(chunks, fs):
        raise RuntimeError("meter broke")

    monkeypatch.setattr(mixing.loudness, "stream_loudness", broken)
    with pytest.raises(RuntimeError, match="meter broke"):
        measure_integrated_lufs(_tone(tmp_path, channels=2))


@needs_ffmpeg
def test_an_undecodable_file_is_an_ffmpeg_error(tmp_path):
    from muvid.visualize.ffmpeg import FfmpegError, stream_pcm

    junk = tmp_path / "junk.m4a"
    junk.write_bytes(b"not media at all")
    with pytest.raises(FfmpegError, match="could not decode"):
        list(stream_pcm(junk, sample_rate=48000, channels=2))


@needs_ffmpeg
@pytest.mark.skipif(not hasattr(__import__("os"), "mkfifo"), reason="needs a FIFO")
def test_the_decode_is_bounded_by_the_ffmpeg_timeout(tmp_path, monkeypatch):
    """The #219 review: mixing's own decoder had no timeout — a stalled input hung the
    check and orphaned ffmpeg. muvid's stream_pcm is bounded like every other decode."""
    import os
    import time

    from muvid.visualize.ffmpeg import FfmpegError, stream_pcm

    fifo = tmp_path / "stall.wav"
    os.mkfifo(fifo)  # nobody writes: ffmpeg blocks opening it
    monkeypatch.setenv("MUVID_FFMPEG_TIMEOUT_S", "1")
    start = time.monotonic()
    with pytest.raises(FfmpegError, match="timed out"):
        list(stream_pcm(fifo, sample_rate=48000, channels=2))
    assert time.monotonic() - start < 10
