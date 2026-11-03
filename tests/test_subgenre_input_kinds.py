"""A subgenre input says what media it is; the name table is only the backstop
(muvid#293). A plugin's ``song`` input — a name no table lists — is fetched and checked
as audio when it declares it."""

import pytest

pytest.importorskip("fastmcp")

from muvid.mcp import subgenre_tools as st  # noqa: E402


def _schema(**props):
    return {"properties": props}


def test_x_muvid_kind_declares_the_kind():
    schema = _schema(song={"type": "string", "x-muvid-kind": "audio"})
    assert st._is_file_input("song", schema)
    assert st._declared_kind("song", schema) == "audio"


def test_content_media_type_declares_it_too():
    schema = _schema(
        song={"type": "string", "contentMediaType": "audio/mpeg"},
        notes={"type": "string", "contentMediaType": "text/markdown"},
        shots={"type": "array", "items": {"contentMediaType": "video/mp4"}},
    )
    assert st._declared_kind("song", schema) == "audio"
    assert st._declared_kind("notes", schema) == ""  # a file, nothing to assert
    assert st._declared_kind("shots", schema) == "video"
    assert all(st._is_file_input(n, schema) for n in ("song", "notes", "shots"))


def test_an_undeclared_input_falls_back_to_its_name():
    assert st._declared_kind("audio", _schema()) is None
    assert st._is_file_input("audio", _schema())  # the backstop table
    assert not st._is_file_input("tempo", _schema(tempo={"type": "number"}))


def test_an_unknown_declared_kind_is_refused():
    with pytest.raises(ValueError, match="x-muvid-kind"):
        st._declared_kind("song", _schema(song={"x-muvid-kind": "smell"}))


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
