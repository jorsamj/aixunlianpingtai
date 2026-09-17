# Resource Discovery + JPEG Normalization Closure Handoff — 2026-09-16

## Baseline

- Branch: `refactor/frontend-runtime-stabilization`
- Start HEAD for this closure pass: `7cc3ea1a1d87e4c19dcec7f1431b2cd0f029e082`
- Formal `VERSION.txt`: `42.24.0` (unchanged)
- A800 RC: deferred
- Genuine 10k ZIP acceptance: deferred

## Resource Discovery contract

Current code already resolves an explicit full-machine user action in the API/task-creation layer through `local_scan_roots()` and persists those roots in the durable `RESOURCE_DISCOVERY` request payload. `ResourceDiscoveryHandler` still fails closed when a `full` or `directory` task reaches the Worker without explicit roots.

This closure pass adds runtime truth to the task projection and UI: task details show the scope plus the exact roots frozen at task creation, permission skips have actionable guidance, cancelled tasks are distinct from failures, and raw backend `ValueError` text is no longer surfaced directly to the user. Successful discovery still refreshes the model/environment cache automatically.

Permanent tests cover Windows multi-drive roots, Linux local roots, network/virtual filesystem exclusion, directory/full Worker fail-closed behavior, API durable-root wiring, frontend full-scan actions and runtime-truth rendering.

## JPEG / Training Bundle contract

The latest code before this closure pass already contains the substantive JPEG fix:

- `ultralytics_jpeg_repair_v1` is part of training Snapshot identity.
- Valid JPEGs ending in `FF D9` are not re-encoded.
- Decodable JPEGs missing EOI are normalized only in the task-derived trainer input before Ultralytics starts.
- Source material SHA/size and training-input SHA/size are recorded separately.
- Unrepairable JPEGs fail early as `TRAINING_IMAGE_INVALID`.
- Final mutation detection reports `TRAINING_BUNDLE_IMAGE_MUTATED` with image id, expected training SHA, actual SHA, source SHA and normalization policy.
- Training Bundle cache schema is v3; trainer-writable images are restored with `shutil.copy2()`, not `os.link()`.
- Legacy schema-v2 cache entries are fenced because earlier writable hardlink restores cannot be assumed immutable.

This pass does not rewrite those working mechanisms. It corrects the stale cache lifecycle documentation so future maintenance cannot treat writable task images as hardlinks again.

## Production validation boundary

Code/tests/CI completion is not production-host acceptance. A real Windows machine with multiple local volumes and a real NVIDIA Linux host should still validate actual discovered roots, permissions, filesystem mounts and representative malformed JPEG training input when production acceptance resumes. A800 RC and genuine 10k ZIP acceptance remain explicitly out of scope.

## Focused validation

The temporary closure workflow appends the exact focused pytest/Node counts here after successful execution, before committing the product patch.

- Focused pytest: `27 passed`, `0 skipped`, `0 failed` (`27` collected).
- Focused frontend Node test: `4 passed`, `0 failed` (`4` tests).
