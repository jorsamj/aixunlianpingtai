# TAKEOVER PROMPT — 2026-09-25 ANNOTATION + CLEANING

Continue GitHub repository jorsamj/aixunlianpingtai on long-lived branch feature/external-algorithm-publishing.

This is a continuation of the 畅联云算法训练平台. Do not redesign the architecture and do not repeat CLOSED work.

## Mandatory first step

Before modifying anything, re-read the live remote truth:

1. current origin/feature/external-algorithm-publishing HEAD
2. VERSION.txt
3. at least the latest 20 commits
4. current GitHub Actions/check-runs
5. every completed failure real job log
6. relevant production code/tests/workflows
7. final runtime/owner actually in effect

The handoff cutoff before documentation was c1e9dc2dbae57c0c36c251e95f918a0ffac8ec3e, but you MUST NOT assume it is still current.

Read first:
- docs/CODEX_HANDOFF_2026-09-25_ANNOTATION_CLEANING.md
- docs/PROJECT_HANDOFF_CURRENT.md
- docs/CODEX_CURRENT_STATE.md

## Absolute rules

- no merge main
- VERSION.txt must remain 42.24.0
- no tag/release/force push
- do not delete/weaken tests
- queued/in_progress is not pass
- read real log for every completed failure
- no production mocks
- no second annotation owner/GT store/poll loop/modal owner
- no second cleaning runtime/store
- Windows 11 dev + NVIDIA Linux production
- no hardcoded Windows paths
- Web stays 127.0.0.1:8010

## Annotation truth already CLOSED

Canonical product chain:
AI inference -> Candidate -> AWAITING_CONFIRMATION -> human review -> accept/reject/edit -> Commit -> formal Ground Truth.

Formal states:
unannotated / annotated / confirmed_empty.

Derived provenance:
manual / ai_confirmed / mixed / imported.

Transient UI may show:
AI待审核 / AI正在入库 / AI候选失败.

The backend is the provenance owner:
- existing AI box provenance survives manual geometry/label edits
- new browser-drawn boxes are manual
- AI + manual derives mixed
- structured imports derive imported
- legacy provenance recovery and reindex preservation exist
- preview-limit parity exists

Legacy v47 AI annotation write backend is retired. Frontend uses durable v60 annotation tasks. Do not restore v47 direct-confirm write flow.

Manual workbench and AI Review UI are already professionalized and have permanent owner/performance guards. Do not add animation to pointermove/drag/resize. Reduced-motion must remain complete.

Earlier validated evidence:
- Frontend tests 741/741
- Real Chrome 76/76
on runtime HEAD 0db514bed31a5c83c970f47122c54982018cf8b4.

At cutoff c1e9dc2d:
- 34 workflows
- 31 success
- 3 failure
- Frontend Runtime Stabilization success
- AI Annotation Recovery success
- Remote Cleaning Runtime success
- Remote Material Import success
- ZIP Import Durable Runtime success
- Task Runtime Truth success

Known red lights at cutoff:
1) two Label Normalization Contract failures: API/frontend tests were green; final source guard still expects old exact alias implementation literal. Treat as stale/mis-scoped guard first, not a reason to restore old code.
2) Training Task Visibility real Chrome: table stayed 暂无记录 instead of showing the mocked refreshed running task. Focus reproduce; not yet classified stale.

## New priority: uploaded-data cleaning

User wants uploaded images to be cleaned and clearly split by annotation truth.

DO NOT build a new cleaning subsystem. Existing runtime is:
- platform_core/cleaning.py
- CleaningAnalysisRuntime
- durable MATERIAL_BATCH / CLEAN
- local Materials Worker capability materials.batch
- optional Agent remote execution
- frontend owner static/modules/cleaning.js

Current deterministic checks:
- SHA256 exact duplicates
- dHash/Hamming near duplicates
- resolution bounds
- OpenCV grayscale + Laplacian variance blur
- brightness mean
- entropy metric
- Pillow corruption/decode verification
- bounded raster analysis for huge images

OpenCV is the correct base image-quality engine. It is CPU work; GPU is not required.

Execution:
- default Central Worker
- optional remote Agent only when preflight proves online agent + effective cleaning capability + portable stable storage evidence
- durable remote assignment uses agent.remote
- Agent runtime requires PIL/cv2/numpy and fails closed if missing
- do not add an opencv capability; keep product capability cleaning

Required UX/data split:
- 全部
- 已标注
- 未标注
- 已确认无目标

Layer A image-quality checks apply to all.

Layer B annotation-quality audit applies only to formal annotated images:
- active/valid class identity
- box bounds/positive dimensions
- tiny/huge box warnings
- duplicate/high-overlap boxes
- object-count outliers
- class balance / annotation density summaries

Layer C:
- unannotated != bad image; route to annotation
- confirmed_empty is a valid negative sample if image quality passes
- model-assisted missing-label detection must be a separate AI suspicion/candidate flow; never auto-write GT

Recommended result UI:
- scanned/passed/needs review/failed KPI
- tabs 图片质量 / 标注质量
- filters by issue and annotation state
- provenance badge on each card
- related duplicate image
- explicit confirm before destructive action
- no silent label/GT deletion

Prefer Central Worker for normal uploads. For large OSS/S3/MinIO datasets, prefer a CPU Agent near the data. Do not consume training GPU just for OpenCV cleaning.

## Continue sequence

1. refresh live HEAD and CI
2. clear only real current CI failures
3. verify annotation owner/provenance not regressed
4. implement cleaning scope split on the existing durable runtime
5. add annotation-quality audit without new GT owner
6. keep local/Agent frontend-backend contract consistent
7. add focused API/frontend/Real Chrome permanent guards
8. preserve restrained UI motion and performance
9. report exact HEAD, tests passed, queued/in-progress, completed failures, and next action after each batch
