from pathlib import Path

ACCEPTED = "1c3fa7f2b5cb826c0998f249637241a59134f053"
RELEASE = "34794630826"
NAV = "34794630808"
FRONTEND = "34794630837"

CLOSURE = r'''## Product closure — Deployment-test durable queue/progress truth CLOSED

The deployment-test business surface now preserves the same durable task truth as the unified v62 task API. Previously the v61 compatibility projection flattened a resource-waiting durable task back to persisted `QUEUED`, dropped queue/resource/worker metadata, and the final `benchPredictOne` loop only considered `QUEUED / RUNNING / CANCEL_REQUESTED` active. That combination could make a real `WAITING_RESOURCE` deployment test appear terminal or fail without showing why it was waiting.

Closed semantics:

```text
v61 business projection: delegates durable task fields to task_to_public()
compatibility aliases: id / progress / stage / result remain for the existing deployment surface
WAITING_RESOURCE: remains active and visible instead of being flattened to QUEUED
queue truth: resource_queue_position + resource_wait_reason are server-derived and visible
worker/progress truth: worker_id / phase / progress_percent come from durable public truth
active polling: after v61 creation, benchPredictOne reads /api/v62/projects/{project_id}/tasks/{task_id} while the task is active
terminal success: v61 is read once after SUCCEEDED to obtain deployment-specific result payload
frontend projection: PlatformCore.deployment.deploymentTaskView reuses taskPoller active/progress semantics
queue order / resource admission / worker claim / progress generation / process fencing: unchanged
```

Permanent guards include `tests/api/test_deployment_test_runtime.py`, `tests/frontend/deployment-runtime-source.test.mjs`, `tests/frontend/deployment-task-view.test.mjs`, `tests/unit/task_runtime/test_public_projection.py`, and `tests/unit/test_deployment_inference_process_fencing.py`. Release Regression now permanently runs the deployment business-projection contract and is triggered by the deployment task view/wiring guards. The frontend does not invent queue order or percentage; it only renders unified durable truth.

Evidence:

```text
valid RED head:             5748a89155e653a49c8a8c743cdd3de7a9fa67cf
valid RED run:              34794353496 (backend v61 QUEUED vs v62 WAITING_RESOURCE; final frontend unified-truth wiring RED)
focused/full GREEN run:     34794490531 PASS (API + frontend + public projection + deployment fencing + full frontend unit)
product commit:             0b800a54ae64507314a5f9199734759250691cb6
formal accepted clean HEAD: 1c3fa7f2b5cb826c0998f249637241a59134f053
Release Regression:         34794630826 PASS
Navigation Action Fencing:  34794630808 PASS (Real Chrome PASS)
Frontend Runtime:           34794630837 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

All temporary deployment RED/migration helpers and workflows were physically removed before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Next product batch: **storage import polling owner / lifecycle-managed polling truth**. Storage import already preserves durable queue/progress display truth, but its action runtime still owns a direct `while + setTimeout(1200)` polling loop; that owner must be audited separately without mixing it into this deployment closure.

'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def insert_closure(text: str, label: str) -> str:
    marker = "## Product closure — Cleaning frontend queue/progress truth CLOSED"
    if CLOSURE.strip() in text:
        return text
    if marker not in text:
        raise SystemExit(f"{label}: cleaning frontend closure marker missing")
    return text.replace(marker, CLOSURE + marker, 1)


# TECH ledger
path = Path("docs/TECH_DEBT_CLOSURE_V42_25.md")
text = path.read_text(encoding="utf-8")
text = replace_once(text,
    "> **最近完整代码验收点：`736b2acdbf2560be657011035de173cde67517d0`**",
    f"> **最近完整代码验收点：`{ACCEPTED}`**",
    "tech accepted head")
text = replace_once(text,
    "> **最新正式门：Release Regression `34793457861` PASS；Navigation Action Fencing `34793457872` PASS（Real Chrome）；Frontend Runtime Stabilization `34793457920` PASS（unit + full Real Chrome）。Resource Discovery SQLite 永久跨平台 run `34700900542` 仍保持 Ubuntu + Windows 全绿。**",
    f"> **最新正式门：Release Regression `{RELEASE}` PASS；Navigation Action Fencing `{NAV}` PASS（Real Chrome）；Frontend Runtime Stabilization `{FRONTEND}` PASS（unit + full Real Chrome）。Resource Discovery SQLite 永久跨平台 run `34700900542` 仍保持 Ubuntu + Windows 全绿。**",
    "tech formal gates")
text = insert_closure(text, "tech")
text = text.replace(
    "Next product scope: continue the horizontal **storage import / deployment-test queue and progress truth audit**. Genuine 10,000-image processing acceptance remains explicitly deferred.",
    "Deployment-test durable queue/progress truth is now CLOSED. Next product scope: **storage import polling owner / lifecycle-managed polling truth**. Genuine 10,000-image processing acceptance remains explicitly deferred.")
path.write_text(text, encoding="utf-8")

# CODEX handoff
path = Path("docs/CODEX_CURRENT_STATE.md")
text = path.read_text(encoding="utf-8")
text = replace_once(text,
    "latest full code acceptance: 736b2acdbf2560be657011035de173cde67517d0",
    f"latest full code acceptance: {ACCEPTED}",
    "codex accepted head")
text = replace_once(text,
    "Frontend Runtime run:        34793457920",
    f"Frontend Runtime run:        {FRONTEND}",
    "codex frontend run")
text = replace_once(text, "app.js cache:                42.25.96", "app.js cache:                42.25.97", "codex app cache")
text = replace_once(text, "main.mjs cache:              42.25.93", "main.mjs cache:              42.25.94", "codex main cache")
text = insert_closure(text, "codex")
text = text.replace(
    "Next product scope: continue the horizontal **storage import / deployment-test queue and progress truth audit**. Genuine 10,000-image processing acceptance remains explicitly deferred.",
    "Deployment-test durable queue/progress truth is now CLOSED. Next product scope: **storage import polling owner / lifecycle-managed polling truth**. Genuine 10,000-image processing acceptance remains explicitly deferred.")
text = text.replace("storage import and deployment-test queue/progress truth", "storage import polling owner / lifecycle-managed polling truth")
text = text.replace("storage import / deployment-test queue/progress truth", "storage import polling owner / lifecycle-managed polling truth")
path.write_text(text, encoding="utf-8")

# Frontend legacy audit
path = Path("docs/frontend-legacy-audit.md")
text = path.read_text(encoding="utf-8")
text = replace_once(text,
    "commit:       736b2acdbf2560be657011035de173cde67517d0",
    f"commit:       {ACCEPTED}",
    "legacy accepted head")
text = replace_once(text, "run:          34793457920", f"run:          {FRONTEND}", "legacy frontend run")
text = replace_once(text, "app.js                  42.25.96", "app.js                  42.25.97", "legacy app cache")
text = replace_once(text, "main.mjs                  42.25.93", "main.mjs                  42.25.94", "legacy main cache")
text = insert_closure(text, "legacy")
text = text.replace(
    "Next product scope: continue the horizontal **storage import / deployment-test queue and progress truth audit**. Genuine 10,000-image processing acceptance remains explicitly deferred.",
    "Deployment-test durable queue/progress truth is now CLOSED. Next product scope: **storage import polling owner / lifecycle-managed polling truth**. Genuine 10,000-image processing acceptance remains explicitly deferred.")
text = text.replace("storage import and deployment-test queue/progress truth", "storage import polling owner / lifecycle-managed polling truth")
text = text.replace("storage import and deployment-test surfaces", "storage import polling owner / lifecycle-managed polling surface")
path.write_text(text, encoding="utf-8")

# Final owner map
path = Path("docs/FRONTEND_OWNER_MAP_V42_25.md")
text = path.read_text(encoding="utf-8")
text = replace_once(text,
    "> Latest fully accepted code point: `736b2acdbf2560be657011035de173cde67517d0` / run `34793457920`",
    f"> Latest fully accepted code point: `{ACCEPTED}` / run `{FRONTEND}`",
    "owner accepted head")
text = insert_closure(text, "owner")
text = text.replace(
    "Next owner audit: storage import and deployment-test queue/progress truth. No frontend queue simulation or alternate progress owner should be introduced.",
    "Deployment-test durable queue/progress truth is CLOSED. Next owner audit: storage import polling owner / lifecycle-managed polling truth. No frontend queue simulation or alternate progress owner should be introduced.")
text = text.replace(
    "Following owner audit status: cleaning frontend row/poll truth is CLOSED. Next: storage import and deployment-test queue/progress truth.",
    "Following owner audit status: cleaning frontend row/poll truth and deployment-test durable queue/progress truth are CLOSED. Next: storage import polling owner / lifecycle-managed polling truth.")
text = text.replace("storage import and deployment-test queue/progress truth", "storage import polling owner / lifecycle-managed polling truth")
text = text.replace("storage import and deployment-test surfaces", "storage import polling owner / lifecycle-managed polling surface")
text = text.replace("classic `app.js` cache is `42.25.96`; `main.mjs` cache remains `42.25.93`", "classic `app.js` cache is `42.25.97`; `main.mjs` cache is `42.25.94`")
path.write_text(text, encoding="utf-8")

print("deployment durable queue/progress truth authority docs synchronized")
