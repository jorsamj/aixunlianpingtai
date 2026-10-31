# Active Material Task Dependencies — Design

## Scope

This batch closes AUDIT-084 and AUDIT-168 without introducing another task,
material, annotation, or dependency owner. It covers canonical MaterialBatch
`DELETE_INDEX` / `DELETE_SOURCE`, explicit training admission, and Agent RKNN
INT8 calibration admission.

## Invariants

1. `TaskRepository` remains the durable truth for whether a task dependency is
   active. Active means `QUEUED`, `RUNNING`, or `CANCEL_REQUESTED`; terminal
   tasks release their dependency automatically.
2. `MaterialRepository` remains the durable truth for a short-lived destructive
   claim while a source object is being deleted outside the lifecycle lock.
3. Training and conversion admission, and deletion publication, serialize on
   the existing project Material/Annotation lifecycle fence.
4. No network storage request runs while that lifecycle fence or a database
   transaction is held.
5. Once source deletion may have succeeded, cancellation cannot leave a usable
   material index pointing at missing bytes. The same task must complete the
   canonical annotation/index deletion; lease recovery retries from the durable
   tombstone and claim.

## Dependency discovery

The MaterialBatch deletion owner reads active task inputs from their existing
artifacts:

- `TRAINING`: requested/frozen image IDs from the training payload and
  `input-freeze.json`.
- `MODEL_CONVERSION`: RKNN INT8 calibration `image_id`, storage source, object
  key, size, and SHA from `remote_execution.conversion.calibration`.

No separate registry is written. Pagination stays bounded to active tasks, and
selection membership checks use SQLite lookups rather than hydrating entire
batch selections.

## Admission ordering

Whichever durable action commits first wins:

- Training/conversion admission first: deletion publication or worker claim
  observes the active task and fails closed.
- Deletion publication first: training/conversion admission observes the active
  deletion selection and fails closed.
- A running `DELETE_SOURCE` additionally owns a per-material claim across the
  unlocked storage-provider call. Final admission revalidates that claim.

RKNN snapshot construction and provider `stat` remain outside the fence. The
final admission revalidates the current Material identity against the frozen
snapshot before exposing the conversion task.

## Failure and recovery

- Failure before irreversible source deletion clears this task's claim.
- Success, an ambiguous prior delete attempt, or a process crash retains the
  claim until canonical annotation/index deletion completes.
- Lease expiry requeues the same durable task; its tombstone and delete-attempt
  evidence make the provider operation idempotent.
- Cancellation before source deletion stops normally. Cancellation racing after
  source deletion cannot interrupt the index commit.
- Terminal training/conversion tasks require no cleanup because their dependency
  is derived from current task status.

## Verification

Small deterministic event/barrier tests cover both admission orderings, queued
RKNN calibration before Agent download, cancellation/terminal release, and the
source-deleted/index-retained failure window. Existing directly related API and
unit tests remain unchanged and are run alongside syntax/import checks.
