# Label Integrity Audit And Repair Implementation Plan

> Scope: implement the approved label-integrity audit and orphan-repair flow without changing `VERSION.txt`, creating a new task runtime, or modifying the training dialog.

## 1. Annotation truth lookup and projection coverage

- Add failing repository tests for fast source-label lookup, all-state `annotation_scope` coverage, legacy fallback reconciliation, and write/remap/remove maintenance.
- Add an AnnotationRepository-owned derived reference index and revision/fingerprint metadata.
- Make MaterialRepository project every concrete annotation scope for comparison purposes, including annotated records.

## 2. Full Audit durable task

- Add failing API/unit tests for a project-level `AUDIT_LABEL_INTEGRITY` request with no material selection.
- Add the dedicated prepare/run branch under `TaskKind.MATERIAL_BATCH` and `MaterialBatchHandler`.
- Scan AnnotationRepository first, compare governance second, then compare MaterialRepository projection.
- Persist a task-scoped SQLite audit snapshot containing metadata, summary, grouped issues, image details, counts, class-id distributions, and repository fingerprints.

## 3. Orphan Repair creation and execution

- Add failing tests proving current AnnotationRepository truth is re-read at repair creation, partially stale audit results are accepted, inactive targets are rejected, and only still-affected images are frozen.
- Freeze `image_id`, `expected_digest`, source label, and current target canonical identity in the existing remap selection/runtime.
- Keep CAS/idempotency behavior during execution and populate canonical identity fields for remapped boxes.

## 4. Unify retirement invariant

- Add failing integration tests proving source retirement is blocked unless AnnotationRepository boxes/scopes and MaterialRepository labels/scopes are all zero.
- Use the AnnotationRepository reference index for high-frequency source-scoped verification.

## 5. Label Management UI and diagnostics

- Add focused frontend tests for the existing Label Management page's “标签完整性” section, audit task polling, explicit target mapping, and repair creation.
- Reuse the existing polling owner and keep the training dialog unchanged.
- Preserve fail-closed training behavior and point orphan errors to 标签管理 → 标签完整性.

## 6. Verification and handoff

- Run only directly related backend/frontend tests.
- Update `docs/codex-handoff.md` and the existing label-governance documentation owner.
- Review the diff, commit, and push only to `feature/external-algorithm-publishing`.
