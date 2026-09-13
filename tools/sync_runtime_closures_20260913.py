from pathlib import Path

MARKER = "<!-- RUNTIME-PROD-CLOSURES-2026-09-13-B -->"
DOCS = [
    Path("docs/TECH_DEBT_CLOSURE_V42_25.md"),
    Path("docs/CODEX_CURRENT_STATE.md"),
    Path("docs/frontend-legacy-audit.md"),
    Path("docs/FRONTEND_OWNER_MAP_V42_25.md"),
]
BLOCK = r'''

<!-- RUNTIME-PROD-CLOSURES-2026-09-13-B -->
## 2026-09-13 — runtime productization closures: video publish + AI annotation cancellation

### Video frame publish cancellation / stale-execution fencing — CLOSED

- Valid RED run: `34752569787`. Old worker continued frame publication after durable cancellation and uploaded `3/3` frames after execution fencing/lease loss.
- Product: `8d267ae86a0a3030aa7faff8d4eccb9a1882b1d9` (`fix(video): fence frame publishing cancellation`). Every publish-side effect is guarded by cancellation/current-execution checks; late stale workers cannot continue material/result publication. Commit-phase progress now continues through the prior 90% plateau toward 97%/98%.
- Focused GREEN: `34752658173`.
- Permanentization: `22378473e077749ee5dc9de80ee9993daf28be64`; permanent contracts include `tests/unit/test_video_commit_fencing.py` plus the real video-worker integration path.
- Annotation integration was aligned with the already-authoritative SQLite truth (`annotations.sqlite3` / `AnnotationRepository`): no per-image JSON shadow was restored. Alignment/accepted HEAD: `cf81fd8b756d902cc6f9168f5f14d6357c806055`.
- Cleaned-head gates: Release `34752863299` PASS; Navigation Action Fencing `34752863247` PASS; Frontend Runtime `34752863225` PASS including Real Chrome.

### AI annotation in-flight cancellation side-effect fencing — CLOSED

- Valid RED run: `34753095270`. Cancellation during materialization still allowed one model inference call; cancellation during an in-flight model call still persisted the returned candidate.
- Product: `a1dabee5d867b19c9815c525e01793692db8b0a5` (`fix(annotation): fence cancellation around inference`). The worker re-proves cancellation/current execution immediately before provider inference and again after inference returns but before candidate/manifest writes. `InterruptedError` / lease-loss `PermissionError` remain control flow and are not converted into failed AI candidates.
- Focused GREEN: `34753193608`.
- Permanentization: `0d1c51f4caa25e1d653a32a5a790e792631126ca`.
- Existing candidate guards were migrated to current stronger truth in `3f6a63362a850049ebe6358d12eecf7d984ae79e`: failed provider generations do not inflate human `unreviewed` count, and unsafe task ids are rejected at `CandidateStore` construction by `ArtifactStore` before any candidate DB path is created.
- Cleaned-head gates on `3f6a63362a85...`: Release `34753389416` PASS; Navigation Action Fencing `34753389436` PASS including Real Chrome stale-mutation; Frontend Runtime `34753389399` PASS including full Real Chrome runtime regressions.

Release boundary remains unchanged: formal `VERSION.txt` is `42.24.0`; no merge to `main`, tag, or release. Genuine 10k/A800 acceptance remains deferred by user request.
'''

for path in DOCS:
    text = path.read_text(encoding="utf-8")
    if MARKER not in text:
        path.write_text(text.rstrip() + BLOCK + "\n", encoding="utf-8")
    assert MARKER in path.read_text(encoding="utf-8"), path

assert Path("VERSION.txt").read_text(encoding="utf-8").strip() == "42.24.0"
