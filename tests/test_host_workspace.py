"""muvid's tools find the projects a HOST placed in the caller's tree (muvid#296).

A host creates ``music_video`` / ``music_visualizer`` projects in its own per-caller
bucket (``nw.create_genre_project(..., projects_dir=...)``) and registers where that
bucket is (``nw.caller_projects_dir``). These pin that muvid's resolvers then open
those projects, refuse everything else with the same "no such project", and change
nothing when no host is registered.
"""

from __future__ import annotations

import json

import pytest

nw = pytest.importorskip("nw")

from muvid import downloads  # noqa: E402
from muvid.downloads import caller_workspaces, open_caller_project  # noqa: E402

A, B = "a@x.com", "b@x.com"


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A host that keeps each caller's projects at ``<tmp>/host/projects/<email>``."""
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path / "muvid"))
    root = tmp_path / "host" / "projects"
    monkeypatch.setattr(
        nw, "caller_projects_dir", lambda email: root / email, raising=False
    )
    return root


def _place(host, email, pid, genre):
    import muvid.genre  # noqa: F401 — registers the factories

    bucket = host / email
    bucket.mkdir(parents=True, exist_ok=True)
    nw.create_genre_project(genre, email, pid, projects_dir=bucket)
    return bucket / pid


def test_no_host_means_no_drawer(tmp_path, monkeypatch):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(nw, "caller_projects_dir", lambda email: None, raising=False)
    with pytest.raises(FileNotFoundError):
        open_caller_project(A, "p", kind="footage")
    assert all(ws.list_projects() == [] for ws in caller_workspaces(A, "footage"))


def test_an_nw_without_the_locator_means_no_drawer(tmp_path, monkeypatch):
    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    monkeypatch.delattr(nw, "caller_projects_dir", raising=False)
    with pytest.raises(FileNotFoundError):
        open_caller_project(A, "p", kind="visualizer")


def test_a_host_placed_music_video_opens_as_the_callers_footage(host):
    from muvid.footage import service
    from muvid.footage.workspace import MusicVideoFootageProject

    root = _place(host, A, "mv", "music_video")
    fp = open_caller_project(A, "mv", kind="footage")
    assert isinstance(fp, MusicVideoFootageProject)
    assert (fp.root, fp.email) == (root / "footage", A)
    assert service.status(fp)["has_song"] is False  # the ops work on it as-is


def test_a_project_of_another_genre_is_no_such_project(host):
    """The genre check is load-bearing: a story handed to a footage tool must not
    sprout a footage/ folder, and must read exactly like an absent id."""
    root = _place(host, A, "lv", "lyric-video")
    for kind in ("footage", "visualizer"):
        with pytest.raises(FileNotFoundError, match="no project 'lv'"):
            open_caller_project(A, "lv", kind=kind)
    assert not (root / "footage").exists() and not (root / "visualizer").exists()


def test_a_folder_that_is_not_a_project_is_no_such_project(host):
    (host / A / "junk").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        open_caller_project(A, "junk", kind="footage")


def test_another_callers_project_is_not_found(host):
    _place(host, A, "mv", "music_video")
    with pytest.raises(FileNotFoundError):
        open_caller_project(B, "mv", kind="footage")
    with pytest.raises(KeyError):
        downloads.resolve(B, "mv", "anything")


def test_a_symlinked_child_cannot_lead_out_of_the_bucket(host, tmp_path):
    elsewhere = _place(host, B, "mv", "music_video")  # B's real project
    (host / A).mkdir(parents=True, exist_ok=True)
    try:
        (host / A / "mv").symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(FileNotFoundError):
        open_caller_project(A, "mv", kind="footage")


def test_a_traversal_id_is_refused(host):
    with pytest.raises(ValueError):
        open_caller_project(A, "../b@x.com/mv", kind="footage")


def test_muvid_s_own_drawer_wins_an_id_both_hold(host):
    from muvid.footage.workspace import FootageWorkspace

    own = FootageWorkspace.for_email(A).create_project("mv")
    _place(host, A, "mv", "music_video")
    assert open_caller_project(A, "mv", kind="footage").root == own.root


def test_a_host_placed_visualizer_renders_resolve_and_list(host):
    root = _place(host, A, "viz", "music_visualizer")
    proj = open_caller_project(A, "viz", kind="visualizer")
    assert proj.root == root / "visualizer" and proj.email == A
    rdir = proj.new_render_dir("r1")
    (rdir / "video.mp4").write_bytes(b"v")
    proj.write_render_meta("r1", {"render_id": "r1"})
    assert downloads.resolve(A, "viz", "r1").path == rdir / "video.mp4"
    listed = {p.project_id: p.meta for p in downloads.list_projects(A)}
    assert listed["viz"]["muvid_genre"] == "visualizer"


def test_the_host_listing_names_only_this_genre(host):
    _place(host, A, "mv", "music_video")
    _place(host, A, "viz", "music_visualizer")
    _place(host, A, "lv", "lyric-video")
    footage = [
        r["project_id"]
        for ws in caller_workspaces(A, "footage")
        for r in ws.list_projects()
    ]
    visual = [
        r["project_id"]
        for ws in caller_workspaces(A, "visualizer")
        for r in ws.list_projects()
    ]
    assert (footage, visual) == (["mv"], ["viz"])


def test_the_footage_tools_open_a_host_placed_project(host):
    pytest.importorskip("fastmcp")
    from muvid.mcp import footage_tools
    from muvid.mcp.identity import use_email

    _place(host, A, "mv", "music_video")
    with use_email(A):
        listed = footage_tools.list_music_video_projects()["projects"]
        assert [r["project_id"] for r in listed] == ["mv"]
        assert footage_tools._open("mv").email == A
    with use_email(B):
        assert footage_tools.list_music_video_projects()["projects"] == []


def test_a_visualizer_factory_places_where_asked(host):
    import muvid.genre  # noqa: F401

    assert nw.can_place_genre_project("music_visualizer")
    root = _place(host, A, "viz", "music_visualizer")
    spec = json.loads((root / "project.json").read_text())
    assert spec  # an nw project, which the host lists and opens
    from muvid.production import Project

    assert Project(root).genre == "music_visualizer"


def test_a_neighbour_with_an_unreadable_graph_hides_nothing(host):
    """The #296 review's blocker: one story in the caller's bucket whose graph cannot
    be read (corrupt, or locked while the host writes it) must not fail the listing
    of their muvid projects, and reads as "no such project" itself."""
    import muvid

    _place(host, A, "mv", "music_video")
    bad = muvid.create_project_at(host / A, "story", genre="lyric-video").root
    (bad / "project.annot.sqlite").write_bytes(b"not a database at all" * 64)
    listed = [p.project_id for p in downloads.list_projects(A)]
    assert listed == ["mv"]
    with pytest.raises(FileNotFoundError):
        open_caller_project(A, "story", kind="footage")


def test_an_id_in_both_footage_drawers_lists_once(host):
    from muvid.footage.workspace import FootageWorkspace

    FootageWorkspace.for_email(A).create_project("mv")
    _place(host, A, "mv", "music_video")
    assert [p.project_id for p in downloads.list_projects(A)] == ["mv"]
