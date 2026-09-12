from pathlib import Path

PRODUCT = "8ba4e10db5958204aca3d87779711d8e95f5d83b"
MIGRATION_RUN = "34700801232"
PERMANENT_GUARD = "5b66ee03e5aaa3af3a2f18a9092f12e303f69937"
PERMANENT_RUN = "34700900542"
CLEANUP = "c6ac70b670a6297ccba065854779c10b8ca47cf3"
CLEANUP_RUN = "34700984963"


def read(path):
    return Path(path).read_text(encoding="utf-8")


def write(path, text):
    Path(path).write_text(text, encoding="utf-8")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 anchor, got {count}")
    return text.replace(old, new, 1)


def replace_between(text, start, end, body, label):
    a = text.find(start)
    b = text.find(end, a + len(start))
    if a < 0 or b < 0:
        raise SystemExit(f"{label}: section anchors missing")
    return text[:a] + body.rstrip() + "\n\n" + text[b:]


# AGENTS.md
path = "AGENTS.md"
text = read(path)
text = replace_once(
    text,
    "latest full code acceptance: f51d44c089b6342398c14bd38c8669747adad48b\nFrontend Runtime run:        34700252041",
    f"latest full code acceptance: {CLEANUP}\nFrontend Runtime run:        {CLEANUP_RUN}",
    "AGENTS state",
)
text = replace_once(
    text,
    "`34700252041` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 32/32。",
    f"`{CLEANUP_RUN}` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 32/32。Resource Discovery SQLite 永久 workflow `{PERMANENT_RUN}` 已在 Ubuntu + Windows 双平台通过。",
    "AGENTS acceptance",
)
new_scope = f"""## 下一批准确范围：Navigation Action Fencing

R20g–R20k 已 CLOSED。Resource Discovery SQLite / FD 本批也已经完成 **代码级关闭**，但只覆盖 SQLite 初始化/连接生命周期，不等于整个 Resource Lifecycle Zero-Point 已关闭。

Resource Discovery SQLite 本批验收：

```text
baseline / migration run: {MIGRATION_RUN}
old-code baseline:        2 failed / 2 passed
  - repeated schema/WAL initialization: FAILED as expected
  - _ModelManifest explicit close:      FAILED as expected (opened 6 / closed 0)
  - concurrent generation allocation:   PASS
  - Linux SQLite FD trend:               PASS
product:                  {PRODUCT}
post-migration focused:   6/6 PASS
permanent guard:          {PERMANENT_GUARD}
permanent guard run:      {PERMANENT_RUN}
Ubuntu:                   PASS (includes /proc SQLite FD trend)
Windows:                  PASS (Linux-only FD test skipped by contract)
cleanup:                  {CLEANUP}
cleanup Frontend run:     {CLEANUP_RUN}
cleanup Real Chrome:      32/32 PASS
formal VERSION.txt:       42.24.0 unchanged
```

最终代码合同：

```text
DiscoveryCache schema/WAL initialization → FileLock single owner + PRAGMA user_version gate
ordinary DiscoveryCache connection       → no journal_mode transition; per-connection PRAGMA only
DiscoveryCache transactions              → deterministic closing + explicit commit/rollback
_ModelManifest connections/cursor        → deterministic closing
permanent cross-platform CI              → .github/workflows/resource-discovery-sqlite-stability.yml
permanent test                            → tests/unit/test_resource_discovery_sqlite_lifecycle.py
```

**仍 OPEN / NOT VERIFIED：** 30–60 分钟真实生产 soak；以及 ZIP/file/subprocess/socket/tempfile/directory iterator/mmap/GPU worker/thread/executor 等其他资源生命周期。本批不得被描述为整个 Resource Lifecycle Zero-Point CLOSED。

按用户授权，SQLite 代码级闭环到这里先停，不让生产 soak 阻塞主线。下一批切到 **Navigation Action Fencing**：审计 POST/PUT/DELETE、XHR upload、setTimeout 与业务 callback 的 stale completion，确保动作可在后台完成，但离开来源页后不得切页、重绘旧页、弹旧 modal 或改当前页 DOM。优先补 Real Chrome：A slow mutation → B/C navigation → mutation completes，最终页面必须保持用户最后选择。"""
text = replace_between(
    text,
    "## 下一批准确范围：Resource Discovery SQLite / FD zero-point",
    "## 不得回退的核心合同",
    new_scope,
    "AGENTS scope",
)
old_priority = """```text
1. R20 final global reload/request zero-point
2. proven-dead app.js/runtime shell cleanup
3. stale async action fencing / lifecycle zero-point
4. cache-busting unification
5. semantic naming + deterministic tests + docs
6. technical-debt zero-point scan
7. unified task progress + durable queue productionization
8. resume A800 RC only after the above acceptance gates
```"""
new_priority = """```text
1. Navigation Action Fencing / stale mutation UI side-effect zero-point
2. R20 final global reload/request zero-point
3. External Algorithm Catalog read-only boundary
4. Resource Lifecycle production soak + remaining non-SQLite resource classes
5. ZIP 10k / Training Progress v2 / GPU Performance Tuner / Deployment Artifact E2E
6. app.js / app.py normalization + cache-busting / semantic naming / deterministic cleanup
7. technical-debt final zero-point + backend regression
8. A800 RC only after acceptance gates
```"""
text = replace_once(text, old_priority, new_priority, "AGENTS priority")
write(path, text)


# CODEX_CURRENT_STATE.md
path = "docs/CODEX_CURRENT_STATE.md"
text = read(path)
text = replace_once(
    text,
    "latest full code acceptance: f51d44c089b6342398c14bd38c8669747adad48b\nFrontend Runtime run:        34700252041",
    f"latest full code acceptance: {CLEANUP}\nFrontend Runtime run:        {CLEANUP_RUN}",
    "CODEX state",
)
text = replace_once(
    text,
    "Run `34700252041` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after R20k artifact cleanup. Browser navigation runs **32 tests and passed 32/32**.",
    f"Run `{CLEANUP_RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after Resource Discovery SQLite migration-artifact cleanup. Browser navigation runs **32 tests and passed 32/32**. Permanent Resource Discovery SQLite workflow `{PERMANENT_RUN}` passed on Ubuntu and Windows.",
    "CODEX acceptance",
)
old_priority = """```text
Resource Discovery SQLite / FD lifecycle code-level closure
→ production soak for resource lifecycle (30–60 min, separate acceptance)
→ resume R20 final global reload/request zero-point
→ Navigation Action Fencing / stale mutation side effects
→ external algorithm catalog read-only boundary
→ ZIP 10k / training progress / GPU tuner / deployment artifact E2E
→ app.js/app.py normalization
→ A800 RC
```"""
new_priority = """```text
Navigation Action Fencing / stale mutation UI side effects
→ resume R20 final global reload/request zero-point
→ external algorithm catalog read-only boundary
→ separate Resource Lifecycle production soak / non-SQLite resource classes
→ ZIP 10k / training progress / GPU tuner / deployment artifact E2E
→ app.js/app.py normalization
→ backend regression
→ A800 RC
```"""
text = replace_once(text, old_priority, new_priority, "CODEX priority")
anchor = "Current exact next scope is **Resource Discovery SQLite / FD lifecycle code-level closure**. Do not claim the entire production lifecycle gate closed until the separate 30–60 minute soak is actually executed."
section = f"""Current exact next scope was **Resource Discovery SQLite / FD lifecycle code-level closure**; that code-level slice is now closed below. The separate 30–60 minute production soak remains OPEN / NOT VERIFIED.

### Resource Discovery SQLite lifecycle — code-level CLOSED

A guarded baseline proved the two target defects before migration: reopening `DiscoveryCache` reran schema bootstrap/WAL work, and `_ModelManifest` opened 6 SQLite connections with 0 explicit closes. The same baseline already passed concurrent generation allocation and Linux FD trend, so the migration was kept narrowly scoped.

Migration result:

```text
DiscoveryCache._initialize
→ FileLock(<db>.init.lock)
→ PRAGMA user_version schema gate
→ WAL transition only during single-owner first initialization

DiscoveryCache._connect
→ foreign_keys + busy_timeout only
→ no repeated journal_mode transition

_ModelManifest
→ closing(connection)
→ transaction context only for commit/rollback
→ closing(cursor) for streamed rows
```

Acceptance:

```text
baseline/migration run: {MIGRATION_RUN}
old baseline:           2 failed / 2 passed
post-migration focused: 6/6 PASS
product:                {PRODUCT}
permanent CI commit:    {PERMANENT_GUARD}
permanent CI run:       {PERMANENT_RUN}
Ubuntu:                 PASS
Windows:                PASS
cleanup:                {CLEANUP}
cleanup Frontend run:   {CLEANUP_RUN}
Real Chrome:            32/32 PASS
```

Permanent proof: `tests/unit/test_resource_discovery_sqlite_lifecycle.py` + `.github/workflows/resource-discovery-sqlite-stability.yml`. One-shot migration artifacts are physically deleted.

**Boundary:** 30–60 minute production soak is still NOT VERIFIED. ZIP/file/subprocess/socket/tempfile/directory iterator/mmap/GPU worker/thread/executor lifecycle is outside this batch. The whole Resource Lifecycle Zero-Point therefore remains OPEN.

Current exact next scope: **Navigation Action Fencing**. Audit stale POST/PUT/DELETE, XHR upload and timer/callback completions so a business mutation may finish after navigation but cannot switch page, render the departed page, open an old modal, or mutate the current-page DOM."""
text = replace_once(text, anchor, section, "CODEX resource section")
write(path, text)


# TECH_DEBT_CLOSURE_V42_25.md
path = "docs/TECH_DEBT_CLOSURE_V42_25.md"
text = read(path)
text = replace_once(
    text,
    "**最近完整代码验收点：`f51d44c089b6342398c14bd38c8669747adad48b`**",
    f"**最近完整代码验收点：`{CLEANUP}`**",
    "TECH accepted",
)
text = replace_once(
    text,
    "**Frontend Runtime Stabilization：run `34700252041`，frontend + Real Chrome 全绿，Real Chrome 32/32 passed。**",
    f"**Frontend Runtime Stabilization：run `{CLEANUP_RUN}`，frontend + Real Chrome 全绿，Real Chrome 32/32 passed；Resource Discovery SQLite 永久跨平台 run `{PERMANENT_RUN}` Ubuntu + Windows 全绿。**",
    "TECH run",
)
text = replace_once(
    text,
    "| resource-discovery SQLite / FD lifecycle | lock-safe single-owner init + deterministic close + soak | **IN PROGRESS — code-level closure next** |",
    "| resource-discovery SQLite init / manifest FD lifecycle | lock-safe single-owner init + deterministic close | **CODE-LEVEL CLOSED; production soak OPEN** |",
    "TECH resource row",
)
insert = f"""## 2.6 Resource Discovery SQLite / FD lifecycle — code-level closure

本批只关闭 Resource Discovery 的 SQLite 初始化与连接生命周期，不扩张为整个 Resource Lifecycle Zero-Point。

旧代码 baseline 在真正迁移前得到可复现红线：

```text
run: {MIGRATION_RUN}
4 tests collected
reopen cache schema/WAL bootstrap      FAILED（重复 executescript）
_ModelManifest explicit close          FAILED（opened 6 / closed 0）
concurrent init + generation allocation PASS
Linux SQLite FD trend                   PASS
baseline total                          2 failed / 2 passed
```

迁移后：

```text
DiscoveryCache schema/WAL → FileLock single-owner + PRAGMA user_version gate
ordinary connection       → 不再执行 PRAGMA journal_mode=WAL
transaction               → closing(connection) + explicit commit/rollback
_ModelManifest            → closing(connection/cursor)
focused regression        → 6/6 PASS
```

永久验收：

```text
product:                 {PRODUCT}
permanent guard commit:  {PERMANENT_GUARD}
permanent workflow:      .github/workflows/resource-discovery-sqlite-stability.yml
permanent run:           {PERMANENT_RUN}
Ubuntu:                  PASS（含 /proc SQLite FD trend）
Windows:                 PASS（Linux-only FD test 按合同 skip）
cleanup:                 {CLEANUP}
cleanup Frontend run:    {CLEANUP_RUN}
cleanup Real Chrome:     32/32 PASS
formal VERSION.txt:      42.24.0 unchanged
```

永久测试：`tests/unit/test_resource_discovery_sqlite_lifecycle.py`。一次性 migration helper/workflow 已物理删除。

**仍 OPEN / NOT VERIFIED：** 30–60 分钟真实生产 soak；file/ZIP handle、subprocess pipe、socket、tempfile、directory iterator、mmap、Torch/GPU worker process、worker lock/stale PID、thread/executor 等其他资源类。故整个 Resource Lifecycle Zero-Point 仍不得标 CLOSED。

按用户授权，下一主线切到 **Navigation Action Fencing**；生产 soak 单独列为后续验收，不阻塞当前代码主线。

"""
text = replace_once(text, "## 3. Canonical owners", insert + "## 3. Canonical owners", "TECH resource insert")
write(path, text)


# FRONTEND_OWNER_MAP_V42_25.md
path = "docs/FRONTEND_OWNER_MAP_V42_25.md"
text = read(path)
text = replace_once(
    text,
    "Latest fully accepted code point: `f51d44c089b6342398c14bd38c8669747adad48b` / run `34700252041`",
    f"Latest fully accepted code point: `{CLEANUP}` / run `{CLEANUP_RUN}`",
    "OWNER accepted",
)
needle = "R20k product: `1e929d47cf1a96bcb3fa17ad3eeb1e6c6029addb`; focused run `34700022284` (211/211 frontend unit, focused Chrome 2/2); validation `60775456f3d4c8a441ba58ce65106af114aeebb2` / run `34700127243`; cleanup `f51d44c089b6342398c14bd38c8669747adad48b` / run `34700252041`; frontend PASS; Real Chrome **32/32 passed**. `doImportData` remains the live v18 XHR owner, but its successful completion now refreshes only labels and the current paged material domain. One-shot R20k migration artifacts are physically deleted.  "
addition = needle + f"\n\nCross-cutting P0 checkpoint: Resource Discovery SQLite lifecycle product `{PRODUCT}`; permanent Linux/Windows guard `{PERMANENT_GUARD}` / run `{PERMANENT_RUN}`; cleanup `{CLEANUP}` / Frontend Runtime `{CLEANUP_RUN}` with Real Chrome **32/32 passed**. This is not a new frontend owner batch and does not close the broader resource-lifecycle soak gate.  "
text = replace_once(text, needle, addition, "OWNER resource note")
write(path, text)


# frontend-legacy-audit.md
path = "docs/frontend-legacy-audit.md"
text = read(path)
text = replace_once(
    text,
    "commit:       f51d44c089b6342398c14bd38c8669747adad48b\nrun:          34700252041",
    f"commit:       {CLEANUP}\nrun:          {CLEANUP_RUN}",
    "AUDIT accepted",
)
needle = "R20k did **not** retire the live `doImportData` owner. It migrated only its successful completion refresh from broad `reload()` to labels + current paged materials. Acceptance: product `1e929d47cf1a96bcb3fa17ad3eeb1e6c6029addb`, validation `60775456f3d4c8a441ba58ce65106af114aeebb2` / run `34700127243`, cleanup `f51d44c089b6342398c14bd38c8669747adad48b` / run `34700252041`, Real Chrome **32/32**. Permanent contracts: `tests/frontend/v18-import-completion-scope.test.mjs` and `tests/browser/material-pagination-performance.spec.mjs`."
addition = needle + f"\n\nCross-cutting checkpoint after R20k: Resource Discovery SQLite code-level lifecycle was accepted at product `{PRODUCT}`. Baseline run `{MIGRATION_RUN}` proved the two target failures before migration; permanent cross-platform workflow run `{PERMANENT_RUN}` passed Ubuntu + Windows; artifact cleanup `{CLEANUP}` passed Frontend Runtime `{CLEANUP_RUN}` with Real Chrome **32/32**. Production soak and non-SQLite resource classes remain outside this frontend audit and OPEN."
text = replace_once(text, needle, addition, "AUDIT resource note")
write(path, text)


if Path("VERSION.txt").read_text(encoding="utf-8").strip() != "42.24.0":
    raise SystemExit("formal VERSION.txt changed unexpectedly")

for required in (
    "tests/unit/test_resource_discovery_sqlite_lifecycle.py",
    ".github/workflows/resource-discovery-sqlite-stability.yml",
):
    if not Path(required).exists():
        raise SystemExit(f"permanent resource guard missing: {required}")

for retired in (
    "tools/migrate_resource_discovery_sqlite_lifecycle.py",
    ".github/workflows/migrate-resource-discovery-sqlite-lifecycle.yml",
):
    if Path(retired).exists():
        raise SystemExit(f"one-shot resource artifact still present: {retired}")

print("Resource Discovery SQLite accepted handoff synchronized across five authority documents")
