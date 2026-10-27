# muvid.mcp.scoring_tools

MCP tools for the footage SCORING layer (thorwhalen/muvid#13).

A background scoring job (via `nw.jobs` — the federation’s durable/cancellable async
facade, reused rather than a second system) computes per-clip score tracks; the editor +
`assemble_music_video(strategy='weighted')` read them. All FREE (no AI/keys).

A transport over [`muvid.footage.service`](muvid.footage.service.html.md#module-muvid.footage.service) (`require_scorable`, `run_scoring`,
`scores`): what stays here is the connector’s own job — enqueueing on `nw.jobs` and the
bounded long-poll over it. A host runs the same `score` operation as its own job.

Key design decisions (LOCKED, see `misc/docs/footage_scoring_design.md`):

- **Scoring is keyed on INPUTS ONLY** (`song_hash` + an alignment fingerprint + the metric
  set + hop). Weights/preset are NOT here — they enter at `assemble` time, so ONE tensor is
  reused across every preset for free, and a re-align mid-flight yields a NEW job (not a dedup
  to the stale run).
- **Bounded long-poll** status so an agent needs ~1 poll, not ~15.
- **NaN never hits the wire** — masked entries serialize as `null`; the `mask` array is
  authoritative.
- \*\*The status without a `job_id` reads the job `score_footage` last started\*\*, recorded
  in the project (`score_job.json`), through `nw.jobs.get_job`, which answers for an
  archived run. `list_jobs` alone stops listing a run 30 days after it ends (nw#169) and
  returns 50 jobs of every kind, so an old or busy project read “no scoring job found”
  (muvid#264). Its head is still a candidate, the newer of the two wins: it covers a
  project scored before the record existed and a job a build without it enqueued.
  nw#185 would make both the record and the scan nw’s.

### Functions

| [`footage_score_status`](#muvid.mcp.scoring_tools.footage_score_status)(project_id, \*[, ...])     | The scoring job's status (bounded long-poll).                                    |
|--------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`footage_scores`](#muvid.mcp.scoring_tools.footage_scores)(project_id, \*[, clip_id, ...])  | The persisted score tracks — for the multichannel editor + inspection.           |
| [`score_footage`](#muvid.mcp.scoring_tools.score_footage)(project_id, \*[, hop_s, metrics]) | Kick a BACKGROUND job that scores every aligned clip (quality + motion-to-beat). |

### muvid.mcp.scoring_tools.footage_score_status(project_id, , job_id='', wait_s=0)

The scoring job’s status (bounded long-poll). Free.

Pass the `job_id` from `score_footage` (or omit for the one it last started — which
may predate a later `set_song`, which drops the scores that job made).
With `wait_s` > 0 this blocks up to ~\`\`wait_s\`\` seconds (capped), returning early on
a terminal state — so an agent needs ~1 poll, not many.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### muvid.mcp.scoring_tools.footage_scores(project_id, , clip_id='', metrics=None, max_points=1500, weights=None, preset='', raw=False)

The persisted score tracks — for the multichannel editor + inspection. Free.

- No `clip_id` → a SUMMARY (metrics, per-clip coverage %, beats, tempo, the decimated
  `selection_margin`, grid geometry) — bounded, safe as the default.
- `clip_id` → that clip’s tracks (values as `null`-masked arrays, decimated to
  `max_points` per metric) plus its `composite` lane, for the editor’s lanes.
- `weights` / `preset` pick the weighting the composite and `selection_margin`
  are computed under (the reply’s `weights` says which applied); `raw` adds each
  metric’s un-normalised values.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### muvid.mcp.scoring_tools.score_footage(project_id, , hop_s=0.1, metrics=None)

Kick a BACKGROUND job that scores every aligned clip (quality + motion-to-beat). Free.

Returns immediately with a `job_id`; poll `footage_score_status`. Scoring extracts ALL
core metrics (re-weight later at assemble time — no re-scoring needed). Requires a song +
a run of `align_footage` first. The heavy lip-sync tier is OFF by default (opt-in,
off-prod).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
