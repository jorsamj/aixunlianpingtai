# Multi-source Material Storage Implementation Plan

> Execute this plan in order. Each task starts with a failing test and ends with focused verification before the next task.

**Goal:** Add local, Alibaba OSS, S3-compatible, and remote HTTP material storage behind one provider layer while preserving the unified material pool, exact image-ID training, annotations, cleaning, previews, and strict latest-version training.

**Architecture:** A platform-level SQLite storage-source repository and per-project SQLite material repository replace future whole-file JSON writes. `StorageManager` resolves providers and secrets. `MaterialResolver` supplies verified local files through a content-addressed cache. Legacy `images.json` is imported transactionally without moving files. UI and workers use material IDs and unified content URLs.

**Tech Stack:** Python 3, FastAPI, SQLite/WAL, pathlib, filelock, keyring, requests, boto3, oss2, vanilla JavaScript, Node test runner, Playwright, pytest.

---

## Task 1: Storage domain and structured errors

**Files:**
- Create: `platform_core/storage/__init__.py`
- Create: `platform_core/storage/models.py`
- Create: `platform_core/storage/errors.py`
- Create: `platform_core/storage/base.py`
- Test: `tests/unit/storage/test_contract.py`

1. Write failing tests for normalized source types, object metadata, health results, safe public errors, and the required Provider protocol operations.
2. Run `python -m pytest tests/unit/storage/test_contract.py -q` and confirm failure.
3. Implement immutable domain objects, error codes and the provider protocol.
4. Run the focused test and `git diff --check`.
5. Commit `feat(storage): define provider contract`.

## Task 2: SQLite storage-source repository and secrets

**Files:**
- Create: `platform_core/storage/source_repository.py`
- Modify: `platform_core/secrets.py`
- Test: `tests/unit/storage/test_source_repository.py`
- Test: `tests/unit/test_secrets.py`

1. Write failing tests for WAL, default-local seeding, CRUD, one-default invariant, reference protection, health persistence and secret-free serialization.
2. Implement transactional SQLite repository with parameterized SQL and indexed source status/type fields.
3. Extend secret errors and credential helpers so compound credentials remain only in SecretStore.
4. Verify stored SQLite rows and public API models contain no secret values.
5. Commit `feat(storage): persist storage source configuration`.

## Task 3: SQLite material repository and non-destructive migration

**Files:**
- Create: `platform_core/material_repository.py`
- Modify: `platform_core/material_store.py`
- Test: `tests/unit/test_material_repository.py`
- Test: `tests/integration/test_material_migration.py`

1. Write failing tests for CRUD, batch patch/removal, pagination, filename/source/status filters, multi-label OR, revision and concurrent readers.
2. Write migration tests using an unchanged legacy `images.json` and existing upload files.
3. Implement `materials`, `material_labels`, `material_migrations` and revision tables with WAL and transactions.
4. Normalize old rows to `default_local` and `uploads/<stored_name>` without moving or deleting files.
5. Add a compatibility facade for existing store callers and explicit query/batch-update methods so new paths never require a full material list.
6. Verify idempotent migration and unchanged legacy file hashes.
7. Commit `feat(materials): add scalable sqlite repository`.

## Task 4: Local Provider and path confinement

**Files:**
- Create: `platform_core/storage/local.py`
- Create: `platform_core/storage/factory.py`
- Test: `tests/unit/storage/test_local_provider.py`
- Test: `tests/unit/storage/test_factory.py`

1. Write failing tests for upload, streaming read, stat, list, preview, delete and materialize.
2. Add Windows/POSIX traversal tests using `Path` and `PureWindowsPath` inputs.
3. Implement configurable local roots with strict containment checks and atomic upload.
4. Seed `default_local` through the factory; keep type dispatch only in this factory.
5. Commit `feat(storage): implement secure local provider`.

## Task 5: Content-addressed cache and StorageManager

**Files:**
- Create: `platform_core/storage/cache.py`
- Create: `platform_core/storage/manager.py`
- Test: `tests/unit/storage/test_material_cache.py`
- Test: `tests/unit/storage/test_manager.py`

1. Write failing tests for first miss, second hit, concurrent same-hash materialization, zero-byte rejection, SHA mismatch and atomic cleanup.
2. Implement `<data>/cache/materials/<prefix>/<sha256>.<ext>` with per-hash FileLock and atomic replace.
3. Implement source lookup, credential resolution, legacy row normalization, upload and delete orchestration.
4. Ensure missing sources, disabled sources and provider failures include source and object context.
5. Commit `feat(storage): add verified material resolver cache`.

## Task 6: Real S3, OSS and remote HTTP providers

**Files:**
- Create: `platform_core/storage/s3.py`
- Create: `platform_core/storage/oss.py`
- Create: `platform_core/storage/remote.py`
- Create: `remote_material_server.py`
- Modify: `requirements.txt`
- Test: `tests/unit/storage/test_optional_providers.py`
- Test: `tests/integration/test_remote_storage_provider.py`
- Test: `tests/integration/test_s3_minio_provider.py`

1. Write failure-path tests for missing SDK, invalid endpoint, invalid credentials, missing bucket, timeout and forbidden access.
2. Implement boto3-based S3 and oss2-based OSS adapters, including pagination and presigned URLs.
3. Define and implement the versioned remote HTTP material protocol and a real filesystem-backed reference server.
4. Run a real local remote-server upload/list/download/delete flow.
5. Run MinIO integration when Docker or an external MinIO endpoint is available; otherwise report it as environment-blocked rather than passed.
6. Run Alibaba OSS success integration only when real test credentials are supplied; always run the real invalid-credentials path.
7. Commit `feat(storage): add object and remote providers`.

## Task 7: Storage-source and material content APIs

**Files:**
- Create: `platform_core/storage/api_models.py`
- Modify: `app.py`
- Test: `tests/api/test_storage_sources.py`
- Test: `tests/api/test_material_content.py`

1. Write failing API tests for source CRUD, dynamic validation, real health checks, enable/default actions and deletion protection.
2. Assert responses and application logs do not expose secret values.
3. Add unified material content/preview endpoints supporting FileResponse, redirect and streaming proxy modes.
4. Add paginated material list/count/ID endpoints with source and multi-label OR filters.
5. Keep old list endpoint temporarily compatible, but move the current UI to the paginated API.
6. Commit `feat(api): expose secure storage and material endpoints`.

## Task 8: Upload and existing-object import

**Files:**
- Create: `platform_core/storage/import_tasks.py`
- Modify: `platform_core/task_runtime/models.py`
- Modify: `task_worker.py`
- Modify: `app.py`
- Test: `tests/api/test_storage_upload.py`
- Test: `tests/integration/test_storage_import_worker.py`

1. Write failing upload tests for selected source, stream failure, partial batch failure, hash/size persistence and no index on failed upload.
2. Implement `storage_source_id` in multipart upload and provider-backed image validation.
3. Add durable scan/import tasks with prefix, recursion, pagination, duplicate detection and resumable checkpoints.
4. Confirm external import creates only an index and does not populate `project/uploads` or material cache.
5. Verify job persistence across API restart and task-worker restart.
6. Commit `feat(materials): upload and index external objects`.

## Task 9: Safe deletion semantics

**Files:**
- Modify: `platform_core/materials.py`
- Modify: `app.py`
- Test: `tests/api/test_material_storage_deletion.py`

1. Write failing single/batch deletion tests for index-only default, explicit source deletion, confirmation token, provider failure and annotation cleanup.
2. Implement `index_only` and `delete_source` actions with external-source default protection.
3. Keep the index when source deletion fails; prevent deleting referenced storage-source configurations.
4. Verify index-only deletion leaves local, S3/MinIO and remote objects byte-identical.
5. Commit `fix(materials): enforce explicit source deletion`.

## Task 10: Replace direct material path access

**Files:**
- Modify: `app.py`
- Modify: `platform_core/annotation_task_service.py`
- Modify: `platform_core/materials.py`
- Modify: `platform_core/video_tasks.py`
- Test: `tests/integration/test_remote_material_workflows.py`
- Test: `tests/api/test_upload_clean_flow.py`
- Test: `tests/integration/test_persistent_ai_annotation_e2e.py`
- Test: `tests/integration/test_video_task_worker.py`

1. Add tests proving remote-source images work in cleaning, manual annotation preview, AI annotation and video-derived indexing.
2. Replace direct upload-path construction with resolver calls in all active routes and workers.
3. Keep annotation JSON storage independent from image storage; only physical image bytes use Provider resolution.
4. Run `rg` guard tests that reject new active `uploads/stored_name` path construction outside compatibility/provider modules.
5. Commit `refactor(materials): route workflows through storage manager`.

## Task 11: Exact-ID mixed-source training

**Files:**
- Modify: `platform_core/snapshots.py`
- Modify: `platform_core/training_tasks.py`
- Modify: `platform_core/training_splits.py`
- Modify: `app.py`
- Modify: `static/modules/training.js`
- Modify: `static/app.js`
- Test: `tests/api/test_training_request.py`
- Test: `tests/unit/test_portable_dataset.py`
- Test: `tests/integration/test_training_storage_sources.py`

1. Write failing tests that reject dataset grouping fields at API and Worker boundaries.
2. Remove `train_dataset_ids`, `test_dataset_ids`, dataset fallback, and current UI `dataset_id/val_image_ids` submissions.
3. Add storage references to snapshots without endpoints or credentials.
4. Materialize local and remote images through StorageManager into the same portable bundle, preserving exact requested IDs.
5. Test cache miss, subsequent hit, source removal, SHA mismatch, mixed-source bundle and no silent skipping.
6. Re-run strict latest-algorithm-version training tests.
7. Commit `feat(training): materialize exact image ids from any source`.

## Task 12: Configuration and unified material-pool UI

**Files:**
- Modify: `static/app.js`
- Modify: `static/style.css`
- Test: `tests/frontend/storage-source-ui.test.mjs`
- Test: `tests/browser/storage-material-flow.spec.mjs`

1. Write source-order tests proving “素材存储配置” only appears under expanded resource configuration.
2. Add source list, create/edit/test/enable/default/delete and import controls in the current visual style.
3. Add upload-location selector and lightweight source filter/badge to the existing material page.
4. Move material browsing to paginated APIs while preserving tag OR, search and exact selection semantics.
5. Run browser flow: create local source, test connection, upload, preview, filter, annotate, clean and create exact-ID training task.
6. Commit `feat(ui): manage and select material storage sources`.

## Task 13: Performance, migration and regression acceptance

**Files:**
- Create: `tests/performance/test_material_repository_scale.py`
- Modify: `README.md`
- Modify: `VERSION.txt`
- Modify: deployment/startup documentation as required

1. Generate disposable SQLite indexes for 100k, 500k and 1m rows without touching user data; record import, count, page and filter timings.
2. Run repeated API/Worker/browser workflows, refresh/restart recovery and concurrent operations.
3. Run full suites:
   - `python -m pytest -q`
   - `npm test`
   - `npm run test:browser`
4. Start API and task worker from a clean process, verify health/version, and run the real acceptance flow.
5. Update README and version only after behavior is verified. Record environment-blocked vendor integrations explicitly.
6. Run `git diff --check`, inspect the final diff, confirm user untracked files remain untouched, and commit `release: 42.22.0 multi-source material storage`.
