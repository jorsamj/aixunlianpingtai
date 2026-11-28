# Training Conflict and Annotation Governance Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for isolated backend implementation and independent reviews; execute integration and visual verification in this existing worktree. This plan is approved in scope by the user on 2026-10-17; do not pause for the same design approval again.

**Goal:** Resolve training duplicate-GT conflicts without deleting protected historical materials, through shared preflight diagnostics, existing annotation editing, explicit new-input adjustment and final freeze revalidation.

**Architecture:** TrainingCompatibility and training_splits share the SHA/GT conflict analysis used by material governance. MaterialRepository/AnnotationRepository remain canonical; source GT and task label projection are distinct. Existing annotation workspace and MaterialBatchRuntime own editing/deletion; no extra worker, polling owner, storage API, or GT store.

**Tech Stack:** Existing Python/FastAPI/SQLite repositories, plain JS/CSS modules, Node24 tests, pytest, Playwright real Chrome.

## Boundaries

- Baseline5a28e4539b81c03b4eaa27fa4b6c718138542169; VERSION42.24.356 unchanged.
- Local changes/tests/commits only; no push, production access, deletion, deployment, main merge.
- Original supplementary source: C:/Users/jorsam/.codex/attachments/f7a4f531-09e5-4a00-935f-f1b4f19e6366/已粘贴的文本.txt. Full preceding UI attachment not found; implement confirmed user scope without inventing extra requirements.
- Reject SHA cross Train/Test even when annotation conflicts coexist. Preserve existing component splitting and frozen Test guarantees.
- No blanket FAILED-task unprotection. Report reasons; any change requires absence of all immutable evidence and comprehensive regression. Keep conservative safety if evidence insufficient.

## Task 1 — Canonical structured duplicate diagnostics and admission

Files: platform_core/training_splits.py, training_compatibility.py, training_tasks.py, remote_training_tasks.py; existing training API router/app.py only where necessary. Tests: tests/unit/test_training_splits.py plus focused compatibility/API tests.

- [ ] RED parameterize state/scope/category/coordinates differences and same-GT duplicates; cross-role SHA leakage cannot be hidden by an annotation error.
- [ ] Add shared pure analysis next to training_annotation_digest, returning real SHA, IDs, filenames, role, state/scope, labels, box counts/digest and conflict types. Keep pagination/bounded previews at API boundary, not a second persisted truth owner.
- [ ] Reuse existing compatibility preflight; report original GT conflicts separately from projected task GT. Final creation and freeze re-evaluate, preserving material/annotation revisions and content identity.
- [ ] Preserve existing ValueError-compatible errors for old callers, enrich durable preparation evidence for failed-task diagnosis. Historical data without freeze must explicitly describe current versus recorded evidence.
- [ ] GREEN commands: python -m pytest --noconftest tests/unit/test_training_splits.py tests/unit/test_training_label_contract.py -q; focused real compatibility/API tests via existing isolated fixtures.

Example invariant:
```python
assert training_annotation_digest(original_a) != training_annotation_digest(original_b)
assert report['conflict_group_count'] == 1
assert report['groups'][0]['content_sha256'] == original_a['content_sha256']
assert report['groups'][0]['images'][0]['image_id'] == original_a['id']
```

## Task 2 — Reference provenance and zero-delete governance

Files: platform_core/material_batches.py and existing integrity API tests; static/app.js existing governance presentation.

- [ ] RED use actual TaskRepository/ArtifactStore: FAILED/no-freeze still protects payload today; enumerate no-freeze/valid-freeze/started/success/model/Test/active/multiple references.
- [ ] Expose bounded provenance classifications from existing historical-reference owner; keep set-returning protection contract and safety unless absence of formal dependencies is positively established. No history mutation or failed-task deletion.
- [ ] Zero-delete preview keeps selection/context, explains selected/protected/skipped counts and MULTIPLE_PROTECTED_REFERENCES versus manual-GT conflicts; expose diagnosis and existing annotation edit rather than a dead confirm button.
- [ ] GREEN: python -m pytest tests/api/test_material_integrity.py tests/api/test_material_batching.py tests/api/test_annotation_sqlite_dataset_delete_atomicity.py -q --tb=short.

## Task 3 — Shared conflict UI and image-first annotation workspace

Files: existing static/app.js annotation/governance functions, static/styles.css, training submit/material summary/recovery modules only where needed. Reuse existing AnnotationRepository API and viewer, not another GT editor.

- [ ] RED Node/Chrome verify current conflicting selection is blocked before POST; diagnosis opens actual image content and correct boxes, user edits via canonical annotation API, rechecks and creates one new task.
- [ ] Desktop workspace: primary image canvas, grouped tools, padded header/footer, separate object list and class picker. Mobile: image first, scrollable controls, no whole-page horizontal overflow; preserve viewport shortcuts, zoom and save semantics.
- [ ] Replace business label 待审核标签 with 未检查类别 where it means missing review scope, default collapsed with count; expanding does not mutate scope; deliberate check/save retains negative-sample semantics.
- [ ] New-input exclusion is explicit and auditable, never deletion, never automatically choose correct GT, never bypass cross-role leakage or immutable Test. Return to preserved training draft and run server preflight again.
- [ ] Historical failure entry identifies recorded/current evidence, input failure versus interrupted running, no checkpoint resume for pretraining failure.
- [ ] GREEN Node24 full: node24 --test 'tests/frontend/*.test.mjs'. Chrome governance/material workflows/training creation/compatibility specs with workers1 and isolated backend8011.

## Task 4 — Integrated verification, reviews and local delivery

- [ ] Run targeted Python, full Node, real Chrome at1920×1080/1440×900/1366×768/375×812; reduced motion, keyboard, failed images, non4:3 dimensions.
- [ ] Performance100/1000/10000 server-side summary and bounded page; record baseline/after and transport scope, not production claims.
- [ ] Independent spec review then quality/security review; resolve all verified P0/P1 before completion. Preserve existing safe-delete tests.
- [ ] Update AGENTS.md and four handoff documents; add acceptance report mapping user's20cases to actual tests and explicit NOT VERIFIED boundaries.
- [ ] Save real screenshots/API/Worker logs outside tracked product data. Production case SHA0dcb43b6… / IDs57512edb455f4b16,11916bbdb5c64595 receives read-only procedure only, not invented findings.
- [ ] Verify VERSION unchanged and git diff --check, commit only reviewed files locally; report exact HEAD/dirty status. GitHub Actions NOT RUN (no push authorized).
