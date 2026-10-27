"""The colour every assembled video is delivered in, and how a source's colour is read.

muvid#195. The assembler's per-cut ``scale`` converts every source to
:data:`DELIVERY_COLOR_SPACE` at :data:`DELIVERY_COLOR_RANGE`, :data:`DELIVERY_TAG`
says so on the frame, and the encode carries the same tags. That gives a look a
frame whose colour is a FACT, which :func:`muvid.footage.look.stylize` declares for
``looks`` Rule 22 instead of assuming it (muvid#190).

Measured on ffmpeg 8.0.1 and 7.0.2, against the RGB original, decoded the way a
player reads a BT.709-tagged file: a BT.601 clip 24 -> 37 dB, a full-range JPEG
still 24 -> 41 dB, a PNG 24 -> 40 dB, a tagged BT.709 clip unchanged at 40 dB.

Two things the conversion cannot get right from the frame alone, which is why a
source is read here first (:func:`read_source_colour`):

- **An untagged source.** ``scale`` reads the frame's matrix tag and swscale treats
  an unspecified one as BT.601, while players read untagged HD as BT.709. Measured:
  an untagged 1280x720 BT.709 clip went 41.6 -> 26.9 dB on both builds until the
  assembler told ``scale`` the matrix. An untagged YUV source that players call HD
  (:func:`is_hd`) is therefore converted FROM BT.709; an SD one keeps swscale's
  BT.601, which is the SD convention.
- **An HDR source** (HLG or PQ transfer — iPhone footage records HLG by default).
  Converting only the YCbCr matrix and range leaves BT.2020 primaries and an HDR
  transfer behind, so the delivered SDR picture is washed out (measured: 10.0 dB
  against the SDR original). So it is TONE MAPPED (muvid#201, :func:`tonemap_chain`):
  to linear light with :data:`HDR_REFERENCE_WHITE_NITS` as SDR white, to BT.709
  primaries, :data:`TONEMAP` with :data:`TONEMAP_PARAM`, then BT.709 limited — 24.7 dB
  on the same clip. Those three are the defaults of a :class:`ToneMap`, which a caller
  can replace (muvid#215: more highlight detail, or a brighter mid-range). A build
  without ``zscale`` / ``tonemap`` cannot, and the assembler then reports each HDR
  clip it delivers washed out.

Import-light (stdlib only at module top): the look compiler imports the constants.
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from typing import Callable, Optional

#: The delivery matrix — and the primaries and transfer it is tagged with. BT.709 is
#: what a player assumes for untagged HD and what phone video mostly is already.
DELIVERY_COLOR_SPACE = "bt709"
#: The delivery range: limited ("tv"), the range H.264 delivery is read in.
DELIVERY_COLOR_RANGE = "tv"

#: The frame-level tag the assembler places last in each part's chain, after the
#: look (and on a gap's black). On the FRAME, not only on the encoder: ffmpeg 8.0.1 takes
#: the stream's colour description from the frames and ignores ``-color_primaries``
#: / ``-color_trc`` (measured: both came out ``unknown`` with the options alone).
DELIVERY_TAG = (
    f"setparams=range={DELIVERY_COLOR_RANGE}:color_primaries={DELIVERY_COLOR_SPACE}"
    f":color_trc={DELIVERY_COLOR_SPACE}:colorspace={DELIVERY_COLOR_SPACE}"
)

#: Where players draw the line between SD (BT.601) and HD (BT.709) for an untagged
#: source: at least this wide, OR taller than :data:`SD_MAX_HEIGHT` (mpv's rule).
#: Width matters for letterboxed HD — an untagged 1280x536 BT.709 clip measured
#: 26.9 dB under a height-only rule.
HD_MIN_WIDTH = 1280
#: The tallest SD frame (PAL, 576 lines).
SD_MAX_HEIGHT = 576

#: ffprobe's names for the transfers that make a source HDR (HLG, PQ).
HDR_TRANSFERS = frozenset({"arib-std-b67", "smpte2084"})

#: The HDR luminance (nits) that becomes SDR white: BT.2408's reference white, where an
#: HLG camera puts diffuse white.
HDR_REFERENCE_WHITE_NITS = 203
#: The ``tonemap`` curve for the highlights above SDR white. ``mobius`` is the identity
#: up to :data:`TONEMAP_PARAM` and rolls off smoothly above it. Measured on an HLG clip
#: of an SDR original, decoded as BT.709 (no highlight above white): ``clip`` 25.2 dB,
#: ``mobius`` 0.85 24.7, 0.7 23.1, ``reinhard`` 15.8, ``hable`` 11.3. On an HLG clip of
#: eight bands from signal 0.60 to 0.95 (0.75 is reference white), the #201 review:
#: ``clip`` sends 56% of the pixels to Y >= 235 and keeps no detail in the four bands
#: above white; ``mobius`` 0.85 sends 6% there and keeps 6/2/1/0/1 code values in the
#: top five; ``mobius`` 0.5 sends none but costs 8 codes at signal 0.70.
TONEMAP = "mobius"
TONEMAP_PARAM = 0.85
#: The curves ffmpeg's ``tonemap`` filter offers (``ffmpeg -h filter=tonemap``) — a
#: closed vocabulary, because the curve is spliced into a filter string.
TONEMAP_CURVES = frozenset(
    {"none", "linear", "gamma", "clip", "reinhard", "hable", "mobius"}
)
#: The curves that ignore ``param`` (ffmpeg's ``tonemap`` docs): one given for them
#: would be a direction that does nothing, so it is refused.
_CURVES_WITHOUT_PARAM = frozenset({"none", "hable"})
#: muvid's measured ``param`` per curve, where it has one; every other curve gets
#: ffmpeg's own default for that curve (the #215 review: an inherited mobius 0.85 made
#: ``gamma`` render 18% grey at Y 44 and ``reinhard`` at 177, against 117).
_MEASURED_PARAMS = {TONEMAP: TONEMAP_PARAM}
#: ``mobius``'s param is the point below which the map is 1:1, a fraction of white;
#: above 1 it renders exactly like the default (measured), so it is refused.
_PARAM_MAX = {"mobius": 1.0}
#: The range a reference white may take. Below the floor most of an HDR picture is
#: pushed to white (1e-7 nits renders solid white); the ceiling is PQ's own peak
#: (10,000 nits — above it, solid black). 203 (BT.2408) sits well inside.
MIN_REFERENCE_WHITE_NITS = 50
MAX_REFERENCE_WHITE_NITS = 10_000
#: The filters :func:`tonemap_chain` needs (``zscale`` is libzimg, WTFPL).
TONEMAP_FILTERS = ("zscale", "tonemap")


@dataclass(frozen=True)
class ToneMap:
    """How an HDR source is brought to the SDR delivery (muvid#215): the ``tonemap``
    ``curve`` and its ``param`` for the highlights, and the HDR luminance (nits) that
    becomes SDR white — lower it for a brighter mid-range. The defaults are the
    measured choice above; ``ToneMap(param=0.5)`` keeps every highlight below white at
    the cost of some mid-tone codes. ``param=None`` means the curve's default: muvid's
    measured one for ``mobius``, ffmpeg's for the rest.

    Checked on construction, because every field lands in a filter string:

    >>> ToneMap(curve="gamma").effective_param is None, ToneMap().effective_param
    (True, 0.85)
    >>> ToneMap(curve="mobius:desat=9")
    Traceback (most recent call last):
    ...
    ValueError: unknown tone curve 'mobius:desat=9'; one of ['clip', 'gamma', 'hable', 'linear', 'mobius', 'none', 'reinhard']
    """

    curve: str = TONEMAP
    param: Optional[float] = None
    reference_white_nits: float = HDR_REFERENCE_WHITE_NITS

    def __post_init__(self):
        if self.curve not in TONEMAP_CURVES:
            raise ValueError(
                f"unknown tone curve {self.curve!r}; one of {sorted(TONEMAP_CURVES)}"
            )
        # `None` is kept as given and resolved per curve in `effective_param`, so
        # `replace(DEFAULT_TONE_MAP, curve=...)` gets the NEW curve's default
        param = self.param
        if param is not None and self.curve in _CURVES_WITHOUT_PARAM:
            raise ValueError(f"the {self.curve!r} tone curve takes no param")
        if param is not None:
            param = _real("param", param, low=0.0, high=_PARAM_MAX.get(self.curve))
        nits = _real(
            "reference_white_nits",
            self.reference_white_nits,
            low=MIN_REFERENCE_WHITE_NITS,
            high=MAX_REFERENCE_WHITE_NITS,
            low_inclusive=True,
        )
        # stored as plain floats: what lands in the filter is float formatting, never
        # a caller type's own `__format__`
        object.__setattr__(self, "param", param)
        object.__setattr__(self, "reference_white_nits", nits)

    @property
    def effective_param(self) -> Optional[float]:
        """The ``param`` the filter gets: the given one, else the curve's default
        (muvid's measured one, or ``None`` for ffmpeg's own)."""
        return (
            self.param if self.param is not None else _MEASURED_PARAMS.get(self.curve)
        )


def _real(name, v, *, low, high=None, low_inclusive=False) -> float:
    """``v`` as a finite float in ``(low, high]`` (``[low, high]`` if ``low_inclusive``)."""
    if isinstance(v, bool) or not isinstance(v, numbers.Real):
        raise ValueError(f"tone map {name} must be a number, got {v!r}")
    v = float(v)
    above = v >= low if low_inclusive else v > low
    if not (math.isfinite(v) and above and (high is None or v <= high)):
        span = f"{'[' if low_inclusive else '('}{low:g}, {'inf)' if high is None else f'{high:g}]'}"
        raise ValueError(f"tone map {name} must be in {span}: {v!r}")
    return v


#: Today's tone mapping, the one every render gets unless it asks for another.
DEFAULT_TONE_MAP = ToneMap()


def tonemap_chain(
    fill: "tuple[tuple[str, str], ...]" = (), *, tone_map: ToneMap = DEFAULT_TONE_MAP
) -> str:
    """HDR -> the SDR delivery colour, for a frame already at the canvas size (float
    frames at the source's 4K would cost 100 MB each), ending in 8-bit 4:2:0. ``fill``
    names the colour tags the source left out (:attr:`SourceColour.hdr_fill`);
    ``tone_map`` is how the highlights are brought down (:class:`ToneMap`).

    >>> tonemap_chain().split(",")[0]
    'zscale=t=linear:npl=203'
    >>> tonemap_chain((("color_primaries", "bt2020"),)).split(",")[0]
    'setparams=color_primaries=bt2020'
    >>> tonemap_chain(tone_map=ToneMap(param=0.5)).split(",")[3]
    'tonemap=mobius:param=0.5:desat=0'
    """
    d = DELIVERY_COLOR_SPACE
    tags = ":".join(f"{k}={v}" for k, v in fill)
    t = tone_map
    return (
        (f"setparams={tags}," if tags else "")
        + f"zscale=t=linear:npl={t.reference_white_nits:g},format=gbrpf32le,"
        f"zscale=p={d},tonemap={t.curve}"
        + (f":param={t.effective_param:g}" if t.effective_param is not None else "")
        + ":desat=0,"
        f"zscale=t={d}:m={d}:r={DELIVERY_COLOR_RANGE},format=yuv420p"
    )


def can_tonemap() -> bool:
    """Whether this ffmpeg has the filters :func:`tonemap_chain` needs."""
    from muvid.visualize.ffmpeg import has_filter

    return all(has_filter(f) for f in TONEMAP_FILTERS)


_UNTAGGED = frozenset({"", "unknown", "unspecified"})


@dataclass(frozen=True)
class SourceColour:
    """What the assembler needs to know about one source's colour."""

    #: The matrix to give ``scale`` as ``in_color_matrix``; ``None`` lets it read the
    #: frame's own tag (a tagged source, an RGB picture, an untagged SD one).
    in_matrix: Optional[str] = None
    #: The source's HDR transfer (``"arib-std-b67"``, ``"smpte2084"``), else ``None``.
    hdr_transfer: Optional[str] = None
    #: For an HDR source, the colour tags it does NOT carry, filled with the HDR
    #: standard's own (BT.2020) — ``{"color_primaries": "bt2020"}`` — because ``zscale``
    #: refuses to convert from a colour it is not told (the #201 review: "no path between
    #: colorspaces" on an HLG clip with untagged primaries, which rendered before).
    hdr_fill: "tuple[tuple[str, str], ...]" = ()


def is_hd(width: int, height: int) -> bool:
    """Whether players read an untagged ``width`` x ``height`` source as HD (BT.709).

    >>> is_hd(1280, 536), is_hd(720, 1280), is_hd(720, 576), is_hd(960, 540)
    (True, True, False, False)
    """
    return width >= HD_MIN_WIDTH or height > SD_MAX_HEIGHT


def source_colour(stream: dict) -> SourceColour:
    """A probed video stream's :class:`SourceColour`.

    >>> source_colour({"pix_fmt": "yuv420p", "width": 1920, "height": 1080})
    SourceColour(in_matrix='bt709', hdr_transfer=None, hdr_fill=())
    >>> source_colour({"pix_fmt": "yuv420p", "width": 1280, "height": 536})
    SourceColour(in_matrix='bt709', hdr_transfer=None, hdr_fill=())
    >>> source_colour({"pix_fmt": "yuv420p", "width": 640, "height": 480})  # SD
    SourceColour(in_matrix=None, hdr_transfer=None, hdr_fill=())
    >>> source_colour({"pix_fmt": "yuv420p", "height": 1080, "color_space": "smpte170m"})
    SourceColour(in_matrix=None, hdr_transfer=None, hdr_fill=())
    >>> source_colour({"pix_fmt": "rgb24", "height": 1080})  # RGB has no matrix
    SourceColour(in_matrix=None, hdr_transfer=None, hdr_fill=())
    >>> source_colour({"pix_fmt": "yuvj420p", "height": 1080})  # JFIF: BT.601
    SourceColour(in_matrix=None, hdr_transfer=None, hdr_fill=())
    >>> source_colour({"pix_fmt": "yuv420p10le", "height": 2160,
    ...                "color_space": "bt2020nc", "color_transfer": "arib-std-b67"})
    SourceColour(in_matrix=None, hdr_transfer='arib-std-b67', hdr_fill=(('color_primaries', 'bt2020'),))
    >>> source_colour({"pix_fmt": "yuv420p10le", "height": 2160,
    ...                "color_transfer": "arib-std-b67"}).hdr_fill
    (('color_primaries', 'bt2020'), ('colorspace', 'bt2020nc'))
    """
    untagged_hd_yuv = (
        stream.get("color_space", "") in _UNTAGGED
        and str(stream.get("pix_fmt", "")).startswith("yuv")
        # yuvj is JPEG's full-range YUV, which JFIF defines as BT.601
        and not str(stream.get("pix_fmt", "")).startswith("yuvj")
        and is_hd(int(stream.get("width") or 0), int(stream.get("height") or 0))
    )
    transfer = stream.get("color_transfer")
    if transfer in HDR_TRANSFERS:
        fill = tuple(
            (tag, value)
            for key, tag, value in _HDR_TAGS
            if stream.get(key, "") in _UNTAGGED
        )
        return SourceColour(hdr_transfer=transfer, hdr_fill=fill)
    return SourceColour(in_matrix=DELIVERY_COLOR_SPACE if untagged_hd_yuv else None)


#: (ffprobe key, setparams option, the HDR standard's value) for the tags an HDR source
#: may leave out.
_HDR_TAGS = (
    ("color_primaries", "color_primaries", "bt2020"),
    ("color_space", "colorspace", "bt2020nc"),
)


def read_source_colour(
    path: str, *, probe: "Optional[Callable]" = None
) -> SourceColour:
    """The :class:`SourceColour` of the first video stream of ``path``.

    A file ffprobe cannot read gets the default (``scale`` reads the tag): the render
    of that file is where an unreadable source is reported, not here.
    """
    from muvid.visualize.ffmpeg import FfmpegError
    from muvid.visualize.ffmpeg import probe as ffprobe

    try:
        info = (probe or ffprobe)(path)
    except FfmpegError:
        return SourceColour()
    stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"), None
    )
    return SourceColour() if stream is None else source_colour(stream)


__all__ = [
    "DELIVERY_COLOR_RANGE",
    "DELIVERY_COLOR_SPACE",
    "DELIVERY_TAG",
    "HD_MIN_WIDTH",
    "SD_MAX_HEIGHT",
    "HDR_TRANSFERS",
    "SourceColour",
    "ToneMap",
    "DEFAULT_TONE_MAP",
    "TONEMAP",
    "TONEMAP_CURVES",
    "TONEMAP_PARAM",
    "MIN_REFERENCE_WHITE_NITS",
    "MAX_REFERENCE_WHITE_NITS",
    "HDR_REFERENCE_WHITE_NITS",
    "can_tonemap",
    "tonemap_chain",
    "read_source_colour",
    "is_hd",
    "source_colour",
]
