"""MCP tools for the footage SCORING layer (thorwhalen/muvid#13).

A background scoring job (via ``nw.jobs`` — the federation's durable/cancellable async
facade, reused rather than a second system) computes per-clip score tracks; the editor +
``assemble_music_video(strategy='weighted')`` read them. All FREE (no AI/keys).

A transport over :mod:`muvid.footage.service` (``require_scorable``, ``run_scoring``,
``scores``): what stays here is the connector's own job — enqueueing on ``nw.jobs`` and the
bounded long-poll over it. A host runs the same ``score`` operation as its own job.

Key design decisions (LOCKED, see ``misc/docs/footage_scoring_design.md``):

- **Scoring is keyed on INPUTS ONLY** (``song_hash`` + an alignment fingerprint + the metric
  set + hop). Weights/preset are NOT here — they enter at ``assemble`` time, so ONE tensor is
  reused across every preset for free, and a re-align mid-flight yields a NEW job (not a dedup
  to the stale run).
- **Bounded long-poll** status so an agent needs ~1 poll, not ~15.
- **NaN never hits the wire** — masked entries serialize as ``null``; the ``mask`` array is
  authoritative.
- **The status without a ``job_id`` reads the job ``score_footage`` last started**, recorded
  in the project (``score_job.json``), through ``nw.jobs.get_job``, which answers for an
  archived run. ``list_jobs`` alone stops listing a run 30 days after it ends (nw#169) and
  returns 50 jobs of every kind, so an old or busy project read "no scoring job found"
  (muvid#264). Its head is still a candidate, the newer of the two wins: it covers a
  project scored before the record existed and a job a build without it enqueued.
  nw#185 would make both the record and the scan nw's.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

from muvid.footage import service
from muvid.mcp.footage_tools import _refusals, _tool_error
from muvid.mcp.identity import current_email

_SCORE_KIND = "footage.score"
#: Cap on the long-poll wait (safely under the connector's HTTP request timeout).
_MAX_WAIT_S = int(os.environ.get("MUVID_SCORING_MAX_WAIT_S", "25"))
#: Default cap on points-per-(clip,metric) returned over the wire (the service's).
_MAX_POINTS = service.MAX_WIRE_POINTS
#: Where ``score_footage`` records the id of the job it last started (muvid#264).
_LAST_JOB_FILE = "score_job.json"


def _open(project_id: str):
    from muvid.footage.workspace import FootageWorkspace

    try:
        return FootageWorkspace.for_email(current_email()).open_project(project_id)
    except FileNotFoundError as e:
        raise _tool_error(f"no such project {project_id!r}") from e


def _score_dispatch():
    """The nw.jobs dispatch callable for a scoring job (kept tiny + picklable-free)."""

    def _run_scoring(
        project, params, *, job_id=None, on_event=None, should_cancel=None
    ):
        return service.run_scoring(
            project,
            metrics=params.get("metrics"),
            hop_s=params.get("hop_s", service.DEFAULT_SCORE_HOP_S),
            enable_lipsync=params.get("enable_lipsync"),
            progress_cb=on_event,
            should_cancel=should_cancel,
        )

    return {_SCORE_KIND: _run_scoring}


def score_footage(
    project_id: str, *, hop_s: float = 0.1, metrics: list | None = None
) -> dict:
    """Kick a BACKGROUND job that scores every aligned clip (quality + motion-to-beat). Free.

    Returns immediately with a ``job_id``; poll ``footage_score_status``. Scoring extracts ALL
    core metrics (re-weight later at assemble time — no re-scoring needed). Requires a song +
    a run of ``align_footage`` first. The heavy lip-sync tier is OFF by default (opt-in,
    off-prod).
    """
    try:
        from nw import jobs as nw_jobs
    except Exception as e:  # muvid[mcp] pins nw; this only fails on a broken env
        raise _tool_error(f"scoring needs nw.jobs (muvid[mcp]): {e}") from e

    proj = _open(project_id)
    with _refusals():
        aligns = service.require_scorable(proj, metrics=metrics)

    # Input-only idempotency: song content + offsets + metric set + hop. A re-align changes
    # the fingerprint → a fresh job (never a dedup onto the stale offsets).
    from muvid.footage.scoring.grid import align_fingerprint

    key_basis = f"{proj.song_hash()}:{align_fingerprint(aligns)}:{sorted(metrics or [])}:{hop_s}"
    idem = hashlib.sha256(f"{proj.root}:{_SCORE_KIND}:{key_basis}".encode()).hexdigest()

    params = {
        "hop_s": hop_s,
        "metrics": metrics,
        "estimated_usd": 0.0,
        "output_kind": "compute",
    }
    # Recorded BEFORE the job starts, so a failed write refuses a job that never ran
    # rather than starting one the status cannot name.
    _remember_job(
        proj, nw_jobs.job_id_for(proj, _SCORE_KIND, params, idempotency_key=idem)
    )
    job = nw_jobs.enqueue(
        proj,
        _SCORE_KIND,
        params,
        dispatch=_score_dispatch(),
        idempotency_key=idem,
        label="Score footage",
        on_event=None,
    )
    return {"project_id": project_id, "job_id": job.job_id, "status": job.status}


def _remember_job(proj, job_id: str) -> None:
    from muvid.footage.workspace import atomic_write_text

    atomic_write_text(proj.root / _LAST_JOB_FILE, json.dumps({"job_id": job_id}))


def _latest_score_job(proj, nw_jobs):
    """The newer of the job :func:`_remember_job` recorded and the newest scoring job
    ``list_jobs`` still lists; ``None`` when neither exists."""
    from muvid.footage.workspace import read_json_dict

    remembered = (read_json_dict(proj.root / _LAST_JOB_FILE) or {}).get("job_id")
    candidates = (
        [nw_jobs.get_job(proj, remembered)] if isinstance(remembered, str) else []
    )
    candidates += nw_jobs.list_jobs(proj)
    jobs = [j for j in candidates if j is not None and j.kind == _SCORE_KIND]
    return max(jobs, key=lambda j: j.created_at or "", default=None)


def footage_score_status(
    project_id: str, *, job_id: str = "", wait_s: float = 0
) -> dict:
    """The scoring job's status (bounded long-poll). Free.

    Pass the ``job_id`` from ``score_footage`` (or omit for the one it last started — which
    may predate a later ``set_song``, which drops the scores that job made).
    With ``wait_s`` > 0 this blocks up to ~``wait_s`` seconds (capped), returning early on
    a terminal state — so an agent needs ~1 poll, not many.
    """
    try:
        from nw import jobs as nw_jobs
    except Exception as e:  # same clean ToolError as score_footage on a broken env
        raise _tool_error(f"scoring needs nw.jobs (muvid[mcp]): {e}") from e

    proj = _open(project_id)
    deadline = time.monotonic() + min(max(0.0, wait_s), _MAX_WAIT_S)

    def _current():
        if job_id:
            return nw_jobs.get_job(proj, job_id)
        return _latest_score_job(proj, nw_jobs)

    job = _current()
    terminal = {"succeeded", "failed", "cancelled"}
    while (
        job is not None and job.status not in terminal and time.monotonic() < deadline
    ):
        time.sleep(0.5)
        job = _current()
    if job is None:
        raise _tool_error("no scoring job found — call score_footage first")
    return {
        "project_id": project_id,
        "job_id": job.job_id,
        "status": job.status,
        "pct": job.pct,
        "stage": _stage_label(job),
        "error": job.error,
        "result": job.result,
    }


def _stage_label(job) -> str | None:
    p = job.progress
    if p.current_transform is None:
        return None
    if p.stage_index is not None and p.stage_count:
        return f"{p.current_transform} ({p.stage_index + 1}/{p.stage_count})"
    return p.current_transform


def footage_scores(
    project_id: str,
    *,
    clip_id: str = "",
    metrics: list | None = None,
    max_points: int = _MAX_POINTS,
    weights: dict | None = None,
    preset: str = "",
    raw: bool = False,
) -> dict:
    """The persisted score tracks — for the multichannel editor + inspection. Free.

    - No ``clip_id`` → a SUMMARY (metrics, per-clip coverage %, beats, tempo, the decimated
      ``selection_margin``, grid geometry) — bounded, safe as the default.
    - ``clip_id`` → that clip's tracks (values as ``null``-masked arrays, decimated to
      ``max_points`` per metric) plus its ``composite`` lane, for the editor's lanes.
    - ``weights`` / ``preset`` pick the weighting the composite and ``selection_margin``
      are computed under (the reply's ``weights`` says which applied); ``raw`` adds each
      metric's un-normalised values.
    """
    proj = _open(project_id)
    with _refusals():
        return service.scores(
            proj,
            clip_id=clip_id,
            metrics=metrics,
            max_points=max_points,
            weights=weights,
            preset=preset,
            raw=raw,
        )
