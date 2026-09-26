# Cache-first Page Loading Design

## Goal

Reduce full-site first-paint and navigation latency without weakening durable truth or introducing another cache, request owner, or polling loop.

## Confirmed root causes

1. Startup applies `/api/v53/bootstrap/snapshot` and then immediately calls `refreshCurrentPage413()`, whose `loadCore412()` adds `refresh=true`. The server-prebuilt snapshot is therefore rebuilt during ordinary browser initialization.
2. One v53 snapshot request calculates every project's counts once for project selection and again while attaching `bootstrap_counts`.
3. The snapshot already carries `jobs` and `model_configs`, but startup `extras412()` fetches those truths again.
4. The v61 material runtime already owns pagination and a page cache, but startup waits for a broad core refresh before the dataset owner gets priority.
5. Label-schema GET scans every material and can read one annotation file per material when `label_counts` is missing.

## Selected design

Keep the existing v53 snapshot, browser `state`, `NavigationStability`, `PageRequestScope`, `PollRegistry`, and page runtimes.

- Ordinary startup reads the cached snapshot once, applies it to `state`, renders immediately, and then starts only page-specific silent refresh work.
- `loadCore412()` defaults to cached snapshot reads. Only explicit user refresh passes `refresh=true`. Selecting a different project remains authoritative because the v53 endpoint rebuilds when the chosen project differs from the cached project.
- `extras412()` stops re-reading `jobs` and `model_configs`; snapshot/state provide initial truth, while TrainingTaskRuntime/PollRegistry and the model-config owner retain authoritative incremental refresh.
- Algorithm, training, dataset, and service-node pages paint their cache/shell synchronously. Their existing page runtimes own silent authoritative requests. Dataset navigation continues using v61 pagination and prioritizes its current 48-row page.
- The v53 endpoint creates one request-local project-count map and reuses it for selection and `bootstrap_counts`; no new cross-request cache is added.
- Label-schema GET aggregates only existing material `label_counts`. It never performs per-image annotation fallback or writes material patches. Existing annotation-index maintenance remains the owner for historical backfill.
- Successful mutations continue updating local state or invoking their existing focused owner refresh. Explicit global refresh remains authoritative.

## Request contracts

### Startup

```text
cached v53 snapshot (one request, no refresh=true)
→ apply state
→ render current page
→ page-specific silent refresh only
```

### Navigation

```text
click
→ correct shell/cache in same navigation commit
→ owner-specific request
→ incremental paint
```

### Explicit refresh

```text
refresh button
→ v53 snapshot?refresh=true
→ apply authoritative core truth
→ current page owner refresh
```

## Error and stale-response handling

Existing `PageRequestScope`, navigation epoch, runtime in-flight deduplication, and PollRegistry lifecycle remain unchanged. Background refresh failures may notify but must not erase valid cached state or replace the current page.

## Verification

- Browser inventory records startup and four page navigations: request count, duplicate URLs, slowest request, snapshot count, `refresh=true`, and click-to-visible time.
- API tests prove project counts execute once per project per v53 request.
- Source/runtime tests prove ordinary core load is cache-first and startup does not execute a second broad refresh.
- Label-schema API test proves ordinary GET performs zero annotation reads and zero material patch writes.
- Existing targeted algorithm, training, material pagination, service-node, and navigation tests remain green.

## Scope exclusions

No v53 replacement, no full snapshot decomposition, no new browser cache layer, no new polling owner, no full annotation-index redesign, and no full test suite in this batch.
