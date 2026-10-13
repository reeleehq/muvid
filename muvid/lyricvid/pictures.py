"""Pictures for a lyric video: a mosaic that builds up as its words are sung (muvid#151).

A learner's lyric video wants a picture of what is being sung. This layer places
small pictures around the lyrics. Each one appears when its word is first sung,
so a mosaic builds up through the song, and it **bounces** (a quick enlarge and
back) every time the word is sung again. The lyrics stay readable because no
tile, even at the top of its bounce, enters the text block.

Four steps, each its own function so a caller can replace one:

1. :func:`text_block` finds where the lyrics are drawn: the union of
   non-background pixels over frames of the finished lyric render.
2. :func:`mosaic_cells` lays out cells in the bands above and below it.
3. :func:`plan_tiles` times each picture from the sung word times
   (:func:`word_times`): it appears just before the first time its word is
   sung, and bounces on every sung occurrence.
4. :func:`render` composites the tiles onto the lyric render in one ffmpeg
   pass. Pictures are fitted inside their cell, never cropped, so a CC BY-SA
   picture is shown unmodified; the bounce is a per-frame ``scale``.

Rights travel with each :class:`Picture` (its ``credit``), and :func:`credits`
lists the credit of every tile actually shown, in order of appearance, so the
end card cannot forget one.

Needs ``ffmpeg``/``ffprobe`` on PATH and nothing beyond muvid's core
dependencies (numpy).
"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

Box = tuple[int, int, int, int]  # x, y, width, height in frame pixels


@dataclass(frozen=True)
class Picture:
    """A picture for one sung word, with the credit line its licence requires."""

    word: str
    path: str
    credit: str | None = None


@dataclass(frozen=True)
class Bounce:
    """A quick enlarge and back, timed to a sung word.

    ``scale`` is the extra size at the peak (0.18 is 18 % larger), ``duration``
    the length of the whole pop in seconds, and ``lead`` how long before the
    sung onset it starts, so the peak lands on the syllable.
    """

    scale: float = 0.18
    duration: float = 0.32
    lead: float = 0.04

    def __post_init__(self):
        if self.scale < 0 or self.duration <= 0:
            raise ValueError(f"Bounce needs scale >= 0 and duration > 0, got {self}")


@dataclass(frozen=True)
class Tile:
    """A picture placed in a cell, with when it appears and when it bounces."""

    picture: Picture
    box: Box
    appear: float
    beats: tuple[float, ...] = field(default_factory=tuple)

    @property
    def centre(self) -> tuple[float, float]:
        x, y, w, h = self.box
        return x + w / 2, y + h / 2


def word_times(timed_text: Mapping | str | Path) -> dict[str, list[float]]:
    """Every sung start of every word, from a ``TimedText.to_dict()`` (or its JSON file).

    A word's time is its first glyph's start when glyph times exist (the measured
    onset), else the word's own start.
    """
    if not isinstance(timed_text, Mapping):
        timed_text = json.loads(Path(timed_text).read_text())
    times: dict[str, list[float]] = {}
    for section in timed_text["sections"]:
        for line in section["lines"]:
            for word in line["words"]:
                glyphs = word.get("glyphs") or []
                start = glyphs[0]["start"] if glyphs else word["start"]
                times.setdefault(word["text"], []).append(float(start))
    return {w: sorted(ts) for w, ts in times.items()}


def _probe_duration(video) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return float(out)


def _probe_rate(video) -> str:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate",
            "-of",
            "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.strip().split(",")[0] or "25"


def _probe_size(video) -> tuple[int, int]:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    w, h = out.strip().split(",")[:2]
    return int(w), int(h)


def frame_size(video) -> tuple[int, int]:
    """``(width, height)`` of ``video``'s frames: the ``size`` to plan cells for."""
    return _probe_size(video)


def _off_frame(tiles: Sequence["Tile"], size: tuple[int, int]) -> list:
    """The tiles whose box leaves a frame of ``size``."""
    W, H = size
    return [
        t
        for t in tiles
        if t.box[0] < 0
        or t.box[1] < 0
        or t.box[0] + t.box[2] > W
        or t.box[1] + t.box[3] > H
    ]


def _rgb(colour: str) -> tuple[int, int, int]:
    c = colour.lstrip("#")
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))


def text_block(
    video,
    *,
    background: str,
    threshold: int = 40,
    fps: float = 1.0,
    downscale: int = 4,
    margin: int = 40,
) -> Box:
    """Where the lyrics are drawn: the box around every non-background pixel of ``video``.

    Frames are sampled at ``fps`` and shrunk by ``downscale`` for speed; a pixel
    is ink when its summed RGB distance from ``background`` exceeds ``threshold``.
    ``margin`` pixels are added on every side. Raises when nothing is drawn.
    """
    W, H = _probe_size(video)
    w, h = W // downscale, H // downscale
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps={fps},scale={w}:{h}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(np.int16)
    ink = (
        np.abs(frames - np.array(_rgb(background), np.int16)).sum(-1) > threshold
    ).any(0)
    ys, xs = np.nonzero(ink)
    if not len(ys):
        raise ValueError(
            f"no text found in {video}: every sampled pixel is the background {background}"
        )
    x0, x1 = (
        max(0, xs.min() * downscale - margin),
        min(W, (xs.max() + 1) * downscale + margin),
    )
    y0, y1 = (
        max(0, ys.min() * downscale - margin),
        min(H, (ys.max() + 1) * downscale + margin),
    )
    return int(x0), int(y0), int(x1 - x0), int(y1 - y0)


def mosaic_cells(
    n: int,
    block: Box,
    *,
    size: tuple[int, int] = (1920, 1080),
    gap: int = 24,
    aspect: float = 4 / 3,
    top: float = 0.04,
    bottom: float = 0.95,
    min_band: int = 120,
    width: float = 0.94,
) -> list[Box]:
    """``n`` cells in one row above and one row below the text block, centre-out.

    Bands thinner than ``min_band`` pixels are skipped. The first cells returned
    are the most central, so a short list of pictures sits near the lyrics.
    """
    if n <= 0:
        return []
    W, H = size
    _, by, _, bh = block
    bands = [
        b
        for b in ((int(top * H), by), (by + bh, int(bottom * H)))
        if b[1] - b[0] >= min_band
    ]
    if not bands:
        raise ValueError(
            f"no room for pictures: the text block {block} leaves no band of {min_band}px"
        )
    cols = math.ceil(n / len(bands))
    cells = []
    for i, (y0, y1) in enumerate(bands):
        ch = y1 - y0 - 2 * gap
        cw = min(int(ch * aspect), (int(width * W) - (cols - 1) * gap) // cols)
        ch = min(ch, int(cw / aspect))
        x0 = (W - (cols * cw + (cols - 1) * gap)) // 2
        yc = y0 + (y1 - y0 - ch) // 2
        row = [(x0 + c * (cw + gap), yc, cw, ch) for c in range(cols)]
        cells += row if i == 0 else row[::-1]
    cells.sort(key=lambda c: (abs(c[0] + c[2] / 2 - W / 2), c[1]))
    return cells[:n]


def plan_tiles(
    pictures: Iterable[Picture],
    times: Mapping[str, Sequence[float]],
    cells: Sequence[Box],
    *,
    lead: float = 0.15,
    bounce: Bounce | None = Bounce(),
) -> list[Tile]:
    """Place each sung picture in a cell, in order of its word's first sung time.

    A picture whose word is never sung is left out (see :func:`unsung_pictures`).
    With a ``bounce``, each picture shrinks inside its cell by the bounce's peak,
    so at full size it still fits the cell, and the cells already keep clear of
    the text.
    """
    sung = sorted((times[p.word][0], p) for p in pictures if times.get(p.word))
    if len(sung) > len(cells):
        raise ValueError(f"{len(sung)} pictures for {len(cells)} cells")
    shrink = 1 + (bounce.scale if bounce else 0)
    tiles = []
    for (first, picture), (x, y, w, h) in zip(sung, cells):
        bw, bh = int(w / shrink), int(h / shrink)
        box = (x + (w - bw) // 2, y + (h - bh) // 2, bw, bh)
        beats = tuple(t - bounce.lead for t in times[picture.word]) if bounce else ()
        tiles.append(Tile(picture, box, max(0.0, first - lead), beats))
    return tiles


def unsung_pictures(
    pictures: Iterable[Picture], times: Mapping[str, Sequence[float]]
) -> list[str]:
    """The words that have a picture but are never sung (so the picture is never shown)."""
    return [p.word for p in pictures if not times.get(p.word)]


def bounce_expr(beats: Sequence[float], bounce: Bounce) -> str:
    """An ffmpeg expression of ``t``: 1 at rest, ``1 + scale`` at the peak of each pop."""
    if not beats or bounce.scale == 0:
        return "1"
    d = bounce.duration
    humps = "+".join(
        f"between(t,{b:.3f},{b + d:.3f})*sin(PI*(t-{b:.3f})/{d:.3f})" for b in beats
    )
    return f"(1+{bounce.scale:.3f}*min(1,{humps}))"


def credits(tiles: Iterable[Tile]) -> list[str]:
    """The credit line of every shown picture, in order of appearance, without repeats.

    Raises when a shown picture has no credit: a dropped attribution is a licence
    failure nobody downstream can see.
    """
    out, missing = [], []
    for t in sorted(tiles, key=lambda t: t.appear):
        if not t.picture.credit:
            missing.append(t.picture.word)
        elif t.picture.credit not in out:
            out.append(t.picture.credit)
    if missing:
        raise ValueError(f"pictures shown without a credit: {missing}")
    return out


def render(
    video,
    tiles: Sequence[Tile],
    out,
    *,
    bounce: Bounce | None = Bounce(),
    fade_in: float = 0.35,
    border: str | None = None,
    border_px: int = 3,
    crf: int = 18,
) -> Path:
    """Composite ``tiles`` onto ``video`` in one ffmpeg pass; audio is copied.

    Each picture is fitted inside its tile box (never cropped), framed by a
    ``border`` of ``border_px`` when given, fades in at ``appear`` and pops on
    each of its ``beats`` when ``bounce`` is set.
    """
    out = Path(out)
    if not tiles:
        raise ValueError("no tiles to render")
    # Cells planned for another frame size (mosaic_cells' default is 1920x1080) would
    # put pictures off-frame: a plausible-looking video missing them, not an error.
    size = _probe_size(video)
    if outside := _off_frame(tiles, size):
        raise ValueError(
            f"{len(outside)} tile(s) fall outside the {size[0]}x{size[1]} frame of "
            f"{video}: plan the cells with mosaic_cells(..., size=frame_size(video))."
        )
    dur, rate = _probe_duration(video), _probe_rate(video)
    args = ["ffmpeg", "-v", "error", "-y", "-i", str(video)]
    chains, prev = [], "0:v"
    for i, t in enumerate(tiles, 1):
        args += [
            "-loop",
            "1",
            "-framerate",
            rate,
            "-t",
            f"{dur:.3f}",
            "-i",
            t.picture.path,
        ]
        _, _, w, h = t.box
        inner_w, inner_h = (w - 2 * border_px, h - 2 * border_px) if border else (w, h)
        chain = f"[{i}:v]scale={inner_w}:{inner_h}:force_original_aspect_ratio=decrease"
        if border:
            chain += f",pad=iw+{2 * border_px}:ih+{2 * border_px}:{border_px}:{border_px}:color={border}"
        chain += f",format=rgba,fade=t=in:st={t.appear:.3f}:d={fade_in:.3f}:alpha=1"
        if bounce and t.beats:
            s = bounce_expr(t.beats, bounce)
            chain += f",scale=w='trunc(iw*{s}/2)*2':h='trunc(ih*{s}/2)*2':eval=frame"
        cx, cy = t.centre
        chains.append(f"{chain}[p{i}]")
        chains.append(
            f"[{prev}][p{i}]overlay=x='{cx:.1f}-w/2':y='{cy:.1f}-h/2':eval=frame"
            f":enable='gte(t,{t.appear:.3f})'[v{i}]"
        )
        prev = f"v{i}"
    args += [
        "-filter_complex",
        ";".join(chains),
        "-map",
        f"[{prev}]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-t",
        f"{dur:.3f}",
        str(out),
    ]
    subprocess.run(args, check=True)
    return out
