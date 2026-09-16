# Cleaning Stall Guard Handoff — 2026-09-16

Repository: `jorsamj/aixunlianpingtai`

Branch: `refactor/frontend-runtime-stabilization`

Validated runtime code baseline:

```text
b59c90ede8d4cebbdede35d5b50e2d64f0232166
```

Formal version remains:

```text
VERSION.txt = 42.24.0
```

No `main` merge, tag, release, force push, or formal version bump is part of this batch.

## User-reported production symptom

A durable cleaning task reached:

```text
progress = 84%
processed = 27 / 32
```

and then appeared not to advance.

The 84% value was not a browser-derived fake percentage. The backend computes progress from durable processed/total truth, so 27/32 correctly projects to 84%. The defect was that the next image could spend an unbounded amount of time inside image decoding/quality analysis, leaving the last successful durable count at 27.

## Runtime changes

### 1. Large-image analysis no longer decodes the source again for dHash

Implementation:

```text
e7f93ad3a39f55ab884e20c346839110adb62ba4
```

`platform_core/cleaning.py` now keeps original width/height for quality rules while expensive visual analysis is bounded by:

```text
MAX_ANALYSIS_PIXELS = 16_000_000
```

For unusually large images, blur, brightness, entropy and dHash reuse the same bounded decoded raster. The previous large-image path could downsample for blur/brightness and then reopen the original full-resolution image for dHash; that duplicate full decode is retired.

Normal-sized images retain the existing quality semantics.

### 2. Cleaning image analysis is isolated from the Materials Worker

Implementation:

```text
214dd4b37687ae6726ba69332d815476f04f7131
9286b593f6adb62d86f51a28f27e59c0f2164056
```

New runtime:

```text
platform_core/cleaning_analysis_runtime.py
```

The durable Materials Worker still owns task state, lease/fencing, selection truth, material writes and manifest progress. Pillow/OpenCV image analysis is executed by one reusable child process created with:

```python
multiprocessing.get_context("spawn")
```

This is intentionally compatible with Windows development and Linux production.

The child is reused across normal images; it is not restarted for every image.

Per-image analysis hard deadline:

```text
DEFAULT_ANALYSIS_TIMEOUT_SECONDS = 30.0
```

If one image does not return from analysis within the deadline:

```text
analysis child -> terminate
               -> join
               -> kill only if still alive
current image  -> durable failed item
batch          -> continue with next image
next analysis  -> fresh analysis child starts lazily
```

The parent continues polling task activity while waiting. Cancellation/lost lease propagates out and also tears down the analysis child, so the new process does not bypass existing TaskRepository/Scheduler fencing.

### 3. Per-item failure no longer freezes the whole batch

`platform_core/cleaning_batches.py` now uses `CleaningAnalysisRuntime.analyze()` during the existing truthful `analyzing` stage.

A timeout/runtime failure is persisted as that image's cleaning failure and the manifest advances. The next selected image is still processed. Corrupt-image semantics remain separate: real `ImageDecodeError` can still become a `corrupt` cleaning finding when `corrupt_check` is enabled.

No fake progress is introduced. A failed image counts as processed only after its durable failed result and manifest state are written.

## Direct regression for the 27/32 symptom

The API regression now explicitly simulates:

```text
image A -> CLEAN_ANALYSIS_TIMEOUT
image B -> real image_metrics()
```

using the real durable Materials Scheduler path.

Required final truth:

```text
TaskStatus = PARTIAL_SUCCESS
progress = 100
total = 2
processed = 2
succeeded = 1
failed = 1
analysis calls = 2
```

The assertion is intentionally order-independent because durable selection processing is ordered by material identity rather than browser upload order. The completed second item may be `passed` or `needs_review` depending on genuine quality findings such as duplicate detection; it must not be left failed merely because the previous image timed out.

Final test-only ordering fix:

```text
b59c90ede8d4cebbdede35d5b50e2d64f0232166
```

No production threshold or quality rule was relaxed to make this pass.

## Permanent CI evidence

Validated runtime baseline:

```text
b59c90ede8d4cebbdede35d5b50e2d64f0232166
```

### Material Upload Cleaning Performance

Run:

```text
35103331085
```

Results:

```text
cross-platform-hot-path (ubuntu-24.04)  PASS
cross-platform-hot-path (windows-latest) PASS
durable-api-flow                         PASS
```

This workflow permanently guards:

- direct-stream plain upload invariants;
- repository initialization reuse;
- verified SHA reuse during cleaning;
- large-image bounded analysis;
- bounded-raster dHash reuse;
- spawned cleaning analysis runtime;
- 30-second analysis hard deadline;
- timeout termination behavior;
- real upload -> durable cleaning flow;
- Windows + Linux compatibility;
- `VERSION.txt = 42.24.0`.

### Release/runtime contracts

Run:

```text
35103330981
```

Results:

```text
runtime-contracts       PASS
training-data-contracts PASS
```

The runtime contract suite includes the timeout-and-continue durable cleaning regression. The final passing run therefore proves the change did not require weakening unrelated Scheduler, training, deployment, storage, video, annotation or task-runtime contracts.

### Frontend / Real Chrome

Run:

```text
35103331084
```

Results:

```text
frontend           PASS
browser-navigation PASS
```

The cleaning fix did not add another frontend progress owner or polling loop. Existing durable task presentation remains authoritative.

### Navigation action fencing

Run:

```text
35103330944
```

Result:

```text
action-fencing PASS
```

## Closure status

Use this wording:

```text
Cleaning Analysis Stall Guard
CODE / WINDOWS / LINUX / DURABLE API / RUNTIME CONTRACTS: CLOSED
REAL SERVER REPRODUCTION WITH THE ORIGINAL 32-IMAGE BATCH: PENDING
```

The code-level defect where one pathological image analysis can keep the entire cleaning batch permanently at e.g. 27/32 is closed for the `analyzing` phase.

Do not claim the original production incident is fully accepted until the latest branch is deployed to the real server and the same or equivalent material batch is rerun.

## Important boundary — materializing is not yet hard-timed

This batch protects the image-analysis phase:

```text
materializing
-> analyzing   [30s hard per-image analysis deadline]
-> evaluating
-> saving_clean_result
```

`StorageManager.materialize()` itself is still executed in the Materials Worker process. If an underlying local/remote storage provider call never returns, the task can still remain in:

```text
materializing
```

That is deliberately not hidden by removing content-integrity checks. In particular, local materialization still validates source content SHA; remote materialization/cache truth must also stay fail-closed.

If a future real-server stall is observed and the backend stage is `materializing`, treat that as a separate storage/provider timeout batch. Do not reopen the now-closed image-analysis timeout work and do not delete SHA verification merely to improve speed.

## Server acceptance after deployment

Re-run a cleaning batch containing the original/problematic materials and observe the durable current stage.

Expected behavior if a problematic image stalls in analysis:

```text
... 27/32
current stage = analyzing
current image = <problem image>
<= about 30 seconds
that image -> failed
processed -> 28/32
batch continues -> 29/32 ...
terminal -> PARTIAL_SUCCESS or SUCCEEDED
progress -> 100%
```

If the same task instead remains in:

```text
current stage = materializing
```

beyond an unreasonable storage access interval, the next development target is storage/provider materialization timeout/isolation, not the cleaning-analysis runtime.

## Related upload-performance state

Plain image upload performance was already separately closed in code/CI before this cleaning stall batch. The current upload path uses direct Starlette `UploadFile` streams into StorageManager rather than writing a second application-level `imports/upload_*` copy. Batch material/annotation persistence and StorageManager reuse remain authoritative.

Real 380-image server timing is still a deployment acceptance measurement; no percentage speedup is claimed until measured on the user's server.
