# OSS + ChangLian Durable Publish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make version/weight publication, OSS artifact delivery, and local recovery use one explicit durable truth per responsibility.

**Architecture:** Preserve the current Provider and runtime boundaries. Tighten the existing ChangLian publication service first, then move storage identity into `ModelArtifactStore` while reducing `ExternalPublicationRepository` to an outbox through compatibility migration rather than destructive table removal.

**Tech Stack:** Python 3, FastAPI, Pydantic, SQLite, Aliyun `oss2`, JavaScript runtime modules, pytest, Node test runner, Playwright only where UI smoke is necessary.

---

### Task 1: Tighten Version and Weight contracts

**Files:**
- Modify: `platform_core/external_algorithm_publish.py`
- Modify: `platform_core/external_algorithm_platform.py`
- Test: `tests/unit/test_external_algorithm_publish.py`
- Test: `tests/unit/test_external_algorithm_platform.py`

- [x] Add failing tests proving `versionNo` comes from durable `version_no`, Version recovery uses product then analysis results, and a near-match never recovers the wrong remote ID.
- [x] Run only the new pytest nodes and confirm the expected contract failures.
- [x] Implement strict matching on `versionName + versionNo + bound analysisId`; product/analysis list endpoints are query paths, not weaker identities.
- [x] Add failing tests proving all five Weight fields are required and recovery requires exact canonical `fileName + computePlatformId + chipCode`, plus returned `filePath` when present.
- [x] Run the new nodes and confirm the expected failures.
- [x] Add minimal fail-closed validation and strict recovery matching, including no remote Version POST when Weight prerequisites are incomplete.
- [x] Keep `code=200` compatibility, label it in source as legacy/OPEN, and retain tests for both `0` and `200`.
- [x] Run focused Version/Weight tests and commit the batch.

### Task 2: Separate OSS connection from artifact binding

**Files:**
- Modify: `app.py`
- Modify: `platform_core/storage/source_repository.py`
- Modify: `platform_core/model_artifacts.py`
- Modify: `static/modules/storage.js`
- Modify: `static/modules/model-artifact-runtime.js`
- Test: `tests/api/test_storage_sources.py`
- Test: `tests/unit/test_model_artifacts.py`
- Test: `tests/frontend/storage-source-ui.test.mjs`
- Test: `tests/frontend/model-artifact-runtime.test.mjs`

- [x] Add failing tests for StorageSource `public_base_url` and artifact binding default `root_prefix=changlian-ai/artifacts/`.
- [x] Implement connection/binding persistence without moving material prefixes.
- [x] Record that existing Provider `prefix` remains general/legacy scope, while Artifact Binding `root_prefix` is the sole artifact namespace; the canonical builder must include it exactly once.
- [x] Add failing tests for the unified training/onnx/rknn/reports key mapping and immutable filename.
- [x] Implement one object-key builder and one public-URL builder; upload the already-canonical Bucket-relative key without reapplying Provider `prefix`.
- [x] Add failing tests for PUT, STAT, READ, DELETE and public URL reachability, including cleanup failure.
- [x] Implement the real health flow and pre-Weight artifact URL probe.
- [x] Run focused storage/model-artifact tests and one storage UI smoke if markup changed.
- [x] Batch 2.1: retain legacy publish storage fields only as migration inputs; remove them from defaults/new durable writes and prove runtime reads only the new owners.
- [x] Batch 2.1: reject empty project/algorithm/version identities and require a full 64-character hexadecimal SHA256 in canonical object keys.

### Task 3: Make repositories single-truth owners

**Files:**
- Modify: `platform_core/model_artifacts.py`
- Modify: `platform_core/external_algorithm_publish.py`
- Modify: `.github/workflows/external-algorithm-publish.yml`
- Test: `tests/unit/test_model_artifacts.py`
- Test: `tests/unit/test_external_algorithm_publish.py`

- [x] Record the corrected owner matrix: `AlgorithmSqlStore` owns local algorithm/version business facts; `ModelArtifactRepository` owns file/storage facts; `ExternalPublicationRepository` owns provider-specific Version/Weight mappings, outbox, retry, error, and UNKNOWN state.
- [x] Add failing tests for `provider` identity and `UNIQUE(provider, project_id, algorithm_id, version_id)` on Version publications.
- [x] Add failing tests for the new `external_artifact_publications` mapping keyed by `UNIQUE(provider, artifact_id)` and prove it stores no file/storage truth.
- [x] Add failing legacy backfill tests for Version publications and Artifact/Weight mappings, including a second migration run that creates no duplicate rows.
- [x] Add failing conflict tests proving different legacy/new Version IDs and Weight IDs become `UNKNOWN` with an explicit reconciliation diagnostic and never trigger a remote POST.
- [x] Implement additive, idempotent schema migration. Keep `algorithm_versions.external_*` columns and `external_model_artifacts` physically present as frozen compatibility sources; do not DROP them.
- [x] Backfill legacy Artifact file/storage truth into `ModelArtifactRepository`, and backfill only provider-specific remote mapping into `external_artifact_publications` through `artifact_id`.
- [x] Switch publication status, publish, auto-publish, retry, Weight sync, and rollback readers to the new publication owners.
- [x] Stop all runtime writes to `algorithm_versions.external_algo_version_id`, `algorithm_versions.external_publish_status`, and `external_model_artifacts`.
- [x] Project `external_algo_version_id` and `external_publish_status` from `ExternalPublicationRepository` in the service response without writing them back to `AlgorithmSqlStore`.
- [x] Add permanent source guards for provider identity, single-write ownership, frozen legacy tables, and conflict fail-closed behavior.
- [x] Run only the directly affected publication/model-artifact test nodes, then commit and safe-push.

**Approved field ownership:**

| Fact | Canonical durable owner | Migration/compatibility rule |
|---|---|---|
| Algorithm product/category/provider/analysis relationships | `AlgorithmSqlStore.algorithms` | Publication request snapshots never overwrite algorithm business identity. |
| Version name/no, bound analysis, training/artifact readiness | `AlgorithmSqlStore.algorithm_versions` | Legacy remote fields remain physical but become read-only migration sources. |
| Provider Version ID/status/attempts/errors/timestamps | `ExternalPublicationRepository.external_version_publications` | Key and uniqueness include `provider`; conflict becomes `UNKNOWN`, never timestamp-winner. |
| File name/path/hash/size/storage/object/public URL/storage status | `ModelArtifactRepository.model_artifacts` | Legacy `external_model_artifacts` can seed missing canonical rows once and is then frozen. |
| Local artifact chip identity | `ModelArtifactRepository.model_artifacts.chip_code` | Represents the actual generated artifact platform. |
| Provider compute platform/remote chip/Weight ID/sync state | `ExternalPublicationRepository.external_artifact_publications` | Keyed by `provider + artifact_id`; references file truth through `artifact_id` only. |

### Task 4: Audit and adopt RK3578 where locally proven

**Files:**
- Modify only after capability proof: `platform_core/conversion.py`, RKNN Agent/runtime owners, relevant frontend target selector
- Modify: `docs/CHANGLIAN_CORE_INTEGRATION.md`
- Modify: `docs/CHANGLIAN_APIFOX_API_CATALOG.md`
- Test: relevant RKNN capability/unit tests and one conversion selector smoke

- [ ] Add a capability test that probes RK3578 through the same Toolkit/Agent path used in production.
- [ ] If the probe contract is supported, replace the product target RK3576 with RK3578 across the authoritative owner and focused tests; otherwise report the concrete blocker without faking support.
- [ ] Keep computePlatformId/chipCode mapping unset until real ChangLian master data is confirmed.
- [ ] Mark analysis detail object/list and code=200 as OPEN in integration docs.
- [ ] Run focused RKNN tests and the minimal browser smoke, then commit.

### Task 5: Final focused verification and handoff

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/CODEX_HANDOFF_2026-09-21.md`
- Modify: `docs/PROJECT_HANDOFF_CURRENT.md`
- Modify: `docs/CODEX_CURRENT_STATE.md`
- Modify other current owner/closure docs only where their stated truth changed

- [ ] Run the focused test commands recorded by each batch; do not run full pytest or full integration.
- [ ] Verify branch, HEAD, VERSION, worktree, and targeted test evidence.
- [ ] Record confirmed contracts and remaining production-environment OPEN items without claiming real ChangLian E2E.
