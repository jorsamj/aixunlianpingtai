from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "docs" / "CODEX_CURRENT_STATE.md"

OLD_CACHE = """Each training task still receives its own `work/bundle`; the trainer never runs
directly inside the shared cache. Reuse hard-links immutable image files when
the OS/filesystem permits it, while labels, hidden test ground truth, Snapshot,
YAML and manifest are copied into the task bundle. `os.link()` is cross-platform
and any hard-link failure (including cross-device filesystems) falls back to a
normal copy. The finalization gate still re-hashes the task bundle on every run
before accepting the model artifact."""

NEW_CACHE = """Each training task still receives its own `work/bundle`; the trainer never runs
directly inside the shared cache. Cache schema v3 restores trainer-writable image
inputs with `shutil.copy2()` rather than writable hard-links, so Ultralytics or
other trainer-side mutations cannot modify the persistent cache inode. Legacy
schema-v2 cache entries are fenced because their prior hard-link isolation cannot
be assumed clean. The finalization gate still re-hashes the task bundle on every
run before accepting the model artifact."""

MARKER = "> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.\n"

SECTION = """

## Current closure — Task Runtime Truth v2 CLOSED

Product implementation: `cc8981888bc4b27ee9594290455bd08e61713c9d`.
Permanent Task Runtime Truth gate expansion: `38aa8f736ee11ae419042fa2e90127bd45937ac5`.
Formal `VERSION.txt` remains `42.24.0`.

The shared durable-task frontend contract now covers training, AI annotation,
material batches, storage scan/import, server material import, resource discovery,
video processing, and deployment tests. For those durable payloads, `task_status`
wins over compatibility `status`, `phase` wins over `task_stage` / `stage`, and
`progress_percent` wins over legacy `progress`; the browser does not derive a
new durable percentage from domain counters.

A numeric `resource_queue_position` is displayed as “队列第 N 位” only when the
backend also returns `resource_queue_position_exact === true`. Candidate order,
priority order, or an inexact numeric position is never presented as an exact
Worker/hardware queue position. Domain-specific diagnostics such as scanned file
counts, extracted bytes, current paths, and wait reasons remain visible.

The permanent `Task Runtime Truth` workflow runs the expanded backend/frontend
contract on both Ubuntu and Windows. The closure run passed both OS jobs, and the
existing Frontend Runtime workflow passed frontend unit/owner guards plus Real
Chrome runtime regressions. The existing cleaning frontend queue/progress truth
closure remains authoritative and was not reopened by this batch.

Detailed handoff: `docs/CODEX_HANDOFF_2026-09-16_TASK_RUNTIME_TRUTH_V2.md`.
"""


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    if OLD_CACHE in text:
        text = text.replace(OLD_CACHE, NEW_CACHE, 1)
    elif NEW_CACHE not in text:
        raise RuntimeError("training cache lifecycle paragraph does not match expected durable state")

    if "## Current closure — Task Runtime Truth v2 CLOSED" not in text:
        if MARKER not in text:
            raise RuntimeError("CODEX_CURRENT_STATE header marker not found")
        text = text.replace(MARKER, MARKER + SECTION, 1)

    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
