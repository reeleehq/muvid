"""``shot_boundaries`` delegates to ``mixing.video.shots`` (muvid#220): muvid maps the
detector's spans onto the song, and only a missing optional package is a degrade."""

from __future__ import annotations

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
