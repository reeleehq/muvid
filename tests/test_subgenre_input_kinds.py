"""A subgenre input says what media it is; the name table is only the backstop
(muvid#293). A plugin's ``song`` input — a name no table lists — is fetched and checked
as audio when it declares it."""

import pytest

pytest.importorskip("fastmcp")

from muvid.mcp import subgenre_tools as st  # noqa: E402
from muvid.subgenres._schema import SchemaError, declared_media_kind  # noqa: E402


def _schema(**props):
    return {"properties": props}


def test_x_muvid_kind_declares_the_kind():
    schema = _schema(song={"type": "string", "x-muvid-kind": "audio"})
    assert st._is_file_input("song", schema)
    assert declared_media_kind("song", schema) == "audio"


def test_content_media_type_declares_it_too():
    schema = _schema(
        song={"type": "string", "contentMediaType": "audio/mpeg"},
        notes={"type": "string", "contentMediaType": "text/markdown"},
        shots={"type": "array", "items": {"contentMediaType": "video/mp4"}},
    )
    assert declared_media_kind("song", schema) == "audio"
    assert declared_media_kind("notes", schema) == ""  # a file, nothing to assert
    assert declared_media_kind("shots", schema) == "video"
    assert all(st._is_file_input(n, schema) for n in ("song", "notes", "shots"))


def test_an_undeclared_input_falls_back_to_its_name():
    assert declared_media_kind("audio", _schema()) is None
    assert st._is_file_input("audio", _schema())  # the backstop table
    assert not st._is_file_input("tempo", _schema(tempo={"type": "number"}))


def test_an_unknown_declared_kind_is_refused():
    with pytest.raises(SchemaError, match="x-muvid-kind"):
        declared_media_kind("song", _schema(song={"x-muvid-kind": "smell"}))


def test_the_declared_kind_reaches_the_fetch(monkeypatch, tmp_path):
    """render_subgenre hands the intake the DECLARED kind, for a name no table lists."""
    from muvid.mcp.identity import use_email
    from muvid.subgenres import Subgenre

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    manifest = Subgenre(
        slug="kinded",
        title="Kinded",
        description="a test plugin",
        render="nowhere:render",
        api_versions=("1",),
        inputs={
            "type": "object",
            "properties": {"song": {"type": "string", "x-muvid-kind": "audio"}},
        },
    )
    monkeypatch.setattr("muvid.subgenres.get_subgenre", lambda slug: manifest)
    from muvid.mcp.workspace import SubgenreWorkspace

    SubgenreWorkspace.for_slug("kinded", "u@x.com").create_project("p")
    seen = []

    def fake(url, dest, *, label, kind=None):
        seen.append((label, kind))
        raise st._tool_error("stopped at the fetch")

    monkeypatch.setattr(st, "_resolve_input", fake)
    with use_email("u@x.com"), pytest.raises(Exception, match="stopped at the fetch"):
        st.render_subgenre("p", subgenre="kinded", inputs={"song": "https://x/s"})
    assert seen == [("song", "audio")]


def test_a_kind_on_the_array_itself_counts():
    """The #293 review: a list input declaring its kind at the array level was not a
    file input, so raw URL strings reached the renderer (muvid#23's trap)."""
    schema = _schema(shots={"type": "array", "x-muvid-kind": "image"})
    assert st._is_file_input("shots", schema)
    assert declared_media_kind("shots", schema) == "image"


def test_a_declared_kind_only_adds_a_check(monkeypatch, tmp_path):
    """``application/ogg`` (Ogg audio's official type) maps to "" — it must not remove
    the audio check an input named ``audio`` always had."""
    from muvid.mcp import tools

    seen = []
    monkeypatch.setattr(
        "muvid.mcp._fetch.fetch_media",
        lambda url, dest, *, kind="", max_bytes=None: seen.append(kind) or dest,
    )
    tools._resolve_input("https://x/a", tmp_path / "a", label="audio", kind="")
    tools._resolve_input("https://x/a", tmp_path / "b", label="song", kind="")
    assert seen == ["audio", ""]


def test_a_misdeclared_kind_is_a_clean_refusal_before_any_folder(monkeypatch, tmp_path):
    from muvid.mcp.identity import use_email
    from muvid.mcp.workspace import SubgenreWorkspace
    from muvid.subgenres import Subgenre

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    manifest = Subgenre(
        slug="smelly",
        title="Smelly",
        description="a test plugin",
        render="nowhere:render",
        api_versions=("1",),
        inputs={"type": "object", "properties": {"song": {"x-muvid-kind": "smell"}}},
    )
    monkeypatch.setattr("muvid.subgenres.get_subgenre", lambda slug: manifest)
    proj = SubgenreWorkspace.for_slug("smelly", "u@x.com").create_project("p")
    from fastmcp.exceptions import ToolError

    with use_email("u@x.com"), pytest.raises(ToolError, match="misdeclared"):
        st.render_subgenre("p", subgenre="smelly", inputs={"song": "https://x/s"})
    assert not proj.renders_dir.exists() or not any(proj.renders_dir.iterdir())


def test_the_conformance_kit_reports_a_misdeclared_kind_at_any_level():
    from muvid.subgenres._schema import media_kind_problems

    schema = _schema(
        shots={
            "type": "array",
            "x-muvid-kind": "image",
            "items": {"x-muvid-kind": "smell"},
        },
        flag=True,  # a boolean subschema is legal JSON Schema and declares nothing
    )
    problems = media_kind_problems(schema)
    assert len(problems) == 1 and "smell" in problems[0]
    assert declared_media_kind("flag", schema) is None


def test_check_subgenre_conformance_carries_it(tmp_path):
    from muvid.subgenres import Subgenre
    from muvid.subgenres.testing import check_subgenre_conformance

    bad = Subgenre(
        slug="smelly",
        title="Smelly",
        description="a test plugin",
        render="nowhere:render",
        api_versions=("1",),
        inputs={"type": "object", "properties": {"song": {"x-muvid-kind": "smell"}}},
    )
    report = check_subgenre_conformance(bad, workdir=tmp_path, render=False)
    assert any("smell" in f for f in report.failures)


def test_one_table_decides_both_what_is_fetched_and_what_is_checked(
    monkeypatch, tmp_path
):
    """muvid#328: the fetch decision and the kind asserted were two name tables that
    could drift. Both now read ``BACKSTOP_INPUT_KINDS``: every name in it is fetched as
    a file AND has its kind asserted on the bytes; a name outside it is neither."""
    from muvid.mcp import _fetch, tools
    from muvid.subgenres._schema import BACKSTOP_INPUT_KINDS

    seen = {}
    monkeypatch.setattr(
        _fetch,
        "fetch_media",
        lambda url, dest, *, kind="": seen.update(kind=kind) or dest,
    )
    for name, kind in BACKSTOP_INPUT_KINDS.items():
        assert st._is_file_input(name, {"properties": {}}), name
        tools._resolve_input("https://example.com/x", tmp_path / "x", label=name)
        assert seen["kind"] == kind, name
    assert not st._is_file_input("tempo", {"properties": {}})
    tools._resolve_input("https://example.com/x", tmp_path / "x", label="tempo")
    assert seen["kind"] == ""
    # a declared kind still wins over the backstop
    tools._resolve_input(
        "https://example.com/x", tmp_path / "x", label="audio", kind="video"
    )
    assert seen["kind"] == "video"
