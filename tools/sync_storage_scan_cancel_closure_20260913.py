from pathlib import Path

MARKER = "<!-- STORAGE-SCAN-CANCEL-CLOSURE-2026-09-13 -->"
DOCS = [
    Path("docs/TECH_DEBT_CLOSURE_V42_25.md"),
    Path("docs/CODEX_CURRENT_STATE.md"),
    Path("docs/frontend-legacy-audit.md"),
    Path("docs/FRONTEND_OWNER_MAP_V42_25.md"),
]
BLOCK = r'''

<!-- STORAGE-SCAN-CANCEL-CLOSURE-2026-09-13 -->
## 2026-09-13 — external storage scan cancellation fencing CLOSED

- Real bug: if Stop was requested while the final remote image read/decode was in flight, old `StorageImportHandler._scan_impl` had no later loop iteration to observe cancellation. It could open the same remote object again for missing SHA256, flush the candidate manifest, publish `scan/result.json`, and finish as `AWAITING_CONFIRMATION`.
- Permanent RED: `tests/unit/storage/test_import_scan_cancel_fencing.py`; valid RED run `34753661080` proved old code returned `AWAITING_CONFIRMATION` instead of `CANCELLED`.
- Product: `2ca557ed0bd72851948ad778163bf47d590b5a54` (`fix(storage): fence scan cancellation after remote reads`). Remote hashing now checks cancellation per chunk; inspection re-checks after image decode before follow-up I/O and after hashing; cancellation propagates rather than becoming INVALID/FAILED; `_scan_impl` refuses to append the in-flight cancelled object and returns `CANCELLED` while preserving only already-completed pending work.
- Migration run `34753741408` PASS: old-product RED, precise migration, syntax, focused GREEN, real storage-import worker/candidate/YOLO regressions, and formal version boundary all passed.
- Permanentization: `da54910048fd88f6cadeef34d130eba94af34303`; one-shot RED/migration workflows and helper were physically deleted. Release Regression permanently covers the cancellation contract, real storage import worker, import candidates, and YOLO import.
- Cleaned-head gates: Release `34753845097` PASS; Navigation Action Fencing `34753845073` PASS including Real Chrome stale-mutation; Frontend Runtime `34753845116` PASS including full Real Chrome runtime regressions.
- Formal `VERSION.txt` remains `42.24.0`; no merge to `main`, tag, or release. Genuine 10k/A800 acceptance remains deferred by user request.
'''

for path in DOCS:
    text = path.read_text(encoding="utf-8")
    if MARKER not in text:
        path.write_text(text.rstrip() + BLOCK + "\n", encoding="utf-8")
    assert MARKER in path.read_text(encoding="utf-8"), path

assert Path("VERSION.txt").read_text(encoding="utf-8").strip() == "42.24.0"
