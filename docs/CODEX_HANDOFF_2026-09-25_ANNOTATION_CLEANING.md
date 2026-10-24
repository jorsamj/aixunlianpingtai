# CODEX HANDOFF — 2026-09-25 ANNOTATION + CLEANING

Repository: jorsamj/aixunlianpingtai
Long-lived branch: feature/external-algorithm-publishing
Code/CI cutoff before this documentation commit: c1e9dc2dbae57c0c36c251e95f918a0ffac8ec3e
VERSION.txt = 42.24.0 and must remain unchanged.

This documentation commit advances HEAD. A new session must re-read the live remote branch before any code change.

## 1. Non-negotiable rules

- Do not merge main.
- Do not tag or release.
- Do not force-push.
- Keep VERSION.txt exactly 42.24.0.
- Do not delete or weaken tests to obtain green CI.
- Do not restore retired legacy frontend/backend owners.
- Do not create a second annotation Ground Truth store, second AI review owner, second cleaning task runtime, second polling loop, or another modal owner.
- Windows 11 is development; Linux/NVIDIA is formal production. Never hardcode Windows paths.
- Web remains 127.0.0.1:8010.
- Queued/in-progress is not pass. Any completed failure must be inspected from its real job log before modifying production code.

## 2. Annotation work completed — do not redesign

The annotation product contract is now:

AI inference -> Candidate -> AWAITING_CONFIRMATION -> human review -> accept/reject/edit -> Commit -> formal Ground Truth.

Raw AI candidates must never become Ground Truth without human confirmation.

Final frontend AI task owner is the durable v60 annotation task runtime. The legacy v47 AI annotation backend write path has been retired. Legacy UI entrypoints, where retained for compatibility, must delegate to the canonical owner and must not recreate the old write flow.

Important current closures include:

- Manual annotation workbench is a single near-fullscreen owner.
- Pointer editing uses Pointer Events + AbortController + requestAnimationFrame hot path.
- pointermove paints only the active box; state/history/sidebar/dirty/autosave commit on pointerup.
- Dirty modal close saves before teardown.
- AI review supports paging, accept/reject, visual candidate editing, label mapping and explicit final confirmation.
- AI review decisions now patch incrementally rather than remounting the whole review surface.
- AI review mapping tools are height-bounded so they do not cover candidate actions.
- Reduced-motion coverage is explicit; visual polish must never add animation to the pointer hot path.
- Candidate labels remain readable.
- Inspector scroll ownership is explicit.
- Canonical annotation helper names and AI decision owner are guarded against duplicate legacy owners.

## 3. Annotation provenance truth — backend is the owner

Formal annotation states remain:

- unannotated
- annotated
- confirmed_empty

Material/display provenance is derived from formal truth:

- manual -> 人工标注
- ai_confirmed -> AI已确认
- mixed -> 混合标注
- imported -> 导入标注
- confirmed_empty -> 已确认无目标
- transient durable AI task state may show AI待审核 / AI正在入库 / AI候选失败

The server now owns provenance. Browser edits are allowed to change geometry/label identity, but browser-supplied source metadata must not be trusted to forge AI/import provenance.

Current provenance fixes include:

- Existing AI-confirmed boxes keep source/source_task_id/candidate_id/confidence when manually moved or relabeled.
- Newly drawn boxes are manual even if a browser posts a forged AI source.
- AI-confirmed formal boxes + newly drawn manual boxes derive mixed.
- Structured COCO/VOC/YOLO imports persist imported provenance.
- Legacy annotation provenance can be recovered when old records lack newer projection fields.
- Annotation reindex preserves provenance.
- Backend annotation preview limit and material preview limit are aligned.
- Material cards and detail views display provenance truth rather than guessing from box count alone.

Do not add a second provenance database column/store unless a new durable requirement is proven. Current material projection is derived from AnnotationRepository truth plus durable AI task truth.

## 4. Annotation UI status at cutoff

The user requested a professional CVAT/Label Studio/Roboflow-like workbench, but without decorative performance cost.

Implemented UI direction:

- Manual workbench: left queue, dominant dark canvas, right labels/objects inspector.
- Core toolbar actions remain visible at 1366x768 and make good use of 1920x1080.
- Object rows expose provenance plus label.
- Material cards show restrained status badges for AI待审核 / AI正在入库 / AI已确认 / 人工标注 / 混合标注 / 已确认无目标 / 导入标注 / failure.
- AI Review has explicit KPIs for candidate images, current-page accepted, rejected, candidate boxes, empty, failed, and edited.
- Motion is intentionally lightweight: modal enter, status badge pulse, queue hover, toolbar/filter hover.
- No animation is allowed in box pointermove/drag/resize hot paths.
- prefers-reduced-motion must disable the annotation UI motion.

At earlier validated runtime HEAD 0db514bed31a5c83c970f47122c54982018cf8b4:
- Frontend Runtime frontend job: 741 / 741 passed.
- Real Chrome browser-navigation: 76 / 76 passed.

The live cutoff c1e9dc2d... is newer and must be treated by its own workflow status below.

## 5. Current CI truth at cutoff c1e9dc2d...

At this cutoff there are 34 workflow runs:
- 31 completed success
- 3 completed failure
- 0 queued
- 0 in progress

Important annotation/cleaning/runtime workflows are completed success:
- Frontend Runtime Stabilization
- AI Annotation Recovery
- Remote Cleaning Runtime
- Remote Material Import
- ZIP Import Durable Runtime
- Task Runtime Truth

The three completed failures are:

1. Label Normalization Contract — two runs.
   Real API and frontend test groups inside the jobs pass with fail 0.
   The final source guard fails because it still requires the old exact app.py source literal:
   *[str(alias).strip() for alias in item.get('aliases') or []]
   Treat this first as stale/mis-scoped source-guard debt. Do not restore old implementation syntax merely to satisfy the grep.

2. Training Task Visibility / real-chrome.
   visibility-contracts job succeeds, but training-task-performance.spec.mjs real Chrome fails because the final table remains 暂无记录 instead of showing 局部刷新训练 / 37%.
   This is not proven stale. Focus-reproduce and inspect the current TrainingTaskRuntime hydration/refresh path before changing production.

Do not call c1e9dc2d fully green.

## 6. Data cleaning — current real implementation

The platform already has a durable cleaning runtime. Do not replace it with a new service.

Canonical frontend view:
- static/modules/cleaning.js
- default execution mode = local
- optional execution mode = agent when preflight proves an eligible remote node

Canonical base image checks live in platform_core/cleaning.py.

Current checks:

1. Exact duplicate
   - SHA256

2. Near duplicate
   - dHash + Hamming distance
   - durable task-local hash index / four-band LSH

3. Resolution
   - min/max width and height

4. Blur
   - OpenCV grayscale + Laplacian variance
   - current default blur threshold = 45

5. Brightness
   - grayscale mean
   - optional by default

6. Entropy
   - OpenCV grayscale histogram metric is collected

7. Corruption
   - Pillow decode/verify
   - decoder failure is separated from storage-access failure

For very large images, expensive visual analysis is bounded to a reduced raster while keeping original dimensions for rule decisions. Current MAX_ANALYSIS_PIXELS is 16,000,000.

Cleaning is a quality scan and review flow, not training and not an automatic destructive delete engine. The result contains issues and suggest_delete; user confirmation remains the safe boundary.

## 7. Should cleaning use OpenCV? Yes, for the base image-quality layer

Use the existing OpenCV/Pillow/hash implementation. It is appropriate for deterministic, explainable CPU-side checks such as blur, brightness, corrupt decode, size and duplicate detection.

OpenCV is not the Ground Truth owner and should not decide whether an unlabeled object is missing. Missing-label detection is a separate model-assisted quality audit.

External product patterns support this separation:
- OpenCV documents Laplacian as an image second-derivative/edge operator; the existing Laplacian-variance blur score is a conventional deterministic quality heuristic.
- Roboflow-style dataset health checks separate image/dataset statistics from missing/null annotation review.
- Null/confirmed-empty images are valid negative examples; they must not be treated the same as accidentally missing annotations.

## 8. Does cleaning call server capability? Current answer

Yes, but GPU is not required.

### Default local mode

Durable task:
- TaskKind = MATERIAL_BATCH
- operation = CLEAN
- required capability = materials.batch
- executed by the existing Materials/background Worker

Required practical resources:
- CPU
- RAM
- temporary disk/cache
- Pillow
- OpenCV
- NumPy
- access to the material bytes / storage provider

No CUDA/GPU is required for the current deterministic cleaning checks.

### Optional remote Agent mode

Preflight only offers Agent execution when:
- node connection_mode = agent
- node is online
- effective_capabilities contains cleaning
- selected material identity is stable
- material object_key / size / SHA256 evidence is complete
- storage is portable/readable by the remote execution contract

Durable remote CLEAN uses agent.remote assignment, while product-level node eligibility is cleaning.

Agent cleaning runtime verifies that PIL, cv2 and numpy are importable. If they are missing it reports CLEANING_RUNTIME_UNAVAILABLE rather than pretending to clean.

Remote result upload/commit is SHA256/size/generation fenced. The control plane revalidates the frozen selection and source identity before committing review truth.

Recommendation: keep the node capability name cleaning. Do not introduce a separate opencv capability; OpenCV is an implementation dependency, while cleaning is the product/runtime capability.

For large object-storage datasets, prefer a CPU Agent near the data to reduce cross-network reads. Do not occupy an expensive training GPU just because the server has one.

## 9. Required cleaning product split: annotated vs unannotated

The next cleaning UX should distinguish four material scopes:

- 全部
- 已标注
- 未标注
- 已确认无目标

Do not infer these from box_count alone; use annotation_state and annotation provenance truth.

### Layer A — image-quality cleaning, applies to all images

Run the current deterministic checks on both annotated and unannotated images:
- corrupt
- exact duplicate
- near duplicate
- resolution
- blur
- brightness
- optional entropy/outlier metrics

These checks say whether the image is technically useful, not whether labels are correct.

### Layer B — annotation-quality audit, only for formal annotated images

Add a separate quality category, not a second annotation store.

Recommended checks:
- class id/code exists and is active
- box is inside image bounds
- width/height/area are positive
- extremely tiny / extremely large box warnings
- duplicate or near-identical boxes
- suspicious same-class high-overlap boxes
- per-image object count outliers
- class balance / annotation density summaries
- annotation spatial heatmap/statistics at dataset level
- imported / manual / AI-confirmed provenance visibility

These should usually produce review warnings, not automatic deletion.

### Layer C — unannotated truth

Never equate no boxes with bad data.

- unannotated means labeling is not finished/confirmed. Route it to manual/AI annotation work.
- confirmed_empty means a human explicitly confirmed no target. If image quality passes, keep it as a valid negative sample.
- A model may later flag a likely missing object, but this must enter Candidate/review semantics and must not directly become Ground Truth.

This distinction is important because missing annotations silently train real objects as background, while valid negative images help detection models learn when not to fire.

## 10. Recommended cleaning page design

Do not create a new top-level subsystem. Reuse the current 自动清洗 task owner.

Creation panel:
- 清洗范围: 全部 / 已标注 / 未标注 / 已确认无目标 / selected images
- 执行位置: 中央 Worker (default) / 远程清洗节点 (when preflight available)
- Basic checks enabled by default: corrupt, exact duplicate, near duplicate, low resolution, blur
- Advanced: brightness range, near-duplicate Hamming threshold, resolution limits
- If scope includes annotated images, show annotation quality audit as a separate switch group.

Result page:
- KPI: scanned / passed / needs review / failed
- tabs: 图片质量 / 标注质量
- filters by issue code and annotation state
- each card shows image, annotation status, provenance, issue reason, related duplicate image where applicable
- destructive action remains explicit user confirmation
- do not silently delete labels or formal GT because an image-quality heuristic fired

Animations should be restrained and reuse global motion tokens. Do not animate large result grids on every refresh.

## 11. Cleaning execution recommendation

For normal uploads:
- default to Central Materials Worker
- OpenCV/Pillow CPU checks are sufficient

For tens of thousands of OSS/S3/MinIO images:
- recommend eligible remote cleaning Agent near the object storage/network
- keep the same durable MATERIAL_BATCH/CLEAN truth and review contract
- do not build a second remote-cleaning database

For future semantic quality:
- optional model-assisted missing-label / wrong-label audit can use inference-capable server resources
- keep it separate from deterministic CLEAN
- output AI candidates/suspicion scores only
- human review is required before formal annotation changes

## 12. External reference rationale

The design above follows current common dataset-quality patterns:
- OpenCV Laplacian for deterministic edge/blur-related image analysis.
- Dataset health checks for image sizes, class balance, annotation counts and null/missing annotation review.
- Duplicate removal before training/splitting to avoid over-representing repeated scenes.
- Explicit distinction between valid null/negative images and genuinely missing annotations.

Do not cargo-cult another platform's UI or thresholds; keep thresholds project-configurable and validate against real camera data.

## 13. Immediate next-session sequence

A. Re-read live feature/external-algorithm-publishing HEAD, VERSION, last 20 commits and all completed checks.
B. Read this file before older handoffs.
C. If current HEAD still has Label Normalization source-guard red lights, migrate the guard to semantic/current owner checks; do not restore old source syntax.
D. Focus-reproduce Training Task Visibility real Chrome failure before production change.
E. Reconfirm annotation workflows remain green after any concurrent commits.
F. Only then implement cleaning UX split:
   1) annotation-state scope filters
   2) image-quality vs annotation-quality result categories
   3) local/Agent preflight presentation
   4) review cards and safe confirmation
G. Reuse current platform_core/cleaning.py, MATERIAL_BATCH/CLEAN, CleaningAnalysisRuntime, Remote Cleaning and Agent runtime. No parallel cleaning service.
H. Keep VERSION 42.24.0; no merge/tag/release/force push.


## 14. Live handoff refresh after documentation commit

Latest observed live remote HEAD after the original documentation commit:

- HEAD: 25cde516c14eb777c48c1ab65b8e6fccf80ad337
- commit: docs: hand off annotation and cleaning state
- VERSION.txt: 42.24.0

The branch moved after earlier runtime validation, so a new session must still re-read the live remote HEAD before modifying code.

Current workflow truth observed on 25cde516...:

- 23 workflow runs total
- 21 completed success
- 2 completed failure
- 0 queued
- 0 in progress

Important completed-success workflows:

- Frontend Runtime Stabilization
- AI Annotation Recovery
- Remote Cleaning Runtime
- Remote Material Import
- ZIP Import Durable Runtime
- Task Runtime Truth

Frontend Runtime Stabilization on the latest validated runtime line remains healthy:

- frontend: 741 / 741 passed
- browser-navigation / Real Chrome: 76 / 76 passed

The two current completed failures are:

### 14.1 Label Normalization Contract

Real test groups are green:

- Python API tests: 53 passed
- frontend Node tests: 36 passed / 0 failed

The job fails only in the final source-string guard because it still requires this old exact app.py literal:

`*[str(alias).strip() for alias in item.get('aliases') or []]`

Treat this as stale/mis-scoped source-guard debt. Fix the workflow guard to assert the current semantic owner instead of restoring old implementation text.

### 14.2 Node Agent Executor / Windows

- API job: success
- ubuntu-24.04 contract job: success
- windows-latest contract job: failure
- Windows result: 275 passed / 1 failed

Failing test:

`tests/unit/test_node_agent_training_runtime.py::test_training_fencing_kills_worker_without_stale_terminal_write`

The failed assertion is real and Windows-specific at this observation point. Do not weaken the test. Reproduce/focus the worker fencing + process termination path on Windows and verify stale terminal writes remain impossible.

## 15. Final cleaning architecture decision for the next session

### 15.1 Base cleaning engine

Keep the existing implementation. Do not introduce another cleaning service.

Use:

- OpenCV for blur / grayscale / histogram-derived image metrics
- Pillow for real image decode/verify and corruption detection
- SHA256 for exact duplicate identity
- dHash + Hamming + durable four-band LSH for near-duplicate discovery
- MaterialBatch durable task truth for execution and progress
- CleaningAnalysisRuntime child-process timeout isolation for pathological images

Current deterministic image-quality cleaning is CPU work. GPU is not required.

### 15.2 Server capability contract

Default mode:

- execution_mode = local
- TaskKind = MATERIAL_BATCH
- operation = CLEAN
- durable required capability = materials.batch
- use the central Materials Worker

Optional remote mode:

- execution_mode = agent
- product/node capability = cleaning
- durable assignment capability = agent.remote
- remote runtime must have Pillow, OpenCV and NumPy
- material bytes must be portable through OSS/S3-compatible object storage
- frozen selection, object_key, size and SHA256 evidence must all pass preflight

Do not create an `opencv` node capability. `cleaning` is the product capability; OpenCV is an implementation dependency.

Prefer a CPU cleaning Agent near object storage for very large datasets. Do not consume expensive training GPU capacity for deterministic blur/duplicate checks.

### 15.3 Required annotated/unannotated split

The next cleaning UX must expose:

- 全部
- 已标注
- 未标注
- 已确认无目标
- selected images

Never derive this only from box_count. Use formal annotation_state/provenance truth.

Image-quality checks apply to all scopes.

For 已标注 materials, add a separate annotation-quality audit category:

- invalid/inactive label identity
- out-of-bounds / zero-area boxes
- tiny/huge box warnings
- exact/near-identical duplicate boxes
- suspicious same-class high-IoU duplicates
- unusual object-count / annotation-density outliers
- dataset class-balance and spatial-distribution summaries

These are review warnings. Do not auto-delete Ground Truth.

For 未标注 materials:

- run only deterministic image-quality cleaning
- do not treat “no box” as bad data
- route remaining usable images to manual/AI annotation

For 已确认无目标:

- treat as valid negative Ground Truth when image quality passes
- never downgrade it to unannotated

Future model-assisted missing-label/wrong-label detection must be a separate semantic-quality audit. It may use inference/GPU capability, but its output is suspicion/candidates only and still requires human review before formal Ground Truth changes.

### 15.4 Recommended next implementation order

After clearing current CI red lights:

1. Add cleaning scope filter by formal annotation state.
2. Keep current deterministic CLEAN runtime unchanged.
3. Add separate 图片质量 / 标注质量 result categories.
4. Show local vs Agent execution preflight clearly in the creation dialog.
5. Preserve safe confirmation before deletion or other destructive action.
6. Add annotation-quality rules as review-only checks.
7. Add permanent frontend/backend/source guards for the scope split.
8. Run Remote Cleaning Runtime + Frontend Runtime Stabilization + relevant API/unit/browser tests.

Do not build a second cleaning database, second Worker, second poller, or second review modal owner.
