"""The beat-grid, score and alignment writers declare which reads they make stale
(reelee#750, muvid#286), and each declaration is checked against the code. For the
beat grid: every read whose calls inside
:mod:`muvid.footage.service` (by name or attribute) reach
:func:`~muvid.footage.service.declared_beat_grid`, or the file it reads, must be in it.
A path through another module is not followed; today none reads the grid."""

import ast
import builtins
import pathlib

from muvid.footage import service


def _functions(*, package: bool) -> dict:
    """``{function name: names and attributes it mentions}`` over ``service`` alone, or
    (``package=True``) over every module of :mod:`muvid.footage`, so a read that hands
    the project to another module is followed there (muvid#318). Name-based: functions
    sharing a name merge, an over-approximation, so the package-wide walk is for targets
    whose answer was checked by eye (a coarse name like ``load_manifest`` drags in
    unrelated reads)."""
    paths = (
        sorted(pathlib.Path(service.__file__).parent.rglob("*.py"))
        if package
        else [pathlib.Path(service.__file__)]
    )
    funcs: dict = {}
    for path in paths:
        for fn in ast.walk(ast.parse(path.read_text())):
            if isinstance(fn, ast.FunctionDef):
                mentioned = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
                mentioned |= {
                    n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)
                }
                funcs.setdefault(fn.name, set()).update(mentioned)
    return funcs


def _reads_reaching(*targets: str, package: bool = False) -> set:
    """The read ops of ``service`` whose call graph reaches any of ``targets``: a
    function, or a module constant (the declared grid's file name). A call is followed
    by bare name and by attribute (``service.f(...)``, ``_svc.f``)."""
    funcs = _functions(package=package)

    def reaches(name, seen=frozenset()):
        if name in targets:
            return True
        return name not in seen and any(
            c in targets or reaches(c, seen | {name})
            for c in funcs.get(name, ())
            if c in funcs or c in targets
        )

    reads = [spec.name for spec in service.FOOTAGE_OP_SPECS if spec.effect == "read"]
    return {r for r in reads if reaches(r)}


#: Where ``service`` hands the project to code the walks above cannot follow, each a
#: reviewed fact: scoring's own entry point (a write), the fingerprint of a keyed input
#: (an object's method), the decorator's wrapped function, the filmstrip and waveform
#: caches (they read the clips and the song, never a placement).
_FP_HANDED_ON = {
    "score_project",
    "k.fingerprint",
    "fn",
    "clip_filmstrip",
    "song_peaks",
}


def test_service_hands_the_project_only_where_the_walks_were_checked():
    """muvid#318: the walks follow calls inside ``service.py`` by name. A call that
    passes the project (``fp``) to a function from another module, or to a method of
    an object, escapes them: a read could depend on a write's data with no declaration
    noticing. Any NEW such hand-off fails here until someone decides whether the callee
    reads what a writer changes (and extends the walk or lists it above)."""
    tree = ast.parse(pathlib.Path(service.__file__).read_text())
    defined = {
        n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))
    }
    escaped = set()
    for call in (c for c in ast.walk(tree) if isinstance(c, ast.Call)):
        if not any(isinstance(a, ast.Name) and a.id == "fp" for a in call.args):
            continue
        f = call.func
        if isinstance(f, ast.Name):
            if f.id not in defined and not hasattr(builtins, f.id):
                escaped.add(f.id)
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            escaped.add(f"{f.value.id}.{f.attr}")
        else:
            escaped.add(ast.dump(f)[:60])
    assert escaped <= _FP_HANDED_ON, sorted(escaped - _FP_HANDED_ON)


def test_beat_grid_invalidations_cover_every_read_of_the_grid():
    grid = _reads_reaching("declared_beat_grid", "_DECLARED_BEAT_GRID_NAME")
    assert grid == set(service.BEAT_GRID_READS)


def test_the_beat_grid_writers_declare_them_and_the_catalogue_says_so():
    import nw

    import muvid.genre_music_video  # noqa: F401 - registers the catalogue

    rows = {row["name"]: row for row in nw.genre_ops_catalogue("music_video")}
    for writer in ("set_beat_grid", "clear_beat_grid"):
        assert rows[writer]["invalidates"] == list(service.BEAT_GRID_READS)
    assert (
        rows["set_cut"]["invalidates"] is None
    )  # not said: the client keeps its own rule


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


def test_span_and_role_writers_declare_the_reads_that_depend_on_them():
    """muvid#318: ``measure_spans`` writes the spans only the unverified-stretch notes
    read; ``set_has_song`` changes the roles the cut and the coverage report read. The
    readers live in other modules, so the walk covers the whole package."""
    import nw

    import muvid.genre_music_video  # noqa: F401 - registers the catalogue

    assert _reads_reaching("unverified_stretches", package=True) == set(
        service.SPAN_READS
    )
    assert _reads_reaching("footage_roles", "_role_of", package=True) == set(
        service.ROLE_READS
    )
    rows = {row["name"]: row for row in nw.genre_ops_catalogue("music_video")}
    assert rows["measure_spans"]["invalidates"] == list(service.SPAN_READS)
    assert rows["set_has_song"]["invalidates"] == list(service.ROLE_READS)
