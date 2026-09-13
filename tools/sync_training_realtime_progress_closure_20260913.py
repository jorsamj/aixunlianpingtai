from __future__ import annotations

from pathlib import Path

DOCS = (
    Path("docs/TECH_DEBT_CLOSURE_V42_25.md"),
    Path("docs/CODEX_CURRENT_STATE.md"),
    Path("docs/frontend-legacy-audit.md"),
    Path("docs/FRONTEND_OWNER_MAP_V42_25.md"),
)
MARKER = "<!-- TRAINING_REALTIME_PROGRESS_CLOSED_20260913 -->"
SECTION = r'''

<!-- TRAINING_REALTIME_PROGRESS_CLOSED_20260913 -->
## Normal training realtime progress closure — 2026-09-13

Status: **CLOSED** on `refactor/frontend-runtime-stabilization`.

- Permanent RED contract commit: `474771da05c9652a1aa7103b737918ebe1011ffa`.
- Successful RED→GREEN migration run: `34756786009` PASS; legacy epoch-only behavior was proven RED before migration.
- Product fix: `16a1f76ebdc704bfbbcd7f96ce7a2b234f4017e7` (`fix(training): publish realtime batch progress`).
- Permanentization / cleaned product head: `65736aefd0b5961c3f6a7b3e45907937a9988973`.
- Progress contract: preparation owns 0..20; active normal training advances 20..90 using epoch + real train-batch completion; batch publication is throttled to about 4 Hz with mandatory final-batch flush; durable task progress remains monotonic.
- `job.json` publication is same-directory atomic replace so higher-frequency batch updates cannot expose a partially-written JSON file to the task handler.
- Durable `current_item` now carries `Epoch X/Y · Batch A/B` when batch truth is available; completed-epoch metrics remain authoritative and are not fabricated by batch callbacks.
- The normal model and the OOM-recreated model both attach the realtime batch callback. AI continuation is intentionally excluded from this closure and tracked as a separate follow-up batch.
- Permanent formal contracts include `tests/unit/test_training_realtime_progress.py`, `tests/unit/test_training_progress_v2.py`, and `tests/api/test_training_unified_task_overlay.py`.
- Cleaned-head Release Regression `34756946382`: PASS (`runtime-contracts` + `training-data-contracts`, release-path guard included).
- Cleaned-head Navigation Action Fencing `34756946390`: PASS; Real Chrome stale-mutation contract executed and passed.
- Cleaned-head Frontend Runtime Stabilization `34756946384`: PASS; full `Real Chrome runtime regressions` executed and passed.
- One-shot migration helper/workflow were deleted in the permanentization commit before cleaned-head gates.
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
