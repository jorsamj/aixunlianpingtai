from pathlib import Path

ACCEPTED = "f51d44c089b6342398c14bd38c8669747adad48b"
RUN = "34700252041"
PRODUCT = "1e929d47cf1a96bcb3fa17ad3eeb1e6c6029addb"
VALIDATION = "60775456f3d4c8a441ba58ce65106af114aeebb2"
VALIDATION_RUN = "34700127243"
CACHE = "42.25.87"


def read(path):
    return Path(path).read_text(encoding="utf-8")


def write(path, text):
    Path(path).write_text(text, encoding="utf-8")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 anchor, got {count}")
    return text.replace(old, new, 1)


def replace_between(text, start, end, new_body, label):
    a = text.find(start)
    b = text.find(end, a + len(start))
    if a < 0 or b < 0:
        raise SystemExit(f"{label}: section anchors missing")
    return text[:a] + new_body.rstrip() + "\n\n" + text[b:]


# AGENTS.md
path = "AGENTS.md"
text = read(path)
text = replace_once(text,
"latest full code acceptance: 9c7a3497b9acf69364d83e5cf778ec4139bdbc69\nFrontend Runtime run:        34699599796\nformal VERSION.txt:          42.24.0\nfrontend badge:              v42.24.0\napp.js cache:                42.25.86",
f"latest full code acceptance: {ACCEPTED}\nFrontend Runtime run:        {RUN}\nformal VERSION.txt:          42.24.0\nfrontend badge:              v42.24.0\napp.js cache:                {CACHE}", "AGENTS state")
text = replace_once(text,
"`34699599796` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 31/31。",
f"`{RUN}` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 32/32。", "AGENTS run")
new_section = f"""## 下一批准确范围：Resource Discovery SQLite / FD zero-point

R20g、R20h、R20i、R20j、R20k 已 CLOSED。R20k 保留 live v18 `doImportData` 的上传、进度和结果语义，只把成功后的 broad `reload()` 收窄为标签刷新 + 当前数据集页分页素材刷新；永久 Real Chrome 请求合同已并入 material pagination suite。

R20k 验收：

```text
product:            {PRODUCT}
focused run:        34700022284 (211/211 frontend unit + focused Chrome 2/2 PASS)
validation:         {VALIDATION}
validation run:     {VALIDATION_RUN}
validation Chrome:  32/32 PASS
cleanup:            {ACCEPTED}
cleanup run:        {RUN}
cleanup Chrome:     32/32 PASS
app.js cache:       {CACHE}
main.mjs cache:     42.25.88
```

永久合同：`tests/frontend/v18-import-completion-scope.test.mjs` + `tests/browser/material-pagination-performance.spec.mjs`。一次性 R20k migration helper/workflow 已物理删除。

按用户授权，前端 R20 同类小债先暂停扩张，下一批切到更高生产风险的 **Resource Discovery SQLite / FD lifecycle**。当前已审计出的真实风险：

```text
DiscoveryCache._connect() 每次连接都执行 PRAGMA journal_mode=WAL
DiscoveryCache 初始化 schema/cache_meta 缺少跨进程 single-owner fencing
_ModelManifest 多处使用 sqlite3.Connection context manager，但该 context manager 只提交/回滚、不负责 close
```

目标：WAL 只在受锁 schema 初始化阶段设置；初始化跨进程 single-owner；普通连接只做 per-connection PRAGMA；所有 DiscoveryCache / _ModelManifest SQLite 连接 deterministic close；补并发初始化、generation 写竞争、Linux FD trend 永久测试。30–60 分钟生产 soak 未执行前必须保持 **NOT VERIFIED**，不得提前宣称整个 Resource Lifecycle Zero-Point CLOSED。"""
text = replace_between(text, "## 下一批准确范围：R20 final zero-point", "## 不得回退的核心合同", new_section, "AGENTS next")
write(path, text)

# CODEX_CURRENT_STATE.md
path = "docs/CODEX_CURRENT_STATE.md"
text = read(path)
text = replace_once(text,
"latest full code acceptance: 9c7a3497b9acf69364d83e5cf778ec4139bdbc69\nFrontend Runtime run:        34699599796",
f"latest full code acceptance: {ACCEPTED}\nFrontend Runtime run:        {RUN}", "CODEX state")
text = replace_once(text, "app.js cache:                42.25.86", f"app.js cache:                {CACHE}", "CODEX cache")
text = replace_once(text,
"Run `34699599796` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after R20j artifact cleanup. Browser navigation runs **31 tests and passed 31/31**.",
f"Run `{RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after R20k artifact cleanup. Browser navigation runs **32 tests and passed 32/32**.", "CODEX run")
old_priority = """app.js/global reload/request debt
→ live v18 doImportData completion scoped refresh
→ live training stop/delete scoped refresh
→ historical import/saveAssign generation liveness cleanup
→ proven dead app.js/runtime shell cleanup
→ stale async action fencing / lifecycle zero-point
→ cache-busting unification
→ semantic naming/dead-code cleanup
→ unified task progress + durable queue productionization
→ A800 RC"""
new_priority = """Resource Discovery SQLite / FD lifecycle code-level closure
→ production soak for resource lifecycle (30–60 min, separate acceptance)
→ resume R20 final global reload/request zero-point
→ Navigation Action Fencing / stale mutation side effects
→ external algorithm catalog read-only boundary
→ ZIP 10k / training progress / GPU tuner / deployment artifact E2E
→ app.js/app.py normalization
→ A800 RC"""
text = replace_once(text, old_priority, new_priority, "CODEX priority")
anchor = "Current exact next scope is **R20k: live v18 `doImportData` success-path scoped refresh**. Preserve its modal/progress/result semantics, replace broad reload with label refresh plus paged-material refresh only while on 数据集, and lock the request boundary in Real Chrome."
r20k = f"""### R20k — live v18 import completion scoped refresh

The final v36 import modal still calls the unique live `doImportData` XHR owner. R20k preserved that UI/protocol owner and replaced only the success-path broad `await reload()` with `refreshLabels414(false)` plus `reloadMaterialPage61()` when the user is still on 数据集. The permanent browser contract performs a mocked ZIP upload and rejects project/dataset/image/job/algorithm/bootstrap fan-out.

```text
product:            {PRODUCT}
focused run:        34700022284 (211/211 frontend unit; focused Chrome 2/2 PASS)
validation:         {VALIDATION}
validation run:     {VALIDATION_RUN}
validation Chrome:  32/32 PASS
cleanup:            {ACCEPTED}
cleanup run:        {RUN}
cleanup Chrome:     32/32 PASS
app.js cache:       {CACHE}
```

Permanent proof: `tests/frontend/v18-import-completion-scope.test.mjs` and `tests/browser/material-pagination-performance.spec.mjs`. One-shot migration artifacts are physically deleted.

Current exact next scope is **Resource Discovery SQLite / FD lifecycle code-level closure**. Do not claim the entire production lifecycle gate closed until the separate 30–60 minute soak is actually executed."""
text = replace_once(text, anchor, r20k, "CODEX R20k")
write(path, text)

# TECH_DEBT_CLOSURE_V42_25.md
path = "docs/TECH_DEBT_CLOSURE_V42_25.md"
text = read(path)
text = replace_once(text, "**最近完整代码验收点：`9c7a3497b9acf69364d83e5cf778ec4139bdbc69`**", f"**最近完整代码验收点：`{ACCEPTED}`**", "TECH accepted")
text = replace_once(text, "**Frontend Runtime Stabilization：run `34699599796`，frontend + Real Chrome 全绿，Real Chrome 31/31 passed。**", f"**Frontend Runtime Stabilization：run `{RUN}`，frontend + Real Chrome 全绿，Real Chrome 32/32 passed。**", "TECH run")
text = replace_once(text, "| resource-discovery SQLite concurrent cache initialization | lock-safe/single-owner cache initialization | **OPEN — R20e validation diagnostic** |", "| resource-discovery SQLite / FD lifecycle | lock-safe single-owner init + deterministic close + soak | **IN PROGRESS — code-level closure next** |", "TECH resource row")
text = replace_once(text, "| live v18 `doImportData` success broad reload | labels + paged materials only | **OPEN — R20k** |", "| live v18 `doImportData` success broad reload | labels + paged materials only | **CLOSED (R20k)** |", "TECH R20k row")
insert = f"""## 2.5 R20k — live v18 import completion scoped refresh

R20k 保留最终 v36 `importData()` → 唯一 `doImportData()` → v18 XHR 的真实 owner，只迁移成功后的刷新边界：`await reload()` 已替换为 `refreshLabels414(false)`，且仅在用户仍处于数据集页时调用 `reloadMaterialPage61()`。导入进度、结果卡、警告和 toast 语义保持不变。

永久 Real Chrome 合同真实走 file input + v18 POST mock，并禁止 projects/datasets/images/jobs/algorithms/publish/test_models/bootstrap 等 broad fan-out。

```text
product:            {PRODUCT}
focused run:        34700022284
focused frontend:   211/211 PASS
focused Chrome:     2/2 PASS
validation:         {VALIDATION}
validation run:     {VALIDATION_RUN}
validation Chrome:  32/32 PASS
cleanup:            {ACCEPTED}
cleanup run:        {RUN}
cleanup Chrome:     32/32 PASS
app.js cache:       {CACHE}
```

永久合同：`tests/frontend/v18-import-completion-scope.test.mjs` + `tests/browser/material-pagination-performance.spec.mjs`。一次性 helper/workflow 已物理删除。

R20 尚未整体 CLOSED；根据用户授权，先切换到 P0 Resource Discovery SQLite / FD lifecycle。代码级并发与 deterministic close 可在 CI 闭环，但 30–60 分钟生产 soak 未执行前仍标记 NOT VERIFIED。

"""
text = replace_once(text, "## 3. Canonical owners", insert + "## 3. Canonical owners", "TECH insert R20k")
write(path, text)

# FRONTEND_OWNER_MAP_V42_25.md
path = "docs/FRONTEND_OWNER_MAP_V42_25.md"
text = read(path)
text = replace_once(text, "Latest fully accepted code point: `9c7a3497b9acf69364d83e5cf778ec4139bdbc69` / run `34699599796`", f"Latest fully accepted code point: `{ACCEPTED}` / run `{RUN}`", "OWNER accepted")
text = replace_once(text, "Real Chrome: 31/31 passed", "Real Chrome: 32/32 passed", "OWNER chrome")
text = replace_once(text, "| R20j | zero-reference dataset actions retired; live import and MaterialPagination owners preserved | `9c7a3497b9...` / `34699599796` (31/31) |", f"| R20j | zero-reference dataset actions retired; live import and MaterialPagination owners preserved | `9c7a3497b9...` / `34699599796` (31/31) |\n| R20k | live v18 import completion broad reload → labels + current paged materials only | `{ACCEPTED[:10]}...` / `{RUN}` (32/32) |", "OWNER row")
anchor = "R20j product: `e6398f7d8ae665079c82d64217c434af4a73073c`; focused run `34699354229`; validation `693a2fa2c3d39378782ac2270a95924eff5ca5ec` / run `34699442423`; cleanup `9c7a3497b9acf69364d83e5cf778ec4139bdbc69` / run `34699599796`; frontend PASS; Real Chrome **31/31 passed**. Five globally zero-reference dataset actions were physically retired. `doImportData` is explicitly preserved as live and becomes R20k because its successful v18 import path still invokes broad `reload()`.  "
replacement = anchor + f"\n\nR20k product: `{PRODUCT}`; focused run `34700022284` (211/211 frontend unit, focused Chrome 2/2); validation `{VALIDATION}` / run `{VALIDATION_RUN}`; cleanup `{ACCEPTED}` / run `{RUN}`; frontend PASS; Real Chrome **32/32 passed**. `doImportData` remains the live v18 XHR owner, but its successful completion now refreshes only labels and the current paged material domain. One-shot R20k migration artifacts are physically deleted.  "
text = replace_once(text, anchor, replacement, "OWNER narrative")
write(path, text)

# frontend-legacy-audit.md
path = "docs/frontend-legacy-audit.md"
text = read(path)
text = replace_once(text, "commit:       9c7a3497b9acf69364d83e5cf778ec4139bdbc69\nrun:          34699599796\nfrontend:     PASS\nReal Chrome:  PASS (31/31)", f"commit:       {ACCEPTED}\nrun:          {RUN}\nfrontend:     PASS\nReal Chrome:  PASS (32/32)", "AUDIT accepted")
text = replace_once(text, "app.js                    42.25.86", f"app.js                    {CACHE}", "AUDIT cache")
needle = "`renderAutoLabel424()` itself remains referenced by historical action functions and is not yet retired as a function."
addition = f"""`renderAutoLabel424()` itself remains referenced by historical action functions and is not yet retired as a function.

R20k did **not** retire the live `doImportData` owner. It migrated only its successful completion refresh from broad `reload()` to labels + current paged materials. Acceptance: product `{PRODUCT}`, validation `{VALIDATION}` / run `{VALIDATION_RUN}`, cleanup `{ACCEPTED}` / run `{RUN}`, Real Chrome **32/32**. Permanent contracts: `tests/frontend/v18-import-completion-scope.test.mjs` and `tests/browser/material-pagination-performance.spec.mjs`."""
text = replace_once(text, needle, addition, "AUDIT R20k")
write(path, text)

if Path("VERSION.txt").read_text(encoding="utf-8").strip() != "42.24.0":
    raise SystemExit("formal VERSION.txt changed unexpectedly")
print("R20k handoff synchronized across five authority documents")
