# Codex Handoff — 2026-09-16 Deployment Candidate

Date: 2026-09-16
Branch: `refactor/frontend-runtime-stabilization`
Runtime-validated clean baseline: `cca721d13ead436c46ee4ffab0dbd06b3cbaeca5`
Formal `VERSION.txt`: `42.24.0`

## Resume from here

This file is the current Codex resume point for the branch as of 2026-09-16. It supersedes older branch/HEAD/push-status snapshots in historical sections of `docs/CODEX_CURRENT_STATE.md`. Live GitHub branch state must still be verified before editing because documentation-only commits may exist after the runtime-validated baseline.

The following work is already implemented and recorded in Git. Do not restart or duplicate these batches without new evidence:

- Resource Discovery durable Worker integration and Training Input Integrity closures.
- Task Runtime Truth v1.
- Task Runtime Truth v2.
- Generic Durable Queue Exactness.
- Previously closed training polling/owner, cleaning durable execution/frontend truth, deployment-test durable truth, navigation fencing and other entries already recorded in `docs/TECH_DEBT_CLOSURE_V42_25.md`.

## Durable task truth contract

For durable task payloads, the frontend must preserve backend truth:

```text
task_status > compatibility status
phase > task_stage / stage
progress_percent > legacy progress
```

The browser must not derive a new durable percentage from item counts or domain counters.

A numeric `resource_queue_position` may be rendered as “队列第 N 位” only when the backend also proves:

```text
resource_queue_position_exact === true
```

Candidate rank, priority order, or an unproved numeric position must not be presented as exact Worker/hardware queue truth. Wait reasons and domain-specific counters remain valid diagnostics.

Read the detailed closures before changing this behavior:

- `docs/CODEX_HANDOFF_2026-09-16_TASK_RUNTIME_TRUTH_V1.md`
- `docs/CODEX_HANDOFF_2026-09-16_TASK_RUNTIME_TRUTH_V2.md`
- `docs/CODEX_HANDOFF_2026-09-16_GENERIC_QUEUE_EXACTNESS.md`

## Git and CI evidence

The runtime product state is in normal commits and the dated handoffs. One-shot migration helpers/workflows used during the Generic Queue Exactness closure were physically deleted before the runtime-validated clean baseline.

Validated evidence leading into the clean baseline:

- `v42.25 Release Regression` run `35065904511`: PASS on `c40389f16d18df7a405ffde342303f72265cb684`.
  - `runtime-contracts`: PASS.
  - `training-data-contracts`: PASS.
- `Frontend Runtime Stabilization` run `35065904465`: PASS on `c40389f16d18df7a405ffde342303f72265cb684`, including full Real Chrome runtime regressions.
- `Navigation Action Fencing` run `35065904464`: PASS on `c40389f16d18df7a405ffde342303f72265cb684`, including the Real Chrome stale-mutation contract.
- Final clean runtime baseline `cca721d13ead436c46ee4ffab0dbd06b3cbaeca5`:
  - `Frontend Runtime Stabilization` run `35066123649`: PASS, including frontend unit/owner guards and full Real Chrome.
  - `Navigation Action Fencing` run `35066123718`: PASS, including Real Chrome stale-mutation coverage.
- The permanent `Task Runtime Truth` closure matrix passed on both Ubuntu and Windows during the closure.

The commits after `c40389f16d18df7a405ffde342303f72265cb684` leading to `cca721d13ead436c46ee4ffab0dbd06b3cbaeca5` only clean up temporary migration artifacts; they do not introduce another runtime product behavior change.

## Test deployment candidate

`cca721d13ead436c46ee4ffab0dbd06b3cbaeca5` is the runtime-validated baseline selected for a single-A800 **test deployment candidate**.

This does **not** mean:

- `main` was merged;
- a tag or release was created;
- formal `v42.25.0` was released;
- real A800 RC was completed;
- genuine 10k ZIP performance acceptance was completed.

Normal upgrade safety remains fail-closed:

- preserve the external platform data root; a code update must not wipe application data;
- do not use `MC_ALLOW_ACTIVE_TASK_UPGRADE=1` as a normal deployment shortcut;
- if an old build still owns `RUNNING` / `CANCEL_REQUESTED` durable tasks, let them finish or cancel them before replacing the Worker build;
- keep the platform runtime and the dedicated CUDA/YOLO training environment isolated; do not blindly install the root requirements into the dedicated CUDA training environment.

The actual target-host process manager/restart procedure must be discovered on the host. Do not invent a systemd unit name or replace a verified deployment mechanism with an assumed one.

## Still unverified / do not overclaim

The following remain separate real-environment acceptance work:

- actual A800 RC on the target server;
- genuine 10k ZIP performance acceptance;
- GPU Runtime Truth Phase 1B and multi-GPU/cross-node production behavior;
- vendor-specific hardware conversion final acceptance;
- production filesystem/mount/permission behavior not already proven by automated contracts;
- exact target-server service-manager/restart mechanics until verified on-host.

Historical P0 A800 acceptance items in `docs/CODEX_READ_FIRST.md` also remain pending unless a newer evidence-backed handoff explicitly closes them.

## Mandatory continuation rule

Before making the next code change, Codex must:

1. `git fetch origin`.
2. verify `git status`.
3. compare local `HEAD` with `origin/refactor/frontend-runtime-stabilization`.
4. verify `VERSION.txt` is still `42.24.0`.
5. read this handoff plus the three 2026-09-16 runtime-truth/queue handoffs.
6. reconcile live GitHub Actions with this recorded baseline.
7. continue only from the actual newest state; do not redo CLOSED batches merely because an older section of a long-lived document contains an obsolete SHA.
