from __future__ import annotations

from pathlib import Path

DOCS = (
    Path("docs/TECH_DEBT_CLOSURE_V42_25.md"),
    Path("docs/CODEX_CURRENT_STATE.md"),
    Path("docs/frontend-legacy-audit.md"),
    Path("docs/FRONTEND_OWNER_MAP_V42_25.md"),
)
MARKER = "<!-- STORAGE_IMPORT_PROGRESS_TRUTH_CLOSED_20260913 -->"
SECTION = r'''

<!-- STORAGE_IMPORT_PROGRESS_TRUTH_CLOSED_20260913 -->
## Storage import progress truth closure — 2026-09-13

Status: **CLOSED** on `refactor/frontend-runtime-stabilization`.

- Product fix: `855abb7fe6fc2c759a85acf6c578dc5f8b62b10d` (`fix(storage): make import progress monotonic across confirmation`).
- Permanentization head: `030afa30c3e076cb6fac2c9234711b2f7d0c0cc6`.
- RED→GREEN migration run: `34755980730` PASS. Legacy behavior was proven RED before migration.
- Durable progress contract: material-import `AWAITING_CONFIRMATION` is a partial-task milestone with a 50% floor, not terminal 100%; confirmation/resume uses `MAX(existing_progress, 50)` and therefore never regresses a higher durable value.
- Confirmed indexing emits real monotonic `progress_percent` from the durable 50% floor toward 99% according to `indexed_at_least / selected_count`; only terminal success reaches 100%.
- Permanent tests: `tests/unit/task_runtime/test_material_import_progress_phases.py` and `tests/integration/test_storage_import_progress_truth.py` are included in the formal Release Regression gate.
- Cleaned-head Release Regression `34756082473`: PASS (`runtime-contracts` + `training-data-contracts`, including release-path guard).
- Cleaned-head Navigation Action Fencing `34756082427`: PASS.
- Cleaned-head Frontend Runtime Stabilization `34756082419`: PASS; `Real Chrome runtime regressions` executed and passed.
- One-shot migration helper/workflow were removed before the cleaned-head gates.
- Formal version boundary remains `VERSION.txt = 42.24.0`; no merge, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.
'''


def main() -> None:
    version = Path("VERSION.txt").read_text(encoding="utf-8").strip()
    if version != "42.24.0":
        raise SystemExit(f"VERSION boundary changed unexpectedly: {version!r}")
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        if MARKER in text:
            continue
        path.write_text(text.rstrip() + SECTION + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
