"""``stylize`` and ``looks`` Rule 22 (muvid#190): an RGB-only step needs a colour space."""

import pytest

import looks

from tests.ffmpeg_support import needs_ffmpeg
from muvid.footage.look import DEFAULT_ASSUMED_COLOR_SPACE, LookError, stylize

_GRADE = looks.Look(steps=(looks.Effect(name="saturation", params={"amount": 0.0}),))
_KW = dict(canvas=(640, 360), fps=25, duration_s=3.0)


@needs_ffmpeg
def test_default_declares_the_assumed_space_on_the_filter_chain():
    frag = stylize(_GRADE, **_KW)
    assert f"in_color_matrix={DEFAULT_ASSUMED_COLOR_SPACE}" in frag


@needs_ffmpeg
def test_opting_out_keeps_the_upstream_refusal():
    with pytest.raises(LookError, match="colour space"):
        stylize(_GRADE, assume_color_space=None, **_KW)

