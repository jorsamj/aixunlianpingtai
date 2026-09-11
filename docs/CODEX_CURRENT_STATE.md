# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always confirm the live branch/HEAD with `git branch --show-current`, `git rev-parse HEAD`, and `git log --oneline -20` before changing code.

## 1. Branches and release state

```text
stable main:                      main
main contains v42.25 runtime:     6683edeb5d8391acbd96909ff22f72022105026b
current frontend cleanup branch:  refactor/frontend-runtime-stabilization
formal VERSION.txt / API version: 42.24.0 until v42.25 release acceptance
frontend development badge:       v42.25.0-dev
```

Do not merge the current frontend cleanup branch into `main` unless explicitly authorized.

`main` already contains the previous v42.25 backend/runtime work. The current branch is specifically for browser/runtime stabilization and legacy frontend consolidation.

## 2. Production / acceptance environment

```text
Ubuntu 22.04
16 CPU
~32 GB RAM
NVIDIA A800-SXM4-40GB
repo: /data/platform/aixunlianpingtai
persistent data: /data/platform-data
app conda env: mc-platform
training Python: /home/vipuser/miniconda3/envs/yolo/bin/python
Torch: 2.5.0+cu124
CUDA: 12.4
```

Windows remains a supported development environment. Production code must stay cross-platform: no hard-coded drive letters, backslash-only paths, Windows-only shell commands, or Windows-only process control.

## 3. Backend/runtime contracts already in main

### Training data correctness

Implemented contracts include:

- pre-split SHA duplicate analysis;
- same SHA + same normalized GT => one canonical training row, duplicate ids excluded without deleting library records;
- same SHA + different normalized GT => fail before YOLO;
- explicit train/test same SHA => leakage error;
- union-find inseparable groups for source/video/session/near-duplicate relations;
- AnnotationRepository is Ground Truth authority;
- Snapshot schema v3 locks annotation state/scope/hash/SHA/storage/source/split audit.

### Negative samples

```text
unannotated      -> no confirmed GT -> cannot train
annotated        -> positive GT      -> can train
confirmed_empty  -> explicit negative -> can train
```

Portable YOLO emits a real empty `.txt` for valid confirmed-empty negatives. Ordinary zero-box save must not silently create a negative sample.

### Task Runtime fencing

Worker execution is fenced by lease token + generation/attempt. Process identity uses PID + create time + command hash. Expired live exact processes are not blindly requeued. Recovery ambiguity fails closed. GPU reservations can be quarantined. Stale execution cannot publish final artifacts or finish another generation's task.

### Training resources

Explicit user settings are protected from the auto resolver:

```text
batch=16   -> auto may downscale for safety, never upscale
workers=4  -> auto never increases it
workers=0  -> remains 0
cache=false -> remains false
batch=-1   -> explicit auto-batch opt-in
```

`TrainingMetrics.on_train_start()` compares actual Ultralytics Trainer values and raises `RESOURCE_RUNTIME_MISMATCH` on divergence.

### Task-scoped label schema

Project label library is not the model label schema.

First training:

- only labels evidenced by the exact selected materials are selectable;
- user must select task labels;
- mother/pretrained classes are not inherited;
- selected labels are reindexed task-locally from 0.

Iteration:

- inherit only the previous successful, artifact-verified, trainable version schema;
- preserve old class ids;
- append explicitly selected new labels;
- never fall back to mother model when historical versions exist but no trainable predecessor exists.

## 4. Current frontend architecture work

The browser is still primarily `static/app.js` plus modules, not a clean Vue application yet.

Current stabilization stack:

```text
static/app.js legacy runtime
  -> static/main.mjs
       ├── Navigation Ownership
       ├── Page RequestScope / AbortController
       ├── PollRegistry
       ├── TrainingDraftRuntime
       └── module training-labels
```

### Navigation stability

Real Chrome regression covers:

```text
enter Training Tasks
-> hold an old GET request
-> navigate to Datasets
-> release the old request
-> page remains Datasets
-> no pageerror
```

Old page async completions are no longer allowed to repaint the current page.

### RequestScope

Same-origin `/api/*` GET/HEAD requests belong to the active page and are aborted/quarantined when that page is left. Mutating requests are not automatically cancelled.

### PollRegistry

Known historical timers are centrally cleared on page exit. Timer creation itself is still partially legacy and is a remaining cleanup item.

### Canonical TrainingDraft

Current canonical frontend training state:

```text
state.trainingDraft
```

It contains algorithm/base-version ids, exact train/test material ids, split mode, experiment/validation percentages, inherited/new/effective labels, resource strategy/device/GPU policy/batch/workers/cache, config and priority.

`TrainingDraftRuntime` now reads final train-v3 DOM values, canonicalizes them, and mirrors back to old state only for compatibility.

Real Chrome regression verifies that stale manually supplied ids/labels/percentages are replaced by the values currently visible in the training UI before `/train/start` is sent.

### Training label cleanup

The old compatibility files have been retired from the active runtime and removed from the branch:

```text
static/training-label-bootstrap.js
static/training-label-v3-anchor.js
```

Current label UI owner:

```text
static/modules/training-labels.js
```

It directly supports final `.train-v3-summary`, writes selected labels into TrainingDraft, and no longer owns `/train/start` request interception.

Current frontend `/train/start` owner:

```text
static/modules/training-draft-runtime.js
```

The backend label contract remains the final authority.

## 5. Historical frontend fields still present

These are compatibility mirrors, not future sources of truth:

```text
state.train428AlgorithmId
state.train428Config
state.train429Selected
state.trainSplitV3
state.trainingLabelSelected
```

Do not create `train430`, `train431`, etc.

Next migration direction:

```text
train-v3 UI action
-> TrainingDraftRuntime.update()
-> state.trainingDraft
-> temporary compatibility mirror
```

Then remove old fields only after browser parity is proven.

## 6. Current frontend regression gate

Workflow:

```text
.github/workflows/frontend-runtime-stabilization.yml
```

Checks:

```text
node --check key runtime modules
node --test tests/frontend/*.test.mjs
Playwright Chrome:
  tests/browser/navigation-stability.spec.mjs
  tests/browser/training-label-selector.spec.mjs
```

Browser tests are necessary but not sufficient for release.

## 7. Next work order

1. Finish direct train-v3 -> `TrainingDraftRuntime.update()` writes; stop rebuilding the submit payload from legacy state.
2. Move polling creation itself into PollRegistry, not only cleanup/adoption.
3. Convert high-frequency pages to incremental row/card updates: Training Tasks -> Algorithms -> Datasets.
4. Run broad repository regression.
5. Run real A800 acceptance:

```text
device=0
batch=16
workers=4
cache=false
select only fire + smoke
short 3-5 epoch run
```

Expected evidence:

```text
requested batch=16 workers=4 cache=false
effective batch=16 workers=4 cache=false
Ultralytics actual batch=16 workers=4 cache=false
nc=2
```

Also verify confirmed-empty negatives create zero-byte label files and no duplicate execution/GPU double-use occurs.

6. Production security hardening after functional regression: remove broad `/data` exposure, restrict CORS, harden secrets/auth/download APIs/SSRF boundaries.

## 8. Do not do yet

- do not rewrite the whole frontend to Vue before P0 cleanup passes;
- do not split Git repositories;
- do not introduce microservices only for architectural appearance;
- do not add another numbered override layer to `static/app.js`;
- do not claim A800/production validation from browser CI alone.

For detailed frontend debt, read `docs/frontend-legacy-audit.md`. For data/runtime/label contracts, read the v42.25 design files under `docs/superpowers/specs/`.
