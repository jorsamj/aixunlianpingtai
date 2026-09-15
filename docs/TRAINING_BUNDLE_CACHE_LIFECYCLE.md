# Training Bundle Cache Lifecycle

This document records the lifecycle contract for the project-scoped verified
training Bundle cache used by `TrainingBundleCache`.

## Scope

Cache entries live under:

```text
<data_dir>/cache/training-bundles/<project_id>/<snapshot_id>
```

The cache remains project-scoped. Snapshot identity, integrity admission,
task-local Bundle restoration and final `verify_portable_dataset()` validation
continue to be the truth boundaries described in `docs/CODEX_CURRENT_STATE.md`.

Lifecycle management is a performance/storage policy only. It must never turn a
verified model result into a failed training result.

## Default policy

The lifecycle policy is configurable with environment variables:

```text
TRAINING_BUNDLE_CACHE_MAX_BYTES
TRAINING_BUNDLE_CACHE_TTL_SECONDS
```

Defaults:

```text
per-project logical cache quota: 64 GiB
unused-entry TTL:                30 days
recent-admission grace:          5 minutes
```

A configured value of `0` disables the corresponding quota or TTL rule.
Negative and non-integer values are rejected instead of being silently coerced.

The quota uses logical Bundle bytes. This is intentionally conservative: image
hardlinks may initially share physical disk blocks with a task Bundle, but the
cache can later become the remaining link after task cleanup.

## LRU / TTL evidence

Each cache entry keeps immutable verified payload under `bundle/` plus:

```text
cache.json    immutable cache identity/integrity metadata
access.json   mutable lifecycle metadata only
```

`access.json` records `last_access_ns` and `last_accessed_at`. A successful
cache lookup refreshes it before the task restores the Bundle, and a successful
restore refreshes it again. The access sidecar is never part of Snapshot,
manifest, label or model correctness.

For older schema-v2 entries without `access.json`, lifecycle ordering falls back
to `cache.json.published_at`, then the entry directory mtime.

TTL admission is strict: an entry whose last access is older than the configured
TTL is not returned by `resolve()`. It can be removed by the next maintenance
pass.

## Maintenance and eviction

A maintenance pass runs after `publish_verified()` and may also be called
explicitly. The pass:

1. removes safely deletable invalid cache directories;
2. removes TTL-expired entries;
3. if the project remains above quota, evicts least-recently-used entries until
   it reaches the configured logical byte budget;
4. reports any remaining over-budget bytes when protected/active entries prevent
   immediate cleanup.

The Snapshot just published is explicitly protected from the same maintenance
pass. Entries accessed in the last five minutes are also protected from normal
TTL/quota eviction to close the lookup-to-restore handoff window.

## Active-use protection

Cache restore and publication use a per-Snapshot `FileLock`. Eviction tries to
acquire that same lock with `timeout=0`.

If another process is actively publishing/restoring the entry, maintenance does
not wait and does not delete it. It records `skipped_locked` and leaves the
entry for a later pass.

After restoration, the trainer reads its own task-local `work/bundle`. Images
may be hardlinks to the same file object, while labels, hidden test ground truth,
Snapshot, YAML and manifest are copied. Removing the cache pathname therefore
does not remove the task-local hardlink.

## Observability

`TrainingBundleCache.restore()` reports real reuse/copy evidence:

```text
hardlinked_images
hardlinked_image_bytes
copied_images
copied_image_bytes
label_files
label_bytes
metadata_bytes
bundle_bytes
cache_bundle_bytes
cache_last_access_ns
```

Training already stores these fields in `bundle-cache.json` on a cache hit.

`publish_verified()` additionally returns a `maintenance` object containing:

```text
max_bytes
ttl_seconds
scanned_entries
before_bytes
after_bytes
evicted_entries
evicted_bytes
ttl_evictions
quota_evictions
invalid_evictions
skipped_locked
skipped_protected
skipped_recent
eviction_failures
over_budget_bytes
evicted_snapshot_ids
```

Those fields flow into the training result's existing `bundle_cache.publish`
evidence. They are operational facts; no estimated speedup percentage is
fabricated.

## Safety invariants

- Cache payload integrity rules from schema v2 remain unchanged.
- Large images are not re-hashed merely for cache lookup, but size/manifest
  evidence is checked and finalization still performs the full SHA256 gate.
- Snapshot, label and data-YAML integrity checks remain mandatory.
- Symlink/reparse traversal remains rejected.
- Maintenance never follows link-like cache paths.
- Cache eviction failure degrades cleanup only; it cannot invalidate a model
  that already passed training finalization.
- `VERSION.txt` is not changed by this lifecycle work.
- No A800 RC or genuine 10k benchmark claim is part of this work.
