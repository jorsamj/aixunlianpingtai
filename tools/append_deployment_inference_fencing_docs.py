from pathlib import Path

MARKER = "<!-- deployment-inference-process-fencing-closed-2026-09-13 -->"
SECTION = """

<!-- deployment-inference-process-fencing-closed-2026-09-13 -->
## Deployment test inference process fencing — CLOSED (2026-09-13)

Deployment-test subprocesses are now part of the durable execution fence instead of being invisible raw `subprocess.Popen` children. The runner is launched through the shared cross-platform process controller, binds exact `PID + create_time + command_hash` to the durable task, terminates the exact process tree on user cancellation or execution/lease fencing, and re-checks the current execution generation before result persistence.

Evidence:
- valid RED: GitHub Actions `34752083670` — real runner PID existed while durable `process_pid` was `None`;
- product: `97efe23ce2d587027150032f71906f03a75fcc51` (`fix(deployment): fence inference runner process`);
- focused GREEN: `34752147610`;
- permanentization: `fbbacad583a8f5ad50b27b1fcb6624b31255658e`;
- cleaned v42.25 Release Regression: `34752225736` PASS (runtime + training-data);
- cleaned Navigation Action Fencing: `34752225727` PASS including Real Chrome stale-mutation;
- cleaned Frontend Runtime Stabilization: `34752225677` PASS including Real Chrome runtime regressions;
- one-shot deployment process-fencing workflow removed during permanentization;
- formal `VERSION.txt` remains `42.24.0`; no merge/tag/release.

Genuine 10k processing acceptance and A800 RC remain deferred and are not closed by this batch.
"""

FILES = [
    Path("docs/TECH_DEBT_CLOSURE_V42_25.md"),
    Path("docs/CODEX_CURRENT_STATE.md"),
    Path("docs/frontend-legacy-audit.md"),
    Path("docs/FRONTEND_OWNER_MAP_V42_25.md"),
]

for path in FILES:
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        continue
    path.write_text(text.rstrip() + SECTION + "\n", encoding="utf-8")
