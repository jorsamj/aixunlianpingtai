from pathlib import Path

ACCEPTED = "3931a9a2d529845f9e698b22f62fe950a7a8b42f"
PRODUCT = "f43631e16a51167cf75bb8e2ec545566f226609f"
RED = "3f41cdae0d4234bf5171f2aa80111513c223407c"
RELEASE_RUN = "34792673327"
NAV_RUN = "34792673293"
FRONTEND_RUN = "34792673296"
FOCUSED_RUN = "34792422835"

CLOSURE = f'''## Product closure — Cleaning durable execution truth CLOSED

The active v47 manual-clean and v55 upload-batch clean entry points now publish one durable `MATERIAL_BATCH/CLEAN` task into the shared `TaskRepository`. The Web/API process no longer owns cleaning execution through legacy daemon threads, and Web startup no longer resurrects those retired workers. Real execution is owned by the registered `materials` worker through `FencedTaskRepository` / `Scheduler` truth.

Closed semantics:

```text
manual v47 create -> prepare + publish one MATERIAL_BATCH/CLEAN durable task
v55 upload-batch decision -> the deterministic clean_task_id points to that same durable task truth
real execution -> materials Scheduler / fenced WorkerContext, never Web daemon execution
prepare -> publish crash window -> reuse the already-frozen semantic request without treating its freeze-time repository_revision as a new user intent
FAILED retry -> same task id is re-queued through TaskRepository retry; no duplicate task identity
successful scan awaiting confirmation -> durable task remains SUCCEEDED/succeeded; v47 compatibility alone projects awaiting_confirmation/review
corrupt image with corrupt_check -> successful flagged cleaning finding for review
source content changed after indexing -> remains SOURCE_CONTENT_CHANGED storage-integrity failure, not disguised as image corruption
```

A real-worker defect was also closed: `MaterialBatchHandler` had called a private artifact validation method that does not exist on the real `FencedArtifactStore`, causing Scheduler execution to fail before processing any material. The handler now validates `project_id` as a safe single path component while preserving fenced artifact access. Corrupt findings are excluded from the hash/dedup index unless real `sha256` and `dhash` metrics exist.

Permanent guards include `tests/api/test_clean_unified_execution_truth.py`, `tests/api/test_upload_clean_flow.py`, `tests/unit/test_material_batch_public_truth.py`, and the Release Regression path/test scope. The final guard explicitly proves that reading the v47 compatibility result may show `awaiting_confirmation / review` while the underlying durable record remains `SUCCEEDED / succeeded`.

Evidence:

```text
valid RED commit:           {RED}
valid RED run:              34790397474 (intended durable-clean execution assertions RED)
focused durable migration:  {FOCUSED_RUN} PASS (4 durable contracts + 32 upload-clean regressions)
product commit:             {PRODUCT}
formal accepted clean HEAD: {ACCEPTED}
Release Regression:         {RELEASE_RUN} PASS
Navigation Action Fencing:  {NAV_RUN} PASS (Real Chrome PASS)
Frontend Runtime:           {FRONTEND_RUN} PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

All one-shot cleaning migration/diagnostic helpers and workflows were physically removed before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Next product batch: audit the **cleaning frontend queue/progress truth**. The backend now exposes durable `resource_queue_position` / `resource_wait_reason`; the final clean-tab renderer/poll lifecycle must preserve that truth and must not create a frontend queue or simulated progress owner.

'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


def insert_once(text: str, anchor: str, block: str, label: str) -> str:
    if "## Product closure — Cleaning durable execution truth CLOSED" in text:
        return text
    return replace_once(text, anchor, block + anchor, label)


# Authoritative ledger.
path = Path("docs/TECH_DEBT_CLOSURE_V42_25.md")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "> **最近完整代码验收点：`cb81ca39016aea0fc53ed52090f0b0199d39109a`**\n",
    f"> **最近完整代码验收点：`{ACCEPTED}`**\n",
    "tech latest acceptance",
)
text = replace_once(
    text,
    "> **Frontend Runtime Stabilization：run `34733035739`，frontend + Real Chrome 全绿，Real Chrome 33/33 passed；Navigation Action Fencing 永久 run `34733035761` 全绿；Resource Discovery SQLite 永久跨平台 run `34700900542` Ubuntu + Windows 全绿。**\n",
    f"> **最新正式门：Release Regression `{RELEASE_RUN}` PASS；Navigation Action Fencing `{NAV_RUN}` PASS（Real Chrome）；Frontend Runtime Stabilization `{FRONTEND_RUN}` PASS（unit + full Real Chrome）。Resource Discovery SQLite 永久跨平台 run `34700900542` 仍保持 Ubuntu + Windows 全绿。**\n",
    "tech latest gates",
)
text = insert_once(text, "## Product closure — Plain image upload whole-task progress truth CLOSED\n", CLOSURE, "tech cleaning closure")
path.write_text(text, encoding="utf-8")


# First-entry state.
path = Path("docs/CODEX_CURRENT_STATE.md")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "latest full code acceptance: cb81ca39016aea0fc53ed52090f0b0199d39109a\nFrontend Runtime run:        34789704610\n",
    f"latest full code acceptance: {ACCEPTED}\nFrontend Runtime run:        {FRONTEND_RUN}\n",
    "codex latest acceptance",
)
text = insert_once(text, "## Product closure — Plain image upload whole-task progress truth CLOSED\n", CLOSURE, "codex cleaning closure")
text = replace_once(
    text,
    "→ Video resource queue truth CLOSED\n→ NEXT: horizontal queue-position/progress truth audit across cleaning, storage import and deployment test\n",
    "→ Video resource queue truth CLOSED\n→ Cleaning durable execution truth CLOSED\n→ NEXT: cleaning frontend queue/progress truth, then continue storage import and deployment-test horizontal truth audit\n",
    "codex current priority",
)
path.write_text(text, encoding="utf-8")


# Frontend legacy audit: backend closure matters because the clean tab now consumes one durable owner.
path = Path("docs/frontend-legacy-audit.md")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "commit:       cb81ca39016aea0fc53ed52090f0b0199d39109a\nrun:          34789704610\n",
    f"commit:       {ACCEPTED}\nrun:          {FRONTEND_RUN}\n",
    "legacy latest acceptance",
)
text = insert_once(text, "## Product closure — Video resource queue truth CLOSED\n", CLOSURE, "legacy cleaning closure")
text = text.replace(
    "Current next product scope: continue the horizontal real queue-position/progress audit across cleaning, storage import and deployment-test surfaces.",
    "Current next product scope: cleaning frontend queue/progress truth first, then continue the horizontal real queue-position/progress audit across storage import and deployment-test surfaces.",
)
path.write_text(text, encoding="utf-8")


# Final-owner map.
path = Path("docs/FRONTEND_OWNER_MAP_V42_25.md")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "> Latest fully accepted code point: `cb81ca39016aea0fc53ed52090f0b0199d39109a` / run `34789704610`\n",
    f"> Latest fully accepted code point: `{ACCEPTED}` / run `{FRONTEND_RUN}`\n",
    "owner latest acceptance",
)
owner_block = '''## Product closure — Cleaning durable execution truth CLOSED

Final backend owner chain for cleaning execution:

```text
v47 manual clean / v55 upload-batch clean decision
→ prepare_material_batch / publish_prepared_material_batch
→ shared TaskRepository: MATERIAL_BATCH / CLEAN
→ materials worker registration
→ FencedTaskRepository + Scheduler / WorkerContext
→ durable result/checkpoint truth
→ v47 compatibility projection for legacy clean UI
```

The compatibility projection is display-only: an unconfirmed successful clean may appear as `awaiting_confirmation / review`, while the underlying durable task remains `SUCCEEDED / succeeded`. Legacy Web daemon workers and Web startup recovery are retired as execution owners. Queue/resource/progress metadata remains server/worker-derived. Permanent backend guard: `tests/api/test_clean_unified_execution_truth.py`; formal acceptance `{accepted}`, Release `{release}` PASS, Navigation `{nav}` PASS with Real Chrome, Frontend `{frontend}` PASS with unit + full Real Chrome. `VERSION.txt` remains `42.24.0`.

Next owner audit: the final cleaning frontend row/poll owner must preserve durable queue position/wait reason and use lifecycle-managed polling without a parallel frontend truth model.

'''.format(accepted=ACCEPTED, release=RELEASE_RUN, nav=NAV_RUN, frontend=FRONTEND_RUN)
text = insert_once(text, "## Product closure — Plain image upload whole-task progress truth CLOSED\n", owner_block, "owner cleaning closure")
text = text.replace(
    "**Video resource queue truth is CLOSED. Current next product scope: continue the horizontal real queue-position/progress audit across cleaning, storage import and deployment-test surfaces. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**",
    "**Video resource queue truth and cleaning durable execution truth are CLOSED. Current next product scope: cleaning frontend queue/progress truth, then continue storage import and deployment-test surfaces. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**",
)
path.write_text(text, encoding="utf-8")

print("cleaning durable truth authority docs synced")
