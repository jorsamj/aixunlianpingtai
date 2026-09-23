# Training Detail / Log Truth Handoff — 2026-09-24

> Branch: `feature/external-algorithm-publishing`  
> Code baseline before this documentation commit: `8e50195f76d0aa58ccf6082bdbd7c93029b528b7`  
> `VERSION.txt = 42.24.0` — do not change.  
> At documentation time: 88 checks queued, 0 completed failures. Queued is not green.

## User-visible problems that triggered this batch

1. A training-related popup could present an error even when canonical task truth was successful.
2. Detail/log popup data was incomplete and did not reliably reflect live Epoch/Batch/progress/resource truth.
3. Progress in an already-open detail/log popup could become stale.
4. Error evidence was too shallow: stage/type/post-training validation/worker lifecycle evidence could be lost.
5. Several historical detail/log renderers and modal owners overlapped, creating owner ambiguity and visual inconsistency.
6. The popup layout was dense/legacy and did not separate status, diagnostics, resource evidence, reproducibility data, lifecycle and technical log.

## Final owner chain

```text
Training task list
→ TrainingTaskRuntime (canonical list refresh / mutations)
→ TrainingProgressStream (/api/v64/.../training-events)
→ TrainingRecoveryRuntime (single detail + log visual owner)
→ GET /api/projects/{project_id}/jobs/{task_id}
→ GET /api/projects/{project_id}/jobs/{task_id}/log
→ canonical durable Task truth + worker job truth + training-metrics.sqlite3
```

Do not restore a second training detail modal, second log modal, legacy run-center owner, raw polling loop, or direct DOM owner in `static/app.js`.

## Closed behavior

- Canonical `task_status` wins over stale legacy `status/error/recovery` fields.
- `SUCCEEDED` never renders historical failure evidence as a fatal error.
- `PARTIAL_SUCCESS` is rendered as completed with non-fatal warnings.
- Failed tasks may show structured:
  - `error`
  - `error_type`
  - `failure_stage`
  - validation/test/report errors
  - process/runtime/AI/archive evidence where present.
- Worker `train.log` and durable scheduler/worker task logs are merged into one canonical read-only log endpoint.
- Detail view displays actual resource truth where available: actual device/GPU, resource profile, Batch/Workers/Cache, effective precision, GPU/VRAM/CPU/I/O telemetry, throughput and epoch duration.
- Reproducibility section displays snapshot / dataset revision / checkpoint / process return code / attempts / resource adjustment reasons.
- Open detail uses PollRegistry; there is no private `setTimeout/setInterval` polling owner.
- Live SSE updates an already-open detail view.
- On terminal SSE (`SUCCEEDED/FAILED/PARTIAL_SUCCESS/etc.`), the runtime performs one final canonical detail + log reconciliation before stopping refresh. This prevents a popup from freezing on the pre-terminal frame.
- Detail GET is explicitly prohibited from triggering algorithm-version archival. A read poll is not a business execution owner.
- Detail GET also no longer dispatches training queues or rebuilds the global jobs index.
- Browser cache keys are advanced with the runtime:
  - `training-recovery-runtime.js?v=422575`
  - `main.mjs?v=42.25.226`

## Important commits in this closure

```text
3414abe89c4c  fix: unify training detail logs and runtime truth
487de1640c64  test: guard successful training detail semantics
b6f4c484f698  fix: unify truthful training detail and live progress
a650cd714467  fix: expose structured training failure evidence
1001aeae8016  test: execute training realtime failure contract
aeadd4b7a029  refactor: retire legacy training run center owner
dc9002d41fd1  fix: return enriched read-only training detail truth
a9e742d320a6  ui: expose live training resource telemetry
be3eaccb09f8  perf: keep training detail polling read-only
da0544ad7c2e  refactor: retire legacy training detail owner
eabaa640602e  fix: reconcile terminal training detail truth
8e50195f76d0  test: guard truthful training detail refresh
```

## Permanent guards

- `tests/frontend/training-recovery-runtime.test.mjs`
  - success must not become failure because of stale recovery/error metadata
  - partial success remains warning-only
  - live metrics/resources/dataset evidence
  - terminal live event must perform final detail/log reconciliation
- `tests/frontend/training-progress-stream.test.mjs`
  - SSE updates list and open detail without a GET per normal progress event
  - terminal tasks reconcile through canonical task truth
- `tests/api/test_training_unified_task_overlay.py`
  - detail returns enriched task truth without overwriting worker job file
  - detail read poll must not archive algorithm versions
  - log endpoint merges worker and durable lifecycle logs
- `.github/workflows/training-recovery-guard.yml`
  - executes the focused frontend contracts and focused backend training-detail contracts
  - permanent owner/cache/read-only grep guards.

## Current UI information groups

The single detail popup now groups information into:
1. overall progress / Epoch / Batch / elapsed / ETA;
2. actual device and adaptive resource profile;
3. current message vs fatal errors vs non-fatal warnings;
4. training configuration and data counts;
5. durable runtime evidence and live GPU/CPU/I/O telemetry;
6. dataset revision, snapshot, checkpoint and process evidence;
7. lifecycle timeline;
8. collapsible engineer technical log.

Keep this hierarchy. Do not flatten all raw fields into one long legacy table.

## Still OPEN / deployment verification

- Current HEAD Actions must complete; do not call queued checks green.
- Real Linux GPU training must verify:
  - Epoch/Batch updates while popup is open;
  - final terminal frame reconciliation;
  - GPU/VRAM/CPU/I/O metrics;
  - final best/last artifacts;
  - CUDA OOM / failed final validation error evidence.
- Remote Agent training should be verified with a real node for the same detail/log contract.
- No merge `main`, tag, release, or `VERSION.txt` change was performed in this batch.

## CI follow-up after the closure

After code baseline `8e50195f...` began producing completed results, two unrelated failures were read from the actual job logs before any change:

- **External Algorithm Platform / Real Chrome**: backend contract + frontend contract + wiring guards were green. The browser test still queried retired `[data-external-category-filter]`; current category/filter ownership is `AlgorithmListRuntime`. The test was migrated to `[data-algorithm-list-owner="AlgorithmListRuntime"]`, `[data-category-picker-toggle]`, `[data-category-popover]`, `[data-category-check]` and `[data-category-confirm]`. Production DOM/owner was not reverted.
- **ZIP Import Durable Runtime / Windows contract**: all 42 frontend ZIP contracts passed; only the permanent guard failed because it hard-coded retired global cache key `main.mjs?v=42.25.195`. The guard now verifies a valid cache-busted `main.mjs?v=42.25.<number>` entry while ZIP-specific cache/owner guards remain exact.

CI-debt fix commit: `3262d5c100caa214517000e985b7b71437edf472` (`test: align stale browser and cache guards`). `VERSION.txt` remains `42.24.0`. New HEAD checks were queued at the time of this documentation update, so this section does not claim green.

