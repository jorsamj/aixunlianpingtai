# CODEX HANDOFF — Resource Discovery + Training Input Integration Closure (2026-09-16)

## Baseline

- Repository: `jorsamj/aixunlianpingtai`
- Branch: `refactor/frontend-runtime-stabilization`
- Starting remote HEAD: `c8f5820ecb3caaa3a2d02bffcee1956f5b266356`
- Formal `VERSION.txt`: `42.24.0`
- No `main` merge, tag, release, A800 RC, or genuine 10k ZIP acceptance belongs to this batch.

## Why this batch exists

The product contracts for Resource Discovery scan-root freezing and training JPEG/cache
integrity were already implemented. The remaining gap was validation depth: the permanent
suite proved the pieces independently but did not exercise the critical filesystem chains
end to end.

This batch therefore adds permanent integration acceptance without weakening any Worker
fence, cache fence, or existing unit test.

## Resource Discovery durable execution chain

`tests/integration/test_resource_discovery_durable_chain.py` creates a real durable
`RESOURCE_DISCOVERY` task in `TaskRepository`, writes its real `request.json`, runs the
existing `Scheduler` with the real `ResourceDiscoveryHandler`, scans a real temporary
directory, publishes the real SQLite discovery cache, and reads the published model page.

The test deliberately uses `scope=full` with a previously frozen explicit root. A valid
model outside that root is created as a sentinel and must not appear. This proves that the
Worker consumes the durable roots exactly as supplied and does not broaden a full-scan
task into an implicit machine scan.

The existing `resource-discovery-sqlite-stability.yml` permanent workflow now runs this
chain on both `ubuntu-24.04` and `windows-latest`, in addition to the existing SQLite,
Windows multi-drive policy, Linux mount-fencing, and fail-closed scope contracts.

This CI chain is intentionally bounded. It does **not** scan the entire GitHub-hosted
runner and it is not a substitute for production-host acceptance of the exact disks and
mounts present on a real Windows workstation or NVIDIA Linux server.

## Training input integrity chain

`tests/integration/test_training_input_integrity_chain.py` exercises one continuous real
filesystem chain:

1. create one valid JPEG and one JPEG whose EOI marker is missing;
2. materialize the task-local portable training bundle;
3. prove both source files remain byte-for-byte unchanged;
4. verify manifest source SHA versus trainer-input SHA evidence;
5. run `verify_portable_dataset()`;
6. publish the verified bundle into `TrainingBundleCache`;
7. resolve and restore it into a second task workspace;
8. prove restored trainer-writable images are independent copies, not cache hardlinks;
9. simulate a trainer rewriting the restored repaired JPEG;
10. prove the persistent cache and original source remain unchanged;
11. prove final verification returns structured `TRAINING_BUNDLE_IMAGE_MUTATED` evidence.

A second integration case feeds a JPEG-signature file that cannot be repaired and proves
`TRAINING_IMAGE_INVALID` occurs before any cache entry can be reused or published, while
the source bytes remain unchanged.

The permanent `training-input-integrity.yml` workflow runs the focused existing unit
guards plus this integration chain on both `ubuntu-24.04` and `windows-latest`.

## Claim boundary

After these workflows pass, the following are code/CI-level CLOSED:

- durable Resource Discovery Worker consumes frozen roots and publishes cache truth;
- a full-scope Worker task does not broaden beyond its durable frozen roots;
- Windows/Linux discovery policy and SQLite lifecycle remain permanently guarded;
- mixed valid/repaired JPEG training input preserves source bytes and SHA evidence;
- verified cache publication and task restore preserve trainer/cache inode isolation;
- simulated trainer mutation cannot corrupt the shared cache or source material;
- invalid repairable-path JPEGs fail with `TRAINING_IMAGE_INVALID`;
- final trainer-input mutation is detected as `TRAINING_BUNDLE_IMAGE_MUTATED`.

Still **NOT VERIFIED** by this batch:

- the exact physical Windows drive set on the user's real host (for example C:/, D:/, F:/);
- the exact production Linux `/`, `/data`, NFS/CIFS topology and permission behavior;
- a real Ultralytics process rewriting representative malformed JPEGs;
- NVIDIA/A800 training acceptance;
- genuine 10k ZIP/data acceptance or performance timing.

Those require the corresponding real host/environment and must not be inferred from CI.
