from pathlib import Path

ACCEPTED = "736b2acdbf2560be657011035de173cde67517d0"
PRODUCT = "9f6f329393018623807cb4fea04707f3b5350676"
RED = "cf3f2c4fec639903435379b3419dbaadad82c949"
RED_RUN = "34793075909"
FOCUSED_RUN = "34793282831"
RELEASE_RUN = "34793457861"
NAV_RUN = "34793457872"
FRONTEND_RUN = "34793457920"

CLOSURE = f'''## Product closure — Cleaning frontend queue/progress truth CLOSED

The final cleaning tab now subscribes to the durable v47 cleaning projection instead of flattening server truth into a generic local row. The backend already exposed `status_text`, `progress`, `processed_images`, `total_images`, `flagged_images`, `resource_queue_position`, `resource_wait_reason`, and worker identity; this batch makes the final visible clean-tab owner preserve those values through both initial rendering and managed refresh.

Closed semantics:

```text
status text: consume server status_text; WAITING_RESOURCE compatibility projection remains “等待资源” instead of being flattened to “排队中”
queue metadata: show real resource_queue_position + resource_wait_reason when present
progress: use server progress / processed_images / total_images only; no browser-simulated percentage
worker metadata: running rows may show the real worker_id supplied by the server
polling owner: PollRegistry owns clean-tasks-v47 as a page/tab-scoped 2200 ms one-shot
refresh owner: refreshCleanOps427Delta refreshes only the cleaning task list and patches clean rows
terminal truth: awaiting_confirmation is terminal for list polling; the clean timer is not re-armed
navigation/tab change: PollRegistry clears the clean timer; switching back to AI annotation also clears it immediately
legacy recursive setTimeout(renderOps427, 2200): retired
backend queue order / claim / progress generation / worker execution: unchanged
```

`static/modules/cleaning.js` now owns the pure `cleanTaskView()` / `isActiveCleanTask()` projection. `static/main.mjs` exposes those helpers through `PlatformCore.cleaning`. `static/modules/poll-registry.js` owns `clean-tasks-v47`, and the final v427 clean branch in `static/app.js` consumes that view-model. The v47 public compatibility contract permanently requires the queue metadata fields to exist; their values remain dynamic server truth (for example, an immediately queued task may legitimately report position `1`).

Permanent guards:

```text
tests/frontend/clean-task-view.test.mjs
  - waiting-resource status/queue/progress truth
  - running worker/progress truth
  - final app.js wiring consumes cleanTaskView + PollRegistry
  - retired direct recursive clean-list timer cannot return

tests/frontend/poll-registry.test.mjs
  - clean-tasks-v47 one-shot lifecycle
  - re-arm only while active
  - stop at awaiting_confirmation
  - clear on navigation

tests/api/test_clean_unified_execution_truth.py
  - v47 public queue metadata fields are permanent
  - dynamic queue position is accepted as server truth, never forced to a frontend assumption
```

Evidence:

```text
valid RED commit:           {RED}
valid RED run:              {RED_RUN} (245 frontend tests: 242 PASS; exactly 3 intended cleaning truth assertions RED)
focused/full GREEN run:     {FOCUSED_RUN} PASS (focused cleaning contracts + full frontend unit + wiring guard)
product commit:             {PRODUCT}
formal accepted clean HEAD: {ACCEPTED}
Release Regression:         {RELEASE_RUN} PASS
Navigation Action Fencing:  {NAV_RUN} PASS (Real Chrome PASS)
Frontend Runtime:           {FRONTEND_RUN} PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

The temporary frontend migration helper/workflow were physically deleted before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Next product scope: continue the horizontal **storage import / deployment-test queue and progress truth audit**. Genuine 10,000-image processing acceptance remains explicitly deferred.

'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


def insert_before(text: str, anchor: str, block: str, label: str) -> str:
    if "## Product closure — Cleaning frontend queue/progress truth CLOSED" in text:
        return text
    return replace_once(text, anchor, block + anchor, label)


# 1. Authoritative closure ledger.
path = Path("docs/TECH_DEBT_CLOSURE_V42_25.md")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "> **最近完整代码验收点：`3931a9a2d529845f9e698b22f62fe950a7a8b42f`**\n",
    f"> **最近完整代码验收点：`{ACCEPTED}`**\n",
    "tech accepted head",
)
text = replace_once(
    text,
    "> **最新正式门：Release Regression `34792673327` PASS；Navigation Action Fencing `34792673293` PASS（Real Chrome）；Frontend Runtime Stabilization `34792673296` PASS（unit + full Real Chrome）。Resource Discovery SQLite 永久跨平台 run `34700900542` 仍保持 Ubuntu + Windows 全绿。**\n",
    f"> **最新正式门：Release Regression `{RELEASE_RUN}` PASS；Navigation Action Fencing `{NAV_RUN}` PASS（Real Chrome）；Frontend Runtime Stabilization `{FRONTEND_RUN}` PASS（unit + full Real Chrome）。Resource Discovery SQLite 永久跨平台 run `34700900542` 仍保持 Ubuntu + Windows 全绿。**\n",
    "tech gates",
)
text = insert_before(text, "## Product closure — Cleaning durable execution truth CLOSED\n", CLOSURE, "tech closure")
text = text.replace(
    "Next product batch: audit the **cleaning frontend queue/progress truth**. The backend now exposes durable `resource_queue_position` / `resource_wait_reason`; the final clean-tab renderer/poll lifecycle must preserve that truth and must not create a frontend queue or simulated progress owner.",
    "Following batch status: **cleaning frontend queue/progress truth is now CLOSED**. Current next product scope is the storage import / deployment-test queue and progress truth audit.",
)
path.write_text(text, encoding="utf-8")


# 2. First-entry state.
path = Path("docs/CODEX_CURRENT_STATE.md")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "latest full code acceptance: 3931a9a2d529845f9e698b22f62fe950a7a8b42f\nFrontend Runtime run:        34792673296\n",
    f"latest full code acceptance: {ACCEPTED}\nFrontend Runtime run:        {FRONTEND_RUN}\n",
    "codex accepted head",
)
text = replace_once(text, "app.js cache:                42.25.95\n", "app.js cache:                42.25.96\n", "codex app cache")
text = replace_once(text, "main.mjs cache:              42.25.92\n", "main.mjs cache:              42.25.93\n", "codex main cache")
text = replace_once(text, "PollRegistry:                422511\n", "PollRegistry:                422517\n", "codex poll registry")
text = insert_before(text, "## Product closure — Cleaning durable execution truth CLOSED\n", CLOSURE, "codex closure")
text = text.replace(
    "Next product batch: audit the **cleaning frontend queue/progress truth**. The backend now exposes durable `resource_queue_position` / `resource_wait_reason`; the final clean-tab renderer/poll lifecycle must preserve that truth and must not create a frontend queue or simulated progress owner.",
    "Following batch status: **cleaning frontend queue/progress truth is now CLOSED**. Current next product scope is the storage import / deployment-test queue and progress truth audit.",
)
text = replace_once(
    text,
    "→ Cleaning durable execution truth CLOSED\n→ NEXT: cleaning frontend queue/progress truth, then continue storage import and deployment-test horizontal truth audit\n",
    "→ Cleaning durable execution truth CLOSED\n→ Cleaning frontend queue/progress truth CLOSED\n→ NEXT: storage import and deployment-test horizontal queue/progress truth audit\n",
    "codex priority",
)
path.write_text(text, encoding="utf-8")


# 3. Legacy runtime audit.
path = Path("docs/frontend-legacy-audit.md")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "commit:       3931a9a2d529845f9e698b22f62fe950a7a8b42f\nrun:          34792673296\n",
    f"commit:       {ACCEPTED}\nrun:          {FRONTEND_RUN}\n",
    "legacy accepted head",
)
text = replace_once(text, "app.js                  42.25.95\n", "app.js                  42.25.96\n", "legacy app cache")
text = replace_once(text, "main.mjs                  42.25.92\n", "main.mjs                  42.25.93\n", "legacy main cache")
text = replace_once(text, "poll-registry             422511\n", "poll-registry             422517\n", "legacy poll cache")
text = insert_before(text, "## Product closure — Cleaning durable execution truth CLOSED\n", CLOSURE, "legacy closure")
text = text.replace(
    "Next product batch: audit the **cleaning frontend queue/progress truth**. The backend now exposes durable `resource_queue_position` / `resource_wait_reason`; the final clean-tab renderer/poll lifecycle must preserve that truth and must not create a frontend queue or simulated progress owner.",
    "Following batch status: **cleaning frontend queue/progress truth is now CLOSED**. Current next product scope is the storage import / deployment-test queue and progress truth audit.",
)
text = text.replace(
    "Current next product scope: cleaning frontend queue/progress truth first, then continue the horizontal real queue-position/progress audit across storage import and deployment-test surfaces.",
    "Current next product scope: continue the horizontal real queue-position/progress audit across storage import and deployment-test surfaces.",
)
path.write_text(text, encoding="utf-8")


# 4. Final-owner map.
path = Path("docs/FRONTEND_OWNER_MAP_V42_25.md")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "> Latest fully accepted code point: `3931a9a2d529845f9e698b22f62fe950a7a8b42f` / run `34792673296`\n",
    f"> Latest fully accepted code point: `{ACCEPTED}` / run `{FRONTEND_RUN}`\n",
    "owner accepted head",
)
owner_closure = f'''## Product closure — Cleaning frontend queue/progress truth CLOSED

Final clean-tab owner chain:

```text
/api/v47/projects/{{project_id}}/clean-tasks
→ v47 compatibility projection backed by durable MATERIAL_BATCH/CLEAN truth
→ PlatformCore.cleaning.cleanTaskView
→ cleanTaskView427 / cleanTaskRow427
→ refreshCleanOps427Delta
→ PollRegistry(clean-tasks-v47)
```

The browser does not compute queue order or progress. `status_text`, `progress`, processed/total/flagged counts, `resource_queue_position`, `resource_wait_reason`, and worker identity remain server-derived. `PollRegistry` is the sole clean-list timer owner; the historical recursive `setTimeout(...renderOps427...,2200)` is retired. `awaiting_confirmation` is terminal for list polling, and navigation/tab changes clear the timer.

Permanent guards: `tests/frontend/clean-task-view.test.mjs`, `tests/frontend/poll-registry.test.mjs`, and the v47 queue-field assertions in `tests/api/test_clean_unified_execution_truth.py`. Evidence: RED `{RED}` / run `{RED_RUN}`; GREEN `{FOCUSED_RUN}`; product `{PRODUCT}`; accepted `{ACCEPTED}`; Release `{RELEASE_RUN}` PASS; Navigation `{NAV_RUN}` PASS with Real Chrome; Frontend `{FRONTEND_RUN}` PASS with unit + full Real Chrome. `VERSION.txt` remains `42.24.0`.

Next owner audit: storage import and deployment-test queue/progress truth. No frontend queue simulation or alternate progress owner should be introduced.

'''
text = insert_before(text, "## Product closure — Cleaning durable execution truth CLOSED\n", owner_closure, "owner closure")
text = text.replace(
    "Next owner audit: the final cleaning frontend row/poll owner must preserve durable queue position/wait reason and use lifecycle-managed polling without a parallel frontend truth model.",
    "Following owner audit status: cleaning frontend row/poll truth is CLOSED. Next: storage import and deployment-test queue/progress truth.",
)
text = text.replace(
    "- **Release boundary unchanged** — formal `VERSION.txt` remains `42.24.0`; visible version remains `v42.24.0`; classic `app.js` cache is `42.25.95`; `main.mjs` cache remains `42.25.92`. No merge/tag/release.",
    "- **Release boundary unchanged** — formal `VERSION.txt` remains `42.24.0`; visible version remains `v42.24.0`; classic `app.js` cache is `42.25.96`; `main.mjs` cache is `42.25.93`. No merge/tag/release.",
)
text = text.replace(
    "**Video resource queue truth and cleaning durable execution truth are CLOSED. Current next product scope: cleaning frontend queue/progress truth, then continue storage import and deployment-test surfaces. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**",
    "**Video resource queue truth, cleaning durable execution truth, and cleaning frontend queue/progress truth are CLOSED. Current next product scope: storage import and deployment-test queue/progress truth. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**",
)
path.write_text(text, encoding="utf-8")

print("cleaning frontend queue/progress authority docs synced")
