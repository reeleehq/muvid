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

    def mentions(node):
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        return names | {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}

    for path in paths:
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef):
                funcs.setdefault(fn.name, set()).update(mentions(fn))
        # a module-level table is a node too: a callable stored in ``TRUST_TIERS`` and
        # called as ``tier.intervals(a)`` is reached through the table's name (#318 review)
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in (t for t in tgts if isinstance(t, ast.Name)):
                    funcs.setdefault(t.id, set()).update(mentions(node.value))
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


#: Where ``service`` hands the project to code the walks above cannot follow, as
#: ``(the function doing it, the callee)`` — each a reviewed fact: scoring's own entry
#: point (a write), the fingerprint of a keyed input (an object's method), the
#: decorator's wrapped function, the filmstrip and waveform caches (they read the clips
#: and the song, never a placement). Compared for EQUALITY, so an entry that goes stale
#: is reported too.
_FP_HANDED_ON = {
    ("run_scoring", "score_project"),
    ("_input_fingerprints", "k.fingerprint"),
    ("_edits_locked", "fn"),
    ("_filmstrip", "clip_filmstrip"),
    ("_prepare_filmstrip", "clip_filmstrip"),
    ("peaks", "song_peaks"),
}


def _callee_name(f) -> str:
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f"{f.value.id}.{f.attr}"
    return ast.dump(f)[:60]


def test_service_hands_the_project_only_where_the_walks_were_checked():
    """muvid#318: the walks follow calls inside ``service.py`` by name. A call that
    passes the project (``fp``, positionally, as a keyword or starred) to a function
    from another module, or to a method of an object, escapes them: a read could depend
    on a write's data with no declaration noticing. Any NEW such hand-off fails here
    until someone decides whether the callee reads what a writer changes (and extends
    the walk or lists it above). It watches the project, not the data taken from it: a
    callee handed ``list(placed.values())`` is what the derivation tests' module-table
    nodes are for."""
    tree = ast.parse(pathlib.Path(service.__file__).read_text())
    defined = {
        n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))
    }

    def hands_fp(call):
        args = [a.value if isinstance(a, ast.Starred) else a for a in call.args]
        args += [k.value for k in call.keywords]
        return any(isinstance(a, ast.Name) and a.id == "fp" for a in args)

    escaped = set()
    for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef)):
        for call in (c for c in ast.walk(fn) if isinstance(c, ast.Call)):
            f = call.func
            if not hands_fp(call):
                continue
            if isinstance(f, ast.Name) and (f.id in defined or hasattr(builtins, f.id)):
                continue
            escaped.add((fn.name, _callee_name(f)))
    assert escaped == _FP_HANDED_ON, (
        sorted(escaped - _FP_HANDED_ON),
        sorted(_FP_HANDED_ON - escaped),
    )


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
