# 2026-10-09 UAT｜ZIP 素材导入等 7 项问题修复进展与验收边界

> Source of truth: GitHub Issue #21. This document records **code changes vs verification separately**. It does not authorize production deployment or data deletion.

- Repo: `jorsamj/aixunlianpingtai`
- Branch: `feature/external-algorithm-publishing`; base before repair: `474d7f694228632b9fc55a2f20ac7c7cbdb791ac`
- Version history for this issue: `42.24.335 -> 42.24.336` (initial repair), then `42.24.337` (read-only audit hardening and regression coverage).
- **Current implementation is committed but CI is not yet green: HEAD check-runs were queued when this note was written.** Always re-fetch real HEAD and check-runs before declaring safe to deploy. No production deployment or server mutation in this round.
- Existing unrelated frozen external-weight inheritance requirement remains GitHub Issue #20; out of scope.

## Incident evidence — retain without reimport
Project `f1fb1e6fa373`, import job `da0ac602ba454a33`, ZIP `Employee_Sleeping.v1i.yolov11.zip`.
- Initial multipart: 377744045 bytes, 46 parts of 8 MiB (last shorter), 44/46 persisted; missing indexes 31,41. Root transport cause unknown.
- Subsequent import state: `failed/FAILED`, `selected_count=processed=imported_images=3042`, `annotated_images=3034`, `boxes=3145`, `skipped_images=0`, `imported_image_ids=3042`.
- Fatal error `formal annotation admission is limited to 500 image ids; 素材已写入正式索引但后续步骤失败，已保留源文件和索引供完整性修复`.
- Report totals are **not** evidence of fully committed formal Ground Truth. Protect Material/Annotation/source files/ZIP and do not repeat the job, delete temporary storage, or include the affected records in training before auditing.
- Read-only audit tool: `python tools/audit_v19_partial_import.py --project-root /data/platform-data/projects/f1fb1e6fa373 --job-id da0ac602ba454a33` (run only from a checkout containing the new tool; no database writes).
- **Production's 3042 records have NOT been repaired or verified in this chat.** Need read-only report, backups, conflict checks and separately approved recovery/deployment.

## Implemented changes by BUG
| Item | Committed change | Verification still required |
| --- | --- | --- |
| BUG-01 (P1) | OSS endpoint parser traps malformed URL/port and returns structured `PlatformError(422)`; invalid endpoint test. | API and OSS regressions + live configuration test |
| BUG-02 (P3) | Training resource empty-state message directs operator to read environment; relevant frontend cache advanced. | Browser UX smoke |
| BUG-03 (P1) | ZIP part XHR bounded timeout, abort other in-flight browser requests on terminal part failure; sessions retain successful chunks for resume. | Simulated timeout plus real large-file LAN/WAN trial; original specific network cause not proven |
| BUG-04 (P2) | Explicit “继续上传” in existing task dialog; choose exact original ZIP with `resume_upload_id`; backend rejects wrong file/session with 409 *before* a second upload task is created. | Refresh/missing parts/expired session/different-file tests and browser end-to-end |
| BUG-05 (P0) | Existing formal material admission 500 limit preserved; `_v50_end_image_batch` chunks deferred GT and postwrite reads <=500; failed V19 tasks with any indexed report IDs blocked from naive retry; 501-image test; read-only discrepancy auditor. | 3k/10k real imported Ground Truth + projections, failure injection, and **existing production data repair** |
| BUG-06 (P2) | Replace contents of original chooser modal with ZIP transfer UI instead of asynchronous close followed by another modal; display errors in same runtime root. | Real browser modal stack/close/dock reopen smoke |
| BUG-07 (P1) | New upload `pause`, `cancel` APIs on canonical ZipMultipartRepository; cancel tombstones and drains per-part writers before removing part bytes; paused state retained in task center; UI pause, continue, cancel. New V19 worker `stop` request only during queue/extract/annotation parse; worker checks cancel flag, guarded DB commit fence and staged-file rollback; refuses abort once commit begins. Tests added for multipart and stop boundaries. | Long-running worker interruption, cross-process race/GC and browser tests. **A durable pause/resume of an already-running extraction/annotation worker is NOT implemented** (safe stop is, and upload pause is). |

## Data safety and architecture
1. Do not change `MaterialRepository.assert_formal_annotation_admission`'s 500-ID protection or bypass `AnnotationRepository`. Do not introduce separate owner/scheduler, duplicate poller or modal stack.
2. `cancel` clears uncommitted multipart bytes only; once ZIP merging/validation/structured commit begins, destructive cancellation is refused. `stop` during uncommitted V19 worker phases rolls back staged uploaded image files; commit/partial-commit is fail-closed and needs audit.
3. Frontend and backend must agree on paused, cancelled, uploading, and running status. Only verified success may be displayed as done. Browser module query versions were incremented.
4. A 409 prevents reusing a failed task with indexed material. This alone does **not** repair earlier partial writes and is not permission to reimport files manually.
5. No production edits, deploy, merge main, tag or release without explicit instruction.

## Regression commands / CI acceptance
```bash
pytest -q tests/api/test_v19_import_bounded_admission.py tests/api/test_v19_multipart_controls.py tests/api/test_v19_import_failure_rollback.py tests/unit/test_zip_multipart.py tests/unit/test_model_artifacts.py
node --test tests/frontend/zip-multipart-upload.test.mjs tests/frontend/zip-import-durable-runtime.test.mjs tests/frontend/upload-task-center.test.mjs
```
**These commands are proposed; do not mark as passed unless execution is observed.** Check final HEAD's required workflows, including material annotation atomicity, frontend/runtime, API and browser. Queued/pending is not success.

## Open acceptance blockers
- Actual safe repair and independent reconciliation report for the live 3042-image failed import, after backup and authorized deployment.
- CI and browser end-to-end smoke for the exact final HEAD.
- Root-cause evidence for the missing network chunks and proof a repeated 360 MiB+ ZIP upload recovers with no duplication.
- Product scope clarification if persistent pause/resume of a **background worker** (rather than safe stop/restart) is required; not silently presented as implemented.

**Status:** CODE PATCHES COMMITTED; INTEGRATION VERIFICATION AND LIVE DATA REPAIR OPEN. Do not close Issue #21 until both are complete.

## 2026-10-09 continuation — independent verification gap and auditor hardening

- Re-read remote development HEAD `0cf233602a34bb27ee2a620e1ca02d2371f10b86` and `VERSION.txt=42.24.336`; its **55/55 check-runs queued** and 21 related runs queued when sampled. This is *not* a successful CI report.
- Found a concrete acceptance blind spot in `tools/audit_v19_partial_import.py`: the previous report checked source existence, Material/Annotation rows and digest projections, but did **not** recompute source SHA256, check material source size, formal boxes vs report totals or box import provenance. Counts of indexed materials could not establish safety.
- Additional code commits: `fdbb38828f22` (bounded, read-only SHA256/source/box/lineage/report reconciliation), `2d97a439cfd9` (four new regression tests), `dbf6698e5d10` (portable SQLite read-only URI). `61e8edce0654` wires these and the existing 501-image, stop and multipart regression tests into `.github/workflows/zip-import-durable-runtime.yml`, including a push path filter.
- New audit is **read-only** and explicitly returns `training_approved=false`. All checks require running against a *consistent backup of production project data* after ensuring its SQLite databases, report.json and local source bytes belong to the same snapshot. Source hashes are checked by default; `--skip-source-hash` is permitted only for incomplete triage, never acceptance.
- Recommended read-only command (against backup, not directly against mutable production databases):

```bash
python tools/audit_v19_partial_import.py --project-root /PATH/TO/CONSISTENT_PROJECT_BACKUP --job-id da0ac602ba454a33
```

- If Material references a remote or non-default local Storage Source, the auditor reports `source_requires_provider_verification` instead of claiming missing/verified bytes. Provider-specific HEAD/GET + SHA256 comparisons must be completed separately.
- An audit can detect mismatches but **does not repair** them. Before proposing recovery: confirm current running server release/worker version, capture backup manifest, compare all 3042 IDs including missing/duplicate Material and formal GT, protect any already-correct GT, then design a separately reviewed idempotent recovery with dry-run/conflict-detection. Do not retry the failed import, delete bytes or release data to training.
- **No local execution or CI pass is claimed for new tests yet**; Python runner/repo clone and production SSH access were not available in this continuation. GitHub actions must reach terminal success on the final exact HEAD before launch discussion. Worker extraction pause/resume remains outside the implemented scope (upload pause + guarded worker stop are implemented).

## 2026-10-09 additional 3042-image integration coverage

- Commit `c69304e4804f939ab21d44b5923e841a5b30b976` parameterizes the existing real Material/Annotation bounded-admission regression at **501 and 3042 images**. The test checks every canonical 500-ID chunk, without raising the 500-ID protection limit.
- ZIP Import Durable Runtime workflow was updated to execute the 3042 regression, multipart API controls, rollback/stop contracts and the read-only integrity auditor tests. This is code and CI configuration committed, **not proof these tests have passed**.
- Live production backup, source/GT cross-checks and authorized recovery remain the gating P0 task.
