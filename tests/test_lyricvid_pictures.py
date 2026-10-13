"""Tests for the lyric-video picture layer (muvid.lyricvid.pictures, muvid#151)."""

import subprocess

import numpy as np
import pytest

from muvid.lyricvid.pictures import (
    frame_size,
    Bounce,
    Picture,
    Tile,
    bounce_expr,
    credits,
    mosaic_cells,
    plan_tiles,
    render,
    text_block,
    unsung_pictures,
    word_times,
)
from tests.ffmpeg_support import needs_ffmpeg

TIMED = {
    "sections": [
        {"label": "Verse", "lines": [
            {"text": "バス ト カップ", "words": [
                {"text": "バス", "start": 1.0, "end": 1.4, "glyphs": [{"text": "バ", "start": 1.05}, {"text": "ス", "start": 1.2}]},
                {"text": "ト", "start": 1.5, "end": 1.6},
                {"text": "カップ", "start": 2.0, "end": 2.5},
            ]},
            {"text": "バス バス", "words": [
                {"text": "バス", "start": 3.0, "end": 3.3},
                {"text": "バス", "start": 3.5, "end": 3.8},
            ]},
        ]},
    ]
}


def _overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def test_word_times_uses_glyph_onsets_and_keeps_every_occurrence():
    t = word_times(TIMED)
    assert t["バス"] == [1.05, 3.0, 3.5]
    assert t["カップ"] == [2.0]


@pytest.mark.parametrize("n", [1, 5, 12])
def test_cells_stay_out_of_the_text_block_and_inside_the_frame(n):
    block = (200, 380, 1520, 320)
    cells = mosaic_cells(n, block)
    assert len(cells) == n
    for c in cells:
        assert not _overlaps(c, block)
        x, y, w, h = c
        assert x >= 0 and y >= 0 and x + w <= 1920 and y + h <= 1080
    for i, a in enumerate(cells):
        assert not any(_overlaps(a, b) for b in cells[i + 1:])


def test_no_room_raises():
    with pytest.raises(ValueError, match="no room"):
        mosaic_cells(3, (0, 40, 1920, 1000))


def test_plan_orders_by_first_sung_time_and_bounces_on_every_occurrence():
    pics = [Picture("カップ", "cup.png", "cup credit"), Picture("バス", "bus.png", "bus credit"),
            Picture("ネコ", "cat.png", "cat credit")]
    t = word_times(TIMED)
    cells = mosaic_cells(3, (200, 380, 1520, 320))
    bounce = Bounce(scale=0.2, lead=0.05)
    tiles = plan_tiles(pics, t, cells, bounce=bounce)
    assert [x.picture.word for x in tiles] == ["バス", "カップ"]
    assert unsung_pictures(pics, t) == ["ネコ"]
    bus = tiles[0]
    assert bus.appear == pytest.approx(0.90)
    assert bus.beats == pytest.approx((1.0, 2.95, 3.45))
    # at the peak of its bounce the tile still fits its cell
    (cx, cy, cw, ch), (x, y, w, h) = cells[0], bus.box
    assert w * 1.2 <= cw + 1 and h * 1.2 <= ch + 1
    assert abs((x + w / 2) - (cx + cw / 2)) <= 1


def test_bounce_expr_is_one_at_rest_and_peaks_mid_pop():
    expr = bounce_expr([1.0], Bounce(scale=0.2, duration=0.4))

    def at(t):
        e = expr.replace("between", "_between").replace("PI", "np.pi").replace("sin", "np.sin").replace("min", "_min")
        return eval(e, {"np": np, "t": t, "_between": lambda v, a, b: float(a <= v <= b), "_min": min})

    assert at(0.5) == pytest.approx(1.0)
    assert at(1.2) == pytest.approx(1.2)
    assert at(2.0) == pytest.approx(1.0)
    assert bounce_expr([], Bounce()) == "1"


def test_credits_in_order_and_missing_credit_raises():
    a = Tile(Picture("a", "a.png", "A by X, CC BY 4.0"), (0, 0, 10, 10), 2.0)
    b = Tile(Picture("b", "b.png", "B by Y, public domain"), (0, 0, 10, 10), 1.0)
    assert credits([a, b]) == ["B by Y, public domain", "A by X, CC BY 4.0"]
    with pytest.raises(ValueError, match="without a credit"):
        credits([Tile(Picture("c", "c.png"), (0, 0, 10, 10), 0.0)])


@needs_ffmpeg
def test_render_finds_the_text_and_bounces_a_tile(tmp_path):
    lyr = tmp_path / "lyrics.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x101010:s=320x180:d=2:r=25",
                    "-vf", "drawbox=x=40:y=70:w=240:h=40:color=white:t=fill", "-pix_fmt", "yuv420p", str(lyr)],
                   check=True)
    img = tmp_path / "red.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=80x60", "-frames:v", "1", str(img)],
                   check=True)
    block = text_block(lyr, background="#101010", margin=4)
    assert block[1] <= 70 and block[1] + block[3] >= 110
    cells = mosaic_cells(1, block, size=(320, 180), gap=4, min_band=30)
    bounce = Bounce(scale=0.3, duration=0.4, lead=0.0)
    tile, = plan_tiles([Picture("w", str(img), "c")], {"w": [0.5, 1.2]}, cells, lead=0.1, bounce=bounce)
    out = render(lyr, [tile], tmp_path / "out.mp4", bounce=bounce)

    def red_width(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        f = np.frombuffer(raw, np.uint8).reshape(180, 320, 3).astype(int)
        row = f[int(tile.centre[1])]
        return int(((row[:, 0] > 150) & (row[:, 1] < 100)).sum())

    assert red_width(0.05) == 0          # not yet shown
    rest, peak = red_width(1.0), red_width(1.4)
    assert rest > 0 and peak > rest * 1.15  # pops on its second sung time
    # never over the text
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.4", "-i", str(out), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(180, 320, 3).astype(int)
    assert (f[72:108, 44:276].min(-1) > 200).all()


@needs_ffmpeg
def test_render_refuses_tiles_planned_for_another_frame_size(tmp_path):
    """mosaic_cells defaults to 1920x1080; on a smaller video those cells are off-frame,
    which used to render a video quietly missing its pictures (sprint review)."""
    lyr = tmp_path / "lyrics.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x101010:s=320x180:d=1:r=25",
                    "-vf", "drawbox=x=40:y=70:w=240:h=40:color=white:t=fill", "-pix_fmt", "yuv420p", str(lyr)],
                   check=True)
    img = tmp_path / "red.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=80x60", "-frames:v", "1", str(img)],
                   check=True)
    assert frame_size(lyr) == (320, 180)
    block = text_block(lyr, background="#101010", margin=4)
    stale = mosaic_cells(1, (block[0] * 6, block[1] * 6, block[2] * 6, block[3] * 6))  # 1920x1080
    tile, = plan_tiles([Picture("w", str(img), "c")], {"w": [0.5]}, stale)
    with pytest.raises(ValueError, match="outside the 320x180 frame"):
        render(lyr, [tile], tmp_path / "out.mp4")
    good = mosaic_cells(1, block, size=frame_size(lyr), gap=4, min_band=30)
    tile, = plan_tiles([Picture("w", str(img), "c")], {"w": [0.5]}, good)
    assert render(lyr, [tile], tmp_path / "ok.mp4").exists()
