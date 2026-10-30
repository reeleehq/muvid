"""The lyric-video stages muvid exposes, and the settings section it owns (muvid#158)."""

import pytest

from muvid.lyricvid import glyph_align as ga
from muvid.lyricvid import stages as st


def test_own_stages_are_listed_in_order_without_importing_renderers():
    names = list(st.lyric_stages(include_plugins=False))
    assert names == ["stem", "glyphs", "render", "pictures", "captions"]


def test_entry_point_group_registers_every_own_stage():
    from importlib.metadata import entry_points

    found = {ep.name: ep.value for ep in entry_points(group=st.ENTRY_POINT_GROUP)}
    if not found:
        pytest.skip("muvid is not installed with its entry points")
    assert set(found) >= {"stem", "glyphs", "render", "pictures", "captions"}
    assert set(st.lyric_stages()) >= set(found)


def test_every_stage_resolves_to_a_callable():
    for stage in st.lyric_stages(include_plugins=False).values():
        assert callable(stage.resolve()), stage.name


def test_stage_rejects_bad_manifest():
    with pytest.raises(ValueError):
        st.Stage("x", "s", "no_colon")
    with pytest.raises(ValueError):
        st.Stage("x", "s", "a:b", memory="huge")


def test_heavy_and_costed_flags_let_a_runner_cap_memory_and_gate_money():
    own = st.lyric_stages(include_plugins=False)
    assert own["glyphs"].memory == "heavy" and own["stem"].costed
    assert not own["render"].costed


def test_settings_from_mapping_refuses_typos():
    with pytest.raises(ValueError, match="unknown muvid settings"):
        st.LyricProductionSettings.from_mapping({"keep_unsong": True})


def test_settings_defaults_and_override_forms():
    s = st.LyricProductionSettings.from_mapping(
        {
            "timing_overrides": {"3": "fine", "5": {"how": "fine", "reason": "vendor junk"}},
            "emphasis": ["pluie"],
        }
    )
    assert s.emphasis == ("pluie",)
    assert s.timing_override_values() == {"3": "fine", "5": "fine"}
    assert s.timing_override_reasons() == {"5": "vendor junk"}
    assert st.LyricProductionSettings.from_mapping(None) == st.LyricProductionSettings()


def test_aligner_accepts_recorded_reason_form():
    assert ga.check_timing_overrides({"1": {"how": "fine", "reason": "r"}, 2: "fine"}, 4) == {
        1: "fine",
        2: "fine",
    }
    with pytest.raises(ValueError):
        ga.check_timing_overrides({"1": {"how": "bogus"}}, 4)


def test_schema_accepts_both_override_forms():
    jsonschema = pytest.importorskip("jsonschema")
    ok = {"timing_overrides": {"1": "fine", "2": {"how": "fine", "reason": "x"}}}
    jsonschema.validate(ok, st.LYRIC_PRODUCTION_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"nope": 1}, st.LYRIC_PRODUCTION_SCHEMA)
