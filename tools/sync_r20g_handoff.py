from pathlib import Path
import re

ACCEPTED_COMMIT = '6337f1a0379c7e60fbbc459668090504c0b6095b'
ACCEPTED_RUN = '34695825386'
R20G_PRODUCT = 'a67778fd9b60384dbfffa2156e99670d244dadc9'
R20G_VALIDATION = 'a2f4cb40abb6d70ad4faf89bde60c1ee39e4a179'
R20G_RUN = '34693503185'


def read(path):
    return Path(path).read_text(encoding='utf-8')


def write(path, text):
    Path(path).write_text(text, encoding='utf-8')


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly one match, got {count}')
    return text.replace(old, new, 1)


def regex_once(text, pattern, repl, label, flags=0):
    updated, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly one regex match, got {count}')
    return updated

# AGENTS.md: first-entry status + exact next scope.
p = 'AGENTS.md'
t = read(p)
t = regex_once(t, r'latest full code acceptance:\s+[0-9a-f]{40}', f'latest full code acceptance: {ACCEPTED_COMMIT}', 'AGENTS acceptance')
t = regex_once(t, r'Frontend Runtime run:\s+\d+', f'Frontend Runtime run:        {ACCEPTED_RUN}', 'AGENTS run')
t = regex_once(t, r'frontend badge:\s+\S+', 'frontend badge:              v42.24.0', 'AGENTS visible version')
t = regex_once(t, r'app\.js cache:\s+\S+', 'app.js cache:                42.25.83', 'AGENTS app cache')
t = regex_once(t, r'main\.mjs cache:\s+\S+', 'main.mjs cache:              42.25.88', 'AGENTS main cache')
t = regex_once(t, r'`\d+` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions。', f'`{ACCEPTED_RUN}` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 30/30。', 'AGENTS acceptance sentence')
new_scope = '''## 下一批准确范围：R20 final zero-point\n\nR20g 已 CLOSED。现在继续处理 `static/app.js` 中剩余的 global reload/request debt 与 proven-dead runtime shell；不回头重构已经 CLOSED 的 `setPage` / NavigationStability。\n\n重点枚举：\n\n```text\nreload() / loadAll() / loadRelated() mutation callers\nolder base/global render generations reached through delegates\nproven-dead algorithm/data compatibility CRUD + renderer shells\nrefresh handlers that still broaden request scope\nstale async completion side effects\n```\n\n规则：先建立 assignment/reference/liveness/semantic 表，再识别 dead generation；真实语义先补永久合同，再迁 owner / 局部 state patch / scoped refresh，最后物理删除。不得按版本号一把删。\n\nR20g 验收：\n\n```text\nproduct:            a67778fd9b60384dbfffa2156e99670d244dadc9\nvalidation:         a2f4cb40abb6d70ad4faf89bde60c1ee39e4a179\nvalidation run:     34693503185 (frontend + Real Chrome 30/30 PASS)\nartifact cleanup:   6337f1a0379c7e60fbbc459668090504c0b6095b\ncleanup run:        34695825386 (frontend + Real Chrome 30/30 PASS)\n```\n\n'''
t = regex_once(t, r'## 下一批准确范围：render owner audit\n.*?(?=## 不得回退的核心合同)', new_scope, 'AGENTS next scope', flags=re.S)
t = replace_once(t, '''```text\n1. render override owner audit / obsolete generation deletion\n2. proven dead app.js + global reload/request debt\n3. cache-busting unification\n4. MutationObserver/timer/fetch/render/setPage zero-point scan\n5. semantic naming + deterministic tests + docs\n6. technical-debt zero-point scan\n7. resume A800 RC\n```''', '''```text\n1. R20 final global reload/request zero-point\n2. proven-dead app.js/runtime shell cleanup\n3. stale async action fencing / lifecycle zero-point\n4. cache-busting unification\n5. semantic naming + deterministic tests + docs\n6. technical-debt zero-point scan\n7. unified task progress + durable queue productionization\n8. resume A800 RC only after the above acceptance gates\n```''', 'AGENTS priorities')
t = t.replace('每批完成后同步四份当前 handoff 文档。', '每批完成后同步 AGENTS.md + 四份 docs 当前 handoff 文档。')
write(p, t)

# CODEX_CURRENT_STATE.md: current state must be immediately trustworthy.
p = 'docs/CODEX_CURRENT_STATE.md'
t = read(p)
t = regex_once(t, r'latest full code acceptance:\s+[0-9a-f]{40}', f'latest full code acceptance: {ACCEPTED_COMMIT}', 'CODEX acceptance')
t = regex_once(t, r'Frontend Runtime run:\s+\d+', f'Frontend Runtime run:        {ACCEPTED_RUN}', 'CODEX run')
t = regex_once(t, r'app\.js cache:\s+\S+', 'app.js cache:                42.25.83', 'CODEX app cache')
t = regex_once(t, r'main\.mjs cache:\s+\S+', 'main.mjs cache:              42.25.88', 'CODEX main cache')
t = regex_once(t, r'Run `\d+` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions\. Browser navigation runs \*\*\d+ tests and passed \d+/\d+\*\*\.', f'Run `{ACCEPTED_RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **30 tests and passed 30/30**.', 'CODEX acceptance sentence')
r20g = f'''### R20g — import completion scoped refresh + mechanical close\n\nThe final ZIP-import completion owner and server-storage import confirmation no longer broaden into `loadRelated()` / `loadAll()`. They refresh only labels when required and the paged material domain when the user is actually on 数据集. The one-shot migration helper/workflow were physically deleted after full acceptance.\n\n```text\nproduct:            {R20G_PRODUCT}\nvalidation:         {R20G_VALIDATION}\nvalidation run:     {R20G_RUN}\nvalidation Chrome:  30/30 PASS\nartifact cleanup:   {ACCEPTED_COMMIT}\ncleanup run:        {ACCEPTED_RUN}\ncleanup Chrome:     30/30 PASS\napp.js cache:       42.25.83\nmain.mjs cache:     42.25.88\n```\n\nCurrent exact next scope is **R20 final global reload/request zero-point** plus proven-dead `app.js` runtime-shell deletion. Do not reopen classic `setPage` ownership.\n\n'''
t = replace_once(t, 'A800 RC remains deferred.\n\nRead in order:', 'A800 RC remains deferred.\n\n' + r20g + 'Read in order:', 'CODEX R20g insertion')
write(p, t)

# TECH_DEBT ledger: top authority + explicit R20g closure.
p = 'docs/TECH_DEBT_CLOSURE_V42_25.md'
t = read(p)
t = regex_once(t, r'\*\*最近完整代码验收点：`[0-9a-f]{40}`\*\*', f'**最近完整代码验收点：`{ACCEPTED_COMMIT}`**', 'TECH acceptance')
t = regex_once(t, r'\*\*Frontend Runtime Stabilization：run `\d+`，frontend \+ Real Chrome 全绿，Real Chrome \d+/\d+ passed。\*\*', f'**Frontend Runtime Stabilization：run `{ACCEPTED_RUN}`，frontend + Real Chrome 全绿，Real Chrome 30/30 passed。**', 'TECH run')
row_anchor = '| global reload / duplicate request | scoped refresh / zero-point proof | **IN PROGRESS (R20)** |'
if row_anchor not in t:
    raise SystemExit('TECH global reload row anchor missing')
t = t.replace(row_anchor, '| ZIP / server-storage import completion broad refresh | scoped labels + paged material refresh | **CLOSED (R20g)** |\n' + row_anchor, 1)
r20g_tech = f'''## 2.1 R20g — import completion scoped refresh\n\nR20g 将最终 ZIP 导入完成与 server-storage 导入确认从 broad `loadRelated()/loadAll()` 收窄到真实受影响域：需要时刷新标签；只有当前处于数据集页面时刷新分页素材。永久测试锁定最终 owner 不再调用 broad refresh。一次性 migration helper/workflow 在验收后已物理删除。\n\n```text\nproduct:          {R20G_PRODUCT}\nvalidation:       {R20G_VALIDATION}\nvalidation run:   {R20G_RUN}\nReal Chrome:      30/30 PASS\ncleanup:          {ACCEPTED_COMMIT}\ncleanup run:      {ACCEPTED_RUN}\ncleanup Chrome:   30/30 PASS\n```\n\nR20 仍未整体 CLOSED；下一批继续做 global reload/request zero-point 与 proven-dead runtime shell 清理。\n\n'''
t = replace_once(t, '## 3. Canonical owners', r20g_tech + '## 3. Canonical owners', 'TECH R20g section')
write(p, t)

# FRONTEND_OWNER_MAP: current point + R20g row.
p = 'docs/FRONTEND_OWNER_MAP_V42_25.md'
t = read(p)
t = regex_once(t, r'Latest fully accepted code point: `[0-9a-f]{40}` / run `\d+`', f'Latest fully accepted code point: `{ACCEPTED_COMMIT}` / run `{ACCEPTED_RUN}`', 'owner map acceptance')
t = regex_once(t, r'Real Chrome: \d+/\d+ passed', 'Real Chrome: 30/30 passed', 'owner map chrome')
r20f_row = '| R20f | final M4 model-config save/edit broad `loadRelated` → authoritative saved item + local `modelConfigs` upsert | `94dbebb4...` / `34690924552` |'
if r20f_row not in t:
    raise SystemExit('owner map R20f row anchor missing')
t = t.replace(r20f_row, r20f_row + '\n| R20g | ZIP + server-storage import completion broad refresh → scoped labels/material refresh | `a2f4cb40...` / `34693503185` (30/30) |\n| R20g close | one-shot migration helper/workflow physical deletion | `6337f1a0...` / `34695825386` (30/30) |', 1)
write(p, t)

# frontend-legacy-audit: top facts + accepted R20g evidence.
p = 'docs/frontend-legacy-audit.md'
t = read(p)
t = regex_once(t, r'commit:\s+[0-9a-f]{40}', f'commit:       {ACCEPTED_COMMIT}', 'audit acceptance')
t = regex_once(t, r'run:\s+\d+', f'run:          {ACCEPTED_RUN}', 'audit run')
t = regex_once(t, r'Real Chrome:\s+PASS \(\d+/\d+\)', 'Real Chrome:  PASS (30/30)', 'audit chrome')
t = regex_once(t, r'app\.js\s+42\.25\.82', 'app.js                    42.25.83', 'audit app cache')
t = regex_once(t, r'main\.mjs\s+42\.25\.87', 'main.mjs                  42.25.88', 'audit main cache')
r20g_audit = f'''### R20g — scoped import completion ownership\n\nThe final live ZIP completion path and server-storage confirmation path now avoid broad `loadRelated()` / `loadAll()` fan-out. Permanent owner tests require label refresh only when needed and paged material refresh only for the active 数据集 page. One-shot migration artifacts were physically removed after acceptance.\n\n```text\nproduct:          {R20G_PRODUCT}\nvalidation:       {R20G_VALIDATION}\nvalidation run:   {R20G_RUN}\nReal Chrome:      30/30 PASS\nartifact cleanup: {ACCEPTED_COMMIT}\ncleanup run:      {ACCEPTED_RUN}\ncleanup Chrome:   30/30 PASS\n```\n\n'''
t = replace_once(t, '## 7. Current live render topology', r20g_audit + '## 7. Current live render topology', 'audit R20g section')
write(p, t)

# Strong cross-document guard: all first-entry surfaces must agree.
for path in [
    'AGENTS.md',
    'docs/CODEX_CURRENT_STATE.md',
    'docs/TECH_DEBT_CLOSURE_V42_25.md',
    'docs/FRONTEND_OWNER_MAP_V42_25.md',
    'docs/frontend-legacy-audit.md',
]:
    text = read(path)
    if ACCEPTED_COMMIT not in text or ACCEPTED_RUN not in text:
        raise SystemExit(f'{path}: latest accepted point missing after sync')

if Path('VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt changed unexpectedly')

print('R20g handoff synchronized across five authority surfaces')
