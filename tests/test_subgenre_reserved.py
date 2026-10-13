"""Reserved subgenre slugs are refused where a plugin is judged, not at project creation (muvid#167).

``footage`` and ``visualizer`` name muvid's own drawers (muvid#103). The refusal
used to live only in ``SubgenreWorkspace.for_slug``, so conformance reported ok
and the nw bridge registered a genre whose project factory could only raise.
Refusing earlier removes nothing from disk: drawers are read from the data root,
so every existing project id stays readable.
"""

from __future__ import annotations

import tempfile
import warnings
from importlib.metadata import EntryPoint

import pytest

import muvid.subgenres._registry as reg
from muvid.subgenres import Subgenre, register_subgenre, subgenre_catalog
from muvid.subgenres._manifest import RESERVED_SLUGS
from muvid.subgenres.testing import check_subgenre_conformance

RESERVED = sorted(RESERVED_SLUGS)


def _manifest(slug: str) -> Subgenre:
    return Subgenre(
        slug=slug,
        title="T",
        description="d",
        render="muvid.subgenres.testing:echo_renderer",
        api_versions=("1",),
    )


@pytest.fixture
def clean_registry():
    saved = dict(reg._SUBGENRES)
    yield
    reg._SUBGENRES.clear()
    reg._SUBGENRES.update(saved)
    reg._DISCOVERED = None
    reg._LOAD_ERRORS.clear()


def test_the_workspace_and_the_manifest_share_one_set():
    from muvid.mcp import workspace

    assert workspace.RESERVED_SLUGS is RESERVED_SLUGS
    assert RESERVED_SLUGS == {"footage", "visualizer"}


@pytest.mark.parametrize("slug", RESERVED)
def test_conformance_refuses_a_reserved_slug(slug):
    with tempfile.TemporaryDirectory() as d:
        report = check_subgenre_conformance(_manifest(slug), workdir=d)
    assert not report.ok
    assert any("reserved" in f for f in report.failures)


def test_conformance_still_passes_an_ordinary_slug():
    with tempfile.TemporaryDirectory() as d:
        assert check_subgenre_conformance(_manifest("a-fine-slug"), workdir=d).ok


@pytest.mark.parametrize("slug", RESERVED)
def test_register_subgenre_refuses_a_reserved_slug(slug, clean_registry):
    with pytest.raises(ValueError, match="reserved"):
        register_subgenre(_manifest(slug))
    assert slug not in reg._SUBGENRES


def test_an_installed_plugin_with_a_reserved_slug_is_recorded_and_skipped(
    monkeypatch, clean_registry
):
    class _Entry(EntryPoint):
        def load(self):  # type: ignore[override]
            return _manifest("visualizer")

    ep = _Entry(name="squatter", value="x:y", group=reg.ENTRY_POINT_GROUP)
    monkeypatch.setattr(
        "importlib.metadata.entry_points", lambda **kw: [ep] if kw else []
    )
    with pytest.warns(RuntimeWarning, match="could not load subgenre plugin"):
        cat = subgenre_catalog(refresh=True)
    assert "reserved" in cat["load_errors"]["squatter"]
    assert "visualizer" not in [s["slug"] for s in cat["subgenres"]]


def test_the_bridge_skips_a_reserved_slug_and_records_why(clean_registry):
    nw = pytest.importorskip("nw")
    import muvid.genre  # noqa: F401  (hand-written genres first, as at import)
    from muvid import genre_subgenres

    # a manifest that got past register_subgenre, which a poked registry can do
    reg._SUBGENRES["visualizer"] = _manifest("visualizer")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bridged = genre_subgenres.bridge_subgenres(refresh=True)
    assert "visualizer" not in bridged
    assert "visualizer" not in genre_subgenres.BRIDGED
    # nw's own built-in is untouched and no muvid factory replaced it
    assert getattr(nw.get_genre("music-visualizer"), "slug", None) == "music-visualizer"
    assert "reserved" in reg.subgenre_catalog()["load_errors"]["visualizer"]


def test_existing_project_ids_stay_readable(tmp_path, monkeypatch):
    nw = pytest.importorskip("nw")
    import muvid.genre  # noqa: F401
    from muvid import downloads
    from muvid.mcp.workspace import SubgenreWorkspace, VisualizerWorkspace

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    email = "u@x.com"
    nw.create_genre_project("music-visualizer", email, "viz", template="cqt")
    nw.create_genre_project("lyric-video", email, "lv")
    for proj, rid in (
        (VisualizerWorkspace.for_email(email).open_project("viz"), "v" * 12),
        (SubgenreWorkspace.for_slug("lyric-video", email).open_project("lv"), "l" * 12),
    ):
        d = proj.new_render_dir(rid)
        (d / "video.mp4").write_bytes(b"\x00" * 16)
        proj.write_render_meta(rid, {"render_id": rid})

    before = {(p.project_id, p.meta["muvid_genre"]) for p in downloads.list_projects(email)}
    with pytest.raises(ValueError, match="reserved"):
        register_subgenre(_manifest("visualizer"))
    after = {(p.project_id, p.meta["muvid_genre"]) for p in downloads.list_projects(email)}
    assert before == after == {("viz", "visualizer"), ("lv", "lyric-video")}
    assert downloads.resolve(email, "viz", "v" * 12).meta["muvid_genre"] == "visualizer"
    assert downloads.resolve(email, "lv", "l" * 12).meta["muvid_genre"] == "lyric-video"


def test_render_stem_needs_no_disk_scan(monkeypatch):
    from muvid import downloads

    monkeypatch.setattr(downloads, "_sources", lambda: pytest.fail("rescanned"))
    assert downloads._render_stem("footage") == "final"
    assert downloads._render_stem("visualizer") == "video"
    assert downloads._render_stem("lyric-video") == "video"
