"""The beat-grid writers declare which reads they make stale (reelee#750), and that
declaration is checked against the code: every read that reaches
:func:`muvid.footage.service.declared_beat_grid` must be in it."""

import ast
import inspect

from muvid.footage import service


def _reads_reaching(target: str) -> set:
    """The read ops of ``service`` whose module-local call graph reaches ``target``."""
    tree = ast.parse(inspect.getsource(service))
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    calls = {
        name: {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id in funcs}
        for name, fn in funcs.items()
    }

    def reaches(name, seen=frozenset()):
        if name == target:
            return True
        return name not in seen and any(reaches(c, seen | {name}) for c in calls.get(name, ()))

    reads = [spec.name for spec in service.FOOTAGE_OP_SPECS if spec.effect == "read"]
    return {r for r in reads if reaches(r)}


def test_beat_grid_invalidations_cover_every_read_of_the_grid():
    assert _reads_reaching("declared_beat_grid") == set(service.BEAT_GRID_READS)


def test_the_beat_grid_writers_declare_them_and_the_catalogue_says_so():
    import nw

    import muvid.genre_music_video  # noqa: F401 - registers the catalogue

    rows = {row["name"]: row for row in nw.genre_ops_catalogue("music_video")}
    for writer in ("set_beat_grid", "clear_beat_grid"):
        assert rows[writer]["invalidates"] == list(service.BEAT_GRID_READS)
    assert rows["set_cut"]["invalidates"] is None  # not said: the client keeps its own rule
