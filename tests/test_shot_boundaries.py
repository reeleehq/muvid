"""``shot_boundaries`` delegates to ``mixing.video.shots`` (muvid#220): muvid maps the
detector's spans onto the song, and only a missing optional package is a degrade."""

from __future__ import annotations

import numpy as np
import pytest

from muvid.footage.scoring import segment


@pytest.fixture
def detector(monkeypatch):
    mixing_video = pytest.importorskip("mixing.video")
    calls = []

    def shots(video, *, strategy):
        calls.append((video, strategy))
        return [(0.0, 2.5), (2.5, 7.0), (7.0, 9.0)]

    monkeypatch.setattr(mixing_video, "shots", shots)
    return calls


def test_the_cuts_are_the_span_starts_after_the_first_on_the_song(detector, monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    assert segment.shot_boundaries("/x/a.mp4", offset_s=10.0) == [12.5, 17.0]
    assert detector == [("/x/a.mp4", "pyscenedetect")]


def test_a_missing_package_degrades_to_no_cuts_without_calling_the_detector(
    detector, monkeypatch
):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    assert segment.shot_boundaries("/x/a.mp4", offset_s=0.0) == []
    assert detector == []


def test_the_ffmpeg_only_strategy_is_there_to_ask_for(detector, monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)  # no scenedetect
    assert segment.shot_boundaries("/x/a.mp4", offset_s=1.0, strategy="diff") == [3.5, 8.0]
    assert detector == [("/x/a.mp4", "diff")]


def test_a_failure_inside_the_detector_is_not_swallowed(monkeypatch):
    mixing_video = pytest.importorskip("mixing.video")

    def broken(video, *, strategy):
        raise RuntimeError("decoder blew up")

    monkeypatch.setattr(mixing_video, "shots", broken)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    with pytest.raises(RuntimeError, match="decoder blew up"):
        segment.shot_boundaries("/x/a.mp4", offset_s=0.0)


def test_a_real_hard_cut_lands_on_the_song(tmp_path):
    """Through the real mixing detector, not a stand-in (ffmpeg-only strategy)."""
    import subprocess

    from tests.ffmpeg_support import HAS_FFMPEG

    if not HAS_FFMPEG:
        pytest.skip("ffmpeg is not installed")
    pytest.importorskip("mixing.video")
    clip = tmp_path / "cut.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "color=red:s=64x48:r=25:d=2",
         "-f", "lavfi", "-i", "color=blue:s=64x48:r=25:d=2",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
         "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )
    [cut] = segment.shot_boundaries(str(clip), offset_s=5.0, strategy="diff")
    assert cut == pytest.approx(7.0, abs=0.5)


def test_the_pyscenedetect_detector_finds_a_real_hard_cut(tmp_path):
    """The named, frame-accurate strategy (``shot_boundaries``' default), through the
    real mixing + PySceneDetect (CI installs the scoring-shots extra for this; the
    canary guards it). Since muvid#259 scoring's default is the ``frames`` strategy."""
    import subprocess

    from tests.ffmpeg_support import HAS_FFMPEG

    if not HAS_FFMPEG:
        pytest.skip("ffmpeg is not installed")
    pytest.importorskip("scenedetect")
    pytest.importorskip("mixing.video")
    clip = tmp_path / "cut.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "color=red:s=64x48:r=25:d=2",
         "-f", "lavfi", "-i", "color=blue:s=64x48:r=25:d=2",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
         "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )
    assert segment.shot_boundaries(str(clip), offset_s=10.0) == [pytest.approx(12.0, abs=0.1)]


# -- the frames strategy: shots from the scoring pass's own frames (muvid#259) --------


def _pass(changes, *, hop=0.2, truncated=False):
    from types import SimpleNamespace

    changes = np.asarray(changes, dtype=float)
    times = np.arange(changes.size + 1) * hop
    return SimpleNamespace(shot_change=changes, clip_times=times, truncated=truncated)


def test_the_frames_strategy_is_scorings_default():
    assert segment.FRAMES_STRATEGY == "frames"
    assert segment.shots_available("frames")
    if not __import__("os").environ.get(segment.SHOT_STRATEGY_ENV_VAR):
        assert segment.DEFAULT_SHOT_STRATEGY == "frames"


def test_sustained_motion_is_not_a_run_of_cuts_and_a_spike_is_one():
    """The point of the spike rule: handheld motion near mixing's threshold ceiling
    (mixing#160) gives no cuts; one isolated jump does, at the sample after it."""
    rng = np.random.default_rng(0)
    handheld = rng.uniform(24.0, 36.0, 60)  # at or above the 30 ceiling, all along
    assert segment.shots_from_frame_pass(_pass(handheld), offset_s=0.0) == []
    with_cut = handheld.copy()
    with_cut[30] = 140.0
    cuts = segment.shots_from_frame_pass(_pass(with_cut), offset_s=10.0)
    assert cuts == [pytest.approx(10.0 + 31 * 0.2)]


def test_a_flash_is_not_a_cut():
    """A frame that differs and comes back changes twice in a row: not a spike."""
    changes = np.full(40, 3.0)
    changes[[20, 21]] = 120.0
    assert segment.shots_from_frame_pass(_pass(changes), offset_s=0.0) == []


def test_no_changes_means_no_cuts():
    assert segment.shots_from_frame_pass(_pass([]), offset_s=0.0) == []


def test_the_scoring_pass_records_changes_and_finds_a_real_cut(tmp_path):
    """Through the real decode pass (cv2: the scoring extra, not installed in CI)."""
    import subprocess

    from tests.ffmpeg_support import HAS_FFMPEG

    if not HAS_FFMPEG:
        pytest.skip("ffmpeg is not installed")
    pytest.importorskip("cv2")
    from muvid.footage.scoring.frames import sample_clip_frames

    clip = tmp_path / "cut.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=s=160x120:r=25:d=4",
         "-f", "lavfi", "-i", "mandelbrot=s=160x120:r=25",
         "-filter_complex", "[1:v]trim=duration=4[m];[0:v][m]concat=n=2:v=1[v]",
         "-map", "[v]", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )
    fp = sample_clip_frames(str(clip))
    assert fp.shot_change.size == fp.n_sampled - 1 and not fp.truncated
    assert segment.shots_from_frame_pass(fp, offset_s=2.0) == [
        pytest.approx(6.0, abs=0.25)
    ]
    capped = sample_clip_frames(str(clip), max_frames=5)
    assert capped.truncated and capped.n_sampled == 5
