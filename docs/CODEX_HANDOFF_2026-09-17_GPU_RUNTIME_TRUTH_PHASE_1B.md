# GPU Runtime Truth Phase 1B Handoff — 2026-09-17

Repository: `jorsamj/aixunlianpingtai`

Branch: `refactor/frontend-runtime-stabilization`

Formal version: `VERSION.txt = 42.24.0` (unchanged)

Product-validated HEAD: `673cf713045fc47ebd5cb4e1a9f73bc834323e68`

Previous focused handoff base: `67777e64dbf53dd942bd41e19ad08e037d363163`

## Closure statement

**GPU Runtime Truth Phase 1B — node-scoped reservation / scheduling automated contract is CLOSED.**

This closure is deliberately limited to the durable scheduling and identity contract proven by repository tests and permanent CI. It is **not** a claim that real multi-node NVIDIA/A800 hardware acceptance, MIG scheduling, throughput, or production contention behavior has been completed.

## What changed

Phase 1A already made GPU inventory, telemetry and Worker identity node-aware, but reservations were still globally scoped. In particular, legacy reservation truth had global `worker_slot` uniqueness and GPU conflicts were keyed only by `gpu_uuid`. Phase 1B removes those cross-node false conflicts and makes assignment identity explicit.

The formal training Worker now resolves one node identity and uses that same `node_id` for both `WorkerInstanceService.acquire(...)` and `NodeScopedGPUResourceManager(...)`. The Scheduler and GPU manager also share the same `worker_id`; no second node registry or competing scheduling owner was introduced.

### Reservation schema v2

`platform_core/gpu_reservations_v2.py` introduces node-scoped reservations with the following durable identity:

- `task_id`
- `node_id`
- `gpu_uuid`
- `physical_index`
- `logical_cuda_index`
- compatibility `gpu_index` equal to the logical CUDA index
- `worker_id`
- `worker_slot`
- lease token / policy / reservation budget / timestamps
- uniqueness: `UNIQUE(node_id, worker_slot)`

Active reservation conflicts are evaluated by `(node_id, gpu_uuid)`, not globally by GPU UUID. Therefore two nodes may legitimately expose the same UUID-like test identity or the same slot name without blocking each other, while the same node still enforces its slot and GPU concurrency contract.

### Worker GPU visibility v2

Phase 1B also closes a remaining Phase 1A multi-node edge case. Visibility is now unique by:

`(worker_id, node_id, logical_cuda_index)`

and refresh only replaces rows for the current `(worker_id, node_id)` pair. A Worker on node B using the same explicitly configured `worker_id` can no longer delete node A's visibility rows.

### Legacy migration and fail-closed behavior

Legacy reservations are migrated to a real node only when `worker_instances` proves exactly one non-legacy `node_id` for that reservation's `worker_id`.

If ownership cannot be proven, the reservation is migrated as `legacy-unscoped`. While such a pre-upgrade lease is still active, new GPU admission is blocked with `GPU_LEGACY_RESERVATION_UNSCOPED` rather than guessing ownership and risking double allocation.

### Assignment fencing

Admission requires current durable Worker visibility for the selected `(worker_id, node_id, gpu_uuid)` and uses its logical CUDA index.

Before publishing `assignment.json`, assignment re-checks:

- `task_id`
- current `lease_token`
- `worker_id`
- `node_id`
- `gpu_uuid`
- current `worker_gpu_visibility.logical_cuda_index`

If the visibility mapping no longer matches the reservation, assignment fails with `GPU_ASSIGNMENT_FENCED`. The training process therefore receives `cuda:<logical index>` only after the physical GPU / UUID / node / Worker-visible CUDA mapping is proven.

## Permanent tests and guards

Added `tests/unit/test_gpu_node_scoped_reservations.py`, covering:

1. legacy reservation migration only with proven Worker node ownership;
2. ambiguous legacy reservation fail-closed behavior;
3. same slot and same GPU UUID independence across nodes;
4. same-node slot conflict preservation;
5. assignment binding of node ID, GPU UUID, physical index and logical CUDA index;
6. assignment fencing after visibility loss;
7. node-scoped summary isolation;
8. identical explicit `worker_id` and logical CUDA index remaining independent across different nodes.

Added permanent workflow `.github/workflows/gpu-runtime-truth.yml` for both `ubuntu-24.04` and `windows-latest`. It runs Python compile checks, focused GPU runtime tests and source guards for the formal Worker wiring and node-scoped schema contracts.

## Validation evidence

Product-validated HEAD: `673cf713045fc47ebd5cb4e1a9f73bc834323e68`

### GPU Runtime Truth

Run: `35172103383`

- `node-scoped-reservations (ubuntu-24.04)`: SUCCESS
- `node-scoped-reservations (windows-latest)`: SUCCESS
- compile checks: SUCCESS
- focused runtime contracts: SUCCESS
- formal Worker/source guards: SUCCESS

### Frontend Runtime Stabilization

Run: `35172103169`

- frontend syntax/unit/owner guards: SUCCESS
- full Real Chrome runtime regressions: SUCCESS

### Navigation Action Fencing

Run: `35172103257`

- source guard: SUCCESS
- unit contracts: SUCCESS
- Real Chrome stale mutation contract: SUCCESS

## Scope audit

Comparing previous focused handoff HEAD `67777e64dbf53dd942bd41e19ad08e037d363163` to product-validated HEAD `673cf713045fc47ebd5cb4e1a9f73bc834323e68` shows only the expected Phase 1B files:

- `.github/workflows/gpu-runtime-truth.yml` — added
- `platform_core/gpu_reservations_v2.py` — added
- `task_worker.py` — narrowly rewired to `NodeScopedGPUResourceManager`
- `tests/unit/test_gpu_node_scoped_reservations.py` — added

No training checkpoint/final-validation recovery code, ZIP runtime, frontend product runtime, `VERSION.txt`, `main`, tags, or releases were changed.

## Explicitly not proven / still open

The following must not be inferred from this automated closure:

- real multi-node NVIDIA Worker execution;
- real A800 reservation/contention behavior;
- process-level GPU memory contention under simultaneous production training;
- MIG scheduling/admission;
- GPU throughput or training-speed claims;
- A800 RC acceptance;
- production performance percentages;
- `/api/v62/gpu-runtime` reservation projection.

The existing `/api/v62/gpu-runtime` read model still exposes nodes, workers, GPUs, Worker visibility and telemetry. Phase 1B makes the internal reservation/scheduling truth node-scoped, but reservation rows have not yet been added to that public read projection. This remains an observability follow-up, not a hidden completion claim.

## Constraints preserved

- no merge to `main`;
- no tag;
- no release;
- `VERSION.txt` remains `42.24.0`;
- Windows development and NVIDIA Linux production paths remain supported;
- A800 RC remains paused;
- genuine 10k ZIP production acceptance remains paused.
