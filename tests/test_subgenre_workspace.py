"""Subgenre projects have their own workspace, and old ones stay readable (muvid#103).

Before muvid#103 every lyric-video (and bridged subgenre) project was created in the
visualizer's workspace: one project-id space across genres, and every such project
listed as ``muvid_genre: "visualizer"``. New projects now go to
``{root}/subgenres/{slug}/projects/{email}/{id}/``. Nothing on disk is moved: an old
project is opened, rendered into, downloaded and organised where it already is.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

nw = pytest.importorskip("nw")

import muvid.genre  # noqa: E402,F401  (registers the genres and their factories)
from muvid import downloads  # noqa: E402
from muvid.mcp.workspace import (  # noqa: E402
    SubgenreWorkspace,
    VisualizerWorkspace,
    open_subgenre_project,
    subgenre_slugs_on_disk,
)

EMAIL = "u@x.com"


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    return tmp_path


def _render(proj, render_id: str, meta: dict) -> None:
    d = proj.new_render_dir(render_id)
    (d / "video.mp4").write_bytes(b"\x00" * 16)
    proj.write_render_meta(render_id, {"render_id": render_id, **meta})


def _labels(email=EMAIL) -> dict:
    return {
        (p.project_id, p.meta["muvid_genre"]) for p in downloads.list_projects(email)
    }


def test_a_lyric_video_project_gets_its_own_directory_and_id_space(data):
    nw.create_genre_project("music_visualizer", EMAIL, "p1", template="cqt")
    # Before muvid#103 this raised FileExistsError: one id space across genres.
    nw.create_genre_project("lyric-video", EMAIL, "p1")
    root = SubgenreWorkspace.for_slug("lyric-video", EMAIL).open_project("p1").root
    assert root == data / "subgenres" / "lyric-video" / "projects" / EMAIL / "p1"
    assert _labels() == {("p1", "visualizer"), ("p1", "lyric-video")}


def test_a_bridged_subgenre_project_lands_in_its_own_directory(data):
    from muvid.genre_subgenres import _factory

    factory = _factory(SimpleNamespace(slug="test-sub"))
    out = factory(EMAIL, "q", title="Q", template=None, params={"subgenre": "x"})
    assert out["project"].root == data / "subgenres" / "test-sub" / "projects" / EMAIL / "q"
    assert ("q", "test-sub") in _labels()


def test_an_old_subgenre_project_in_the_visualizer_drawer_is_labelled_by_its_renders(data):
    ws = VisualizerWorkspace.for_email(EMAIL)
    lyric = ws.create_project("old-lyric")
    _render(lyric, "a" * 12, {"meta": {"treatment_source": "proposed"}})
    sub = ws.create_project("old-sub")
    _render(sub, "b" * 12, {"subgenre": "choreo", "meta": {}})
    plain = ws.create_project("viz")
    _render(plain, "c" * 12, {"visual": "cqt"})
    ws.create_project("empty")
    assert _labels() == {
        ("old-lyric", "lyric-video"),
        ("old-sub", "choreo"),
        ("viz", "visualizer"),
        ("empty", "visualizer"),
    }
    # Read in place: nothing was moved.
    assert not (data / "subgenres").exists()
    got = downloads.resolve(EMAIL, "old-lyric", "a" * 12)
    assert got.meta["muvid_genre"] == "lyric-video"


def test_the_subgenre_tools_open_their_own_bucket_else_an_old_visualizer_one(data):
    old = VisualizerWorkspace.for_email(EMAIL).create_project("legacy")
    assert open_subgenre_project("lyric-video", EMAIL, "legacy").root == old.root
    nw.create_genre_project("music_visualizer", EMAIL, "both", template="cqt")
    nw.create_genre_project("lyric-video", EMAIL, "both")
    new = SubgenreWorkspace.for_slug("lyric-video", EMAIL).open_project("both")
    assert open_subgenre_project("lyric-video", EMAIL, "both").root == new.root
    with pytest.raises(FileNotFoundError):
        open_subgenre_project("lyric-video", EMAIL, "nobody")


def test_one_id_in_two_drawers_resolves_and_organises_each_render_where_it_is(data):
    nw.create_genre_project("music_visualizer", EMAIL, "p1", template="cqt")
    nw.create_genre_project("lyric-video", EMAIL, "p1")
    viz = VisualizerWorkspace.for_email(EMAIL).open_project("p1")
    lyr = SubgenreWorkspace.for_slug("lyric-video", EMAIL).open_project("p1")
    _render(viz, "v" * 12, {"visual": "cqt"})
    _render(lyr, "l" * 12, {"subgenre": "lyric-video"})

    assert downloads.resolve(EMAIL, "p1", "v" * 12).meta["muvid_genre"] == "visualizer"
    assert downloads.resolve(EMAIL, "p1", "l" * 12).meta["muvid_genre"] == "lyric-video"
    with pytest.raises(KeyError):
        downloads.resolve(EMAIL, "p1", "z" * 12)

    downloads.organise(EMAIL, "p1", "l" * 12, title="Take two")
    meta = json.loads((lyr.renders_dir / ("l" * 12) / "meta.json").read_text())
    assert meta["organise"] == {"title": "Take two"}
    assert downloads.resolve(EMAIL, "p1", "Take two").artifact_id == "l" * 12
    kinds = {d.meta["muvid_genre"] for d in downloads.list_deliverables(EMAIL)}
    assert kinds == {"visualizer", "lyric-video"}


def test_the_workspace_is_per_subgenre_and_the_drawers_come_from_disk(data):
    with pytest.raises(TypeError, match="for_slug"):
        SubgenreWorkspace.for_email(EMAIL)
    assert subgenre_slugs_on_disk() == ()
    SubgenreWorkspace.for_slug("lyric-video", EMAIL).create_project("p")
    (data / "subgenres" / "stray-file").write_text("not a drawer")
    # A directory shadowing a built-in drawer is never read as a subgenre.
    (data / "subgenres" / "visualizer" / "projects").mkdir(parents=True)
    assert subgenre_slugs_on_disk() == ("lyric-video", "visualizer")
    kinds = [k for k, _w, _s in downloads._sources()]
    assert kinds == ["footage", "visualizer", "lyric-video"]


def test_project_status_reports_the_subgenre(data):
    pytest.importorskip("fastmcp")
    from muvid.mcp import tools
    from muvid.mcp.identity import use_email

    nw.create_genre_project("lyric-video", EMAIL, "lv")
    with use_email(EMAIL):
        assert tools.project_status("lv")["muvid_genre"] == "lyric-video"
        rows = tools.list_projects()["projects"]
    assert [(r["project_id"], r["muvid_genre"]) for r in rows] == [("lv", "lyric-video")]


# -- adversarial-review findings: one id in two drawers ------------------------


def _two_drawers(*, email=EMAIL):
    nw.create_genre_project("music_visualizer", email, "p1", template="cqt")
    nw.create_genre_project("lyric-video", email, "p1")
    viz = VisualizerWorkspace.for_email(email).open_project("p1")
    lyr = SubgenreWorkspace.for_slug("lyric-video", email).open_project("p1")
    _render(viz, "v" * 12, {"visual": "cqt"})
    _render(lyr, "l" * 12, {"subgenre": "lyric-video"})
    return viz, lyr


def test_a_title_in_one_drawer_never_shadows_a_render_id_in_another(data):
    _two_drawers()
    # The title would make resolve('l'*12) serve the visualizer render.
    with pytest.raises(ValueError, match="collides with render id"):
        downloads.organise(EMAIL, "p1", "v" * 12, title="l" * 12)
    # Even a title written straight to disk cannot beat a raw id elsewhere.
    viz = VisualizerWorkspace.for_email(EMAIL).open_project("p1")
    meta = json.loads((viz.renders_dir / ("v" * 12) / "meta.json").read_text())
    meta["organise"] = {"title": "l" * 12}
    viz.write_render_meta("v" * 12, meta)
    assert downloads.resolve(EMAIL, "p1", "l" * 12).artifact_id == "l" * 12


def test_a_title_must_be_unique_across_drawers(data):
    _two_drawers()
    downloads.organise(EMAIL, "p1", "v" * 12, title="Final")
    with pytest.raises(ValueError, match="already the title"):
        downloads.organise(EMAIL, "p1", "l" * 12, title="final")
    assert downloads.resolve(EMAIL, "p1", "Final").artifact_id == "v" * 12


def test_project_status_shows_every_drawer_holding_the_id(data):
    pytest.importorskip("fastmcp")
    from muvid.mcp import tools
    from muvid.mcp.identity import use_email

    _two_drawers()
    with use_email(EMAIL):
        st = tools.project_status("p1")
    assert st["muvid_genre"] == "visualizer"
    assert [r["render_id"] for r in st["renders"]] == ["v" * 12]
    [other] = st["also_in"]
    assert other["muvid_genre"] == "lyric-video"
    assert [r["render_id"] for r in other["renders"]] == ["l" * 12]


def test_creating_an_old_subgenre_project_again_is_refused_not_forked(data):
    old = VisualizerWorkspace.for_email(EMAIL).create_project("song")
    _render(old, "a" * 12, {"meta": {"treatment_source": "proposed"}})
    with pytest.raises(FileExistsError):
        nw.create_genre_project("lyric-video", EMAIL, "song")
    assert open_subgenre_project("lyric-video", EMAIL, "song").root == old.root
    # A visualizer bucket that is not this subgenre's does not block the id.
    viz = VisualizerWorkspace.for_email(EMAIL).create_project("tune")
    _render(viz, "c" * 12, {"visual": "cqt"})
    nw.create_genre_project("lyric-video", EMAIL, "tune")


def test_a_mixed_visualizer_bucket_stays_labelled_visualizer(data):
    ws = VisualizerWorkspace.for_email(EMAIL)
    mixed = ws.create_project("mixed")
    for i in range(3):
        _render(mixed, f"{i}" * 12, {"visual": "cqt"})
    _render(mixed, "0" * 11 + "a", {"meta": {"treatment_source": "proposed"}})
    assert _labels() == {("mixed", "visualizer")}
    # Each render still says what made it.
    by_id = {d.artifact_id: d.meta["muvid_genre"] for d in downloads.list_deliverables(EMAIL)}
    assert by_id["0" * 11 + "a"] == "lyric-video" and by_id["1" * 12] == "visualizer"


def test_a_subgenre_cannot_take_a_built_in_drawer_name(data):
    for slug in ("footage", "visualizer"):
        with pytest.raises(ValueError, match="reserved"):
            SubgenreWorkspace.for_slug(slug, EMAIL)


# -- second review pass ---------------------------------------------------------


def test_a_failed_render_is_not_evidence(data):
    old = VisualizerWorkspace.for_email(EMAIL).create_project("pA")
    _render(old, "a" * 12, {"meta": {"treatment_source": "proposed"}})
    old.new_render_dir("b" * 12)  # a refused render: a folder, no meta.json
    assert _labels() == {("pA", "lyric-video")}
    with pytest.raises(FileExistsError):
        SubgenreWorkspace.for_slug("lyric-video", EMAIL).create_project("pA")


def test_fetched_lyric_inputs_are_evidence_for_an_unrendered_bucket(data):
    old = VisualizerWorkspace.for_email(EMAIL).create_project("drafted")
    (old.root / "lyricvid").mkdir()
    assert _labels() == {("drafted", "lyric-video")}
    with pytest.raises(FileExistsError):
        nw.create_genre_project("lyric-video", EMAIL, "drafted")


@pytest.mark.parametrize("named", ["footage", "visualizer", "../x", "a/b", ""])
def test_a_subgenre_name_that_cannot_be_a_drawer_is_not_believed(data, named):
    old = VisualizerWorkspace.for_email(EMAIL).create_project("odd")
    _render(old, "a" * 12, {"subgenre": named})
    assert _labels() == {("odd", "visualizer")}
