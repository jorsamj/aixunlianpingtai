# Worker Runtime Truth Design

## Goal

Extend the existing durable Worker lease registry so the backend can query the actual runtime identity and liveness of registered Workers. This batch establishes truth only; it does not use that truth for task admission, claim fencing, or frontend behavior.

## Scope

The existing `worker_instances` table, `WorkerInstanceService`, lease renewal, and `worker_registry` remain the only Worker registry and heartbeat owners.

Each Worker registration records and exposes:

- `worker_id`;
- `hostname`;
- `pid`;
- actual Worker `build_id`;
- actual registered roles and task kinds;
- actual registered capabilities;
- `started_at`;
- `heartbeat_at`;
- `expires_at`;
- derived `online` state.

## Data sources

- `build_id` comes from `resolve_build_id()` in the running `task_worker.py` process.
- roles come from the parsed Worker CLI registration request after `all` is expanded through `ROLE_MODULES`.
- task kinds come from the actual handler keys returned by `build_worker_registration()`.
- capabilities come from the actual capability set returned by `build_worker_registration()`.
- `hostname` comes from the Worker host at acquisition time.
- `pid`, `started_at`, heartbeat, and expiry reuse the existing Worker instance lease.

No value is inferred from API Build identity, task rows, frontend state, or remote PID inspection.

## SQLite migration

Extend `worker_instances` additively with text columns for hostname, Build ID, roles, task kinds, and capabilities. JSON arrays are stored deterministically so the registry can return stable values. Existing rows remain valid and receive empty defaults for metadata they predate.

The repository initialization path checks `PRAGMA table_info(worker_instances)` and adds only missing columns. No table replacement, destructive migration, or existing-row rewrite is allowed.

## Query behavior

Add a read-only `WorkerInstanceService.list_runtime()` query and expose it through a simple backend endpoint.

- The query returns active and expired rows; expiry does not delete history in this batch.
- `online` is derived only from `expires_at > current UTC time`.
- The query does not use PID state because API and Worker can run on different hosts.
- The endpoint returns sanitized Worker runtime fields only; it never returns `owner_token` or `instance_key`.
- Ordering is deterministic: newest heartbeat first, then Worker ID.

## Worker wiring

`task_worker.py` resolves handlers and capabilities using the existing `build_worker_registration()` call, then passes the expanded roles, actual handler task kinds, actual capabilities, actual Build ID, hostname, and PID into `WorkerInstanceService.acquire()`.

The existing lease renewal thread remains the only heartbeat. `renew()` continues to update the existing `heartbeat_at` and `expires_at` fields; no second timer, table, registry, or heartbeat path is introduced.

## Minimal verification

Only two behavior contracts are required:

1. After registration, the query reports correct Build ID, roles, task kinds, capabilities, heartbeat/expiry, and `online=true`.
2. After the lease expires, the same query reports `online=false` without consulting PID state.

Add one focused API assertion that the read-only endpoint exposes the same sanitized runtime truth. Reuse the existing Worker instance test area and API test fixtures. Run the focused unit/API tests plus Python compilation/import checks for affected files. Do not run full pytest, Real Chrome, or temporary workflows.

## Explicitly deferred

The following are not implemented in this batch:

- `runtime.build:<build_id>` task capability;
- task claim changes or Build claim fencing;
- Worker readiness/admission decisions;
- training or other task-creation admission;
- training `503` rejection;
- training task creation changes;
- training modal or frontend Worker probes;
- `TrainingSubmitRuntime` changes;
- submit-button readiness changes;
- independent startup-failure diagnostics.

These are separate future batches that may consume Worker Runtime Truth after this batch is accepted.

## Release boundaries

Do not merge `main`, modify `VERSION.txt`, create tags, or release. `VERSION.txt` remains `42.24.0`. Do not restore legacy or temporary workflow/helper assets, and do not touch unrelated training logic.
