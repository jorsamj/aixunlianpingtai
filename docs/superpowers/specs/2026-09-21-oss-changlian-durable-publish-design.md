# OSS + 新畅联 durable publish design

## Goal

Build one recoverable delivery chain in which `AlgorithmSqlStore.algorithm_versions` is version business truth, `ModelArtifactStore` is artifact/storage truth, and `ExternalPublicationRepository` is only the remote-operation outbox. Model creation, OSS upload, and ChangLian publication remain distinct states.

## Confirmed contract

- ChangLian business calls use `Authorization: Bearer <accessToken>`.
- `algorithm-version/add` receives `versionName`, `versionNo`, and exactly one of `analysisId` or `productId`; scalar `data` is the remote version ID.
- `algorithm-weight/add` receives `algoVersionId`, `computePlatformId`, `chipCode`, `fileName`, and stable `filePath`; scalar `data` is the remote weight ID.
- `code=0` is the primary success contract. `code=200` remains explicitly documented legacy compatibility until official documentation or production verification rules it out.
- An uncertain POST is reconciled by authoritative list APIs before any retry. UNKNOWN is never blindly retried.
- OSS upload and local durable accounting happen before remote Version/Weight creation.
- All artifacts belonging to one local version reuse one `external_algo_version_id`.
- Rollback deletes the remote version first and does not delete retained OSS artifacts.

## Ownership

### Version business truth

`AlgorithmSqlStore.algorithm_versions` owns local version identity, `version_name`, `version_no`, training linkage, external analysis/version identity, and externally visible publish status.

### Artifact/storage truth

`ModelArtifactStore` owns artifact identity, artifact kind/platform, local evidence, SHA256, size, storage source, canonical object key, public URL, and upload state. It does **not** own provider-specific remote Weight identity.

### Remote-operation outbox

`ExternalPublicationRepository` owns provider-specific mappings (including `external_weight_id`, keyed through `artifact_id`), attempts, retry eligibility, pending/publishing/unknown/failed operation state, last error, and audit/reconciliation state. It references `ModelArtifactStore`; it must not independently own or rewrite `source_path`, SHA256, size, object key, or public URL. Existing duplicate columns/tables remain readable during compatibility migration but must not remain independently writable formal truth.

Before any batch-3 schema change, the migration must use this field-owner table:

| Field | Durable owner | Compatibility boundary |
|---|---|---|
| `version_name`, `version_no` | `AlgorithmSqlStore.algorithm_versions` | old JSON/publication rows may be read during migration only |
| `external_algo_version_id` | `AlgorithmSqlStore.algorithm_versions` | publication outbox may carry an operation result until reconciled, but is not a second business truth |
| `external_publish_status` | `AlgorithmSqlStore.algorithm_versions` | distinct outbox `operation_status` may track an attempt; it must not compete with business status |
| `object_key`, `storage_source_id`, `sha256`, `size`, `public_url` | `ModelArtifactStore` | outbox references `artifact_id` and does not duplicate these fields as writable truth |
| `external_weight_id` | `ExternalPublicationRepository` provider-artifact mapping | keyed by provider + `artifact_id`; never a single-provider property on the artifact body |
| `publish_status`, `retry_count`, `last_error` | `ExternalPublicationRepository` | remote-operation/outbox state only |

Batch 3 is migration -> dual-read compatibility only where required -> single-write owner -> permanent guard -> later deprecation. There is no direct DROP and no long-lived dual-write period.

## OSS configuration model

- `StorageSource` owns connection identity: Endpoint, Bucket, `public_base_url`, AccessKeyId, AccessKeySecret.
- Access credentials remain in Secret Store and are never returned in API payloads.
- Artifact binding owns `storage_source_id` and `root_prefix`, defaulting to `changlian-ai/artifacts/`.
- Material prefixes remain independent; the artifact prefix is not moved into global OSS connection configuration.
- Any existing Storage Provider `prefix` remains a general/legacy provider namespace for non-artifact callers. Artifact publishing does not concatenate it with `root_prefix`: the unified builder emits the final Bucket-relative `artifact.object_key`, including `root_prefix` exactly once, and the upload operation stores that canonical key without reapplying Provider `prefix`.

## Object identity

A single builder produces keys under:

```text
changlian-ai/artifacts/projects/<project_id>/algorithms/<algorithm_id>/versions/<version_id>/
  training/
  onnx/
  rknn/rk3568/
  rknn/rk3578/
  reports/
```

An immutable SHA-based filename may be retained. Callers provide artifact facts; they do not concatenate their own directory paths. `StorageSource.public_base_url + artifact.object_key` is the only public URL composition path; `changlian-ai/artifacts/changlian-ai/artifacts/...` is an invalid key and must be guarded by tests.

## Validation and failure handling

- OSS connection test is PUT -> STAT/HEAD -> READ -> DELETE. Every stage must succeed; cleanup failure is a failed test.
- When `public_base_url` is configured, the generated test object URL must be directly readable.
- Immediately before `algorithm-weight/add`, the actual artifact URL is checked with HEAD or Range GET. Failure closes publication without a remote write.
- Version recovery may query product and analysis lists, but identity always requires `versionName + versionNo` and the locally bound `analysisId`. Multiple or incomplete candidates fail closed as UNKNOWN.
- Weight creation requires all five fields: `algoVersionId`, `computePlatformId`, `chipCode`, `fileName`, and `filePath`.
- Weight recovery requires exact `fileName`, `computePlatformId`, and canonical non-empty `chipCode`; when the remote row supplies `filePath`, it must also match the current stable URL. Multiple, incomplete, or conflicting candidates fail closed.

## Open contracts

- `code=200` remains legacy compatibility / OPEN.
- `analysis getInfo/{analysisId}` may return an object or list; parsing supports both, documentation must not claim the response shape is confirmed.
- Local RKNN support for RK3578 must be established from the actual Toolkit/Agent capability path before changing conversion behavior.
- ChangLian `computePlatformId/chipCode` mapping remains OPEN and cannot be guessed or hardcoded.

## Delivery batches

1. Version/Weight payload validation and idempotent recovery.
2. OSS connection/binding separation, unified key/URL builder, and real connectivity checks.
3. Durable truth compatibility migration and anti-double-write guards.
4. RK3578 local capability audit, product-contract update when proven, documentation and minimal browser smoke.

## Test policy

Only focused unit/API tests and necessary browser smoke are run. Full pytest, full integration, and full Actions are outside this task.
