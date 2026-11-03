"""The beat-grid, score and alignment writers declare which reads they make stale
(reelee#750, muvid#286), and each declaration is checked against the code. For the
beat grid: every read whose calls inside
:mod:`muvid.footage.service` (by name or attribute) reach
:func:`~muvid.footage.service.declared_beat_grid`, or the file it reads, must be in it.
A path through another module is not followed; today none reads the grid."""

import ast
import inspect

from muvid.footage import service


def _reads_reaching(*targets: str) -> set:
    """The read ops of ``service`` whose call graph inside the module reaches any of
    ``targets``: a function, or a module constant (the declared grid's file name). A
    call is followed by bare name and by attribute (``service.f(...)``, ``_svc.f``)."""
    tree = ast.parse(inspect.getsource(service))
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    def uses(fn):
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        return names | attrs

    calls = {name: uses(fn) for name, fn in funcs.items()}

    def reaches(name, seen=frozenset()):
        if name in targets:
            return True
        return name not in seen and any(
            c in targets or reaches(c, seen | {name}) for c in calls.get(name, ()) if c in funcs or c in targets
        )

    reads = [spec.name for spec in service.FOOTAGE_OP_SPECS if spec.effect == "read"]
    return {r for r in reads if reaches(r)}


def test_beat_grid_invalidations_cover_every_read_of_the_grid():
    grid = _reads_reaching("declared_beat_grid", "_DECLARED_BEAT_GRID_NAME")
    assert grid == set(service.BEAT_GRID_READS)


def test_the_beat_grid_writers_declare_them_and_the_catalogue_says_so():
    import nw

    import muvid.genre_music_video  # noqa: F401 - registers the catalogue

    rows = {row["name"]: row for row in nw.genre_ops_catalogue("music_video")}
    for writer in ("set_beat_grid", "clear_beat_grid"):
        assert rows[writer]["invalidates"] == list(service.BEAT_GRID_READS)
    assert rows["set_cut"]["invalidates"] is None  # not said: the client keeps its own rule


def test_score_and_alignment_invalidations_cover_every_read_of_them():
    """muvid#286: what ``score`` and the alignment writers make stale, checked against
    the code the same way. ``beat_grid`` is a score read because it lifts the grid a
    scoring run measured; ``explain_edit`` is not, because it reads no scores."""
    assert _reads_reaching("load_tensor", "load_manifest") == set(service.SCORE_READS)
    placed = _reads_reaching("load_alignments", "_placements")
    assert set(service.ALIGNMENT_READS) == placed | set(service.SCORE_READS)
    assert set(service.PLACEMENT_READS) == placed - set(service.SCORE_READS)


def test_the_score_and_alignment_writers_declare_them():
    import nw

    import muvid.genre_music_video  # noqa: F401 - registers the catalogue

    rows = {row["name"]: row for row in nw.genre_ops_catalogue("music_video")}
    assert rows["score"]["invalidates"] == list(service.SCORE_READS)
    for writer in ("align", "set_offset", "clear_offset"):
        assert rows[writer]["invalidates"] == list(service.ALIGNMENT_READS)
