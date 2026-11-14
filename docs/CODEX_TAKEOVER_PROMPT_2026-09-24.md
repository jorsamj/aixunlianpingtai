# CODEX TAKEOVER PROMPT — 2026-09-24

Continue work on GitHub repository `jorsamj/aixunlianpingtai`.

Long-lived branch:

`feature/external-algorithm-publishing`

Project:

**畅联云算法训练平台**

This is a continuation of an active development session. Do not redesign the architecture and do not redo CLOSED work.

## Start by re-reading live GitHub truth

Before any modification, re-read:

1. remote HEAD of `feature/external-algorithm-publishing`;
2. `VERSION.txt`;
3. latest 20 commits;
4. all current GitHub Actions/check-runs;
5. real logs for every completed failure;
6. `docs/CODEX_HANDOFF_2026-09-24_CURRENT.md`;
7. `docs/CODEX_HANDOFF_2026-09-24_TRAINING_DETAIL_LOGS.md`;
8. relevant current production owners/tests before changing code.

Documentation cutoff before the handoff commit was:

`3b6187a2124ed536f63a37be6ebb2c69f7ed049c`

Do NOT assume it is still HEAD.

`VERSION.txt` must remain exactly `42.24.0`.

## Absolute constraints

- no merge `main`;
- no tag/release;
- no force-push;
- no test deletion or weakening;
- do not restore retired pages/owners to satisfy stale tests;
- no second training detail/log owner;
- no second polling loop;
- no duplicate training truth store;
- formal Web listener remains `127.0.0.1:8010`;
- Windows is development, Linux/NVIDIA is production;
- queued Actions are not green.

## CLOSED — do not redo

Training resource/scheduler work is already closed code-side:

- frontend three automatic profiles:
  - `balanced` = 智能推荐
  - `performance` = 性能优先
  - `stability` = 稳定优先
- frontend/API/durable payload/worker/resource resolver are aligned;
- central server/GPU scheduling;
- manual `cuda:N` requests respected;
- no same-GPU double assignment;
- multi-GPU host CPU/RAM/cache budget uses actual concurrent reservations;
- single task on dual-GPU host does not have Workers divided by installed GPU count;
- remote Agent carries dataset memory evidence for RAM/disk cache;
- busy externally-loaded GPU can remain queued;
- GPU shared training remains fail-closed;
- `ultralytics==8.4.127` training precision truth is `auto/fp16/fp32`; BF16 training is fail-closed;
- bounded OOM retry may reduce Batch; runtime must not dynamically enlarge Batch.

Training detail/log work is also already closed code-side:

- `TrainingTaskRuntime` = canonical list owner;
- `TrainingProgressStream` = durable SSE live progress owner;
- `TrainingRecoveryRuntime` = sole training detail/log visual owner;
- successful terminal truth cannot be overridden by stale error/recovery metadata;
- partial success is warning, not fatal failure;
- open detail receives live Epoch/Batch/progress;
- terminal SSE triggers one final detail/log reconciliation;
- structured failure evidence is exposed;
- detail GET is read-only and must not dispatch/publish/archive;
- detail/log popup includes actual resource/telemetry/reproducibility/lifecycle data;
- legacy run-center/detail owners are retired.

Do not create another training modal/runtime.

## Current CI state at documentation cutoff

For `3b6187a...`:

- 51 total checks
- 41 success
- 10 failure

The branch was NOT green.

Confirmed stale/mis-scoped failures from real logs:

1. Remote Training guard globally greps `<option value="bf16"` in `static/app.js`; it hits legitimate Sophon deployment BF16. Scope the guard to training UI. Do not remove deployment BF16.
2. Windows training resource tests expect Workers 8/12 although production Windows safety cap is 4. Make tests OS-aware; do not remove the cap.
3. Label Normalization frontend contract expects retired exact `createAiLabelCanonical429` wrapper. Do not restore a duplicate owner without focused production evidence.
4. Broad browser navigation still expects retired `工作台` instead of canonical `总览`, and contains stale exact build markers.

Failures still requiring focused classification:

- External Algorithm Publish Real Chrome;
- Storage Source Real Chrome;
- Model/RKNN Agent Real Chrome;
- External Algorithm Platform Real Chrome;
- Remote Material permanent guard;
- Frontend Runtime legacy-poll compatibility guard;
- remaining broad-browser selector/request-count failures.

Read each real failure log before editing production.

## Current highest priority

1. Re-read latest live HEAD/checks.
2. Clear confirmed stale/mis-scoped CI first.
3. Focused reproduce every remaining failure before modifying production.
4. Re-run focused training detail/log tests.
5. Verify training task UI behavior:
   - successful training never shows failure;
   - live progress/Epoch/Batch refreshes while detail is open;
   - log grows without rebuilding the modal;
   - errors contain useful structured evidence;
   - terminal state performs final reconciliation;
   - popup remains readable and uses the single owner.
6. When a real Linux GPU/Agent is available, verify scheduler/resource/detail truth end-to-end.

## Do not claim deployment-ready until

- relevant completed CI is green or every remaining failure is explicitly classified;
- Linux/NVIDIA real training verifies device selection, Batch/Workers/Cache, precision, OOM behavior and artifacts;
- remote Agent verifies the same contracts;
- real popup/log terminal behavior is observed.

Use the current code and tests as truth. Never use this prompt's SHA as a checkout target without re-reading remote HEAD.
