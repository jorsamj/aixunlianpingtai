# Training Task Auto-Refresh Design

## Scope

This batch closes only the training task list auto-refresh lifecycle. It does not change task creation, Worker readiness, GPU scheduling, pause/resume semantics, ETA calculation, the training detail view, or backend execution.

## Existing truth and owners

- `GET /api/projects/{project_id}/jobs` remains the single batch data source for the visible training list.
- The endpoint projects the existing training `job.json` and metrics through `enrich_job_runtime()`, including durable `TaskRepository` status, progress, queue, worker, epoch, elapsed-time, and terminal truth.
- `TrainingTaskRuntime` remains the only focused list refresh and table-patch owner.
- `PollRegistry` remains the only timer lifecycle owner. No second polling or task-state implementation is introduced.

## Refresh lifecycle

- Replace the fixed training interval with a PollRegistry-managed 2-second one-shot while at least one task is `queued`, `running`, `waiting`, or `pending`.
- A successful refresh replaces the in-memory job list with the latest complete backend response and patches only the training table and tab counts.
- After each one-shot completes, re-arm only from the newly returned backend state.
- A transient request failure may re-arm while the last known state still contains a non-terminal task, so one network error does not permanently disable live updates.
- If only `paused` tasks remain, keep them in the activity tab but re-arm at a lower 5-second cadence rather than the 2-second active cadence.
- Existing resume behavior performs an immediate forced jobs refresh after the mutation. That refreshed state then restores the appropriate one-shot cadence.
- If all tasks are terminal, do not re-arm. Terminal states are `done`, `finished`, `completed`, `failed`, `stopped`, `cancelled`, and `canceled`.
- Training polling is owned only by the `训练任务` page. Navigation to any other module clears its pending timer through the existing PollRegistry navigation lifecycle. Re-entering the page uses the normal page data load and render to start polling again when required.

## Truthfulness rules

- Status, `progress_percent`, current/total epoch, elapsed time, queue metadata, and worker metadata are rendered only from the latest backend response.
- The frontend does not increment progress, synthesize epochs, assume a next state, or simulate running.
- Terminal backend truth replaces stale running UI state. Existing backend terminal elapsed-time freezing remains unchanged.
- One request refreshes the entire current jobs collection; there is no per-task N+1 polling.

## Error handling

- A failed poll leaves the last successfully rendered state intact and does not manufacture fallback task data.
- Polling is not re-armed after navigation away, even if an in-flight request settles later.
- The existing navigation epoch guard continues to discard stale responses from the previous page.

## Verification

Focused frontend tests will prove:

1. Successive real API responses update status, progress, epoch, and elapsed display without a full-page render.
2. A transition from running to every supported terminal class is treated as terminal, with a representative completed transition proving the stale running row is replaced.
3. Active tasks re-arm at 2 seconds, paused-only state re-arms at 5 seconds, and terminal-only state does not re-arm.
4. Leaving the training task page clears the pending one-shot.
5. Resume still performs an immediate forced jobs refresh and returns polling to the cadence implied by the refreshed backend state.

One existing training backend truth regression will be run alongside the focused frontend tests. No Real Chrome or unrelated full suite is required.
