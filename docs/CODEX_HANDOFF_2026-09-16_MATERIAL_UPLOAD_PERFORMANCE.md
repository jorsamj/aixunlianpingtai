# Material Upload Performance Handoff — 2026-09-16

Repository: `jorsamj/aixunlianpingtai`

Branch: `refactor/frontend-runtime-stabilization`

Formal version remains exactly:

```text
VERSION.txt = 42.24.0
```

## Status

```text
Plain Multi-image Upload Backend Performance
PRODUCT CODE: CLOSED
PERMANENT WINDOWS + LINUX + API REGRESSION: CLOSED
REAL SERVER 380-IMAGE TIMING ACCEPTANCE: PENDING
```

Do not claim a percentage speedup until the current branch is deployed and the same production-shaped image batch is measured on the real server.

## Final implementation chain

The upload path is now intentionally one request / one batch boundary from the browser through durable material persistence.

### 1. Browser request shape

The existing material upload frontend already sends all selected images in one `FormData` request to:

```text
POST /api/projects/{project_id}/images
```

It does **not** send one HTTP request per image. Do not replace this with parallel per-file requests; that would break the backend batch transaction boundary and can increase storage/SQLite contention.

The existing progress contract remains:

```text
browser transfer       -> 0..85%
transfer finished      -> 文件已上传，正在服务器入库
server durable success -> 100% / 服务器入库完成
```

The browser must not fabricate server-side ingestion percentage while the request is still being committed.

### 2. Request-level material / annotation batching

A plain multi-image upload is wrapped by the existing image batch owner:

```text
_v50_begin_image_batch(project_id)
...
_v50_end_image_batch(save=True)
```

New material rows are committed together instead of invoking one durable material upsert transaction per image. New-image annotations are committed with `AnnotationRepository.upsert_many()` rather than one annotation transaction per image.

Per-file validation/failure isolation is retained: one corrupt or unsupported image does not make the entire valid remainder fail.

The response is rebuilt from the final committed material rows, so frontend state reflects the durable annotation/material truth rather than pre-commit buffered copies.

### 3. Request-level StorageManager reuse

The upload request reuses one project StorageManager / storage-source repository instead of recreating storage source initialization for every image.

This removes repeated storage-source schema/default-source checks from the per-image hot path while preserving the same configured storage source truth.

### 4. Local storage copy hashes in the write pass

The local storage provider calculates SHA256 while writing the final atomic object and retains the existing durability sequence:

```text
write destination-side temporary object
-> hash during the same byte pass
-> flush
-> fsync
-> os.replace into final object
```

No SQLite durability or storage fsync policy was weakened for performance.

### 5. Plain upload no longer creates a second app-level full-file copy

Runtime implementation commit:

```text
8eee1c49b8ce023622dec1cfea2180ad855d444e
perf(materials): stream plain uploads directly to storage
```

Before this commit, Starlette already owned a seekable/spooled `UploadFile`, but `upload_images()` copied every image to another application temporary path:

```text
imports/upload_<uuid>.<ext>
```

`add_image_record()` then read that temporary file again and copied it into the final StorageManager object.

The current path is:

```text
browser multipart
-> Starlette UploadFile / spooled stream
-> image validation
-> StorageManager
-> final storage atomic write
```

The redundant `imports/upload_*` full-file write/read is removed from ordinary image upload.

Legacy/path-based callers such as structured imports can still pass a `Path`; `add_image_record()` accepts both path-backed and caller-owned seekable stream sources.

### 6. Pillow ownership fence

During implementation, the first direct-stream regression exposed an important ownership bug: Pillow's PNG image object closes the file pointer when the image is closed. Passing the Starlette-owned `SpooledTemporaryFile` directly into Pillow therefore made the subsequent StorageManager upload see a closed stream and all valid images were rejected.

The final runtime uses `_NonClosingImageStream` for the Pillow probe:

```text
caller-owned UploadFile.file
-> _NonClosingImageStream view for Pillow
-> Pillow closes the view only
-> original upload stream remains open
-> rewind original stream
-> StorageManager consumes original stream
```

This preserves caller ownership without copying the full image into memory and without creating another disk temporary file.

## Permanent regression gate

Permanent workflow:

```text
.github/workflows/material-upload-cleaning-performance.yml
```

Permanent gate expansion commit:

```text
f1c075bf2e8535c28ba995868d779a4124053eef
ci(materials): guard direct upload stream on Windows and Linux
```

Validated workflow run:

```text
Material Upload Cleaning Performance
run: 35094056816

cross-platform-hot-path (ubuntu-24.04)  PASS
cross-platform-hot-path (windows-latest) PASS
durable-api-flow                        PASS
```

The Windows and Ubuntu matrix both execute the direct-stream multi-image API contract, not only static grep/compile checks.

The durable API job also runs the existing upload-to-cleaning flow and permanent invariants.

Current permanent guards include:

```text
request-level image batch is present
material upsert_many path is present
annotation upsert_many path is present
StorageManager is reused
_NonClosingImageStream is present
plain upload passes UploadFile.file directly
imports/upload_* ordinary-upload temp copy is absent
12-image direct-stream API contract passes
cleaning hash/progress/runtime contracts remain intact
VERSION.txt remains 42.24.0
```

No test was removed or relaxed to obtain this closure.

## Temporary migration cleanup

The one-shot migration workflow used only to safely edit/test the large `app.py` was deleted after the permanent workflow passed.

Cleanup commit:

```text
1e28e0aa91ac3312c9e081f1fdb7fa4d10342e8d
ci(materials): remove direct upload one-shot migration
```

Do not restore the one-shot workflow.

## What is proved now

Automated evidence proves:

- multi-image upload keeps one browser request and one backend batch boundary;
- valid images persist successfully from caller-owned upload streams;
- unsupported/corrupt file isolation remains;
- new material and annotation SQLite writes are batched;
- StorageManager initialization is not repeated for every image in the request;
- ordinary uploads no longer write a second `imports/upload_*` full-file copy;
- final local object writes remain atomic and fsync-protected;
- upload response uses final durable records;
- upload-batch decisions and durable cleaning flow still work;
- the direct-stream path passes on both Ubuntu and Windows.

## Still pending: real server timing

After deploying the latest branch to the real server, repeat the previously slow production-shaped batch (for example the same ~380-image set) and record at minimum:

```text
image count
source total bytes
browser transfer duration
server-ingestion duration after transfer reaches 100%
API elapsed_seconds
final uploaded_count / failed_count
storage type / mount
CPU / disk utilization if ingestion is still slow
```

The expected qualitative improvement is lower duplicate local disk I/O and much lower per-image SQLite/storage initialization overhead. Do not record a numerical improvement until measured on the real deployment.

If real 380-image ingestion is still materially slow after this deployment, the next investigation should use measured phase timings before changing concurrency. In particular, do not automatically split one batch into hundreds of parallel HTTP requests.

## Repository constraints preserved

This closure did not:

- merge `main`;
- change `VERSION.txt`;
- tag or release;
- force-push;
- lower test thresholds;
- remove durability/fsync behavior;
- introduce Windows-only or Linux-only runtime paths.
