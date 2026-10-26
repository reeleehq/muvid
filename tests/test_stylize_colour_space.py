"""``stylize`` and ``looks`` Rule 22 (muvid#190): an RGB-only step needs a colour space."""

import pytest

looks = pytest.importorskip("looks")

from muvid.footage.look import DEFAULT_ASSUMED_COLOR_SPACE, LookError, stylize

_GRADE = looks.Look(steps=(looks.Effect(name="saturation", params={"amount": 0.0}),))
_KW = dict(canvas=(640, 360), fps=25, duration_s=3.0)


def test_default_declares_the_assumed_space_on_the_filter_chain():
    frag = stylize(_GRADE, **_KW)
    assert f"in_color_matrix={DEFAULT_ASSUMED_COLOR_SPACE}" in frag


def test_opting_out_keeps_the_upstream_refusal():
    with pytest.raises(LookError, match="colour space"):
        stylize(_GRADE, assume_color_space=None, **_KW)


def test_a_different_space_is_honoured():
    assert "in_color_matrix=bt2020" in stylize(
        _GRADE, assume_color_space="bt2020nc", **_KW
    )
