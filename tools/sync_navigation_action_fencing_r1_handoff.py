from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPTED = '7fcfcaec0b088a851dbcd580ac226b3dd892fa83'
FRONTEND_RUN = '34702374386'
ACTION_RUN = '34702374346'
PRODUCT = '8269eb0cca84ea310f48ee13af34ab09dd1bfeff'
FOLLOWUP = '01234ef186f3e57bef2d29ac19420952beef6c36'
BASELINE_RUN = '34701875185'


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected one anchor, got {count}')
    return text.replace(old, new, 1)


def replace_section(text: str, start: str, end: str, replacement: str, label: str) -> str:
    a = text.find(start)
    b = text.find(end, a + len(start)) if a >= 0 else -1
    if a < 0 or b < 0:
        raise SystemExit(f'{label}: section anchors missing')
    return text[:a] + replacement.rstrip() + '\n\n' + text[b:]


r1 = f"""### Navigation Action Fencing R1 — resource/Paddle mutation completion CLOSED

真实旧代码 baseline 已在 Real Chrome 证明：训练资源页慢 `POST /api/train_servers` 发出后，用户切到数据集并打开属于新页面的 modal；旧 POST 完成会执行 `closeModal()`，把新页面 modal 关闭并清掉 sentinel。该行为不是测试推断，而是浏览器复现。

```text
baseline / focused migration run: {BASELINE_RUN}
old Chrome failure: stale save completion closed or rewrote the new-page modal
product:            {PRODUCT}
follow-up:          {FOLLOWUP}
cleanup:            {ACCEPTED}
Frontend Runtime:   {FRONTEND_RUN}
full Real Chrome:   32/32 PASS
permanent Action Fencing run: {ACTION_RUN} PASS
formal VERSION.txt: 42.24.0 unchanged
app.js cache:       42.25.88
main.mjs cache:     42.25.89
NavigationStability: 422512
```

R1 新增 `NavigationStability.action(ownerPage)`，通过 navigation epoch/token 暴露 `isCurrent()` / `commit()`；后台 mutation 可以完成，但 stale completion 不得再提交 modal、DOM、state 或 render side effect。`saveServer` 在 POST 后和 scoped `training_options` refresh 后都执行 stale fence。Paddle 手动/一键激活同样有 action fence；若用户仍在训练资源页，只做当前页 render + toast，不再冗余导航回自己。

R1 还将目标范围内的 direct page write 清零：训练资源、模型配置、部署转换、训练任务以及旧“新建算法/自动迭代 → 算法列表”renderer rewrite 不再通过 `state.page='xxx'; render()` 导航；需要跳页时统一走 `NavigationStability`/`window.setPage`。

永久合同：

```text
tests/frontend/navigation-action-fencing.test.mjs
tests/frontend/training-server-refresh-owner.test.mjs
tests/browser/navigation-action-fencing.spec.mjs
.github/workflows/navigation-action-fencing.yml
```

一次性 R1 migration/follow-up helper 与 workflow 已物理删除。

**边界：整个 Navigation Action Fencing 仍为 IN PROGRESS。** R1 只关闭训练服务器/Paddle 与本批 direct-page-write surface；最终 Model Config 427、AI 标注/清洗确认、图片/ZIP/XHR upload completion、deployment mutation、其他 timer/callback family 尚未全部迁移，不能宣称 stale async UI side effect 全局为 0。下一批为 **R2：最终 Model Config / AI 清洗与 modal mutation completion**。"""

# AGENTS.md
p = ROOT / 'AGENTS.md'
t = p.read_text(encoding='utf-8')
t = replace_once(t, 'latest full code acceptance: c6ac70b670a6297ccba065854779c10b8ca47cf3', f'latest full code acceptance: {ACCEPTED}', 'AGENTS acceptance')
t = replace_once(t, 'Frontend Runtime run:        34700984963', f'Frontend Runtime run:        {FRONTEND_RUN}', 'AGENTS run')
t = replace_once(t, 'app.js cache:                42.25.87', 'app.js cache:                42.25.88', 'AGENTS app cache')
t = replace_once(t, 'main.mjs cache:              42.25.88', 'main.mjs cache:              42.25.89', 'AGENTS main cache')
t = replace_once(t, 'NavigationStability:         422511', 'NavigationStability:         422512', 'AGENTS nav build')
t = replace_once(t, '`34700984963` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 32/32。Resource Discovery SQLite 永久 workflow `34700900542` 已在 Ubuntu + Windows 双平台通过。', f'`{FRONTEND_RUN}` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 32/32。Navigation Action Fencing 永久 workflow `{ACTION_RUN}` 全绿；Resource Discovery SQLite 永久 workflow `34700900542` 继续保持 Ubuntu + Windows 双平台通过。', 'AGENTS acceptance paragraph')
new_agents = f"""## 下一批准确范围：Navigation Action Fencing R2

{r1}

Resource Discovery SQLite 仍保持 **CODE-LEVEL CLOSED / production soak OPEN**；30–60 分钟生产 soak 和非 SQLite resource classes 不因本批改变状态。"""
t = replace_section(t, '## 下一批准确范围：Navigation Action Fencing', '## 不得回退的核心合同', new_agents, 'AGENTS next section')
p.write_text(t, encoding='utf-8')

# CODEX_CURRENT_STATE.md
p = ROOT / 'docs' / 'CODEX_CURRENT_STATE.md'
t = p.read_text(encoding='utf-8')
t = replace_once(t, 'latest full code acceptance: c6ac70b670a6297ccba065854779c10b8ca47cf3', f'latest full code acceptance: {ACCEPTED}', 'CODEX acceptance')
t = replace_once(t, 'Frontend Runtime run:        34700984963', f'Frontend Runtime run:        {FRONTEND_RUN}', 'CODEX run')
t = replace_once(t, 'app.js cache:                42.25.87', 'app.js cache:                42.25.88', 'CODEX app cache')
t = replace_once(t, 'main.mjs cache:              42.25.88', 'main.mjs cache:              42.25.89', 'CODEX main cache')
t = replace_once(t, 'NavigationStability:         422511', 'NavigationStability:         422512', 'CODEX nav build')
old_para = 'Run `34700984963` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after Resource Discovery SQLite migration-artifact cleanup. Browser navigation runs **32 tests and passed 32/32**. Permanent Resource Discovery SQLite workflow `34700900542` passed on Ubuntu and Windows. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.'
new_para = f'Run `{FRONTEND_RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after Navigation Action Fencing R1 migration-artifact cleanup. Browser navigation runs **32 tests and passed 32/32**. Permanent Action Fencing workflow `{ACTION_RUN}` is green; permanent Resource Discovery SQLite workflow `34700900542` remains green on Ubuntu and Windows. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.'
t = replace_once(t, old_para, new_para, 'CODEX acceptance paragraph')
t = replace_once(t, 'Navigation Action Fencing / stale mutation UI side effects\n→ resume R20 final global reload/request zero-point', 'Navigation Action Fencing R2 — final Model Config / AI-cleaning modal mutations\n→ resume R20 final global reload/request zero-point', 'CODEX priority')
t = replace_once(t, '### R20g — import completion scoped refresh + mechanical close', r1 + '\n\n### R20g — import completion scoped refresh + mechanical close', 'CODEX R1 insert')
p.write_text(t, encoding='utf-8')

# TECH_DEBT_CLOSURE_V42_25.md
p = ROOT / 'docs' / 'TECH_DEBT_CLOSURE_V42_25.md'
t = p.read_text(encoding='utf-8')
t = replace_once(t, '**最近完整代码验收点：`c6ac70b670a6297ccba065854779c10b8ca47cf3`**', f'**最近完整代码验收点：`{ACCEPTED}`**', 'TECH acceptance')
t = replace_once(t, '**Frontend Runtime Stabilization：run `34700984963`，frontend + Real Chrome 全绿，Real Chrome 32/32 passed；Resource Discovery SQLite 永久跨平台 run `34700900542` Ubuntu + Windows 全绿。**', f'**Frontend Runtime Stabilization：run `{FRONTEND_RUN}`，frontend + Real Chrome 全绿，Real Chrome 32/32 passed；Navigation Action Fencing 永久 run `{ACTION_RUN}` 全绿；Resource Discovery SQLite 永久跨平台 run `34700900542` Ubuntu + Windows 全绿。**', 'TECH top run')
row_anchor = '| navigation alias/readiness/sidebar/apply/persistence | `NavigationStability` + `ui-state.js` | **CLOSED** |'
t = replace_once(t, row_anchor, row_anchor + '\n| Navigation Action Fencing R1 — training-server/Paddle + targeted direct page writes | `NavigationStability.action` + epoch/token fence | **CLOSED (R1); overall action fencing IN PROGRESS** |', 'TECH action row')
t = replace_once(t, '## 2.1 R20g — import completion scoped refresh', '## 2.0a Navigation Action Fencing R1\n\n' + r1 + '\n\n## 2.1 R20g — import completion scoped refresh', 'TECH R1 section')
p.write_text(t, encoding='utf-8')

# FRONTEND_OWNER_MAP_V42_25.md
p = ROOT / 'docs' / 'FRONTEND_OWNER_MAP_V42_25.md'
t = p.read_text(encoding='utf-8')
t = replace_once(t, 'Latest fully accepted code point: `c6ac70b670a6297ccba065854779c10b8ca47cf3` / run `34700984963`', f'Latest fully accepted code point: `{ACCEPTED}` / run `{FRONTEND_RUN}`', 'OWNER acceptance')
nav_anchor = '`static/app.js` contains zero classic `window.setPage=` assignments.'
t = replace_once(t, nav_anchor, nav_anchor + f"\n\nNavigation Action Fencing R1 is also accepted: `NavigationStability.action(ownerPage)` owns stale mutation commit checks for the migrated surface. `saveServer` no longer closes/redraws UI after leaving its owner page; targeted direct fixed-page business writes are zero. Product `{PRODUCT}`, follow-up `{FOLLOWUP}`, cleanup `{ACCEPTED}`; permanent run `{ACTION_RUN}` PASS; full Real Chrome `{FRONTEND_RUN}` **32/32**. Overall async-action zero-point remains IN PROGRESS; R2 targets final Model Config / AI-cleaning modal mutations.", 'OWNER action checkpoint')
p.write_text(t, encoding='utf-8')

# frontend-legacy-audit.md
p = ROOT / 'docs' / 'frontend-legacy-audit.md'
t = p.read_text(encoding='utf-8')
t = replace_once(t, 'commit:       c6ac70b670a6297ccba065854779c10b8ca47cf3', f'commit:       {ACCEPTED}', 'AUDIT acceptance')
t = replace_once(t, 'run:          34700984963', f'run:          {FRONTEND_RUN}', 'AUDIT run')
t = replace_once(t, 'app.js                    42.25.87', 'app.js                    42.25.88', 'AUDIT app cache')
t = replace_once(t, 'main.mjs                  42.25.88', 'main.mjs                  42.25.89', 'AUDIT main cache')
t = replace_once(t, 'navigation-stability      422511', 'navigation-stability      422512', 'AUDIT nav build')
nav_block = """NavigationStability.stableSetPage
  → normalizeNavigationPage
  → PageRequestScope / navigation epoch
  → PollRegistry.beforeNavigate
  → waitForNavigationReady
  → beforeInvokeNavigation
  → performNavigation(page)
  → PageRequestScope.alignPage
  → PollRegistry.afterNavigate
  → persistNavigationState
```"""
t = replace_once(t, nav_block, nav_block + f"\n\nR1 action fencing adds `NavigationStability.action(ownerPage) → token/isCurrent/commit` for mutation-completion ownership. Real Chrome proved the old `saveServer` could close a modal created after navigation; that stale side effect is now fenced. Product `{PRODUCT}`, follow-up `{FOLLOWUP}`, cleanup `{ACCEPTED}`, full run `{FRONTEND_RUN}` **32/32**, permanent Action Fencing run `{ACTION_RUN}` PASS. R1 is closed; global stale-async zero-point is not. R2 targets final Model Config / AI-cleaning modal mutation families.", 'AUDIT nav R1')
p.write_text(t, encoding='utf-8')

for rel in ('AGENTS.md','docs/CODEX_CURRENT_STATE.md','docs/TECH_DEBT_CLOSURE_V42_25.md','docs/FRONTEND_OWNER_MAP_V42_25.md','docs/frontend-legacy-audit.md'):
    data = (ROOT / rel).read_text(encoding='utf-8')
    for required in (ACCEPTED, FRONTEND_RUN, ACTION_RUN, '42.24.0'):
        if required not in data:
            raise SystemExit(f'{rel}: missing required handoff marker {required}')

print('Navigation Action Fencing R1 handoff synchronization applied')
