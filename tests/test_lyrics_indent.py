"""Shaped lyric input: the default parse is pinned, and flattening it says so (muvid#109).

``parse_lyrics_md`` strips leading whitespace, which destroys a drawn layout
before any archetype sees it. The fix is a signal plus an opt-in, never a change
of default: a live pipeline renders from this parser daily, so
``tests/data/lyrics_parse_golden.json`` — recorded from the parser *before*
muvid#109 touched it — pins the default output byte for byte, including the
shaped and oddly-whitespaced inputs a future "fix" would be tempted to change.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from muvid.lyrics import (
    ShapedLyricsWarning,
    indentation_varies,
    line_indents,
    parse_lyrics_md,
    read_lyrics_md,
    render_lyrics_md,
)

GOLDEN = json.loads(
    (Path(__file__).parent / "data" / "lyrics_parse_golden.json").read_text(
        encoding="utf-8"
    )
)

IL_PLEUT = GOLDEN["il_pleut_shaped"]["md"]


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_default_parse_is_byte_identical_to_before(name):
    case = GOLDEN[name]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ShapedLyricsWarning)
        doc = parse_lyrics_md(case["md"])
    assert repr(doc) == case["repr"]
    assert render_lyrics_md(doc) == case["rendered"]


def test_shaped_input_warns_and_names_the_way_out():
    with pytest.warns(ShapedLyricsWarning, match="preserve_indent=True"):
        parse_lyrics_md(IL_PLEUT)


@pytest.mark.parametrize(
    "name", ["plain", "sections_anchors_placeholders", "uniform_indent", "empty"]
)
def test_unshaped_input_is_silent(name):
    # Uniform indentation carries no shape: nothing is lost, so nothing is said.
    with warnings.catch_warnings():
        warnings.simplefilter("error", ShapedLyricsWarning)
        parse_lyrics_md(GOLDEN[name]["md"])


def test_preserve_indent_keeps_the_shape_and_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error", ShapedLyricsWarning)
        doc = parse_lyrics_md(IL_PLEUT, preserve_indent=True)
    assert [L.text for L in doc.lines] == [
        "Il pleut des voix de femmes",
        "  comme si elles",
        "    étaient mortes",
        "      même dans le souvenir",
        "\tc'est vous aussi",
        "        qu'il pleut",
    ]
    assert doc.lines[-1].start_s == 7.5


def test_preserve_indent_changes_only_the_text():
    with pytest.warns(ShapedLyricsWarning):
        default = parse_lyrics_md(IL_PLEUT, preserve_indent=False)
    kept = parse_lyrics_md(IL_PLEUT, preserve_indent=True)
    assert [(L.line_index, L.section_label, L.start_s) for L in kept.lines] == [
        (L.line_index, L.section_label, L.start_s) for L in default.lines
    ]
    assert [L.text.lstrip() for L in kept.lines] == [L.text for L in default.lines]


def test_preserve_indent_round_trips_through_render():
    doc = parse_lyrics_md(IL_PLEUT, preserve_indent=True)
    again = parse_lyrics_md(render_lyrics_md(doc), preserve_indent=True)
    assert again == doc


def test_line_indents_aligns_with_the_parsed_lines():
    indents = line_indents(IL_PLEUT)
    assert len(indents) == len(parse_lyrics_md(IL_PLEUT, preserve_indent=True).lines)
    assert indents == ("", "  ", "    ", "      ", "\t", "        ")
    assert indentation_varies(indents)
    assert not indentation_varies(line_indents(GOLDEN["uniform_indent"]["md"]))


def test_read_lyrics_md_threads_the_option(tmp_path):
    path = tmp_path / "lyrics.md"
    path.write_text(IL_PLEUT, encoding="utf-8")
    assert read_lyrics_md(path, preserve_indent=True).lines[1].text == "  comme si elles"
    with pytest.warns(ShapedLyricsWarning):
        assert read_lyrics_md(path).lines[1].text == "comme si elles"
