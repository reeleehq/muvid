"""muvid's tools find the projects a HOST placed in the caller's tree (muvid#296).

A host creates ``music_video`` / ``music_visualizer`` projects in its own per-caller
bucket (``nw.create_genre_project(..., projects_dir=...)``) and registers where that
bucket is (``nw.caller_projects_dir``). These pin that muvid's resolvers then open
those projects, refuse everything else with the same "no such project", and change
nothing when no host is registered.
"""

from __future__ import annotations

import json
import shutil

import pytest

nw = pytest.importorskip("nw")

from muvid import downloads  # noqa: E402
from muvid.downloads import caller_workspaces, open_caller_project  # noqa: E402

from tests.ffmpeg_support import needs_ffmpeg, needs_ffmpeg_filter  # noqa: E402

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


def test_an_id_in_both_footage_drawers_lists_both_and_marks_the_placed_one(host):
    """muvid#334: the host's project under an id muvid's own drawer holds was dropped as
    a duplicate and unreachable from the listing. It is listed beside muvid's, marked
    placed so the host drops its own copy of the row; the tools still open muvid's own
    for that id."""
    from muvid.footage.workspace import FootageWorkspace
    from nw.delivery import PLACED_META_KEY

    own = FootageWorkspace.for_email(A).create_project("mv")
    _place(host, A, "mv", "music_video")
    rows = [p for p in downloads.list_projects(A) if p.project_id == "mv"]
    assert len(rows) == 2
    assert sorted(bool(r.meta.get(PLACED_META_KEY)) for r in rows) == [False, True]
    assert open_caller_project(A, "mv", kind="footage").root == own.root
    # a second spelling of the same side still lists once
    assert len([p for p in downloads.list_projects(A) if p.project_id == "mv"]) == 2


def test_only_a_host_placed_project_carries_the_placed_marker(host):
    from muvid.footage.workspace import FootageWorkspace
    from nw.delivery import PLACED_META_KEY

    FootageWorkspace.for_email(A).create_project("own")
    _place(host, A, "placed", "music_video")
    meta = {p.project_id: p.meta for p in downloads.list_projects(A)}
    assert PLACED_META_KEY not in meta["own"] and meta["placed"][PLACED_META_KEY] is True


def _make_video(path):
    import subprocess

    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x48:rate=10:duration=1",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )


@needs_ffmpeg
def test_a_host_placed_visualizer_registers_its_render_and_has_a_cover_status_title(
    host,
):
    """muvid#311: the studio can play the render, the card has a cover, ``genre_status``
    speaks in muvid's terms, and the title is the project's, not its id."""
    from muvid.mcp._cover import refresh_cover
    from muvid.production import Project

    root = _place(host, A, "viz", "music_visualizer")
    project = Project(root)
    assert project.genre_status() == {"renders": 0, "renders_ok": 0, "has_cover": False}
    assert project.cover_artifact_id() is None
    proj = open_caller_project(A, "viz", kind="visualizer")
    assert proj.manifest()["title"] == project.title
    rdir = proj.new_render_dir("r1")
    _make_video(rdir / "video.mp4")
    meta = {
        "render_id": "r1",
        "video": str(rdir / "video.mp4"),
        "thumbnail": None,
        "duration": 1.0,
        "ok": True,
    }
    meta = proj.register_render(meta)
    proj.write_render_meta("r1", meta)
    assert meta["artifact_id"] in project.media_catalog.registered_ids()
    assert "thumbnail_artifact_id" not in meta  # omit-when-absent
    cover = refresh_cover(proj, meta)
    assert cover and cover == project.cover_artifact_id()
    assert cover in project.media_catalog.registered_ids()
    assert project.genre_status() == {"renders": 1, "renders_ok": 1, "has_cover": True}
    # the newest render retakes the cover (footage's rule)
    rdir2 = proj.new_render_dir("r2")
    _make_video(rdir2 / "video.mp4")
    meta2 = {"render_id": "r2", "video": str(rdir2 / "video.mp4"), "duration": 1.0}
    assert refresh_cover(proj, meta2)
    assert proj.cover()["taken_from"] == "render:r2"


@needs_ffmpeg_filter("showcqt")
def test_the_render_tool_registers_on_a_host_placed_project(
    host, tmp_path, monkeypatch
):
    """The wiring, not just the method: ``render_visualizer`` on a host-placed project."""
    pytest.importorskip("fastmcp")
    import subprocess

    from muvid.mcp import tools
    from muvid.mcp.identity import use_email
    from muvid.production import Project

    root = _place(host, A, "viz", "music_visualizer")
    audio = tmp_path / "a.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=1", str(audio)],
        check=True,
    )
    monkeypatch.setattr(
        tools, "_resolve_input", lambda url, dest, *, label: shutil.copy(audio, dest)
    )
    with use_email(A):
        meta = tools.render_visualizer("viz", audio="https://x/a.wav", visual="cqt")
    project = Project(root)
    assert meta["artifact_id"] in project.media_catalog.registered_ids()
    assert project.cover_artifact_id()
    assert project.genre_status()["renders"] == 1


def test_muvids_own_visualizer_bucket_registers_nothing(tmp_path, monkeypatch):
    from muvid.mcp.workspace import VisualizerWorkspace

    monkeypatch.setenv("MUVID_DATA_HOME", str(tmp_path))
    proj = VisualizerWorkspace.for_email(A).create_project("v", title="T")
    meta = {"render_id": "r", "video": str(tmp_path / "nope.mp4")}
    assert proj.register_render(meta) is meta
    assert proj.manifest()["title"] == "T" and "cover" not in proj.manifest()


def test_a_neighbour_of_another_genre_is_classified_without_opening_its_graph(
    host, monkeypatch
):
    """muvid#339: the genre comes from the document mirror (``nw.project_genre``), so a
    bucket of other projects costs one small read each, and only a project of THIS genre
    is opened as a ``Project``."""
    import muvid.production as production

    _place(host, A, "mv", "music_video")
    for pid in ("story1", "story2"):
        _place(host, A, pid, "lyric-video")
    opened = []
    real = production.Project

    def counting(root, *a, **kw):
        opened.append(root.name)
        return real(root, *a, **kw)

    monkeypatch.setattr(production, "Project", counting)
    listed = [
        r["project_id"]
        for ws in caller_workspaces(A, "footage")
        for r in ws.list_projects()
    ]
    assert listed == ["mv"] and opened == ["mv"]


def test_a_project_whose_mirror_is_unknown_is_still_classified_by_its_graph(
    host, monkeypatch
):
    """An envelope that predates the mirror reads ``None``; the authoritative read
    decides, as before."""
    _place(host, A, "mv", "music_video")
    monkeypatch.setattr(nw, "project_genre", lambda root: None, raising=False)
    assert open_caller_project(A, "mv", kind="footage").email == A
    with pytest.raises(FileNotFoundError):
        open_caller_project(A, "mv", kind="visualizer")
