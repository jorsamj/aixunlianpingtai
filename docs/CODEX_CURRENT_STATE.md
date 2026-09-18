# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.



## Current closure — Remote MATERIAL_IMPORT Phase 5 COCO / Pascal VOC CLOSED

Formal `VERSION.txt` remains `42.24.0`.

COCO and Pascal VOC are now real remote annotation formats for
`MATERIAL_IMPORT + storage_scan + execution_mode=agent`. This closure is
deliberately limited to object-storage directory scanning; Agent server_zip is
not claimed for these formats.

A project-database-agnostic `DetectionDatasetScanner` reads only the brokered
StorageProvider and persists task-owned candidate/annotation evidence. COCO
preserves external category ids/names and split identity; VOC parses
object/bndbox XML with deterministic external class ids and rejects
DOCTYPE/ENTITY declarations. Image dimensions come from the real source object,
boxes are normalized for durable review, clipped/invalid boxes are represented
as quality evidence, and object/annotation/box counts are bounded.

Review archives remain metadata/annotation-only. Server-confirm revalidates the
review schema, prefix, candidate coverage, classes, normalized boxes and issue
evidence. Users then confirm external-class to platform-label mappings. The
local storage indexer re-stats source objects (size/ETag/SHA256) before writing
MaterialRepository and AnnotationRepository truth and converts normalized boxes
back to pixel coordinates. The Agent never creates labels or writes central
project databases directly.

The product UI exposes COCO and Pascal VOC only for object-storage Agent scans.
Local directory/server ZIP modes disable those options, and dataset_yaml
remains YOLO-only. Real Chrome verifies a COCO storage_scan submission.

Acceptance at code HEAD `9fb67096718e5ece1b72a2acf601662fe337e1d7`:
- Remote Material Import `35318574008`: API / Ubuntu / Windows / Real Chrome success.
- Node Agent Executor `35318574014`: success.
- Central Node Assignment `35318574002`: success.
- Task Runtime Truth `35318573876`: success.
- Storage Cache Governance `35318573935`: success.
- Portable Deployment `35318573871`: success.
- Remote Training Runtime `35318573869`: success.
- Remote Conversion Runtime `35318573929`: success.

## Current closure — Remote MATERIAL_BATCH/CLEAN Phase 1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Remote cleaning now executes on scheduled Agent nodes without creating a
competing cleaning task owner. The sole durable truth remains
`TaskKind.MATERIAL_BATCH + operation=CLEAN`; local execution stays the default
and explicit `execution_mode=agent` is fenced with `agent.remote`.

The control plane preflights the exact requested material range and requires
durable object evidence, enabled OSS/S3-compatible storage (including MinIO),
and an online Agent with effective `cleaning` capability. The UI consumes this
truth and disables remote execution when it is not genuinely available.
Direct API requests fail closed too and do not leave an Agent task behind.

The Agent never opens central SQLite/NFS and never receives long-lived object
storage credentials. It pages the frozen exact selection through an
execution-lease-fenced broker, receives per-image short-lived GET contracts,
verifies source size/SHA256 and runs the real CleaningAnalysisRuntime locally.
Its output is task-owned metrics evidence only. The control plane re-runs
`metric_issues` with the existing `DurableHashIndex`, verifies the immutable
uploaded review, and commits results into the existing
`selection.sqlite3/clean_results` and MaterialRepository projection.

The legacy user-facing semantics are preserved: a successful scan remains
"awaiting confirmation" until the user chooses suggested removals/keeps and
confirms. The product UI now exposes a preflight-driven Central Worker / Remote
Cleaning Node picker and maps remote execution stages to Chinese runtime text.

Acceptance at code HEAD `b41f784a3765e09a2184453e03e895a1cda0271d`:
- Remote Cleaning Runtime `35324894972`: API / Ubuntu / Windows / Real Chrome success.
- Node Agent Executor `35324894991`: success.
- Central Node Assignment `35324894963`: success.
- Task Runtime Truth `35324895005`: success.
- Portable Deployment `35324894993`: success.
- Remote Material Import `35324894988`: success.
- Remote Training Runtime `35324895079`: success.
- Remote Conversion Runtime `35324894962`: success.

**OPEN / next:** Remote MODEL_CONVERSION Phase 2 — Rockchip RKNN. Prioritize
the user's RK3568 / RK3578 hardware only; do not simultaneously claim TensorRT,
Sophon or Ascend. Add a real `conversion.rknn` effective capability that is
reported only when the node has a verified RKNN conversion SDK/runtime
environment. Frontend and backend must use that same capability truth.


## Current closure — Remote MATERIAL_IMPORT Phase 4 storage_scan CLOSED

Formal `VERSION.txt` remains `42.24.0`.

`MATERIAL_IMPORT + mode=storage_scan + execution_mode=agent` is now a real
cross-machine flow. The product UI exposes an object-storage-directory mode for
enabled OSS/S3/MinIO sources and submits the same durable mode/source/prefix/
recursive/import-format truth consumed by the control plane and Agent.

Long-lived object-store credentials remain control-plane-only. The Agent uses
execution-lease-fenced broker list/read APIs and short-lived GET contracts.
Both the broker and Agent enforce the durable prefix; object reads revalidate
size and ETag and verify SHA256 when available. The Agent continues to use
`YoloImportScanner` for YOLO datasets without central SQLite/NFS access.

Unlike ZIP import, storage-scan review bundles are metadata/annotation evidence
only: source images are not repacked into the review ZIP. After server-confirm
and user confirmation, the local indexer re-stats the original object and
checks size/ETag/SHA256 before committing MaterialRepository and
AnnotationRepository truth. Phase 3 staging GC therefore never treats the
formal source objects as temporary staging.

Frontend/backend task truth is aligned: execution_mode survives refresh, the
unified poll owner is retained, and canonical task status wins over stale stage
text (for example AWAITING_CONFIRMATION cannot still render as reviewing).
The classic app script now has a permanent `node --check` gate after this batch
found and fixed dangling async-function syntax that unit tests had not parsed.

Acceptance at code HEAD `639cded30a6a2fed67275f19450cb70b4e0a9128`:
- Remote Material Import `35316129031`: API / Ubuntu / Windows / Real Chrome success.
- Node Agent Executor `35316128986`: success.
- Central Node Assignment `35316128928`: success.
- Task Runtime Truth `35316128916`: success.
- Portable Deployment `35316129051`: success.
- Remote Training Runtime `35316128920`: success.
- Remote Conversion Runtime `35316129033`: success.

Phase 5 COCO / Pascal VOC is CLOSED above. Do not reopen the generic detection
review path unless a regression is proven. The next control-plane task is
Remote MATERIAL_BATCH/CLEAN Phase 1.

## Current closure — Remote MATERIAL_IMPORT Phase 3 Staging GC CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Remote material input/review objects now have durable, exact-reference lifecycle
governance. Server-confirmed review commit first persists the control-plane
review archive and candidate/annotation truth, then records a cleanup ledger.
Deletion is deliberately deferred until the task/result state is durable, so a
crash between commit and result-state publication cannot destroy the only
retryable remote review object.

The existing local storage Worker heartbeat owns the periodic sweep. It retries
immediately-eligible cleanup for AWAITING_CONFIRMATION tasks and applies a
default seven-day retention to FAILED/CANCELLED/BLOCKED orphan staging. Exact
orphan generation refs are recovered from task-owned upload-state artifacts.
Every delete revalidates task-owned key prefix, source id, size and SHA256.
Changed objects are CONFLICT and are not deleted; transient failures remain
PENDING. Missing objects are idempotently complete.

No prefix list/delete exists in the GC path and formal target material object
keys are never candidates. The reporter reuses WorkerInstance renew hooks with a
five-minute throttle and persisted pagination cursor, so there is no new timer
or competing scheduler.

Acceptance:
- Remote Material Import `35312109805`: API / Ubuntu / Windows success.
- Task Runtime Truth `35312109707`: Ubuntu / Windows success.
- Storage Cache Governance `35312109834`: success.

Phase 4 `storage_scan` is now CLOSED above; do not reopen or reimplement this
broker/list/read path unless a regression is proven. Remaining material-format
work continues with COCO / Pascal VOC.

## Current closure — Remote MATERIAL_IMPORT Phase 2 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The real Agent MATERIAL_IMPORT path now covers both plain-image server ZIP
review and YOLO dataset review. In YOLO mode the Agent reuses the hardened
`YoloImportScanner` against its task-local extracted tree. It parses the
dataset YAML, image/label pairing, external classes, normalized boxes,
confirmed-empty samples and bounded issue evidence without accessing central
SQLite/NFS.

The immutable review ZIP carries candidate metadata/content plus
`yolo/annotations.jsonl`. The control plane re-downloads and verifies that
bundle before accepting it as durable task truth: task/project/generation,
target source/prefix, dataset YAML identity, external classes, candidate
coverage, annotation status, box counts, class IDs and normalized coordinates
are all checked fail-closed.

User confirmation freezes object selection, label mapping, optional label
creation and quality acceptance. The local `storage.import` indexer then
publishes only selected verified image bytes, rechecks object-store size/hash,
maps external class IDs to still-active platform label codes, converts YOLO
coordinates to pixels and writes MaterialRepository plus AnnotationRepository.
Confirmed-empty samples are persisted as formal negative annotation truth;
missing/invalid sidecars cannot erase an existing annotation.

A permanent end-to-end integration now exercises:
Agent-style YOLO review → server commit → explicit label mapping → local object
publication → MaterialRepository → AnnotationRepository, including a positive
sample with two mapped boxes and a confirmed-empty sample. The API contract was
updated to treat Agent YOLO import as supported rather than the old
unimplemented-mode expectation.

Final acceptance:
- Remote Material Import run `35311171823`: API / Ubuntu / Windows success.
- Temporary draft PR #17 was closed without merge.

**OPEN / next:** remote staging-object lifecycle/GC, then Agent storage_scan,
then COCO/VOC format expansion. GC must delete only task/generation-owned
temporary input/review objects that are outside their retention/retry window;
it must never prefix-delete or remove formal target material objects.

## Current closure — Remote MODEL_CONVERSION / ONNX Runtime CLOSED

Formal `VERSION.txt` remains `42.24.0`.

`MODEL_CONVERSION` is now the third real cross-machine Agent task kind. The
closed remote target is ONNX only. Vendor conversions such as TensorRT, RKNN,
Sophon and Ascend remain environment-specific and must not be inferred as
remote-capable from this closure.

The deployment resource model now accepts explicit `mode=agent`. Agent resource
health is derived from the Service Node Registry: the resource is ready only
when at least one fresh enabled Agent has effective `conversion` capability.
Creation rechecks that state and portable staging failures fail closed rather
than silently falling back to a local conversion.

The durable conversion request keeps verified object references, source trace,
portable ONNX params and an Agent execution-mode marker. A dedicated Worker
capability fence prevents the legacy path-bound ConversionHandler from claiming
an Agent conversion while Central Scheduler assignment owns it.

`AgentConversionRunner` is database-free. It verifies model downloads against
size/SHA256 evidence, resolves Python and `deployment_worker.py` locally on the
node, persists ProcessIdentity before running a real subprocess, renews the
execution lease, forwards bounded logs/progress, and kills the exact process
tree when cancellation/fencing/shutdown wins. Runtime startup recovery is
fail-closed; unresolved stale conversion processes make the runner unready and
heartbeat withdraws the conversion capability.

Success requires the local worker to report `status=done`,
`runtime_verified=true`, `validation_status=runtime_verified`, a verified
ONNX manifest, and exactly one non-empty ONNX artifact. The Agent recomputes
output hash/size, uses generation-scoped immutable prepare/PUT/confirm transport,
and enters finalization only after server confirmation.

A further usability gap is closed on the server: after the finalization fence,
the control plane downloads the verified object again, checks size/SHA256, and
commits `deploy/jobs/<task>/artifacts/model.onnx`, `manifest.json`, and
`job.json`. Existing deployment artifact listing/download packaging therefore
continues to use the same local deploy-job truth instead of exposing a second UI
result model.

A real executor race discovered by the conversion tests was also fixed: a
globally supported task kind is no longer enough to call `start_execution`.
The loop now checks that this concrete Agent still has the corresponding
effective capability and a ready runner before acquiring the execution lease.
A stale assignment to an Agent whose runtime became unsafe therefore remains an
assignment/retry problem, not a false RUNNING execution.

Final acceptance:
- Remote Conversion Runtime `35306100598`: control-plane / Ubuntu / Windows success.
- Node Agent Executor `35306100599`: API / Ubuntu / Windows success.
- Central Node Assignment `35306100621`: API / Ubuntu / Windows success.
- Portable Deployment `35306100612`: production API / Ubuntu / Windows success.
- Remote Training Runtime `35306100615`: production API / Ubuntu / Windows success.
- Temporary draft PR #15 was closed without merge.

**OPEN / next:** Remote MATERIAL_IMPORT Runtime. Move large archive/image import
work to a real material-import Agent without granting access to central
MaterialRepository/SQLite/NFS. The Agent should safely unpack/parse, identify
label formats, perform deterministic conversion/basic validation, upload
immutable source/material objects to configured object storage, and let the
control plane commit only server-confirmed metadata/object refs.

## Current closure — Remote TRAINING Runtime CLOSED

Formal `VERSION.txt` remains `42.24.0`.

`TRAINING` is now the second real cross-machine Agent task kind after
`DEPLOYMENT_TEST`. The control plane does not use the old remote-train ZIP
server as execution truth and the Agent never opens central SQLite or requires
shared NFS.

A remote request creates the durable TRAINING task plus an isolated
`TRAINING_PREPARE` task. Preparation freezes the split/snapshot, builds or
restores the verified v3 portable dataset bundle, safely archives it, records
SHA256/size/member-count/snapshot evidence, uploads it to configured
OSS/S3/MinIO and revalidates provider metadata. Explicit remote training cannot
fall back to a local node while this contract is still PREPARING.

Base-model semantics remain strict: a first run may use an allow-listed official
Ultralytics reference; an iterative run must resolve the current/latest
trainable previous version and publish/reuse its verified ModelArtifact object.
Control-plane absolute model paths are not executable Agent inputs.

`AgentTrainingRunner` downloads and verifies the portable bundle/base model,
uses node-local Python plus node-local `train_worker.py`, starts a real
subprocess, renews the execution lease, forwards bounded logs/progress, and
terminates the exact process tree when cancel/fencing/shutdown wins. Process
identity is persisted without execution secrets. Natural worker exit is not
enough to publish success: descendant/process-group cleanup must also be
provable. Cleanup uncertainty fails closed and makes the runner unready.

Agent capability reporting is runtime-safe:
`SUPPORTED_AGENT_EXECUTOR_CAPABILITIES` includes
`deployment-test` and `training`, but `effective_capabilities()` removes
training whenever its runner reports unsafe recovery state. Heartbeat advertises
that effective set, so a node with unresolved stale training processes cannot
claim another training task.

Successful training recomputes local best/last SHA256 and size, requests
generation-scoped immutable upload contracts, uploads and confirms each model,
then publishes a manifest-only training result bundle. The server verifies
result/model evidence before the finalization gate and only then commits the
verified model assets/algorithm-version truth. Old generations cannot publish
current terminal state.

A real production bug discovered by the subprocess tests was fixed:
portable scalar parameters that are absent or explicitly null now use their
defaults rather than propagating `None` into `int()`/numeric conversion.

Final acceptance on the verified implementation:
- Remote Training Runtime `35303815439`: Ubuntu / Windows / API success.
- Node Agent Executor `35303815460`: Ubuntu / Windows / API success.
- Central Node Assignment `35303815499`: Ubuntu / Windows / API success.
- Portable Deployment `35303815438`: Ubuntu / Windows / production API success.
- Temporary draft PR #14 was closed without merge.

**OPEN / next:** Remote MODEL_CONVERSION Runtime. Existing conversion payloads
still carry control-plane path-bound fields such as job_dir/worker_path/python_path.
Refactor conversion to verified model object inputs, node-local tool/SDK/runtime
resolution, execution-lease/process-tree fencing, immutable output upload and
server-confirmed finalization. Do not expose conversion as a remote Agent
capability until its real runner and permanent Windows/Linux gates exist.

## Current closure — Agent-side Real Deployment Runtime CLOSED

Formal `VERSION.txt` remains `42.24.0`.

`node_agent.py` now runs the first real cross-machine task kind:
`DEPLOYMENT_TEST`. The Agent only reports capabilities implemented by its
current executor build; at this closure that is `deployment-test` only.
The single-concurrency executor starts only after the first successful control
plane heartbeat, claims central assignments, obtains the one real execution
lease/generation, and dispatches `AgentDeploymentRunner`.

The deployment runner is database-free and NFS-independent. It verifies object
downloads against durable size/SHA256 evidence, accepts only allow-listed
official model references or verified model objects, resolves Python and runner
paths from the node itself, launches a real subprocess, renews the central
execution lease, forwards bounded logs, and terminates the exact local process
tree when cancellation, lease fencing, or Agent shutdown wins.

Successful output follows the closed hash-bound publication protocol:
local hash/size → prepare → generation-scoped signed PUT → confirm →
begin-finalization → finish. Stale generations never publish a terminal state.
The task-local execution workdir is cleaned after success, failure, cancellation
or fencing.

A permanent-CI gap was also closed: `node_agent.py`,
`node_agent_executor_loop.py`, the single-concurrency tests and entrypoint
integration tests are now included in both relevant workflows.

Latest acceptance:
- Node Agent Executor run `35297453169`: API / Ubuntu / Windows success.
- Portable Deployment run `35297453136`: production API / Ubuntu / Windows success.

**OPEN / next:** Remote TRAINING Runtime. TRAINING is still not executable by
the remote Agent and is deliberately filtered out of reported capabilities.
The next implementation must transport a verified portable dataset/bundle,
run the node-local training runtime, preserve lease/cancel/process/GPU fencing,
return logs/metrics to central task truth, publish verified model artifacts,
and only then pass finalization. Do not use shared SQLite/NFS as a shortcut.

## Current closure — Portable Deployment + Fenced Result Publication CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Deployment test is now the first task kind with a real version-1
`object-storage-v1` portable contract. Durable task truth keeps only object
references and content evidence. Temporary signed transport URLs are minted
just in time and never stored in Scheduler truth.

Remote output publication is execution-fenced. The Agent must compute local
SHA256 and size before requesting `result-upload/prepare`. S3/MinIO and OSS
PUT signatures bind size, SHA256 metadata, content type and no-overwrite
semantics. Actual output keys are scoped by execution generation. The control
plane then verifies the uploaded object through provider `stat()`, requires
matching size and SHA256 metadata, and uses the existing finalization
transaction as the atomic cancellation-vs-commit gate.

Confirmed durable truth lives under
`remote-results/<generation>/upload.json` and
`remote-results/<generation>/result.json`; signed URLs are not persisted.
Portable remote deployment cannot finalize or finish successfully before
confirmation. A successful finish ignores any Agent-provided result_ref and
uses the current generation's confirmed server result.

Validation:
- Portable transport closure run `35292400487`.
- Result publication Agent run `35295427105`.
- Result publication Portable run `35295427110`.
- Central regression run `35295427100`.
All directly relevant API / Ubuntu / Windows jobs passed. Temporary CI PRs
were closed without merge.

**OPEN / next:** implement the real database-free Agent-side deployment runner,
then integrate it into `node_agent.py`. The runner must verify downloads,
use node-local runtime/runner paths, kill the exact local process tree on
cancel/fence, compute output evidence, execute prepare/PUT/confirm, finalize,
finish, and clean the task-local workdir. Real cross-machine deployment test
is not CLOSED until that path is exercised.

## Current closure — Remote Portability Gate + Production Runtime Mount CLOSED

Formal `VERSION.txt` remains `42.24.0`.

`CentralTaskAllocator` now fails closed for `connection_mode=agent`: an Agent
node is ineligible unless the task payload contains an explicit version-1
`remote_execution` contract whose task kind and supported transport match.
Legacy path-bound payloads remain eligible for `local` nodes but are never
implicitly treated as portable. Scheduler truth stores only the allow-listed
version/task_kind/transport metadata; arbitrary credentials, signed URLs and
control-plane paths from the task payload are not copied into assignment truth.

This gate passed Central Node Assignment run `35290891091` and Node Agent
Executor run `35290891208` on API, Ubuntu and Windows.

A separate production integration gap was also closed: `app.py` now mounts
`training_recovery_router(get_project, shared_task_repository,
shared_task_artifacts)` exactly once. That composed router is the single owner
of training recovery, material picker, service nodes, central scheduler and
node executor. `tests/api/test_runtime_router_app_mount.py` uses AST/source
contracts to prevent a missing mount, duplicate mount, or scattered direct
subrouter ownership.

Production mount validation passed Central run `35291195275` and Agent run
`35291195262` on API, Ubuntu and Windows. Temporary validation PRs were
closed without merge.

**OPEN / next:** make one task kind actually portable end-to-end. Deployment
test is the preferred first target because the existing model artifact layer
already uploads verified model artifacts to configured OSS/S3/MinIO. The next
work must provide remote-safe input/output transport and a real Agent-side
runner; no shared SQLite/NFS or control-plane absolute path translation.

## Current closure — HTTP Agent Executor Control Protocol CLOSED

Development branch remains `feature/external-algorithm-publishing`; formal
`VERSION.txt` remains `42.24.0`.

`platform_core/agent_execution.py` now provides the control-plane execution
protocol for centrally assigned remote tasks. Node identity/authentication,
assignment ownership, and execution ownership are deliberately separate:
Node Token authenticates the registered node; Assignment Lease Token authorizes
one start; Execution Lease Token plus `tasks.attempt` generation fences all
heartbeat/log/finalization/finish mutations.

Execution start performs the one real `QUEUED -> RUNNING` transition under
`BEGIN IMMEDIATE`, revalidates the current Node Token hash, enabled/fresh
node state and capability, increments the existing task generation, and
releases the central assignment with `release_reason=execution_started`.
The protocol does not create a second task status model. Cancellation and
finalization continue to use the existing TaskRepository/FencedTaskRepository
truth.

The API exposes claim, start, heartbeat, log append, begin-finalization and
finish under `/api/v63/node-executor/{node_id}`. Remote logs are server-owned
and execution-fenced. A disabled node cannot accept new work but an already
owned execution can still report/finish, preventing a desired-state change
from needlessly wedging the task until lease expiry. Missing task payloads
cannot transition a task to RUNNING. Token rotation is rechecked inside the
start transaction, closing the pre-authentication rotation race.

Permanent workflow `.github/workflows/node-agent-executor.yml` passed API,
Ubuntu 24.04 and Windows latest in validation run `35288805083`. Tests cover
duplicate start, invalid assignment token, cross-node execution use, disable
semantics, cancellation precedence, finalization, log fencing/size bounds,
expired-generation takeover, Node Token rotation race, missing payload,
structured generation validation, VERSION guard and source guards.

**OPEN / next:** Agent-side Remote Execution Runtime + Object Storage
Transport. `node_agent.py` does not yet consume this executor protocol and
run a remote task handler, so real cross-machine training/material execution
is NOT CLOSED. The Agent client must not open control-plane SQLite or require
shared NFS; large task inputs/results must use object storage or an explicit
artifact transport. It must kill its local process tree when execution fencing
or cancellation wins.

Detailed handoff: `docs/NODE_CONTROL_PLANE_V42_25.md`.

## Current closure — Service Node Control Plane + Central Assignment CLOSED

Current development branch: `feature/external-algorithm-publishing`. Formal
`VERSION.txt` remains `42.24.0`. Older branch-state sections later in this
file are historical snapshots; live branch/HEAD must always be re-read before
editing.

Service-node control plane is implemented through
`platform_core/service_nodes.py`, `platform_core/node_agent_runtime.py`, and
`node_agent.py`. The management UI is implemented by
`static/modules/service-node-runtime.js`. Node identity, heartbeat,
allowed/reported/effective capabilities, CPU/RAM/disk/GPU/Torch/CUDA/process
telemetry and one-time Agent token handling are now real backend/frontend
contracts, not simulated UI state.

Central durable task-to-node assignment is implemented in
`platform_core/task_node_assignments.py` and composed through the existing
single additive runtime-router integration point. An active assignment is
durable control-plane truth and is protected by a partial unique index.
`AssignmentAwareFencedTaskRepository` prevents legacy Workers from
self-claiming a centrally assigned queued task. Allocation and claim paths use
`BEGIN IMMEDIATE`; schema scripts are initialized before the scheduling
transaction so SQLite implicit commit cannot break allocator atomicity.

Permanent Central Node Assignment workflow run `35288111906` passed API,
Ubuntu 24.04, and Windows latest contracts. It covers node eligibility,
training node/GPU selection, execution snapshot persistence, MATERIAL_BATCH
capability mapping, concurrent single-assignment fencing, claim/reclaim,
release generation, legacy Worker fencing, API contracts, VERSION guard and
`git diff --check`.

**OPEN / next:** HTTP Agent Executor Protocol. A remote Agent must not open the
control-plane SQLite or depend on NFS in order to claim work. The next protocol
must authenticate the node, claim its assignment, atomically acquire the one
real TaskRepository execution lease/generation on the control plane, exchange
execution inputs/artifact references over HTTP/object storage, and return
progress/log/result/cancel/failure updates to the same durable task truth.

Detailed handoff: `docs/NODE_CONTROL_PLANE_V42_25.md`.

## Current closure — Task Runtime Truth v2 CLOSED

Product implementation: `cc8981888bc4b27ee9594290455bd08e61713c9d`.
Permanent Task Runtime Truth gate expansion: `38aa8f736ee11ae419042fa2e90127bd45937ac5`.
Formal `VERSION.txt` remains `42.24.0`.

The shared durable-task frontend contract now covers training, AI annotation,
material batches, storage scan/import, server material import, resource discovery,
video processing, and deployment tests. For those durable payloads, `task_status`
wins over compatibility `status`, `phase` wins over `task_stage` / `stage`, and
`progress_percent` wins over legacy `progress`; the browser does not derive a
new durable percentage from domain counters.

A numeric `resource_queue_position` is displayed as “队列第 N 位” only when the
backend also returns `resource_queue_position_exact === true`. Candidate order,
priority order, or an inexact numeric position is never presented as an exact
Worker/hardware queue position. Domain-specific diagnostics such as scanned file
counts, extracted bytes, current paths, and wait reasons remain visible.

The permanent `Task Runtime Truth` workflow runs the expanded backend/frontend
contract on both Ubuntu and Windows. The closure run passed both OS jobs, and the
existing Frontend Runtime workflow passed frontend unit/owner guards plus Real
Chrome runtime regressions. The existing cleaning frontend queue/progress truth
closure remains authoritative and was not reopened by this batch.

Detailed handoff: `docs/CODEX_HANDOFF_2026-09-16_TASK_RUNTIME_TRUTH_V2.md`.


## Product closure — Training Bundle Snapshot Cache CLOSED

Training Bundle Snapshot Cache is implemented at product commit `b0868a7409ec019365e74355b46f21643d0da2a3`.
It reuses only a project-scoped portable bundle whose Snapshot ID is derived
from the durable material index and whose previous run reached final dataset
verification. The cache lives under
`<data_dir>/cache/training-bundles/<project_id>/<snapshot_id>`; entries are not
shared across projects.

The fast path is intentionally ahead of source materialization. When every
selected material already has a locked SHA256 and positive indexed size, the
Worker rebuilds the deterministic split manifest/Snapshot from durable material
and annotation truth first. If a matching cache entry exists, source files are
not reread merely to rediscover the same hashes. A miss keeps the previous
behavior: every selected source is materialized/verified, the manifest and
Snapshot are rebuilt from those verified bytes, and the task-local portable
bundle is constructed normally.

Cache entries are published only during successful training finalization, after
the existing `verify_portable_dataset()` full image/label SHA256 gate has passed
and after the official algorithm version has been attached successfully. An
incomplete/failed training run therefore cannot seed this cache. Cache
publication failure is recorded as optimization evidence and cannot turn an
otherwise verified model result into a failed training result. Cache-hit
admission re-hashes the small Snapshot, label and data-YAML files while large
images use their locked size/manifest evidence; finalization still performs the
full image SHA256 gate on every run.

Each training task still receives its own `work/bundle`; the trainer never runs
directly inside the shared cache. Cache schema v3 restores trainer-writable image
inputs with `shutil.copy2()` rather than writable hard-links, so Ultralytics or
other trainer-side mutations cannot modify the persistent cache inode. Legacy
schema-v2 cache entries are fenced because their prior hard-link isolation cannot
be assumed clean. The finalization gate still re-hashes the task bundle on every
run before accepting the model artifact.

Permanent contracts cover project isolation, cache marker/manifest identity,
missing-member rejection, verified-file-count fencing, hard-link reuse,
cross-device copy fallback, indexed hash/size eligibility, and the production
TrainingHandler wiring. Formal `VERSION.txt` remains `42.24.0`; no tag, release
or `main` merge is part of this closure. A800 / genuine 10k timing remains
unverified and no performance percentage is claimed.

## 1. Branch / release state

```text
branch:                                  refactor/frontend-runtime-stabilization
local scoped product HEAD:               de0c37dd93ecc3396935bf9ad6159568d77a03da
remote HEAD last verified:               ca8d80cba3cbfa1282e4ff4d9b0a1c341cbd73a4
ahead / behind last verified:            2 / 0
push status:                             PENDING — GitHub 443 unavailable during Phase 1A handoff
latest remotely accepted state:          ca8d80cba3cbfa1282e4ff4d9b0a1c341cbd73a4
latest local scoped product implementation: de0c37d (GPU Runtime Truth Phase 1A)
latest full-suite acceptance:            ca8d80cba3cbfa1282e4ff4d9b0a1c341cbd73a4
formal VERSION.txt:                      42.24.0
visible frontend version:                v42.24.0
internal UI build metadata:              42.25.0-dev
app.js cache:                            42.25.99
main.mjs cache:                          42.25.99
NavigationStability:                     422512
UI state runtime:                        422500
PollRegistry:                            422518
TrainingDraftRuntime:                    422516
TrainingLabelRuntime:                    422513
TrainingSubmitRuntime:                   training-submit-422504
TrainingTaskRuntime:                     training-task-runtime-422522
AutoLabelPollRuntime:                    422501
```

The latest remotely accepted branch state is `ca8d80cba3cbfa1282e4ff4d9b0a1c341cbd73a4`. GPU Runtime Truth Phase 1A is committed locally at `de0c37dd93ecc3396935bf9ad6159568d77a03da`; push and GitHub CI remain pending because GitHub port 443 was unreachable during handoff. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## Product status — GPU Runtime Truth Phase 1A

```text
GPU Runtime Truth Phase 1A
IMPLEMENTED + BASIC TESTS
REAL MULTI-NODE NVIDIA ACCEPTANCE PENDING
```

Implementation commit: `de0c37dd93ecc3396935bf9ad6159568d77a03da`.
This phase extends the existing Worker Runtime and GPU resource owner; it does
not add a second Worker registry, heartbeat, task queue, Scheduler, or GPU
assignment path.

Node identity resolves in this order: explicit `MC_NODE_ID`; otherwise a
hashed node-local Windows MachineGuid or Linux machine-id; when those are not
available, a generated identity persisted under `MC_NODE_STATE_DIR` or the
OS-local application state directory. Hostname is display metadata only.
Node identity is never written to shared `MC_TRAIN_DATA_DIR`. Containers that
need identity across replacement should set `MC_NODE_ID` or mount a node-local
`MC_NODE_STATE_DIR`.

`worker_instances` now has an additive `node_id` column. New Worker leases
write the resolved node through the existing `WorkerInstanceService.acquire()`
and existing heartbeat. `GET /api/v62/workers` returns `node_id` with the
existing sanitized runtime fields. Existing rows migrate to
`legacy-unscoped`; no existing lease secret becomes public.

The existing `gpu_inventory` and `gpu_samples` tables are migrated
transactionally from global `uuid/gpu_index` rows to node-scoped
`(node_id, gpu_uuid)` identity and `physical_index`. Inventory now records
`model`, `total_bytes`, `free_bytes`, `utilization`, `sampled_at`,
`telemetry_source`, `telemetry_available`, and `mig_mode`. Old rows remain
recoverable as `legacy-unscoped` until a real Worker observes that UUID and
adopts it for its Node. The former global
`UPDATE gpu_inventory SET healthy=0` refresh is retired: a Node only upserts
its own observations, and missing reports become stale through `sampled_at`.

`worker_gpu_visibility` records the many-to-many runtime relationship
`worker_id + node_id + gpu_uuid + logical_cuda_index + observed_at`.
`CUDA_VISIBLE_DEVICES` order is applied only to the Worker logical index;
physical index and GPU UUID remain separate. NVML is preferred, nvidia-smi is
the second telemetry source, and Torch fallback contributes identity only:
it never fabricates memory or utilization. Hardware health is not inferred;
the public `health_status` remains `unknown` while
`telemetry_available`, `metrics_fresh`, and `mig_mode` carry the proven facts.

`GET /api/v62/gpu-runtime` is a read-only projection returning `nodes`,
`workers`, `gpus`, `worker_gpu_visibility`, and telemetry counts. It neither
samples hardware nor writes task/Scheduler state. Reservations are deliberately
not exposed as node truth because `gpu_reservations` is not node-scoped yet.
The existing local `/api/v62/gpu-resources` compatibility endpoint remains.

Minimum verification passed on Windows: focused Worker/GPU schema, migration,
Node isolation, visibility reorder, stale telemetry, Torch identity-only,
no-GPU behavior, read-only API, Scheduler and recovery contracts `22/22`; the
affected Python modules compiled successfully. Real multi-Node NVIDIA, A800,
MIG, and container/NFS deployment remain **NOT VERIFIED**.

Phase 1B explicitly retains: node-scoping `gpu_reservations`, resolving the
global `worker_slot UNIQUE` conflict, binding assignments to
`node_id + gpu_uuid + physical_index + logical_cuda_index`, Worker/server
binding, remote routing, and GPU automatic scheduling. None of those claims
are closed by Phase 1A.

## Product closure — Training Queue Readiness Truth CLOSED

Training task queue readiness is closed at scoped product implementation
`bfe9f7d`, with remote acceptance recorded at
`92b8275e5a75167b040738d21a153f487f799b9b`. The earlier local-only/pending-push
state is resolved: local and remote are synchronized at `0 / 0`, and all four
directly related workflows passed. This batch consumes the already-closed Worker
Runtime Truth and the existing durable TaskRepository/Scheduler state; it does
not add another queue,
Worker registry, Scheduler, durable task status, or frontend polling owner.

For a local durable `TRAINING` task whose persisted status is `QUEUED`, the GET
projection now evaluates the current `worker_instances` lease snapshot. No
online Worker returns `WAITING_RESOURCE / 当前没有在线 Worker`; online Workers
without the `TRAINING` task kind return `当前没有可执行训练任务的 Worker`; online
Training Workers missing any required capability return
`当前在线 Training Worker 不支持 <capability>`. A provably compatible Worker with
an existing Scheduler/GPU admission wait preserves the authoritative
`resource_wait_reason`. Otherwise the public state remains `QUEUED`. The read
path never writes `tasks.status`, `stage`, or wait reasons.

The current compatible local pool is deliberately limited to durable Worker
truth that is already proven: online lease, registered `TRAINING` task kind,
and a capability superset of the task's `required_capabilities`. The requested
`resource_key` remains the resource boundary. `training:remote:<server_id>` is
not matched to an arbitrary local Training Worker because current Worker truth
does not store server binding or resource affinity and the current handler
rejects non-local targets. Remote tasks therefore expose
`指定远程服务器的 Worker 路由尚未建立` until a later Worker/server-binding batch.

`resource_queue_position` remains the existing resource-scoped numeric value;
it is not represented as a universally exact Scheduler rank. The backend now
returns `resource_queue_position_exact`. Exactness is conservative and is only
proved for a single compatible CPU Worker when its current claimable queue has
no cross-resource candidate and the Scheduler scan position equals the
resource-scoped position. GPU auto/concrete GPU, multiple compatible Workers,
cross-resource competition, and remote routing remain non-exact. The training
UI displays `队列第 N 位` only when this proof flag is true; otherwise it shows
the backend pool label plus `排队中` without a fabricated number.

Backend-owned display metadata is:

```text
resource_pool_key
resource_pool_label
resource_queue_position_exact

training:cpu      -> CPU
training:auto     -> GPU 自动
training:cuda:N   -> GPU N
training:remote:* -> 指定远程服务器
```

The training UI now renders public `waiting` as `等待资源`, prioritizes the
server-provided wait reason, and never parses `resource_key` to infer resource
availability. Worker recovery and queue changes continue to arrive through the
already-closed page-scoped two-second PollRegistry one-shot; no new timer or
request endpoint was added. The jobs-list path reuses one Worker runtime and
queued-candidate snapshot for the response rather than issuing those full
queries once per visible task.

Core files:

```text
app.py
platform_core/task_runtime/__init__.py
platform_core/task_runtime/public.py
platform_core/task_runtime/repository.py
static/modules/training-task-runtime.js
static/main.mjs
static/index.html
tests/unit/task_runtime/test_public_projection.py
tests/api/test_training_unified_task_overlay.py
tests/frontend/training-task-runtime.test.mjs
docs/superpowers/specs/2026-09-14-training-queue-resource-truth-design.md
docs/superpowers/plans/2026-09-14-training-queue-resource-truth.md
```

Minimum verification passed: focused backend queue/Worker/admission contracts
`13/13`; focused TrainingTaskRuntime rendering and existing list-refresh
contracts `12/12`; affected Python compilation and JavaScript syntax checks.
The first backend run was blocked before test setup by the known Windows global
Temp permission issue; the identical focused tests passed with a worktree-local
temporary directory, which was removed afterward.

This batch did **not** implement GPU Runtime Truth, GPU automatic scheduling,
GPU memory/affinity changes, Worker/server binding, remote affinity, designated
GPU/machine selection, Scheduler claim changes, Worker registration schema
changes, ETA, pause/resume changes, SSE, or a new polling owner. Linux/A800,
real multi-Worker concurrency, and remote-server routing remain **NOT
VERIFIED**. Formal `VERSION.txt` remains `42.24.0`.

## Product closure — Worker Runtime Truth CLOSED

Worker Runtime Truth is complete at implementation HEAD `a5acc6bf9b3de3bab0bd2231a40c9fe8436f1816`. The existing `worker_instances` lease row now durably records `worker_id`, `hostname`, `pid`, the running Worker's resolved `build_id`, actually registered roles, registered task kinds, registered capabilities, `started_at`, `heartbeat_at`, and `expires_at`. SQLite migration is additive and gives existing rows safe defaults; it does not rebuild or discard the table.

Durable truth remains single-owner: `task_worker.py` obtains handlers and capabilities from the existing `worker_registry`, then writes that actual registration into `worker_instances` through `WorkerInstanceService.acquire()`. The existing lease renewal remains the only heartbeat. `WorkerInstanceService.list_runtime()` derives `online` only when a valid heartbeat exists and `expires_at` is later than the query's UTC time; it never uses PID liveness to judge remote Worker availability. `GET /api/v62/workers` returns the sanitized durable runtime list and does not expose `owner_token` or `instance_key`.

Modified files:

```text
app.py
task_worker.py
platform_core/worker_registry.py
platform_core/task_runtime/repository.py
platform_core/task_runtime/worker_instances.py
tests/unit/task_runtime/test_worker_runtime_truth.py
tests/unit/task_runtime/test_worker_registry.py
tests/api/test_worker_runtime_truth.py
docs/superpowers/specs/2026-09-14-worker-runtime-truth-design.md
docs/superpowers/plans/2026-09-14-worker-runtime-truth.md
docs/CODEX_CURRENT_STATE.md
```

Minimum verification passed: affected Python modules compiled successfully; focused Worker Runtime Truth, actual registry metadata, read-only API, and existing Worker lease connection-lifecycle tests passed `7/7`. Linux/A800 deployment and real distributed Worker heartbeat behavior were not executed in this Windows development environment and remain **NOT VERIFIED**. Formal `VERSION.txt` remains `42.24.0`.

> Build claim fencing、Worker readiness admission、training 503 拦截和前端 Worker readiness 尚未实现，留待后续独立批次。

### CI follow-up — Material Annotation Atomicity

The `Material Annotation Atomicity` failure at `cbc9d5c9e4678160d2acf18124b8c06b1a104702` was an existing test-orchestration mismatch, not a Worker Runtime Truth regression. `f43631e16a51167cf75bb8e2ec545566f226609f` had already moved cleaning execution out of the Web process into the durable `MATERIAL_BATCH` Worker, while `test_upload_to_selected_storage_source_enters_unified_pool` still waited for `awaiting_confirmation` without running a materials Worker. The workflow's previous successful run predated that durable-cleaning migration; the Worker Runtime Truth `app.py` change merely caused this workflow to run again and expose the stale assumption.

The test now drives the existing real `FencedTaskRepository` / `Scheduler` materials registration before asserting the same terminal business truth. No production cleaning, storage, training, Worker Runtime Truth, workflow timeout, or application behavior changed. Focused verification passed the formerly failing storage-upload test and the existing real fenced material-worker regression (`2/2`). GitHub Actions Run `34825337016` passed on fix commit `6abb63a1cb1de2da209879974bfca6c70d0a0c45`.

## Product closure — Training task status/progress auto-refresh CLOSED

Training task list auto-refresh is complete at implementation HEAD `753416e`. The visible list continues to use the existing batch truth endpoint `GET /api/projects/{project_id}/jobs`; `enrich_job_runtime()` projects the persisted training job and metrics together with durable `TaskRepository` status, progress, queue, Worker, epoch, elapsed-time, and terminal truth. The frontend does not synthesize status, percentage, Epoch, or elapsed time.

`TrainingTaskRuntime` remains the focused request/state/table-patch path and updates only the task table plus tab counts. `PollRegistry` remains the only training timer owner: `training-jobs` is now a page-scoped 2-second one-shot for `queued`, `waiting`, `pending`, or `running`. Every completed request re-arms from the latest backend response; a transient request failure retries only while the last-known state is still dynamic. Paused tasks remain in the activity list but paused-only state has no pending timer. `done`, `finished`, `completed`, `failed`, `stopped`, `cancelled`, and `canceled` do not re-arm. Leaving `训练任务` clears the timer, `检测台` is no longer an owner, and re-entering restores polling from freshly loaded state. Resume keeps the existing immediate forced refresh, after which PollRegistry restores the one-shot only if the returned state is dynamic.

Core files:

```text
static/modules/poll-registry.js
static/main.mjs
tests/frontend/poll-registry.test.mjs
tests/frontend/training-task-runtime.test.mjs
docs/superpowers/specs/2026-09-14-training-task-auto-refresh-design.md
docs/superpowers/plans/2026-09-14-training-task-auto-refresh.md
docs/CODEX_CURRENT_STATE.md
```

Minimum verification passed: focused PollRegistry and TrainingTaskRuntime frontend contracts `22/22`; JavaScript syntax checks for PollRegistry, TrainingTaskRuntime, and `main.mjs`; existing durable training overlay API regression `2/2`. The first API attempt was blocked before test setup by the known Windows global Temp permission issue; the same test passed using a dedicated worktree-local pytest temp directory, which was removed afterward. Real Chrome and Linux/A800 execution were not run and remain **NOT VERIFIED**.

This batch did not implement GPU Runtime Truth or scheduling, Worker readiness admission, pause/resume feature changes, machine selection, ETA redesign, training-detail refactoring, deployment-center changes, creation-modal changes, SSE, or backend training changes. Formal `VERSION.txt` remains `42.24.0`.

### CI follow-up — Browser navigation training polling guard

The browser navigation guard is synchronized with the current training polling lifecycle. In `delayed request from previous page cannot jump back over the current page`, the initial training `/jobs` request is intentionally held before any dynamic task truth exists, so the correct PollRegistry state is no `training-jobs` timer. The test no longer expects the removed `检测台` owner or unconditional polling; it still verifies that completing the stale training request cannot navigate away from the current dataset page. This follow-up changed only `tests/browser/navigation-stability.spec.mjs`; no product business code or workflow changed.

Focused Playwright verification passed `1/1`. GitHub Actions Run `34830800955` completed successfully, including `browser-navigation` success, on guard commit `23e53363ec9a1a94143ecc25d052f56c66cc242a`.

## Product closure — Deployment-test durable queue/progress truth CLOSED

The deployment-test business surface now preserves the same durable task truth as the unified v62 task API. Previously the v61 compatibility projection flattened a resource-waiting durable task back to persisted `QUEUED`, dropped queue/resource/worker metadata, and the final `benchPredictOne` loop only considered `QUEUED / RUNNING / CANCEL_REQUESTED` active. That combination could make a real `WAITING_RESOURCE` deployment test appear terminal or fail without showing why it was waiting.

Closed semantics:

```text
v61 business projection: delegates durable task fields to task_to_public()
compatibility aliases: id / progress / stage / result remain for the existing deployment surface
WAITING_RESOURCE: remains active and visible instead of being flattened to QUEUED
queue truth: resource_queue_position + resource_wait_reason are server-derived and visible
worker/progress truth: worker_id / phase / progress_percent come from durable public truth
active polling: after v61 creation, benchPredictOne reads /api/v62/projects/{project_id}/tasks/{task_id} while the task is active
terminal success: v61 is read once after SUCCEEDED to obtain deployment-specific result payload
frontend projection: PlatformCore.deployment.deploymentTaskView reuses taskPoller active/progress semantics
queue order / resource admission / worker claim / progress generation / process fencing: unchanged
```

Permanent guards include `tests/api/test_deployment_test_runtime.py`, `tests/frontend/deployment-runtime-source.test.mjs`, `tests/frontend/deployment-task-view.test.mjs`, `tests/unit/task_runtime/test_public_projection.py`, and `tests/unit/test_deployment_inference_process_fencing.py`. Release Regression now permanently runs the deployment business-projection contract and is triggered by the deployment task view/wiring guards. The frontend does not invent queue order or percentage; it only renders unified durable truth.

Evidence:

```text
valid RED head:             5748a89155e653a49c8a8c743cdd3de7a9fa67cf
valid RED run:              34794353496 (backend v61 QUEUED vs v62 WAITING_RESOURCE; final frontend unified-truth wiring RED)
focused/full GREEN run:     34794490531 PASS (API + frontend + public projection + deployment fencing + full frontend unit)
product commit:             0b800a54ae64507314a5f9199734759250691cb6
formal accepted clean HEAD: 1c3fa7f2b5cb826c0998f249637241a59134f053
Release Regression:         34794630826 PASS
Navigation Action Fencing:  34794630808 PASS (Real Chrome PASS)
Frontend Runtime:           34794630837 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

All temporary deployment RED/migration helpers and workflows were physically removed before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Historical sequencing note: at this closure point, storage import polling ownership was recorded as the subsequent batch. That statement is retained only as history and is not a current work instruction.

## Product closure — Cleaning frontend queue/progress truth CLOSED

The final cleaning tab now subscribes to the durable v47 cleaning projection instead of flattening server truth into a generic local row. The backend already exposed `status_text`, `progress`, `processed_images`, `total_images`, `flagged_images`, `resource_queue_position`, `resource_wait_reason`, and worker identity; this batch makes the final visible clean-tab owner preserve those values through both initial rendering and managed refresh.

Closed semantics:

```text
status text: consume server status_text; WAITING_RESOURCE compatibility projection remains “等待资源” instead of being flattened to “排队中”
queue metadata: show real resource_queue_position + resource_wait_reason when present
progress: use server progress / processed_images / total_images only; no browser-simulated percentage
worker metadata: running rows may show the real worker_id supplied by the server
polling owner: PollRegistry owns clean-tasks-v47 as a page/tab-scoped 2200 ms one-shot
refresh owner: refreshCleanOps427Delta refreshes only the cleaning task list and patches clean rows
terminal truth: awaiting_confirmation is terminal for list polling; the clean timer is not re-armed
navigation/tab change: PollRegistry clears the clean timer; switching back to AI annotation also clears it immediately
legacy recursive setTimeout(renderOps427, 2200): retired
backend queue order / claim / progress generation / worker execution: unchanged
```

`static/modules/cleaning.js` now owns the pure `cleanTaskView()` / `isActiveCleanTask()` projection. `static/main.mjs` exposes those helpers through `PlatformCore.cleaning`. `static/modules/poll-registry.js` owns `clean-tasks-v47`, and the final v427 clean branch in `static/app.js` consumes that view-model. The v47 public compatibility contract permanently requires the queue metadata fields to exist; their values remain dynamic server truth (for example, an immediately queued task may legitimately report position `1`).

Permanent guards:

```text
tests/frontend/clean-task-view.test.mjs
  - waiting-resource status/queue/progress truth
  - running worker/progress truth
  - final app.js wiring consumes cleanTaskView + PollRegistry
  - retired direct recursive clean-list timer cannot return

tests/frontend/poll-registry.test.mjs
  - clean-tasks-v47 one-shot lifecycle
  - re-arm only while active
  - stop at awaiting_confirmation
  - clear on navigation

tests/api/test_clean_unified_execution_truth.py
  - v47 public queue metadata fields are permanent
  - dynamic queue position is accepted as server truth, never forced to a frontend assumption
```

Evidence:

```text
valid RED commit:           cf3f2c4fec639903435379b3419dbaadad82c949
valid RED run:              34793075909 (245 frontend tests: 242 PASS; exactly 3 intended cleaning truth assertions RED)
focused/full GREEN run:     34793282831 PASS (focused cleaning contracts + full frontend unit + wiring guard)
product commit:             9f6f329393018623807cb4fea04707f3b5350676
formal accepted clean HEAD: 736b2acdbf2560be657011035de173cde67517d0
Release Regression:         34793457861 PASS
Navigation Action Fencing:  34793457872 PASS (Real Chrome PASS)
Frontend Runtime:           34793457920 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

The temporary frontend migration helper/workflow were physically deleted before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Deployment-test durable queue/progress truth is CLOSED. The storage-import polling work that followed this historical closure is no longer a current instruction. Genuine 10,000-image processing acceptance remains explicitly deferred.

## Product closure — Cleaning durable execution truth CLOSED

The active v47 manual-clean and v55 upload-batch clean entry points now publish one durable `MATERIAL_BATCH/CLEAN` task into the shared `TaskRepository`. The Web/API process no longer owns cleaning execution through legacy daemon threads, and Web startup no longer resurrects those retired workers. Real execution is owned by the registered `materials` worker through `FencedTaskRepository` / `Scheduler` truth.

Closed semantics:

```text
manual v47 create -> prepare + publish one MATERIAL_BATCH/CLEAN durable task
v55 upload-batch decision -> the deterministic clean_task_id points to that same durable task truth
real execution -> materials Scheduler / fenced WorkerContext, never Web daemon execution
prepare -> publish crash window -> reuse the already-frozen semantic request without treating its freeze-time repository_revision as a new user intent
FAILED retry -> same task id is re-queued through TaskRepository retry; no duplicate task identity
successful scan awaiting confirmation -> durable task remains SUCCEEDED/succeeded; v47 compatibility alone projects awaiting_confirmation/review
corrupt image with corrupt_check -> successful flagged cleaning finding for review
source content changed after indexing -> remains SOURCE_CONTENT_CHANGED storage-integrity failure, not disguised as image corruption
```

A real-worker defect was also closed: `MaterialBatchHandler` had called a private artifact validation method that does not exist on the real `FencedArtifactStore`, causing Scheduler execution to fail before processing any material. The handler now validates `project_id` as a safe single path component while preserving fenced artifact access. Corrupt findings are excluded from the hash/dedup index unless real `sha256` and `dhash` metrics exist.

Permanent guards include `tests/api/test_clean_unified_execution_truth.py`, `tests/api/test_upload_clean_flow.py`, `tests/unit/test_material_batch_public_truth.py`, and the Release Regression path/test scope. The final guard explicitly proves that reading the v47 compatibility result may show `awaiting_confirmation / review` while the underlying durable record remains `SUCCEEDED / succeeded`.

Evidence:

```text
valid RED commit:           3f41cdae0d4234bf5171f2aa80111513c223407c
valid RED run:              34790397474 (intended durable-clean execution assertions RED)
focused durable migration:  34792422835 PASS (4 durable contracts + 32 upload-clean regressions)
product commit:             f43631e16a51167cf75bb8e2ec545566f226609f
formal accepted clean HEAD: 3931a9a2d529845f9e698b22f62fe950a7a8b42f
Release Regression:         34792673327 PASS
Navigation Action Fencing:  34792673293 PASS (Real Chrome PASS)
Frontend Runtime:           34792673296 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

All one-shot cleaning migration/diagnostic helpers and workflows were physically removed before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Historical sequencing note: cleaning frontend queue/progress truth was subsequently closed, followed by the storage-import and deployment-test queue/progress audits. This is historical context, not current scope.

## Product closure — Plain image upload whole-task progress truth CLOSED

The final live ordinary-image upload owner is the storage61 `doUploadImages426` path posting to `/api/projects/{project_id}/images`. The endpoint is synchronous HTTP, but after browser request bytes are sent the server still performs temporary-file handling, image validation, selected-storage object write, SHA256 calculation and material record commit. Therefore browser `xhr.upload` byte completion is not whole-task completion.

Closed semantics:

```text
browser byte transfer: 0% -> 85%
byte transfer complete: hold at 85%, show “文件已上传，正在服务器入库”
server-side synchronous commit: no fabricated percentage animation
successful HTTP completion after material commit: 100%, show “服务器入库完成”
network/non-2xx failure: never claims terminal 100%
```

This batch deliberately does **not** invent a durable background task, fake queue, or fake server progress for a synchronous endpoint. Terminal 100% is fenced to the authoritative successful HTTP completion. Permanent behavior guard: `tests/frontend/image-upload-overall-progress.test.mjs`; Release Regression includes that test in its permanent path scope.

Evidence:

```text
valid RED commit:          03be0050644af80709bddb97321f1a4ec0b1528c
valid RED run:             34788264443 (237 existing tests PASS; 2 intended new assertions RED)
focused migration/GREEN:   34788320142 PASS
product commit:            259d76d753993f2dd10e1963ee1a9a13887209ad
accepted clean code point: bae90eae4b3768d365d20344c1f2db9a75795ac8
Release Regression:        34788383779 PASS
Navigation Action Fencing: 34788383742 PASS (Real Chrome PASS)
Frontend Runtime:          34788383772 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:        42.24.0 unchanged
```

The one-shot product migration workflow was removed in the product commit. No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

## Product closure — Video resource queue truth CLOSED

The live v424 video task page already reads `/api/v33/projects/{project_id}/video-tasks`, whose public projection is backed by the shared durable `TaskRepository`. `task_to_public()` dynamically exposes resource-scoped `resource_queue_position` / `resource_wait_reason`; a durable queued task in the `resource_waiting` phase is publicly projected as `WAITING_RESOURCE`. The frontend previously dropped that queue metadata and also failed to classify `WAITING_RESOURCE` as an active video task, so a genuinely resource-waiting task could lose timely managed polling and never show its real queue position/reason.

Closed semantics:

```text
QUEUED: remains active under PollRegistry and shows real resource_queue_position when available
WAITING_RESOURCE: remains active, shows “等待资源”, real queue position and resource wait reason
initial render + delta polling: both use the same v424 row projection and preserve runtimeText
progress: continues to come from durable server/worker truth; no frontend progress simulation
queue ordering / claim / queue_rank / resource fencing: unchanged
cancel / stale-worker / publish fencing: unchanged
```

The fix is intentionally narrow. `static/modules/video-tasks.js` now projects the existing durable queue metadata into `runtimeText` and treats public `WAITING_RESOURCE` as active; the final v424 `videoTaskRow424()` renders that view-model text. `PollRegistry` remains the sole video polling lifecycle owner. Permanent behavior guard: `tests/frontend/video-tasks.test.mjs`, which executes the real final row renderer and verifies both queued and waiting-resource behavior.

Evidence:

```text
final permanent RED commit: 32284a8972faec46775144b8c47406e67edee014
valid RED run:              34789541200 (242 total; 239 PASS; only 3 intended video truth assertions RED)
focused/full GREEN run:     34789628840 PASS
product/self-cleanup:       c0fee2b7c8dfbf03481cbc6dfb1019f922293576
formal clean HEAD:          cb81ca39016aea0fc53ed52090f0b0199d39109a
Release Regression:         34789701814 PASS
Navigation Action Fencing:  34789703315 PASS (Real Chrome PASS)
Frontend Runtime:           34789704610 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP processing acceptance was performed. One-shot product/gate migration assets were physically deleted before formal gate acceptance.

## Product closure — AI annotation polling queue metadata truth CLOSED

The durable v60 AI annotation backend/public projection already exposes real `resource_queue_position` and `resource_wait_reason`, and `annotationTaskView()` already turns that truth into `runtimeText`. Initial page rendering consumed `runtimeText`, but `AutoLabelPollRuntime` used a separate row renderer during polling refresh and omitted it. Result: a task could initially show `资源队列第 N 位` / resource wait reason and then lose that truthful metadata after the first managed poll refresh even though durable truth had not changed.

Closed semantics:

```text
initial render: durable status + progress + runtimeText
managed polling refresh: the same durable status + progress + runtimeText
QUEUED / WAITING_RESOURCE: resource queue position remains visible after every refresh
resource wait reason: remains visible when projected by annotationTaskView
no frontend queue simulation, no claim/order/resource-fencing changes
```

The fix is intentionally narrow: `static/modules/auto-label-poll-runtime.js` now renders existing `view.runtimeText` beside the status pill. No backend queue ordering, task claim, execution fencing, polling cadence, or progress semantics changed. Permanent behavior guard lives in `tests/frontend/auto-label-poll-runtime.test.mjs`; Release Regression path scope now includes both the polling runtime and its guard.

Evidence:

```text
valid RED commit:          186005b428f361e88553555b3a86013d206f11b3
valid RED run:             34788748122 (239 existing tests PASS; 1 intended queue-metadata assertion RED)
product commit:            ddb1168a8f3457fef3d875ceec79e618b75acee9
accepted clean code point: 2bc6f72fddd878a7e2d4802c5affd3d640f807e7
Release Regression:        34788824842 PASS
Navigation Action Fencing: 34788824910 PASS (Real Chrome PASS)
Frontend Runtime:          34788824849 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:        42.24.0 unchanged
```

No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

## 2. Current priority

```text
TECH-DEBT CLEANUP PAUSED BY USER REQUEST
→ Worker Runtime Truth CLOSED
→ Training Task Status / Progress Auto-Refresh CLOSED
→ Training Queue Readiness Truth CLOSED
  product implementation: bfe9f7d
  remote acceptance: 92b8275e5a75167b040738d21a153f487f799b9b
→ GPU Runtime Truth Phase 1A IMPLEMENTED + BASIC TESTS; push/CI and real multi-Node NVIDIA acceptance pending
→ NEXT AFTER PHASE 1A REMOTE ACCEPTANCE: GPU Runtime Truth Phase 1B (only when explicitly resumed)
→ genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction
→ SSE/event stream evaluation DEFERRED
→ non-blocking Navigation Action Fencing final scan remains DEFERRED
→ Resource Lifecycle production soak / non-SQLite resource classes
→ backend regression / A800 RC only when explicitly resumed
```

A800 RC remains deferred unless the user explicitly resumes it.

### 当前产品主线 — ZIP 10k import scalability CLOSED

Technical-debt cleanup remains paused by user request. Product productionization is the active line.

- **Deployment Artifact E2E CLOSED** — successful conversion jobs surface only verified, existing deployment artifacts. Product `b75b7d09780f691b01e4207c3107977b0500d8aa`, focused run `34726749756`, cleanup `8f3d3e394ceed73e5f522cba512622286fead7a5`.
- **Unified Task Truth API Phase 1 CLOSED** — `/api/v62/projects/{project_id}/tasks` remains the durable public truth for queue/resource/worker/progress metadata. Product `aa5b82ebd2140d3a9f03dc6ae6754c9b7a55afcc`, focused run `34727100684`, cleanup `6de0758e9f0c0cd45d79c48bf7fb022dde8f9ca6`.
- **Unified Task Progress Phase 2 CLOSED** — model conversion, AI annotation and cleaning/material-batch business surfaces expose durable waiting-resource/queue/worker/progress truth without parallel polling owners. Products `9817f450b3fbd20256279c3c861b0938ffdcef16` and `ff31f879b6d501a501188fed8bc78426d9eb31ea`.
- **SSE/event stream evaluation DEFERRED** — current page-scoped polling remains lifecycle-managed; no EventSource/replay/reconnect base is introduced without demonstrated need.
- **Training Progress v2 CLOSED** — existing `training-metrics.sqlite3` persists truthful latest-epoch duration, rolling ETA, throughput, losses, trainer metrics/mAP when supplied, LR and elapsed time; Worker mirrors the compact snapshot into `job.json` without extra list requests. Product `70110f9668e593215bc77c8614dd9d6dd55b7601`, focused run `34730431744`.
- **ZIP 10k import scalability CLOSED — hot-state/candidate split + live v19 owner**: baseline proved the final v36 visible ZIP action still delegated to synchronous `doImportData()` / `/api/v18/.../import`, and a synthetic 10,000-candidate v19 `job.json` was **1,370,177 bytes**. The product now routes final v36 ZIP upload through existing v19 background jobs and stores the full candidate manifest once in `scan-images.json`; hot `job.json`, running list polling and detail polling no longer carry the 10k candidate array. Create response is bounded to 500 candidates for the picker; selecting-job list preview is bounded to 300; running/terminal task state stays O(1) in candidate count. Selected-path validation reads the cold manifest. Product `b4875ada5ff084fd4e21d7c5f026f5b09128033b`, focused run `34731027723`, cleanup `e819a35c71f6aa20f7739281ddfc75e8502104ce`.
