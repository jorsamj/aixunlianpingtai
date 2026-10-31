# Storage Source active-task lifecycle design

## Decision

Keep `StorageSourceRepository`, `SecretCredentialStore`, `TaskRepository`, and
`MaterialRepository` as the only owners.  A short, cross-process fence adjacent
to the Storage Source database coordinates final durable task publication with
runtime-destructive Source mutations.  The fence stores no state.

## Runtime contract

- Display-name-only PATCH is allowed while tasks are active.
- Disable, runtime config changes, credential replacement, empty credentials,
  and `clear_credentials` are rejected with 409 while an active task can still
  read that Source.
- Active truth is derived in bounded pages from canonical task status and its
  existing request/input-freeze/selection artifacts.  It includes
  Import/Rescan, CLEAN/AI material batches, AI annotation, TRAINING,
  TRAINING_PREPARE, and MODEL_CONVERSION calibration.
- Terminal status releases the dependency.  Lease recovery remains queued or
  running and therefore retains it; cancel releases only when canonical status
  is terminal.
- Network, object transfer, model staging, and inference remain outside the
  fence.  Import/Rescan and RKNN staging capture a runtime generation before
  external work and revalidate it at final publication.

## Secret commit

Credential replacement writes a new versioned Secret reference first, then
atomically changes the SQLite pointer.  A failed SQLite update deletes only the
unpublished Secret and leaves the old generation intact.  Clearing or replacing
an old reference rolls the complete Source row back if Secret cleanup fails.
No credential bytes enter task artifacts.

## Verification boundary

Focused tests cover active/terminal behavior, name-only updates, SQL/Secret
failure, TRAINING_PREPARE parent input-freeze resolution, active RKNN
calibration, and a deterministic admission-vs-PATCH barrier.  Real OSS,
production Keyring, Agent/RKNN hardware, and long-running mixed-source tasks are
`PENDING USER UAT`.
