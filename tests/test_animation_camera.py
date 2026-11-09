"""The animation renderer's camera must speak ``an``'s vocabulary.

muvid's ``ShotSpec.camera`` is free prose a director writes into the script
(``**camera**: slow push-in``). ``an``'s ``camera.move`` is a closed set of
named moves, and a name outside it is a hard refusal at BOTH validate and
compile — so a scene muvid synthesizes with a move ``an`` cannot name never
renders. That is muvid#44: this module emitted ``move: static``, which ``an``
has never implemented, and because nothing in the suite compiled the
synthesized ``scene.md`` the break was invisible until someone ran the
renderer, where it surfaced only as a silent fallback to the ``still``
strategy.

**The vocabulary guard runs in CI, and it has to.** ``an`` is deliberately not
a declared muvid dependency (the import in ``muvid/renderers/animation.py`` is
soft) and muvid's CI installs only the ``ai,mcp`` extras, so a guard that
imports ``an`` skips on every runner — i.e. the exact failure class this file
exists to close would be unguarded in the only environment that gates a merge.
So the set ``an`` implements is RECORDED in ``tests/data/an_camera_moves.json``
and the table is pinned against the recording, which needs no ``an``. The
imported-``an`` tests below are then the FRESHNESS check on that recording:
they go red on a developer machine when ``an``'s vocabulary moves, and the fix
is to refresh the file. Same shape as reelee-web's
``schemas/destructive-tools.json``.

The recording is generated, never hand-typed — see ``_refresh_snapshot`` at the
bottom of this file. A hand-copied vocabulary is exactly how ``static``
survived here after ``an`` tightened the rule.

Skips are per-test rather than a module-level ``importorskip``: an
``importorskip`` at module scope aborts the import and the tests are never
collected at all, which is invisible in both the pass and the skip counts.
"""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path

import pytest

from muvid.renderers import RenderContext
from muvid.renderers.animation import (
    AN_CAMERA_MOVE_PHRASES,
    AN_ENTITY_KINDS,
    DFLT_AN_CAMERA_MOVE,
    _build_an_scene_md,
    an_camera_move,
)
from muvid.schema import ShotSpec

SNAPSHOT_PATH = Path(__file__).parent / "data" / "an_camera_moves.json"
SNAPSHOT = json.loads(SNAPSHOT_PATH.read_text())
RECORDED_AN_CAMERA_MOVES = frozenset(SNAPSHOT["moves"])
#: ``{genre owner: [entity kinds]}`` — by owner, because the kinds are not all
#: ``an``'s: ``character`` is the ``cutout_animation`` genre's, shipped by the
#: separate ``cutan`` distribution (``an[cutout]``), muvid#277.
RECORDED_AN_ENTITY_KINDS = {
    owner: frozenset(kinds) for owner, kinds in SNAPSHOT["entity_kinds"].items()
}

try:  # `an` is a soft dependency — see the module docstring.
    from an.ir.camera import CAMERA_MOVES as AN_CAMERA_MOVES

    HAS_AN = True
except ImportError:  # pragma: no cover - depends on the environment
    AN_CAMERA_MOVES = {}
    HAS_AN = False

needs_an = pytest.mark.skipif(not HAS_AN, reason="`an` is not installed")


def _scene_md(
    camera: str,
    *,
    characters: tuple[str, ...] = ("alice",),
    environment: str = "park",
) -> str:
    """The exact ``scene.md`` the renderer hands to ``an``, for one shot."""
    shot = ShotSpec(
        id="s1",
        start_s=0.0,
        end_s=4.0,
        render_strategy="animation",
        characters=characters,
        environment=environment,
        camera=camera,
        description="she sings",
    )
    ctx = RenderContext(
        project=None,
        shot=shot,
        shot_dir=None,
        audio_slice_path=None,
        character_image_paths={},
        environment_image_path=None,
        lyric_lines=[],
        global_style="",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _build_an_scene_md(ctx)


def _emitted_move(camera: str) -> str:
    """Parse the move back out of the synthesized ``scene.md``."""
    lines = [L for L in _scene_md(camera).splitlines() if L.startswith("camera:")]
    assert len(lines) == 1, f"expected one camera line, got {lines}"
    # `camera: { move: push_in }`
    return lines[0].split("move:", 1)[1].strip(" }")


def _quiet(direction: str, **kw) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return an_camera_move(direction, **kw)


# --------------------------------------------------------------------------
# The vocabulary pin — runs in CI, against the recorded set
# --------------------------------------------------------------------------


def test_every_translated_move_is_in_ans_recorded_vocabulary():
    """The whole table, pinned against the set ``an`` accepts.

    This is the CI-visible half, and it is the one that catches a move being
    ADDED to the table: `CAMERA_DIRECTION_CASES` hardcodes an expectation per
    direction, so it can only see an entry that CHANGED. Adding
    `("truck left", "truck_left")` goes red HERE and nowhere else.
    """
    emitted = {move for _, move in AN_CAMERA_MOVE_PHRASES} | {DFLT_AN_CAMERA_MOVE}
    unknown = sorted(emitted - RECORDED_AN_CAMERA_MOVES)
    assert not unknown, (
        f"muvid emits camera moves {unknown} that `an` does not implement "
        f"(it has: {sorted(RECORDED_AN_CAMERA_MOVES)}). If `an` gained them, "
        f"refresh {SNAPSHOT_PATH.name} — do not hand-edit it."
    )


def test_the_fallback_move_is_in_the_recorded_vocabulary():
    assert DFLT_AN_CAMERA_MOVE in RECORDED_AN_CAMERA_MOVES


def test_the_snapshot_is_a_generated_recording_not_a_hand_list():
    """It must say where it came from and which `an` can honour it."""
    assert SNAPSHOT["source"] == "an.ir.camera.CAMERA_MOVES"
    assert SNAPSHOT["min_an_version"] == "0.1.65"  # an#109; see the module docstring
    assert SNAPSHOT["moves"] == sorted(SNAPSHOT["moves"])


# --------------------------------------------------------------------------
# Translation — runs everywhere (no `an` needed)
# --------------------------------------------------------------------------

# Directions a director plausibly writes, and how each must read at the
# boundary. `static` is the muvid#44 case: it is muvid's own prose spelling of
# "no move" and `an`'s is `hold`, which is precisely the translation that was
# missing.
CAMERA_DIRECTION_CASES = [
    ("", "hold"),
    ("static", "hold"),
    ("locked off", "hold"),
    ("handheld, drifting", "hold"),
    ("slow push-in", "push_in"),
    ("SLOW PUSH IN", "push_in"),
    ("dolly in on her face", "dolly_in"),
    ("zoom in hard", "zoom_in"),
    ("pull back to reveal the room", "pull_out"),
    ("zoom out", "zoom_out"),
    ("pan left across the crowd", "pan_left"),
    ("pan right", "pan_right"),
    ("tilt up to the sky", "tilt_up"),
    ("tilt down", "tilt_down"),
    # A negated move is REFUSED, not obeyed. Before this, "static, no push-in"
    # rendered a push-in — the one move the direction forbids.
    ("static, no push-in", "hold"),
    ("hold — do not zoom in", "hold"),
    ("don't zoom in", "hold"),
    ("without a push in", "hold"),
    # ...but a negator only reaches to the end of its own clause.
    ("no clouds, push in", "push_in"),
    # Word boundaries, not substrings.
    ("push into the crowd", "push_in"),
    ("she pushes in on the note", "hold"),
    # The director's FIRST-written move wins, not the table's declaration order.
    ("pan left, then push in", "pan_left"),
    ("push in, then pan left", "push_in"),
]


@pytest.mark.parametrize("direction,expected", CAMERA_DIRECTION_CASES)
def test_an_camera_move_translates_prose(direction, expected):
    assert _quiet(direction) == expected


@pytest.mark.parametrize("direction,expected", CAMERA_DIRECTION_CASES)
def test_emitted_scene_md_carries_the_translated_move(direction, expected):
    """The translation is not merely available — the template uses it."""
    assert _emitted_move(direction) == expected


def test_the_emitted_move_is_never_the_muvid_spelling():
    """The literal that broke muvid#44 must not reappear in the template."""
    for direction, _ in CAMERA_DIRECTION_CASES:
        assert _emitted_move(direction) != "static"


def test_the_first_move_in_the_direction_wins_not_the_tables_order():
    """Both orders, so the test can tell the rule from its opposite.

    The pair matters: a table-order rule passes one of these and fails the
    other, and the previous single case ("push in, then pan left") agreed with
    table order, so it could not distinguish them.
    """
    assert _quiet("pan left, then push in") == "pan_left"
    assert _quiet("push in, then pan left") == "push_in"


def test_a_longer_phrase_beats_a_shorter_one_starting_at_the_same_word():
    """`push into` is reachable — under substring matching it never was."""
    assert _quiet("push into the crowd") == "push_in"


# --------------------------------------------------------------------------
# The two ways a direction can fail to reach `an` — both must be audible
# --------------------------------------------------------------------------


def test_an_unrecognised_direction_warns_rather_than_being_dropped():
    """`hold` is right; SILENTLY choosing it is not.

    The module docstring justifies `an`'s strictness by "a camera move that
    silently no-ops is the failure it exists to prevent" — so this boundary
    must not commit that failure on the way in.
    """
    with pytest.warns(UserWarning, match="truck left"):
        assert an_camera_move("truck left") == DFLT_AN_CAMERA_MOVE


def test_a_refused_move_is_obeyed_silently():
    """A director who wrote "no push-in" named a move; nothing was dropped."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert an_camera_move("static, no push-in") == "hold"


def test_a_move_the_installed_an_lacks_degrades_to_hold_with_a_warning():
    """The version floor muvid cannot declare, enforced where it is knowable.

    `an` is in no extra and pinned to no floor, so a user may have 0.1.60 —
    where `pan_left` (an#109, `an` 0.1.65) is a hard refusal at validate and at
    compile. Emitting it there is muvid#44 verbatim.
    """
    old_an = {"hold", "push_in", "pull_out", "zoom_in", "zoom_out"}
    with pytest.warns(UserWarning, match="0.1.65"):
        assert an_camera_move("pan left", known_moves=old_an) == DFLT_AN_CAMERA_MOVE
    # A move that old `an` DOES have still translates.
    assert _quiet("slow push-in", known_moves=old_an) == "push_in"


# --------------------------------------------------------------------------
# The other silent-fallback route: a scene.md that does not parse
# --------------------------------------------------------------------------


def test_an_entity_less_shot_omits_the_entities_block():
    """Both `**env**` and `**chars**` are optional in a muvid script.

    An empty ```yaml entities``` block does not parse; `an`'s reader raises a
    `yaml.scanner.ScannerError`, `orchestrate` reports `success=False`, and the
    renderer falls back to `still` with no message — muvid#44's failure mode
    from a second cause. `an`'s own serializer omits the block; so do we.
    """
    md = _scene_md("static", characters=(), environment="")
    assert "yaml entities" not in md
    assert "```yaml shot" in md and "```dialogue" in md


# --------------------------------------------------------------------------
# Freshness of the recording — skipped when `an` is absent
# --------------------------------------------------------------------------


@needs_an
def test_the_recorded_vocabulary_matches_the_installed_an():
    """The recording's freshness check, and the reason it is trustworthy.

    Imported from `an`, never re-typed. This is the test that goes red when
    `an` renames or retires a move, which is the drift muvid#44 was — and the
    remedy is to regenerate `tests/data/an_camera_moves.json`, which is what
    CI then enforces the table against.
    """
    assert RECORDED_AN_CAMERA_MOVES == frozenset(AN_CAMERA_MOVES), (
        "tests/data/an_camera_moves.json is stale against the installed `an`; "
        "regenerate it (see _refresh_snapshot in this file)."
    )


def _installed_entity_kinds() -> dict:
    """``{owner: kinds}`` the installed ``an`` registers once its genres are loaded
    (what ``an.orchestrate`` does before it validates)."""
    import an.genres
    from an.genres.registry import CORE_OWNER, entity_kind_names

    an.genres.load()
    owners = (CORE_OWNER, *an.genres.installed())
    found = {o: sorted(entity_kind_names(owner=o)) for o in owners}
    return {o: kinds for o, kinds in found.items() if kinds}


def _owner_of(kind: str) -> "str | None":
    return next((o for o, ks in RECORDED_AN_ENTITY_KINDS.items() if kind in ks), None)


@needs_an
def test_the_recorded_entity_kinds_match_the_installed_an():
    """The entity kinds' freshness check, per recorded owner. An owner recorded here
    but not installed on this machine (``cutan`` absent) is not staleness — it is
    a machine that cannot render that kind, which the skip names."""
    installed = _installed_entity_kinds()
    missing = sorted(set(RECORDED_AN_ENTITY_KINDS) - set(installed))
    for owner in set(RECORDED_AN_ENTITY_KINDS) & set(installed):
        assert RECORDED_AN_ENTITY_KINDS[owner] == frozenset(installed[owner]), (
            f"tests/data/an_camera_moves.json is stale for genre {owner!r}; "
            "regenerate it (see _refresh_snapshot in this file)."
        )
    moved = {
        kind: owner
        for gone in missing
        for kind in RECORDED_AN_ENTITY_KINDS[gone]
        for owner, kinds in installed.items()
        if kind in kinds
    }
    assert not moved, (
        f"{moved} moved to another genre since the recording; regenerate it "
        "(see _refresh_snapshot in this file)"
    )
    if missing:
        pytest.skip(f"genre(s) {missing} are recorded but not installed here")


def test_every_entity_kind_the_scene_names_is_one_an_registers():
    """CI's guard (no ``an`` there): every kind the synthesized scene emits has a
    recorded owner genre, and the scene emits no kind the renderer does not declare."""
    unowned = [k for k in AN_ENTITY_KINDS if _owner_of(k) is None]
    assert not unowned, (
        f"the scene names {unowned}, which no recorded `an` genre registers"
    )
    md = _scene_md("static", characters=("alice",), environment="park")
    assert set(re.findall(r"kind: (\w+)", md)) == set(AN_ENTITY_KINDS)


@needs_an
def test_the_fallback_move_is_ans_no_op():
    """`hold` is `an`'s spelling of "the camera does not move"."""
    assert DFLT_AN_CAMERA_MOVE in AN_CAMERA_MOVES
    assert AN_CAMERA_MOVES[DFLT_AN_CAMERA_MOVE](4.0) == []


@needs_an
@pytest.mark.parametrize("direction,_expected", CAMERA_DIRECTION_CASES)
def test_synthesized_scene_md_validates_against_an(direction, _expected, tmp_path):
    """The full round trip: muvid's `scene.md` → `an`'s IR → semantic validate.

    Zero ERROR findings. `an` errors exactly where it would raise at compile,
    so this is the check that would have caught muvid#44 the day `an`
    tightened the rule — and it costs no render.
    """
    _assert_validates_as_rendered(_scene_md(direction), tmp_path)


@needs_an
@pytest.mark.parametrize(
    "characters,environment",
    [((), ""), (("alice",), ""), ((), "park")],
    ids=["no-entities", "chars-only", "env-only"],
)
def test_synthesized_scene_md_parses_for_every_entity_shape(
    characters, environment, tmp_path
):
    """The shot shapes a muvid script can actually contain, all round-tripped.

    The entity-less one is the case the camera-only harness could not see: it
    raised at PARSE, before validate ever ran.
    """
    md = _scene_md("static", characters=characters, environment=environment)
    _assert_validates_as_rendered(md, tmp_path)


@needs_an
def test_the_render_path_validator_refuses_an_unknown_kind(tmp_path):
    """The control: the helper below can fail — a kind no genre registers is an
    error through the same path, so its green on the real scenes means something."""
    md = _scene_md("static").replace("kind: character", "kind: dragon")
    with pytest.raises(AssertionError, match="dragon"):
        _assert_validates_as_rendered(md, tmp_path)


def _assert_validates_as_rendered(md: str, tmp_path) -> None:
    """Validate ``md`` the way ``render_animation`` has ``an`` do it: written to a
    scene folder and read through ``an.orchestrate.validate_project``, which loads
    the installed genres first (``an.project.load``). Parsing the markdown directly
    skips that load, so every genre-scoped entity kind reads as unregistered
    (muvid#277) — a failure of the test, not of the render. Zero ERROR findings;
    a missing asset is a warning, and these scenes name no real assets."""
    from an.orchestrate import validate_project

    registered = {k for ks in _installed_entity_kinds().values() for k in ks}
    absent = sorted(
        set(re.findall(r"kind: (\w+)", md)) & set(AN_ENTITY_KINDS) - registered
    )
    if absent:  # a supported machine that cannot animate these (muvid#306)
        pytest.skip(
            f"{absent} need genre(s) {[_owner_of(k) for k in absent]}, not installed "
            "(`pip install 'an[cutout]'`)"
        )
    (tmp_path / "scene.md").write_text(md, encoding="utf-8")
    report = validate_project(tmp_path)
    errors = [f for f in report.findings if f.severity == "error"]
    assert not errors, [f"{f.ir_path}: {f.description}" for f in errors]


def _refresh_snapshot() -> None:  # pragma: no cover - a maintenance helper
    """Regenerate ``tests/data/an_camera_moves.json`` from the installed ``an``.

    Run on a machine that has ``an``::

        python -c "import tests.test_animation_camera as t; t._refresh_snapshot()"

    Never hand-edit the file: a hand-copied vocabulary is the bug.
    """
    from importlib.metadata import version

    from an.ir.camera import CAMERA_MOVES

    doc = dict(SNAPSHOT)
    doc["recorded_from_an_version"] = version("an")
    doc["moves"] = sorted(CAMERA_MOVES)
    # genre-scoped and owned (muvid#277): record only the owners the scene relies
    # on, so a third-party genre installed on the recording machine stays out
    installed = _installed_entity_kinds()
    owners = {o for o, ks in installed.items() if set(ks) & set(AN_ENTITY_KINDS)}
    doc["entity_kinds"] = {o: installed[o] for o in sorted(owners)}
    SNAPSHOT_PATH.write_text(json.dumps(doc, indent=2) + "\n")


# --------------------------------------------------------------------------
# The prose an authoring agent is told to write must be prose muvid honours
# --------------------------------------------------------------------------

SKILL_PATH = Path(__file__).parents[1] / ".claude" / "skills" / "muvid" / "SKILL.md"


def test_the_skill_lists_exactly_the_phrases_the_renderer_recognises():
    """A hand-typed list in a skill is a second vocabulary, so pin it.

    The skill is what an agent reads before writing `**camera**:` into a
    script. If it advertises a phrase the table dropped, the agent writes a
    direction that renders locked off; if it omits one, the agent avoids a move
    that works. Behaviour-driving text drifts silently — a call-site sweep
    cannot see prose.
    """
    text = SKILL_PATH.read_text()
    listed = {seg.strip() for seg in text.split("`") if seg.strip()}
    missing = sorted(p for p, _ in AN_CAMERA_MOVE_PHRASES if p not in listed)
    assert not missing, (
        f"{SKILL_PATH.name} does not name the camera phrases {missing}; an agent "
        "reading it cannot know they work."
    )


def test_a_dolly_degrades_to_its_push_or_pull_on_an_older_an_not_to_hold():
    """muvid#307: dolly_in/dolly_out (an#478) fall back to the move they extend."""
    from muvid.renderers.animation import (
        AN_CAMERA_MOVE_FALLBACKS,
        an_camera_move,
    )

    old = {"hold", "push_in", "pull_out"}
    new = old | {"dolly_in", "dolly_out"}
    with pytest.warns(UserWarning, match="dolly_in"):
        assert an_camera_move("dolly in", known_moves=old) == "push_in"
    with pytest.warns(UserWarning, match="dolly_out"):
        assert an_camera_move("dolly out", known_moves=old) == "pull_out"
    with pytest.warns(UserWarning, match="dolly_in"):
        assert an_camera_move("dolly in", known_moves={"hold"}) == "hold"
    assert an_camera_move("dolly in", known_moves=new) == "dolly_in"
    assert an_camera_move("dolly out", known_moves=new) == "dolly_out"
    assert set(AN_CAMERA_MOVE_FALLBACKS.values()) <= old
    fb = AN_CAMERA_MOVE_FALLBACKS
    assert fb.keys() | set(fb.values()) <= RECORDED_AN_CAMERA_MOVES
    assert not set(fb) & set(fb.values())  # no chain, so no cycle
