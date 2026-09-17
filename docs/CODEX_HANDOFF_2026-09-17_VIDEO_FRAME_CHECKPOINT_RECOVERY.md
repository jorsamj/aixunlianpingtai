# Video Frame Checkpoint Recovery Closure — 2026-09-17

## Scope

Repository: `jorsamj/aixunlianpingtai`

Branch: `refactor/frontend-runtime-stabilization`

Formal product version remains `VERSION.txt = 42.24.0`.

Product acceptance HEAD for this batch:

`6eb90871dddc44a1ec172d4b4a0489d9c9aa4240`

This handoff closes the **video frame extraction checkpoint recovery automated contract**. It does not claim large-video production throughput, host power-loss durability, or per-object publishing checkpoint recovery.

## Problem before this batch

`VideoFrameHandler.recover()` could recognize a fully committed `result.json`, but a Worker failure during frame extraction otherwise fell back to `run()` and `extract_video()` started decoding/writing from frame zero again.

For long videos this meant an expired/crashed Worker could lose expensive extraction work even though complete JPEG frame artifacts already existed inside the durable task artifact directory.

## Implemented recovery contract

### 1. Deterministic frame artifact names

Each planned frame now has a deterministic artifact path:

`frame_{ordinal:06d}_src_{source_frame_index:09d}.jpg`

This lets a replacement execution prove which exact planned frames already exist.

### 2. Durable validated extraction prefix

`platform_core/video_tasks.py` now validates an existing contiguous frame prefix before resuming:

- file must exist;
- file size must be positive;
- OpenCV must be able to decode it;
- SHA256 and size are recomputed from the actual artifact;
- only the contiguous prefix is trusted;
- the first missing/corrupt frame invalidates the remaining suffix;
- stale suffix files and temporary `.tmp.jpg` files are removed before continuation.

A frame is still published through a temporary file followed by `os.replace()`.

Therefore, if a Worker process dies after a complete JPEG was renamed into place but before `worker.json` was updated, the replacement execution can still recover that frame from the artifact itself.

This is a **process-crash recovery contract**, not a claim of durability against sudden host power loss before filesystem persistence.

### 3. Resume without rewriting verified frames

`extract_video(..., resume_existing=True)` now:

1. rebuilds the validated completed prefix;
2. returns immediately when all planned frames are already present;
3. otherwise targets only the remaining planned frame indices;
4. asks OpenCV to seek to the first remaining source frame when supported;
5. falls back to decoding from frame zero when the backend cannot seek reliably, but still does **not** rewrite the validated prefix.

This keeps correctness independent of codec/backend seek quality while avoiding duplicate frame artifact publication.

### 4. Worker checkpoint metadata

After every recovered/new completed frame, `VideoFrameHandler` persists `checkpoints/worker.json` with:

- `schema_version = 1`
- `stage = extracting`
- `extracted_frames`
- `expected_frames`
- `current_source_frame`
- `output_ref = frames`

After extraction is complete the checkpoint advances to `stage = extracted`.

The frame artifacts remain the stronger recovery evidence for the small crash window between JPEG publication and checkpoint JSON publication.

### 5. Existing execution fencing preserved

No alternate unfenced write path was introduced.

The handler still runs through `WorkerContext` / `FencedArtifactStore`, so a Worker that loses its execution generation cannot continue publishing task artifacts or business truth over the replacement execution.

### 6. Material publication remains deterministic and replay-safe

Material IDs remain derived from:

`{task_id}:{source_frame_index}`

Existing annotation/material publication behavior therefore remains deterministic across a retry.

This batch does **not** add per-object publishing checkpoints. If a Worker crashes after extraction while publishing frames into storage/material truth, recovery may repeat deterministic upload work before the final material batch is committed. That is safe/idempotent under the existing contract, but can repeat remote upload cost.

## Frontend / backend consistency

The unified public task truth already exposes:

- `attempt`
- `phase`
- `progress_percent`
- `current_item`
- persisted/canonical task status

The `/api/v33/projects/{project_id}/video-tasks` projection derives from that durable task truth.

`static/modules/video-tasks.js` now surfaces active executions with `attempt > 1` as:

`恢复执行 · 第 N 次执行`

This is deliberately conservative:

- it is true from durable backend execution history;
- it does not invent an exact resumed-frame claim;
- the existing progress bar and current-frame column continue to show backend truth;
- queue/resource-wait text keeps precedence over recovery text.

The existing compact table UI and status-pill style were retained rather than adding a large recovery warning block.

## Tests added / strengthened

### Unit extraction recovery

`tests/unit/test_video_sampling.py`

Covers a real OpenCV short video where the first run fails after a partial prefix and a later call with `resume_existing=True` completes the plan without rewriting the already completed prefix.

### Scheduler / Worker recovery integration

`tests/integration/test_video_task_worker.py`

Covers:

1. real task creation;
2. real Scheduler claim;
3. forced mid-extraction failure after partial progress;
4. persisted FAILED task + worker checkpoint/frame artifacts;
5. `repository.retry(task_id)`;
6. replacement Scheduler execution entering `recover()`;
7. final success with the exact material count and no duplicate material rows;
8. previously completed frame artifacts remaining unchanged.

Existing corrupt-video and terminal idempotence tests remain intact.

### Frontend durable recovery truth

`tests/frontend/video-tasks.test.mjs`

Covers an active task with `attempt = 2` and verifies:

- normalized attempt remains 2;
- UI runtime text is `恢复执行 · 第 2 次执行`;
- the final video table renderer exposes that text;
- current backend frame truth remains visible.

### Permanent workflow

`.github/workflows/video-frame-recovery.yml`

Runs on Ubuntu 24.04 and Windows latest and permanently guards:

- Python compile contract;
- extraction/resume behavior;
- execution fencing behavior;
- Scheduler/Worker checkpoint recovery;
- frontend recovery truth.

## CI evidence

Product acceptance HEAD: `6eb90871dddc44a1ec172d4b4a0489d9c9aa4240`

### Video Frame Recovery

Run: `35174798772`

- `recovery-contract (ubuntu-24.04)`: success
- `recovery-contract (windows-latest)`: success
- compile: success
- extraction and fencing guards: success
- Worker checkpoint recovery: success
- frontend recovery truth: success

### Frontend Runtime Stabilization

Run: `35174798779`

- frontend syntax/owner/unit guards: success
- full Real Chrome runtime regressions: success

### Navigation Action Fencing

Run: `35174798782`

- permanent source guard: success
- unit contracts: success
- Real Chrome stale-mutation contract: success

## ZIP browser regression discovered during full-suite validation

The first full-browser validation exposed one unrelated stale test expectation around the ZIP background-import modal.

The product had already been intentionally changed so opening the modal reads fresh backend job truth. The old browser test still expected an empty/stale snapshot until the user pressed Refresh.

The browser contract was strengthened instead of weakened:

- opening the modal must issue a fresh list request and render `modal-open.zip`;
- pressing Refresh must issue another fresh list request and replace it with `modal-refresh.zip`.

Commit:

`0e5fa3c2b4c596f1873e148105244770b75b019b`

That contract passed the full frontend Real Chrome regression and the existing `v42.25 Release Regression` run `35174375475`.

No ZIP production runtime code was changed in this video batch.

## Batch commit chain

Key commits in this batch:

- `eea3896f17579262e966d82baca7eea59db6f140` — video extraction checkpoint recovery
- `4d8faee008d2f48780fff972580428767b8ee56d` — unit resume regression
- `6e03bb344d1a7dfa2bd319936802df91a4c34196` — Scheduler/Worker retry integration regression
- `5ac0765d28d6e9f625c8f7c3742a42b268764078` — permanent Video Frame Recovery workflow
- `0e5fa3c2b4c596f1873e148105244770b75b019b` — align ZIP modal browser contract with fresh backend truth
- `da82c1f44e2ce3af3c58cf3abc60a1aac2011f3c` — frontend recovery execution visibility
- `50c1cc3b64656902a597dfb02b5801872776eb07` — frontend recovery truth regression
- `6eb90871dddc44a1ec172d4b4a0489d9c9aa4240` — add frontend truth to permanent video recovery gate

## Closure decision

### CLOSED by automated contract

- Video extraction no longer has to rewrite a verified completed frame prefix after Worker/process failure.
- A replacement Scheduler execution can retry/recover from durable task artifacts/checkpoint state.
- Existing execution fencing still prevents stale Worker generations from publishing over the replacement execution.
- Windows and Ubuntu focused recovery contracts are green.
- The frontend exposes recovered execution state from durable backend `attempt` truth.
- Full frontend Real Chrome and navigation fencing regressions are green.

### Not claimed / still outside this closure

- large real production-video throughput or latency;
- sudden machine/power-loss filesystem durability beyond the process-crash contract;
- codec-specific seek performance guarantees;
- per-object checkpoint recovery during the later material/storage publishing phase;
- zero-repeat remote object upload cost after a crash during publishing;
- A800/GPU validation (video extraction is CPU/OpenCV oriented and this batch does not require GPU proof).

## Release constraints preserved

- no merge to `main`;
- no tag;
- no release;
- no `VERSION.txt` change;
- formal version remains `42.24.0`.
