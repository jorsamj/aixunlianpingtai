# Material Upload Chunking / Server-confirmed Progress Handoff

Date: 2026-09-16
Branch: `refactor/frontend-runtime-stabilization`
Formal version: `VERSION.txt = 42.24.0`

## Why this batch exists

The earlier material-upload performance closure removed the largest backend hot paths:

- request-level Material / Annotation batch commits;
- repeated repository / storage-manager initialization;
- post-copy SHA256 rereads;
- the extra application-level `imports/upload_*` temporary copy;
- plain browser uploads now stream Starlette's seekable/spooled `UploadFile.file` directly to `StorageManager`.

That work improves the server path, but the browser still submitted every selected image as one giant multipart request. For hundreds or thousands of images this has two product problems even when backend processing is healthy:

1. the request is unnecessarily large and fragile;
2. after transfer finishes, the UI has no incremental server-ingest truth until the whole request completes.

This batch addresses those two problems without inventing a second backend upload protocol.

## Runtime contract

`static/modules/material-upload-runtime.js` is the upload owner installed by `static/material-upload-bootstrap.mjs` after the classic application has loaded.

The browser partitions selected files with both limits:

```text
DEFAULT_UPLOAD_CHUNK_SIZE = 64 files
DEFAULT_UPLOAD_CHUNK_BYTES = 128 MiB
```

A single file is never split. Chunks are submitted strictly sequentially to the existing authoritative endpoint:

```text
POST /api/projects/{project_id}/images
```

The backend contract is unchanged. Each chunk returns the existing real persisted result:

```text
batch_id
uploaded[]
failed[]
uploaded_count
failed_count
```

The frontend advances the main progress only after the server response accounts for every file in that chunk. Network transfer is shown separately for the active chunk.

Example for 380 selected images with the default file limit:

```text
64 + 64 + 64 + 64 + 64 + 60
```

The UI can therefore show real server-confirmed state such as:

```text
服务器已处理 128 / 380 · 成功入库 127 · 失败 1
当前批次传输 43%
```

It no longer needs to sit at a synthetic 85% while one giant request finishes all server-side work.

## Why chunks are deliberately NOT concurrent yet

The current backend image-batch compatibility context is request/thread scoped with existing runtime assumptions. This batch does not introduce concurrent chunk requests merely to chase throughput.

Invariant:

```text
max active browser upload chunks = 1
```

Before allowing browser chunk concurrency, the backend batch context / blocking I/O ownership must first be proven coroutine/request-safe and storage/SQLite contention must be measured. Do not change this to `Promise.all()` or an arbitrary concurrency pool.

## Failure truth

There is no automatic retry after an ambiguous network failure.

Reason: if the server committed the current chunk but the response was lost, blindly resending that chunk can duplicate materials. The runtime therefore reports only responses it has actually received, stops at the ambiguous chunk, and tells the user how many files are server-confirmed.

A future retry-safe design requires an explicit idempotency/upload-session contract. Do not fake retry safety in the browser.

## Frontend compatibility

The final success UI intentionally preserves the existing product contract:

```text
成功上传 N 张
本次上传 N 张素材
批量无需清洗
批量清洗
```

The decision buttons still enter the existing `openBatch414('ready', ids)` / `openBatch414('clean', ids)` flow using only IDs returned by the server as successfully persisted.

Both classic entry points are routed to the same runtime:

```text
window.doUploadImages426
window.uploadData424
```

This avoids one upload path being chunked while another silently keeps the old giant multipart behavior.

## Permanent verification

Focused workflow:

```text
.github/workflows/material-upload-chunking.yml
```

It runs:

- Node syntax + unit contracts on Ubuntu;
- Node syntax + unit contracts on Windows;
- permanent source guards;
- Real Chrome upload regression.

Real Chrome test:

```text
tests/browser/material-upload-chunking.spec.mjs
```

Acceptance case:

```text
65 browser-selected images
-> exactly 2 POST /images requests
-> max active requests = 1
-> final UI = server processed 65/65
-> legacy cleaning decisions remain visible
```

Focused workflow run `35108548624` passed:

```text
frontend-contract (ubuntu-24.04)  PASS
frontend-contract (windows-latest) PASS
real-chrome-upload                 PASS
```

The normal Frontend Runtime unit job on the same product HEAD also passed. The broader navigation Real Chrome suite may complete separately because it is an independent long-running regression set.

## Important performance boundary

This closure proves upload architecture, bounded request size, server-confirmed progress and browser behavior. It does NOT claim a production throughput number.

The user's historical observation was roughly:

```text
5m30s -> only ~380 images processed
```

That measurement predates multiple backend upload optimizations plus this chunking runtime. After deployment, repeat the same real-image test and record at least:

```text
selected image count
selected total bytes
browser transfer time
server-confirmed completion time
successful / failed count
storage type / mount
```

Only that real server retest can close the production wall-clock performance claim.

## Do not regress

Do not:

- restore one giant browser multipart request for arbitrary image counts;
- update server-ingest progress from bytes transferred rather than backend responses;
- auto-retry an ambiguous chunk without an idempotency contract;
- make chunks concurrent without first fixing/proving request-scoped backend batch ownership;
- bypass `StorageManager` or create a second material persistence path;
- change formal `VERSION.txt` as part of this closure.
