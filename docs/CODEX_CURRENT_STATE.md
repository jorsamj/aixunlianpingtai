# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.


## Current closure — Feedback → Supplement Data Candidate v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Confirmed online feedback now enters a version-owned supplement-data candidate
workflow without introducing a second data or training owner.

Only confirmed feedback bound to the exact current algorithm/version is
considered. The backend joins feedback with current MaterialRepository and
AnnotationRepository truth and returns authoritative `eligible`,
`reason_codes`, and `candidate_digest` values. Pending/dismissed feedback is
excluded. A needs-correction sample remains ineligible until formal annotation
truth exists.

The user explicitly selects candidates. Freeze posts feedback IDs together with
the observed candidate digests; the server rereads current material/annotation
truth and fails closed when it changed. The resulting
`supplement_data_candidate_set` is stored on the Algorithm Version with a
deterministic candidate_set_id, feedback/material IDs, annotation hashes, and
model/input identities. Repeating the same set is idempotent; a different set
cannot overwrite the frozen version truth.

Frontend Impact Review is complete. The existing Dataset page is reused:
review candidate list → freeze → Dataset page candidate banner/filter. No
parallel page or owner was added, and the UI explicitly states that no Dataset
Revision, Snapshot, or TRAINING task exists yet.

Acceptance HEAD: `a54e0e735b27bde400b205fe1d07ede03903a973`.

- Online Feedback Runtime push `35428464451`：Ubuntu / Windows contract / Real Chrome 全部 success。
- Online Feedback Runtime PR `35428467030`：Ubuntu / Windows contract / Real Chrome 全部 success。
- 当前 code HEAD `a54e0e735b27bde400b205fe1d07ede03903a973`：17 个相关 workflows，0 failure / 0 pending；Node Agent Executor API / Ubuntu / Windows 也全部 success。
- `VERSION.txt = 42.24.0` 未修改。

**NEXT:** Supplement Candidate Set → Dataset Revision / Snapshot / Training
Lineage v1. Before training submit, revalidate candidate material/annotation
identities and carry only the actually selected feedback subset into revision,
snapshot, training lineage, and the produced Algorithm Version. Automatic
training remains forbidden.

## Current closure — Online Algorithm Sampling / Feedback v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Online sampling, test-publish feedback, and external SaaS/edge sample intake now
share one reviewed feedback contract. No second training owner or automatic
retraining path was introduced.

Feedback has only three durable states: `pending_review`, `confirmed`, and
`dismissed`. Each record is bound to prediction/external sample identity,
algorithm/version, model SHA256, input SHA256, detections, confidence, engine,
and source channel evidence.

External intake at
`/api/v63/projects/{project_id}/online-feedback/external-intake` verifies the
formal algorithm version and exact model SHA, validates the uploaded image and
bounded detection evidence, then stages `pending_review` only. It does not
write MaterialRepository, AnnotationRepository, Dataset Revision, Snapshot, or
TRAINING.

Explicit user confirmation is required before promotion:
- `correct` may confirm prediction boxes only when they do not overwrite
  different existing annotation truth;
- `false_positive` requires explicit all-active-label negative confirmation;
- `needs_correction` remains a manual annotation path.

Confirmed samples reuse material by content SHA when possible and otherwise
enter the existing MaterialRepository. AnnotationRepository remains the sole
formal annotation owner. Dismissed feedback has no material, annotation,
revision, or training side effect. Legacy v42 feedback/automatic iteration
writes are retired.

Frontend Impact Review is complete. Test Publish uses the v63 reviewed flow for
submit/review/confirm/dismiss/external intake. The legacy audit-connect alias
routes only to the new reviewed external-intake contract. Real Chrome verifies
the product flow and absence of automatic training/revision side effects.

Acceptance HEAD: `7a1ade605b6a55e1fe9027a86dc6756af795456b`.

- Online Feedback Runtime push `35427702717`：Ubuntu contract / Windows contract / Real Chrome 全部 success。
- Online Feedback Runtime PR `35427704825`：Ubuntu contract / Windows contract / Real Chrome 全部 success。
- Product code HEAD `05ba04f132e746ac3bd96b05790f0b526acd0236` 的其他共享 workflows 均 success；当时唯一红项是 Online Feedback Runtime，根因仅为 focused CI 缺少 OpenCV 依赖和测试使用了不存在的 MaterialRepository.list()，均已在 acceptance HEAD 修正。
- `VERSION.txt = 42.24.0` 未修改。

**NEXT:** Feedback → Supplement Data Candidate / Dataset Revision Candidate v1.
Only confirmed feedback may enter a frozen supplement-data candidate set. The
user must explicitly confirm the selected material scope before the existing
Dataset Revision → Snapshot → Durable TRAINING chain is invoked. Every later
revision/snapshot/training lineage must remain traceable back to feedback IDs.
Rockchip physical-board acceptance remains independently OPEN.

## Current closure — Iteration Decision → Confirmed Action v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The version-owned `iteration_decision` now drives one explicit, user-confirmed
`confirmed_iteration_action` contract. The algorithm version remains the
long-term owner. No second training/data owner and no frontend-derived action
state was introduced.

Confirmation is fenced to the current algorithm version and exact persisted
decision identity. Repeating the same confirmation is idempotent; attempting a
different action after confirmation fails closed.

The four formal actions are:

- `needs_data -> supplement_data`: freezes weak-label and FP/FN problem-sample
  evidence into a data draft. It does not mutate Dataset Revision or import/delete
  material automatically.
- `continue_training -> continue_training`: freezes a deterministic Durable
  TRAINING task ID and exact action/decision/evaluation/version/revision/snapshot
  lineage. The existing Scheduler, lease, generation and server-confirm owners
  remain authoritative. A real task starts only after user submit.
- `ready_for_business_validation -> business_validation`: persists a validation
  entry bound to decision/evaluation/version/revision/snapshot/model identities.
- `review_required -> manual_review`: persists a review entry with reason codes,
  recommendations and source lineage, without automatic execution.

New training lineage carries the confirmed action identity. Frontend Impact
Review is complete: the evaluation modal reads persisted
`evaluation + iteration_decision + confirmed_iteration_action`; after refresh
it shows the already-confirmed action and can resume supplement-data,
continue-training, business-validation or manual-review flows from version truth.
Real Chrome verifies confirm -> navigation -> transient-state reset -> version
refresh -> resume without a second confirm call, accidental `/train/start`, or
historical `/jobs` refetch.

Acceptance:

- Product code HEAD `d422fc21b3394edd71567a81bc34316d1172c652` shared regressions: 0 pending / 0 shared failure.
- Latest acceptance HEAD `4076f8adb376c24e32db78cf3bd15f83182ebcb4`: Algorithm SQL Store run `35424317881` contracts + Real Chrome success.
- Remote Training Runtime PR `35424280734`: API / Ubuntu / Windows success.
- Node Agent Executor PR `35424280790`: API / Ubuntu / Windows success.
- Remote Material Import PR `35424280896`: API / Ubuntu / Windows / Real Chrome success.
- Remote Cleaning Runtime PR `35424280779`: API / Ubuntu / Windows / Real Chrome success.
- Remote Conversion Runtime PR `35424280823`: control-plane / Ubuntu / Windows / Real Chrome success.
- Portable Deployment `35424280766`, Central Node Assignment `35424280780`, Task Runtime Truth `35424280794`, Training Input Integrity `35424280757`, Remote RKNN Board Runtime Protocol `35424280702`, Storage Cache Governance `35424280744` all success.
- `VERSION.txt = 42.24.0` remains unchanged.

**OPEN / next:** Online Algorithm Sampling / Feedback v1. Production inference
sampling, FP/FN review and user feedback should enter as reviewable evidence bound
to source algorithm/version/model identity, then reuse the existing
Material/Annotation -> Dataset Revision -> Snapshot -> Durable TRAINING ->
Evaluation -> Iteration Decision -> Confirmed Action chain. Do not create an
automatic retraining owner or mutate dataset truth directly from online feedback.
Rockchip physical RK3568/RK3576 acceptance remains independently OPEN.

## Current closure — Training Evaluation / Iteration Decision v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The existing algorithm-version owner now persists both blind-test `evaluation`
truth and a deterministic `iteration_decision` v1. No second training owner,
evaluation database, or frontend-derived decision path was introduced.

`build_iteration_decision()` consumes the persisted evaluation plus the
training task's existing quality gate. It therefore reuses the already-defined
`eval_metric / continue_threshold / stop_threshold` semantics instead of
inventing a second threshold system.

The persisted decision states are:

- `review_required`: independent evaluation is absent/failed, its metric is
  unavailable, or no final stop threshold was configured.
- `needs_data`: weak labels are present or the final metric falls below the
  original continue threshold.
- `continue_training`: the metric is above the continue threshold but below
  the configured stop threshold.
- `ready_for_business_validation`: the stop threshold is reached and there
  are no weak labels.

The version also freezes metric name/key/value, both thresholds, ordered weak
labels, FP/FN/problem-sample signals, reason codes, recommended actions and a
stable decision ID. `automatic_execution=false` and
`requires_confirmation=true`: this closure does not create a new training
task, mutate data, or silently change conversion semantics.

Algorithm SQL Store round-trip preserves `iteration_decision`. Frontend Impact
Review is complete: the stable version evaluation modal reads only persisted
`version.evaluation + version.iteration_decision`, shows the backend decision
and recommended actions, and explicitly states that no next training run is
started automatically. Real Chrome verifies this without historical `/jobs`
refetch.

Acceptance code HEAD: `d11d0e16998e7630bbc5811a937ba3c21395548e`.

- 17 workflows: 17 success / 0 failure / 0 pending.
- Algorithm SQL Store push `35422469494`: contracts + Real Chrome success.
- Remote Training Runtime push `35422469499`: Windows / Ubuntu contracts + API success.
- Shared Training / Scheduler / Agent / Material / Cleaning / Conversion / RKNN
  / Deployment regressions are green.
- `VERSION.txt` remains `42.24.0`.

**OPEN / next:** Iteration Decision → Confirmed Action v1. Wire the persisted
decision to explicit user-confirmed product actions: weak-label/data supplement
draft, current-version retraining draft, business-validation entry, or manual
review. Every action must carry decision/evaluation/version/dataset/snapshot
identity into the next lineage and must reuse the existing Durable TRAINING and
data owners. Online algorithm sampling/feedback can then enter this same chain.
Rockchip physical-board acceptance remains independently OPEN.

## Current closure — Training Lineage / Algorithm Version Provenance v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Algorithm versions now own stable training provenance instead of depending on
transient job/cache state. Both local training and Remote Agent training build
the same `training_lineage` schema v1.

The persisted lineage references the immutable Dataset Revision and Snapshot,
then records task identity, framework, selected base version/model/reason,
execution mode/worker/Agent node/generation, requested/assigned/actual device,
public GPU identity, requested/actual training parameters, verified model
artifacts and the final training outcome.

`platform_core/training_lineage.py` is public-safe by construction: persisted
fields are allow-listed primitives, model paths collapse to safe filenames, and
signed URLs/secrets/credentials are excluded. Dataset revision IDs are validated
as SHA256 identities.

Local archival and Remote Agent server-confirm both persist lineage on the
algorithm version. Algorithm SQL Store round-trip preserves the lineage, so
historical provenance survives job cleanup and restart.

Frontend Impact Review is complete. The stable algorithm-version renderer shows
“训练溯源” only when persisted lineage exists. The modal reads the version truth
directly and shows dataset revision, snapshot, task, base model/version,
execution/node/device, effective parameters and model artifact identity. Real
Chrome verifies the flow without refetching historical `/jobs`.

Acceptance at HEAD `c6c7289b3a13d20053e1a8aed44525a4901f5059`:

- 当前代码 HEAD `c6c7289b3a13d20053e1a8aed44525a4901f5059`：21 个相关 workflow，21 success / 0 failure / 0 pending。
- Training Input Integrity、Remote Training Runtime、Node Agent Executor、Central Node Assignment、Task Runtime Truth、Portable Deployment、Remote Material Import、Remote Cleaning、Remote Conversion、Remote RKNN Board Runtime Protocol 均 success。
- Algorithm SQL Store / Training Task Visibility / External Algorithm Platform / Publish 等共享回归 success。
- Real Chrome 已验证算法版本“训练溯源”来自持久化版本 truth，点击查看不会重新请求历史 job。
- `VERSION.txt = 42.24.0` 未修改。

**OPEN / next:** build the formal post-training Evaluation truth on the existing
Durable TRAINING/version chain: frozen test-split evaluation, overall and
per-label metrics, FP/FN/weak-label evidence, and an explicit retraining/data
decision. Do not create a second training owner. Rockchip physical-board
acceptance remains independently OPEN.

## Current closure — Dataset Snapshot / Revision v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The existing Snapshot V3 path now owns a deterministic Dataset Revision v1.
No parallel snapshot system was introduced.

`dataset_revision_id` identifies the selected dataset truth independently of
the train/validation/test assignment. The same selected material, platform
annotation truth, Canonical Annotation Schema v1 provenance and label schema
produce the same revision across different split seeds, while `snapshot_id`
still changes with split/role truth.

Dataset Revision v1 freezes material/source identity, content SHA256,
storage-source/object identity, platform annotation state/scope/hash,
source labels/box count, canonical external annotation provenance and the
locked label schema. Revision persistence is immutable and fails closed if a
previous revision ID maps to different content.

Snapshot V3 now carries dataset revision schema v1 and canonical annotation
schema v1 alongside its existing split, duplicate-exclusion and negative-scope
truth. Legacy V1/V2 portable snapshots are deterministically upgraded with a
revision identity without changing their historical snapshot IDs.

Remote TRAINING contract v2 requires a valid revision SHA256. The Agent verifies
the downloaded bundle's snapshot ID and dataset revision before execution.
Server-confirmed results, model artifacts, algorithm-version metadata, durable
jobs and frontend runtime preserve the same revision identity.

Frontend Impact Review is complete. The training runtime center displays
backend-backed “数据版本” and “训练快照” truth; focused refresh/cache paths retain
both fields. Real Chrome verifies the visible lineage fields.

Acceptance at HEAD `5e330fd3de9a958c2eac1ad1f18c11cf81b381b6`:
- Training Task Visibility push `35415738121`：visibility-contracts + Real Chrome success。
- 父代码 HEAD `5e2a0959a3a822f5725f684bd9351350b150a6b1`：Remote Training、Training Input Integrity、Node Agent Executor、Central Node Assignment、Task Runtime Truth、Portable Deployment、Remote Material Import、Remote Cleaning、Remote Conversion、RKNN Board Runtime 等共享回归 success。
- Dataset Revision / Snapshot focused unit、API、frontend identity/cache tests success。
- `VERSION.txt = 42.24.0` 未修改。

**OPEN / next:** use the revision/snapshot identities as the base for formal
Training Lineage / Algorithm Version Provenance, then build the automatic
evaluation/retraining loop on that immutable lineage. Rockchip physical-board
acceptance remains independently OPEN.

## Current closure — Canonical Annotation Schema v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

YOLO, COCO and Pascal VOC external annotation evidence now shares one explicit,
versioned contract in `platform_core/annotation_schema.py`. Source-format
parsers remain unchanged and retain their existing ownership; the canonical
layer only owns deterministic evidence normalization and validation.

Schema v1 preserves the previous flat evidence shape and source-digest semantics,
so existing synchronized annotations do not become false CHANGED deltas merely
because the abstraction was formalized. The contract freezes source format,
object key, split, annotation status, source-object identities, class-catalog
digest and normalized boxes.

`ImportCandidateStore.annotation_source_evidence()` now delegates to the
canonical builder. Rescan delta construction validates freshly produced evidence,
and formal apply validates it again before any AnnotationRepository write.
Tampered digests, unsupported versions/formats, object-key mismatches and
request-format mismatches fail closed.

This does not create a second annotation owner. Canonical evidence remains
external-source provenance; AnnotationRepository remains platform truth.

Frontend Impact Review: no UI change was required because public task/API fields
and status semantics are unchanged. Real Chrome and shared runtime regressions
remain green.

Acceptance at code HEAD `e262819dd7c4eb7a245e43eefc91bc452a4060fc`:
- Remote Material Import push：Ubuntu / Windows / API / Real Chrome success。
- Canonical schema builder/validator 在 Ubuntu + Windows contract 中通过。
- source_digest legacy compatibility 对 YOLO / COCO / VOC 均通过。
- Consumer-side tamper / format mismatch fencing 通过。
- Node Agent Executor、Remote Cleaning、Remote Training、Remote Conversion、Central Assignment、Portable Deployment、RKNN Board Runtime 等共享回归全部 success。
- 当前代码 HEAD 共 16 个相关 workflow：16 success / 0 failure / 0 pending。
- `VERSION.txt = 42.24.0` 未修改。

**OPEN / next:** extend the existing Snapshot V3 path into Dataset Snapshot /
Revision by freezing canonical annotation source/schema truth alongside content
SHA, annotation hash, split and label schema. Do not create a parallel snapshot
system.

## Current closure — Remote storage_rescan Phase 2C Pascal VOC Annotation Delta CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The existing `MATERIAL_IMPORT + mode=storage_rescan` owner now reconciles
Pascal VOC XML annotation changes through the same durable flow used by Phase 1
images, Phase 2A YOLO and Phase 2B COCO. No second VOC parser, TaskKind or
AnnotationRepository owner was introduced.

Local and Agent product truth is now `import_format=images|yolo|coco|voc`.
The Agent reuses `DetectionDatasetScanner`, the execution-fenced broker and
short-lived GET contracts. It freezes XML object identity (key, size, ETag and
SHA256), split, external class catalog, normalized boxes, quality issues and
per-image source digest without opening central SQLite/NFS or receiving
long-lived object-store credentials.

Image delta and annotation delta remain separate. VOC uses the shared
`ANNOTATION_NEW / CHANGED / REMOVED / UNCHANGED / CONFLICT / INVALID`
categories. XML deletion or XML/class/bbox/split changes are detected even when
image bytes are unchanged.

External source evidence remains distinct from platform AnnotationRepository
truth. Manual annotation edits after review are protected by stale-write
fencing. New images continue through the existing MATERIAL_IMPORT indexer and
rescan records provenance instead of creating a second annotation write path.
Ambiguous multiple VOC XML references for one image fail closed.

Frontend Impact Review is complete. Preflight, API schema and storage rescan UI
expose the same four formats. Pascal VOC uses backend task truth for image and
annotation counts, quality, external-class mapping, removal/conflict policy and
confirmation. Real Chrome covers the Agent VOC request/review/confirmation chain.

Acceptance at code HEAD `5a1c18c8fc18c783a95d55f4f6a3ad826ffef69a`:
- Remote Material Import push `35412658236`：API / Ubuntu / Windows / Real Chrome success。
- Remote Material Import PR `35412660855`：API / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor push `35412658140` / PR `35412660966`：success。
- Central Node Assignment push `35412658117` / PR `35412660834`：success。
- Task Runtime Truth `35412660757`：success。
- Remote Training Runtime push `35412658157` / PR `35412660756`：success。
- Remote Conversion Runtime push `35412658182` / PR `35412660808`：success。
- Remote Cleaning Runtime push `35412658119` / PR `35412660762`：success。
- Portable Deployment push `35412658228` / PR `35412660767`：success。
- Remote RKNN Board Runtime Protocol push `35412658162` / PR `35412660872`：success。
- Storage Cache Governance `35412660802`：success。
- 当前代码 HEAD 共 28 个相关 workflow：28 success / 0 failure / 0 pending。
- `VERSION.txt = 42.24.0` 未修改。

**OPEN / next:** formalize the already-shared YOLO/COCO/VOC evidence as
Canonical Annotation Schema v1, then build Dataset Snapshot / Revision on top of
that versioned annotation truth. Rockchip physical-board acceptance remains
independently OPEN.

## Current closure — Remote storage_rescan Phase 2B COCO Annotation Delta CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The existing `MATERIAL_IMPORT + mode=storage_rescan` owner now reconciles COCO
annotation JSON changes in the same product/control-plane flow as Phase 1 image
objects and Phase 2A YOLO annotations. No second COCO parser, TaskKind or
AnnotationRepository owner was introduced.

Local and Agent rescan now share `import_format=images|yolo|coco`. COCO reuses
the existing `DetectionDatasetScanner` and task-owned `ImportCandidateStore`.
The Agent reads object storage only through the execution-fenced broker and
short-lived GET contracts; it never opens central SQLite/NFS and receives no
long-lived storage credentials.

COCO review freezes the real annotation JSON object identity (key, size, ETag,
SHA256), split, external category catalog, normalized boxes, annotation status,
quality issues and per-image source digest. Full source image inventory is kept,
including images not referenced by JSON, so annotation coverage is never
mistaken for image existence.

External source provenance remains separate from platform AnnotationRepository
truth. JSON changes/removals produce annotation deltas and require user
confirmation. A manual platform annotation edit after review is protected by
stale-write fencing. New images continue through the existing MATERIAL_IMPORT
indexer, then rescan records matching external provenance instead of creating a
parallel annotation write path.

COCO ambiguity now fails closed: conflicting category ID/name mappings, one
image across multiple splits, one image referenced by multiple COCO annotation
documents, or duplicate references to the same object key inside COCO metadata
are rejected instead of allowing first/last-write ambiguity.

Frontend Impact Review is complete. The storage rescan modal exposes COCO only
when backend preflight says it is supported, keeps data.yaml YOLO-only, and uses
the same backend task truth for image/annotation counts, mapping, quality,
removal/conflict policy and confirmation. Real Chrome validates the Agent COCO
request/review/confirmation path.

Acceptance at code HEAD `ac1470c9049f7151fb6ae78daf6d21802ea6a263`:
- Remote Material Import push `35411646993`：API / Ubuntu / Windows / Real Chrome success。
- Remote Material Import PR `35411650317`：success。
- Node Agent Executor `35411650294`：success。
- Central Node Assignment `35411650355`：success。
- Task Runtime Truth `35411650324`：success。
- Remote Training Runtime `35411650292`：success。
- Remote Conversion Runtime `35411650281`：success。
- Remote Cleaning Runtime `35411650314`：API / Ubuntu / Windows / Real Chrome success。
- Portable Deployment `35411650458`：success。
- Remote RKNN Board Runtime Protocol `35411650309`：API / Ubuntu / Windows / Real Chrome success。
- Storage Cache Governance `35411650330`：success。
- Training Input Integrity `35411650297`：success。
- 16/16 related workflows on the code HEAD succeeded; no failures or pending jobs.
- `VERSION.txt = 42.24.0`.

**OPEN / next:** Phase 2C Pascal VOC XML annotation delta, then formal Canonical
Annotation Schema versioning over the already-shared YOLO/COCO/VOC evidence.
Rockchip physical-board acceptance remains independently OPEN.

## Current closure — Remote storage_rescan Phase 2A YOLO Annotation Delta CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The existing `MATERIAL_IMPORT + mode=storage_rescan` owner now reconciles
YOLO annotation changes in addition to Phase 1 image-object changes. Local and
Agent execution consume the same request truth: `execution_mode`,
`import_format=images|yolo` and optional `dataset_yaml`.

For YOLO, the portable review freezes source-object evidence for label sidecars
and `data.yaml` (object key, size, ETag and SHA256), split identity, external
class catalog, normalized boxes and issues. The task-owned store derives a
per-image source digest and compares it with the previously synchronized
external provenance plus current AnnotationRepository truth.

Delta categories are `ANNOTATION_NEW / CHANGED / REMOVED / UNCHANGED /
CONFLICT / INVALID`. External provenance is not the platform annotation
authority. User confirmation explicitly controls existing-image updates,
external removals and manual-edit conflicts, plus external-class label mapping
and quality acceptance.

New images continue through the already-closed MATERIAL_IMPORT indexing owner,
including their YOLO GT. After indexing, rescan records the matching external
source provenance and synchronized annotation hash rather than flagging that GT
as pending review.

Two fail-closed concurrency rules are permanent:
1. durable rescan intent is frozen before any new project label is created;
2. before overwriting/clearing an existing platform annotation, the current
   annotation hash/state must still match the review snapshot. A manual edit
   after review forces a new rescan instead of being overwritten.

Frontend Impact Review was completed in the same batch. The storage rescan modal
shows one backend-backed execution/format truth, separate image/annotation delta
counts, label mapping, quality acceptance, removal policy and conflict policy.
The YOLO mapping rendering runtime error was fixed, and Real Chrome validates the
Agent request/review/confirmation chain.

Acceptance at code HEAD `6505c51e1916a8aab5d506387b51d01e413b7775`:
- Remote Material Import push `35410155924`：API / Ubuntu / Windows / Real Chrome success。
- Remote Material Import PR `35410158432`：API / Ubuntu / Windows / Real Chrome success。
- 父层 UI/确认顺序回归：
  - `9e8ada…` push Remote Material Import `35409879583` 全绿。
  - `c6ee2ab…` push/PR Remote Material Import 全绿。
- `VERSION.txt = 42.24.0` 未修改。

**OPEN / next:** Phase 2B COCO annotation JSON delta, then Phase 2C Pascal VOC
XML delta. After those, version the already-shared YOLO/COCO/VOC evidence as the
Canonical Annotation Schema instead of creating new parser owners.

Rockchip real-board acceptance remains independently OPEN.

## Current closure — Remote storage_rescan Phase 1 image objects CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The existing `MATERIAL_IMPORT + mode=storage_rescan` durable owner now supports a
real portable Agent execution path for **image-object reconciliation**. No new
TaskKind, database owner, or parallel storage importer was introduced.

The control plane freezes the current MaterialRepository source baseline into a
task-owned artifact before remote execution. An Agent can scan the complete
OSS/S3/MinIO source only under explicit `intent=storage_rescan`; ordinary
`storage_scan` still requires an explicit prefix. The Agent receives no
long-lived storage credentials and never opens central SQLite/NFS. It uses the
existing execution-fenced broker and short-lived GET contracts to inspect real
image bytes, dimensions, SHA256, size and ETag.

Server-confirmed review evidence is compared with the frozen baseline to produce
`NEW / MISSING / CHANGED / UNCHANGED` plus quality evidence. Rescan preserves
object identity: equal content hashes under different object keys are not
collapsed as duplicates. CHANGED classification includes SHA256, size and ETag.

The user must confirm the reconciliation policy. After confirmation, the same
task returns to the existing central `storage.rescan` worker for formal
MaterialRepository updates. The control plane revalidates Agent-reviewed objects
with provider stat identity (size/ETag/available SHA metadata) rather than
downloading and hashing all bodies again, so heavy image I/O remains remote.
Missing records are marked unavailable instead of deleted; changed records keep
their existing annotation truth but are marked for review.

Frontend Impact Review was completed in the same batch. The storage-source UI
shows Central Worker / Remote Agent, consumes real preflight node truth, displays
durable status/worker/wait reason and incremental counts, and restores the same
task after refresh. Real Chrome covers the remote rescan flow.

Acceptance at code HEAD `64dc87c6e295429f79adfc813093bff33ce61587`:
- Remote Material Import `35408027919`：API / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor `35408027776`：API / Ubuntu / Windows success。
- Central Node Assignment `35408027804`：success。
- Task Runtime Truth `35408027769`：success。
- Portable Deployment `35408027802`：success。
- Remote Training Runtime `35408027815`：success。
- Remote Conversion Runtime `35408027785`：success。
- Remote Cleaning Runtime `35408027775`：API / Ubuntu / Windows / Real Chrome success。
- Remote RKNN Board Runtime Protocol `35408027782`：API / Ubuntu / Windows / Real Chrome success。
- Storage Cache Governance `35408027828`：success。

**OPEN / next code phase:** storage_rescan Phase 2 for YOLO `.txt/data.yaml`,
COCO annotation JSON and Pascal VOC XML deltas, followed by formal versioning of
the existing shared evidence as the Canonical Annotation Schema. These are
extensions of the closed import/review chain, not permission to create parallel
parsers or owners.

Rockchip physical-board acceptance remains independently OPEN. No CI result
proves that a user-owned RK3568/RK3576 board has passed hardware acceptance.


## Current closure — Remote MATERIAL_IMPORT Phase 6 COCO / Pascal VOC Agent server_zip CLOSED

Formal `VERSION.txt` remains `42.24.0`.

COCO and Pascal VOC now also run through the existing portable Agent
`server_zip` MATERIAL_IMPORT path. This does not create a second annotation
truth: the Agent safely downloads/extracts the task-owned ZIP, reuses
`DetectionDatasetScanner`, and emits the same candidate/class/normalized-box/
split/issue evidence used by the already-closed storage_scan path.

The ZIP variant embeds only the IMPORTABLE image payloads needed after user
confirmation. Server-confirm revalidates the review archive, payload
size/SHA256/dimensions, candidate coverage and detection evidence before any
formal material is indexed. Users still confirm external-class to platform-label
mappings; the local Storage Worker then publishes verified payloads and commits
the existing MaterialRepository / AnnotationRepository truth.

Long-lived object-store credentials and central SQLite/NFS never reach the
Agent. The source ZIP is staged as a task-owned verified object; review
publication remains generation-fenced and immutable. dataset_yaml stays
YOLO-only.

The server-ZIP UI now has an explicit Central Worker / Remote Agent execution
choice. Local execution retains the previous local-storage behavior and does
not expose COCO/VOC. Agent execution switches the target to an enabled
OSS/S3/MinIO source, requires an explicit format (no auto), and exposes
COCO/VOC. Real Chrome covers that exact switch and request body.

Acceptance at code HEAD `3f5c34ae587aee04971e8e5160073898f288cba4`:
- Remote Material Import `35357183468`: API / Ubuntu / Windows / Real Chrome success.
- Node Agent Executor `35357183397`: success.
- Central Node Assignment `35357183504`: success.
- Task Runtime Truth `35357183682`: success.
- Portable Deployment `35357183477`: success.
- Remote Training Runtime `35357183476`: success.
- Remote Conversion Runtime `35357183564`: success.
- Remote Cleaning Runtime `35357183532`: success.
- Remote RKNN Board Runtime Protocol `35357183788`: success.

## Current closure — Remote MATERIAL_IMPORT Phase 5 COCO / Pascal VOC CLOSED

Formal `VERSION.txt` remains `42.24.0`.

COCO and Pascal VOC are now real remote annotation formats for
`MATERIAL_IMPORT + storage_scan + execution_mode=agent`. This was the Phase 5
closure boundary; Agent server_zip for these formats is now separately CLOSED in
Phase 6 above.

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

The Phase 5 product UI exposed COCO and Pascal VOC for object-storage Agent scans.
Phase 6 now also exposes them for Agent server_zip; local directory and Central
Worker ZIP modes still disable those options. dataset_yaml remains YOLO-only.

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

## Current closure — Remote MODEL_CONVERSION Phase 2 Rockchip RKNN CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Rockchip RKNN is now a real remote MODEL_CONVERSION target. ONNX keeps the
existing `conversion` capability while Rockchip uses the independent
`conversion.rknn` capability. The Agent reports that capability only after a
real RKNN-Toolkit2 import plus target-platform config probe; control-plane resource discovery also
requires the node to be online, Agent-connected, effective for
`conversion.rknn`, and to publish an available RKNN probe with supported chips.

The portable RKNN contract is deliberately bounded to RK3568 / RK3576, FP16,
batch=1 and static input shape. Unsupported chips, INT8 calibration, dynamic
shape or batch>1 fail before durable execution. The Agent downloads the verified
model object, executes the node-local conversion worker/RKNN-Toolkit2, requires
exactly one non-empty .rknn result, hashes it locally, uploads with generation
fencing, and waits for server confirmation.

The control plane re-downloads and verifies size/SHA256 and commits the artifact
to the existing deployment job artifact directory. RKNN remains
`converted_unverified`: `runtime_verified=false` and
`hardware_verified=false` until a real Rockchip board runs the model. The
product UI includes RK3576 and uses backend resource truth; it does not infer
RKNN availability from generic conversion capability.

Earlier references to RK3578 were corrected. The official RKNN-Toolkit2 support
list names RK3576 Series, not RK3578. Any device sold/labeled as “3578” must have
its real SoC identified before being mapped to an RKNN target.

Acceptance at code HEAD `5a02aa5ba03e94cc731bfd0e62437c57738efab1`:
- Remote Conversion Runtime `35330889750`: control-plane / Ubuntu / Windows / Real Chrome success.
- Node Agent Executor `35330889657`: success.
- Central Node Assignment `35330889375`: success.
- Task Runtime Truth `35330889784`: success.
- Portable Deployment `35330889497`: success.
- Remote Material Import `35330889535`: success.
- Remote Training Runtime `35330889384`: success.
- Remote Cleaning Runtime `35330889291`: success.

## Current closure — Rockchip RKNN board runtime verification protocol CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The Rockchip board verification software/product path is now complete. A
separate `deployment-test.rknn` capability is reported only by an Agent that
is Linux arm64/aarch64, identifies an RK3568/RK3566-family or RK3576 SoC from
`/proc/device-tree/compatible`, and can import the node-local RKNNLite runtime.
The heartbeat publishes the board chip/runtime truth and assignment requires an
exact chip match.

Board verification reuses the existing DEPLOYMENT_TEST durable task. The
control plane verifies the source .rknn artifact against its conversion
manifest, stages verified model/input objects, and the Agent executes the
node-local `predict_rknn_lite_runner.py`. That runner performs real
`RKNNLite.load_rknn`, `init_runtime`, and `inference`; it returns inference
latency, output count and output shapes, but deliberately does not claim model
accuracy or decode model-specific YOLO outputs.

Result publication remains generation-fenced and server-confirmed. Before
publishing hardware truth, the control plane revalidates the original
conversion job/chip/model SHA256. Only matching successful RKNNLite evidence
may set `runtime_verified=true`, `hardware_verified=true` and
`validation_status=hardware_verified` on the existing deployment job and
manifest.

The deployment UI now exposes “板端验证” for Rockchip
`converted_unverified` jobs, accepts a real test image, polls the durable task,
and refreshes the original job to “实机已验证” with chip/inference/output
evidence. Real Chrome covers this product flow.

Acceptance at code HEAD `05c7b93339414ac028214fd3d046dfdf7977c0a1`:
- Remote RKNN Board Runtime Protocol `35335720990`: API / Ubuntu / Windows / Real Chrome success.
- Remote Conversion Runtime `35335720906`: success.
- Node Agent Executor `35335720915`: success.
- Central Node Assignment `35335720909`: success.
- Task Runtime Truth `35335720969`: success.
- Portable Deployment `35335720910`: success.
- Remote Material Import `35335720921`: success.
- Remote Training Runtime `35335720913`: success.
- Remote Cleaning Runtime `35335721027`: success.

This is a software/protocol closure, not evidence that a physical user-owned
RK3568/RK3576 board has already passed acceptance. A specific model becomes
`hardware_verified` only after a real connected board Agent executes the
runtime task successfully.

## Current closure — Rockchip RKNN INT8 calibration portable transport CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Remote Rockchip conversion now supports real FP16 and INT8 execution on an
Agent. INT8 is exposed only when backend resource truth reports it in
`supported_precisions`; the UI does not infer quantization support itself.

Before creating the durable conversion task, the control plane freezes an
RKNN calibration snapshot bound to the requested dataset/split and current
MaterialRepository revision. Every calibration item contains an exact portable
object reference plus size/SHA256 evidence. Non-portable/local materials,
missing evidence or changed source objects fail before the Agent task is
persisted.

The start payload contains only the frozen snapshot and short-lived object GET
contracts. The Agent downloads every calibration image into its generation
workdir, verifies size/SHA256, checks snapshot/count/file-count consistency and
only then starts the node-local deployment worker. That worker creates the
RKNN dataset file from the downloaded images and performs the real
RKNN-Toolkit2 INT8 build.

INT8 publication uses the same immutable generation-scoped upload,
server-confirm and deployment artifact commit as FP16. A successful RKNN INT8
conversion remains `converted_unverified` with `hardware_verified=false`;
the already-closed Rockchip board runtime flow is still the only path that may
promote the model to `hardware_verified=true`.

The deployment UI now exposes dataset, split and calibration count for RKNN
INT8 and Real Chrome verifies a real Agent INT8 task submission.

Acceptance at code HEAD `314757c1601420640acedc074e9aeb795e8a2097`:
- Remote Conversion Runtime `35340943761`: control-plane / Ubuntu / Windows / Real Chrome success.
- Remote RKNN Board Runtime Protocol `35340943851`: success.
- Node Agent Executor `35340943850`: success.
- Central Node Assignment `35340943861`: success.
- Task Runtime Truth `35340943758`: success.
- Portable Deployment `35340943913`: success.
- Remote Material Import `35340943781`: success.
- Remote Training Runtime `35340943764`: success.
- Remote Cleaning Runtime `35340943815`: success.

## Current closure — Rockchip real-device onboarding tooling CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Rockchip board onboarding is now productized without weakening the existing
runtime truth. `node_agent.py --doctor` is a strict capability preflight:
requested capabilities that cannot actually be reported make the command exit
non-zero and include actionable issues. Existing `--check` behavior remains
compatible.

`tools/install_rockchip_agent.sh` installs the board Agent as a Linux systemd
service. It runs doctor before installation and through `ExecStartPre` on
service starts. The one-time Agent token is never embedded in the install
command or systemd `ExecStart`; it is read from a silent prompt/environment
and stored in a root-owned 0600 EnvironmentFile.

The Service Node UI now understands `conversion.rknn` and
`deployment-test.rknn`, offers a Rockchip-board preset, surfaces observed
SoC/RKNNLite/RKNN-Toolkit2 runtime truth, and shows board-specific doctor and
systemd onboarding commands in the one-time-token dialog. The generated
systemd command itself contains no token.

Acceptance at code HEAD `b8caf7753994988d5161321c2536ae75e64d3252`:
- Service Node UI `35342366446`: Ubuntu / Windows contracts + Real Chrome success.
- Remote RKNN Board Runtime Protocol `35342366573`: API / Ubuntu / Windows / Real Chrome success.
- Remote Conversion Runtime `35342369723`: success.
- Node Agent Executor `35342369838`: success.
- Central Node Assignment `35342369780`: success.
- Remote Training Runtime `35342369831`: success.
- Remote Material Import `35342369794`: success.
- Task Runtime Truth `35342369798`: success.
- Portable Deployment `35342369765`: success.

This closes the **software onboarding tooling only**. It does not prove that any
specific user-owned board has passed hardware acceptance.

Capability probing was hardened again at code HEAD `b20470c8f57ee99fcde3ff0da5f26a5be4b7124f`: `supported_chips` now comes from actual `RKNN.config(target_platform=...)` calls for RK3568/RK3576 rather than a Toolkit-version threshold. Remote Conversion `35344315905`, RKNN Board `35344315931`, Node Agent Executor `35344315955`, Central Assignment `35344316219`, Task Runtime Truth `35344315903`, and Portable Deployment `35344315907` all passed.

**OPEN / next:** Rockchip physical-board acceptance. A real RK3568/RK3576 (or a
device whose actual SoC is first identified) must run the Agent, become online
with effective `deployment-test.rknn`, and execute a real converted `.rknn`
through RKNNLite. Only that real task may promote that specific conversion to
`hardware_verified=true`. CI/mock/x86 execution is not hardware acceptance.




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
