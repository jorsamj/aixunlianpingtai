import os
from pathlib import Path

path = Path("docs/CODEX_CURRENT_STATE.md")
text = path.read_text(encoding="utf-8")
heading = "## Product closure — Training Bundle Snapshot Cache CLOSED"
if heading in text:
    raise SystemExit("bundle cache closure already documented")
marker = "> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.\n"
if text.count(marker) != 1:
    raise SystemExit("CODEX current-state insertion marker changed")
sha = os.environ["CODE_SHA"]
section = f"""

## Product closure — Training Bundle Snapshot Cache CLOSED

Training Bundle Snapshot Cache is implemented at product commit `{sha}`.
It reuses only a project-scoped portable bundle whose Snapshot ID is derived
from the durable material index and whose previous run reached final dataset
verification. The cache lives under
`<data_dir>/cache/training-bundles/<project_id>/<snapshot_id>`; entries are not
shared across projects.

The fast path is intentionally ahead of source materialization. When every
selected material already has a locked SHA256 and positive indexed size, the
Worker rebuilds the deterministic split manifest/Snapshot from durable material
and annotation truth first. If a matching cache entry exists, source files are
not reread merely to rediscover the same hashes. A miss keeps the previous
behavior: every selected source is materialized/verified, the manifest and
Snapshot are rebuilt from those verified bytes, and the task-local portable
bundle is constructed normally.

Cache entries are published only during successful training finalization, after
the existing `verify_portable_dataset()` full image/label SHA256 gate has passed.
An incomplete/failed training run therefore cannot seed this cache. Cache
publication failure is recorded as optimization evidence and cannot turn an
otherwise verified model result into a failed training result.

Each training task still receives its own `work/bundle`; the trainer never runs
directly inside the shared cache. Reuse hard-links immutable image files when
the OS/filesystem permits it, while labels, hidden test ground truth, Snapshot,
YAML and manifest are copied into the task bundle. `os.link()` is cross-platform
and any hard-link failure (including cross-device filesystems) falls back to a
normal copy. The finalization gate still re-hashes the task bundle on every run
before accepting the model artifact.

Permanent contracts cover project isolation, cache marker/manifest identity,
missing-member rejection, verified-file-count fencing, hard-link reuse,
cross-device copy fallback, indexed hash/size eligibility, and the production
TrainingHandler wiring. Formal `VERSION.txt` remains `42.24.0`; no tag, release
or `main` merge is part of this closure. A800 / genuine 10k timing remains
unverified and no performance percentage is claimed.
"""
path.write_text(text.replace(marker, marker + section, 1), encoding="utf-8")
