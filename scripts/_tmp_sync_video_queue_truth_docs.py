from pathlib import Path

CLEAN_HEAD = "cb81ca39016aea0fc53ed52090f0b0199d39109a"
FRONTEND_RUN = "34789704610"
RELEASE_RUN = "34789701814"
NAV_RUN = "34789703315"
RED_COMMIT = "32284a8972faec46775144b8c47406e67edee014"
RED_RUN = "34789541200"
GREEN_RUN = "34789628840"
PRODUCT_COMMIT = "c0fee2b7c8dfbf03481cbc6dfb1019f922293576"
MARKER = "## Product closure — Video resource queue truth CLOSED"

COMMON = f'''{MARKER}

The live v424 video task page already reads `/api/v33/projects/{{project_id}}/video-tasks`, whose public projection is backed by the shared durable `TaskRepository`. `task_to_public()` dynamically exposes resource-scoped `resource_queue_position` / `resource_wait_reason`; a durable queued task in the `resource_waiting` phase is publicly projected as `WAITING_RESOURCE`. The frontend previously dropped that queue metadata and also failed to classify `WAITING_RESOURCE` as an active video task, so a genuinely resource-waiting task could lose timely managed polling and never show its real queue position/reason.

Closed semantics:

```text
QUEUED: remains active under PollRegistry and shows real resource_queue_position when available
WAITING_RESOURCE: remains active, shows “等待资源”, real queue position and resource wait reason
initial render + delta polling: both use the same v424 row projection and preserve runtimeText
progress: continues to come from durable server/worker truth; no frontend progress simulation
queue ordering / claim / queue_rank / resource fencing: unchanged
cancel / stale-worker / publish fencing: unchanged
```

The fix is intentionally narrow. `static/modules/video-tasks.js` now projects the existing durable queue metadata into `runtimeText` and treats public `WAITING_RESOURCE` as active; the final v424 `videoTaskRow424()` renders that view-model text. `PollRegistry` remains the sole video polling lifecycle owner. Permanent behavior guard: `tests/frontend/video-tasks.test.mjs`, which executes the real final row renderer and verifies both queued and waiting-resource behavior.

Evidence:

```text
final permanent RED commit: {RED_COMMIT}
valid RED run:              {RED_RUN} (242 total; 239 PASS; only 3 intended video truth assertions RED)
focused/full GREEN run:     {GREEN_RUN} PASS
product/self-cleanup:       {PRODUCT_COMMIT}
formal clean HEAD:          {CLEAN_HEAD}
Release Regression:         {RELEASE_RUN} PASS
Navigation Action Fencing:  {NAV_RUN} PASS (Real Chrome PASS)
Frontend Runtime:           {FRONTEND_RUN} PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP processing acceptance was performed. One-shot product/gate migration assets were physically deleted before formal gate acceptance.
'''

OWNER_SECTION = f'''{MARKER}

Final owner chain:

```text
/api/v33/projects/{{project_id}}/video-tasks
→ shared TaskRepository / task_to_public
→ _public_video_task
→ PlatformCore.video.normalizeVideoTask
→ videoTaskRow424
→ patchVideoRows424 / renderVideo424
→ PollRegistry(video-frames)
```

`resource_queue_position` and `resource_wait_reason` remain server-derived dynamic truth. `WAITING_RESOURCE` is a public active status and must continue polling. The v424 row displays `runtimeText`; it does not compute queue order locally. No alternate timer, frontend queue model, or shadow progress owner was introduced.

Permanent guard: `tests/frontend/video-tasks.test.mjs` executes the actual final row renderer and locks queued / waiting-resource visibility plus active-state polling semantics.

Evidence: RED `{RED_COMMIT}` / run `{RED_RUN}`; GREEN `{GREEN_RUN}`; product `{PRODUCT_COMMIT}`; accepted clean HEAD `{CLEAN_HEAD}`; Release `{RELEASE_RUN}` PASS; Navigation `{NAV_RUN}` PASS with Real Chrome; Frontend `{FRONTEND_RUN}` PASS with unit + full Real Chrome. `VERSION.txt` remains `42.24.0`.
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


def insert_before(text: str, anchor: str, section: str, label: str) -> str:
    if MARKER in text:
        return text
    if anchor not in text:
        raise SystemExit(f"{label}: anchor missing")
    return text.replace(anchor, section.rstrip() + "\n\n" + anchor, 1)


# CODEX current-state handoff.
p = Path("docs/CODEX_CURRENT_STATE.md")
s = p.read_text(encoding="utf-8")
s = s.replace("latest full code acceptance: 2bc6f72fddd878a7e2d4802c5affd3d640f807e7", f"latest full code acceptance: {CLEAN_HEAD}", 1)
s = s.replace("Frontend Runtime run:        34788824849", f"Frontend Runtime run:        {FRONTEND_RUN}", 1)
s = insert_before(s, "## Product closure — AI annotation polling queue metadata truth CLOSED", COMMON, p.name)
s = replace_once(
    s,
    "→ AI annotation polling queue metadata truth CLOSED\n→ NEXT: horizontal queue-position/progress truth audit across video, cleaning, storage import and deployment test",
    "→ AI annotation polling queue metadata truth CLOSED\n→ Video resource queue truth CLOSED\n→ NEXT: horizontal queue-position/progress truth audit across cleaning, storage import and deployment test",
    "CODEX priority",
)
p.write_text(s, encoding="utf-8")

# Technical-debt authority ledger.
p = Path("docs/TECH_DEBT_CLOSURE_V42_25.md")
s = p.read_text(encoding="utf-8")
s = s.replace("**最近完整代码验收点：`2bc6f72fddd878a7e2d4802c5affd3d640f807e7`**", f"**最近完整代码验收点：`{CLEAN_HEAD}`**", 1)
s = insert_before(s, "## Product closure — AI annotation polling queue metadata truth CLOSED", COMMON, p.name)
s = replace_once(
    s,
    "**Current next product scope: continue the horizontal real queue-position/progress audit across video, cleaning, storage import and deployment-test surfaces. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**",
    "**Video resource queue truth is CLOSED. Current next product scope: continue the horizontal real queue-position/progress audit across cleaning, storage import and deployment-test surfaces. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**",
    "TECH_DEBT next scope",
)
p.write_text(s, encoding="utf-8")

# Frontend legacy audit.
p = Path("docs/frontend-legacy-audit.md")
s = p.read_text(encoding="utf-8")
s = s.replace("commit:       2bc6f72fddd878a7e2d4802c5affd3d640f807e7", f"commit:       {CLEAN_HEAD}", 1)
s = s.replace("run:          34788824849", f"run:          {FRONTEND_RUN}", 1)
s = insert_before(s, "## Product closure — AI annotation polling queue metadata truth CLOSED", COMMON, p.name)
s = replace_once(
    s,
    "**Current next product scope: continue the horizontal real queue-position/progress audit across video, cleaning, storage import and deployment-test surfaces. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**",
    "**Video resource queue truth is CLOSED. Current next product scope: continue the horizontal real queue-position/progress audit across cleaning, storage import and deployment-test surfaces. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**",
    "legacy audit next scope",
)
p.write_text(s, encoding="utf-8")

# Final-owner map.
p = Path("docs/FRONTEND_OWNER_MAP_V42_25.md")
s = p.read_text(encoding="utf-8")
s = s.replace(
    "Latest fully accepted code point: `2bc6f72fddd878a7e2d4802c5affd3d640f807e7` / run `34788824849`",
    f"Latest fully accepted code point: `{CLEAN_HEAD}` / run `{FRONTEND_RUN}`",
    1,
)
s = insert_before(s, "## Product closure — AI annotation polling queue metadata truth CLOSED", OWNER_SECTION, p.name)
s = replace_once(
    s,
    "**Current next product scope: continue the horizontal real queue-position/progress audit across video, cleaning, storage import and deployment-test surfaces. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**",
    "**Video resource queue truth is CLOSED. Current next product scope: continue the horizontal real queue-position/progress audit across cleaning, storage import and deployment-test surfaces. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**",
    "owner map next scope",
)
p.write_text(s, encoding="utf-8")

for path in (
    "docs/TECH_DEBT_CLOSURE_V42_25.md",
    "docs/CODEX_CURRENT_STATE.md",
    "docs/frontend-legacy-audit.md",
    "docs/FRONTEND_OWNER_MAP_V42_25.md",
):
    text = Path(path).read_text(encoding="utf-8")
    if MARKER not in text:
        raise SystemExit(f"closure marker missing from {path}")
    if "42.24.0" not in text:
        raise SystemExit(f"formal version boundary missing from {path}")
