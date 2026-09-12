from pathlib import Path
import re

PRODUCT = 'd58e690ffcc1523f213a65cfc0a57380ffdc571e'
FOCUSED_RUN = '34696508446'
VALIDATION = '210a9ad1f6271a8a8986db3f223f4813a6cce288'
VALIDATION_RUN = '34696729028'
APP_CACHE = '42.25.84'
MAIN_CACHE = '42.25.88'


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

# AGENTS.md
p = 'AGENTS.md'
t = read(p)
t = regex_once(t, r'latest full code acceptance:\s+[0-9a-f]{40}', f'latest full code acceptance: {VALIDATION}', 'AGENTS acceptance')
t = regex_once(t, r'Frontend Runtime run:\s+\d+', f'Frontend Runtime run:        {VALIDATION_RUN}', 'AGENTS run')
t = regex_once(t, r'app\.js cache:\s+\S+', f'app.js cache:                {APP_CACHE}', 'AGENTS app cache')
t = regex_once(t, r'main\.mjs cache:\s+\S+', f'main.mjs cache:              {MAIN_CACHE}', 'AGENTS main cache')
t = regex_once(t, r'`\d+` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome \d+/\d+。', f'`{VALIDATION_RUN}` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 31/31。', 'AGENTS acceptance sentence')
next_scope = f'''## 下一批准确范围：R20 final zero-point\n\nR20g、R20h 已 CLOSED。R20h 已退休旧算法 CRUD 与 shadowed algorithm renderer generations；创建/编辑/删除现在由 414/423/429 稳定 owner 直接 patch authoritative `state.algorithms`，不得恢复 broad `reload()/loadAll()/loadRelated()`。\n\n下一批继续审计剩余 global reload/request debt，优先从数据集 mutation 家族开始，但必须先证明 current renderer/action liveness：\n\n```text\nsaveDataset / saveEditDataset / delDataset\nuploadImages / doImportData / autoSplit / setImageSplit\nstopJob / deleteJob\nsaveAssign\nremaining loadAll().then(render) manual refresh handlers\n```\n\n规则：先建立 assignment/reference/liveness/semantic 表；确认 live mutation 后，先补永久浏览器请求合同，再改成 authoritative result + local state patch / scoped refresh。被 later owner 完全 shadowed 的 generation 才允许整组物理删除。不得回头重构已经 CLOSED 的 `setPage` / NavigationStability。\n\nR20h 验收：\n\n```text\nproduct:          {PRODUCT}\nfocused run:      {FOCUSED_RUN} (frontend unit + focused Real Chrome PASS)\nvalidation:       {VALIDATION}\nvalidation run:   {VALIDATION_RUN}\nfrontend:         PASS\nReal Chrome:      31/31 PASS\napp.js cache:     {APP_CACHE}\nmain.mjs cache:   {MAIN_CACHE}\n```\n\n一次性 R20h migration helper/workflow 已物理删除；永久 guard 位于 `tests/frontend/legacy-algorithm-crud-owner.test.mjs`，CRUD Real Chrome 合同已并入永久执行的 `tests/browser/algorithm-list-performance.spec.mjs`。\n\n'''
t = regex_once(t, r'## 下一批准确范围：R20 final zero-point\n.*?(?=## 不得回退的核心合同)', next_scope, 'AGENTS next scope', flags=re.S)
write(p, t)

# CODEX_CURRENT_STATE.md
p = 'docs/CODEX_CURRENT_STATE.md'
t = read(p)
t = regex_once(t, r'latest full code acceptance:\s+[0-9a-f]{40}', f'latest full code acceptance: {VALIDATION}', 'CODEX acceptance')
t = regex_once(t, r'Frontend Runtime run:\s+\d+', f'Frontend Runtime run:        {VALIDATION_RUN}', 'CODEX run')
t = regex_once(t, r'app\.js cache:\s+\S+', f'app.js cache:                {APP_CACHE}', 'CODEX app cache')
t = regex_once(t, r'main\.mjs cache:\s+\S+', f'main.mjs cache:              {MAIN_CACHE}', 'CODEX main cache')
t = regex_once(t, r'Run `\d+` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions\. Browser navigation runs \*\*\d+ tests and passed \d+/\d+\*\*\.', f'Run `{VALIDATION_RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **31 tests and passed 31/31**.', 'CODEX acceptance sentence')
t = replace_once(t, '''```text\napp.js/global reload/request debt\n→ proven dead app.js/runtime shell cleanup\n→ cache-busting unification\n→ zero-point lifecycle scan\n→ semantic naming/dead-code cleanup\n→ A800 RC\n```''', '''```text\napp.js/global reload/request debt\n→ remaining dataset/job/publish mutation liveness audit + scoped refresh\n→ proven dead app.js/runtime shell cleanup\n→ stale async action fencing / lifecycle zero-point\n→ cache-busting unification\n→ semantic naming/dead-code cleanup\n→ unified task progress + durable queue productionization\n→ A800 RC\n```''', 'CODEX priority')
r20h = f'''### R20h — legacy algorithm CRUD / shadowed renderer retirement\n\nThe original algorithm CRUD generation (`newAlgorithm/saveAlgorithm/editAlgorithm/saveEditAlgorithm/viewAlgorithm`), v30 `oldRenderAlgorithms`, v39 `oldViewAlgoV39`, and the shadowed v42.2 algorithm page generation were physically retired after proving that the final algorithm route is owned by `renderAlgorithms423` and stable 414/423/429 actions. The bounded base `renderAlgorithms()` symbol remains only as a compatibility delegate to `renderAlgorithms423` until older global render maps are retired. The later report compatibility owner is intentionally preserved because `viewAlgorithm423/versionRows423` still uses it.\n\nStable mutations now remain:\n\n```text\nalgorithm.create → openNewAlgorithm423 → saveNewAlgorithm414 → local state.algorithms prepend\neditAlgorithm423 → saveEditAlgorithm414 → local state.algorithms replace\ndelAlgorithm → DELETE → local state.algorithms filter\n```\n\nAll three paths are permanently guarded against `reload()/loadAll()/loadRelated()` fan-out. The permanent Real Chrome contract creates, edits and deletes through the UI and forbids broad project/dataset/image/job/label/algorithm/bootstrap refreshes while allowing unrelated runtime polling.\n\n```text\nproduct:          {PRODUCT}\nfocused run:      {FOCUSED_RUN}\nvalidation:       {VALIDATION}\nvalidation run:   {VALIDATION_RUN}\nfrontend:         PASS\nReal Chrome:      31/31 PASS\napp.js cache:     {APP_CACHE}\nmain.mjs cache:   {MAIN_CACHE}\n```\n\nOne-shot R20h migration artifacts are physically deleted. Current exact next scope remains **R20 final global reload/request zero-point**, starting with a liveness audit of dataset mutation owners.\n\n'''
t = replace_once(t, 'Read in order:\n', r20h + 'Read in order:\n', 'CODEX R20h insertion')
write(p, t)

# TECH_DEBT_CLOSURE_V42_25.md
p = 'docs/TECH_DEBT_CLOSURE_V42_25.md'
t = read(p)
t = regex_once(t, r'\*\*最近完整代码验收点：`[0-9a-f]{40}`\*\*', f'**最近完整代码验收点：`{VALIDATION}`**', 'TECH acceptance')
t = regex_once(t, r'\*\*Frontend Runtime Stabilization：run `\d+`，frontend \+ Real Chrome 全绿，Real Chrome \d+/\d+ passed。\*\*', f'**Frontend Runtime Stabilization：run `{VALIDATION_RUN}`，frontend + Real Chrome 全绿，Real Chrome 31/31 passed。**', 'TECH run')
retired_anchor = '#modalBody normalization MutationObserver\n'
t = replace_once(t, retired_anchor, retired_anchor + '''base algorithm CRUD `window.newAlgorithm/saveAlgorithm/editAlgorithm/saveEditAlgorithm/viewAlgorithm`\nv30 `oldRenderAlgorithms` algorithm renderer wrapper\nv39 `oldViewAlgoV39` algorithm detail wrapper\nv42.2 `renderAlgorithms422/openNewAlgorithm422/saveNewAlgorithm422` shadowed algorithm page generation\n''', 'TECH retired surfaces')
row = '| ZIP / server-storage import completion broad refresh | scoped labels + paged material refresh | **CLOSED (R20g)** |'
t = replace_once(t, row, row + '\n| legacy algorithm CRUD + shadowed algorithm renderer generations | stable 414/423/429 owners + authoritative local `state.algorithms` patch | **CLOSED (R20h)** |', 'TECH R20h row')
r20h_tech = f'''## 2.2 R20h — legacy algorithm CRUD / shadowed renderer retirement\n\nR20h 证明并物理退休最早算法 CRUD owner、v30 算法 renderer wrapper、v39 `viewAlgorithm` wrapper 与 v42.2 已被最终路由遮蔽的算法页面 generation。最终算法列表仍由 `renderAlgorithms423` 负责；创建/编辑/删除由 414/423 稳定 action 直接使用服务端 authoritative result 更新 `state.algorithms`，不再触发 broad reload。\n\n保留边界：\n\n```text\nfunction renderAlgorithms() → 仅作为 bounded compatibility delegate 到 renderAlgorithms423\n后代 window.showReport owner → 仍被 viewAlgorithm423/versionRows423 使用，未误删\n```\n\n永久合同：\n\n```text\ntests/frontend/legacy-algorithm-crud-owner.test.mjs\ntests/browser/algorithm-list-performance.spec.mjs\n```\n\n```text\nproduct:        {PRODUCT}\nfocused run:    {FOCUSED_RUN}\nvalidation:     {VALIDATION}\nvalidation run: {VALIDATION_RUN}\nfrontend:       PASS\nReal Chrome:    31/31 PASS\napp.js cache:   {APP_CACHE}\nmain.mjs cache: {MAIN_CACHE}\n```\n\n一次性 migration helper/workflow 已物理删除。R20 尚未整体 CLOSED；下一批继续对 dataset/job/publish 等 mutation 做 liveness + request zero-point。\n\n'''
t = replace_once(t, '## 3. Canonical owners', r20h_tech + '## 3. Canonical owners', 'TECH R20h section')
write(p, t)

# FRONTEND_OWNER_MAP_V42_25.md
p = 'docs/FRONTEND_OWNER_MAP_V42_25.md'
t = read(p)
t = regex_once(t, r'Latest fully accepted code point: `[0-9a-f]{40}` / run `\d+`', f'Latest fully accepted code point: `{VALIDATION}` / run `{VALIDATION_RUN}`', 'owner map acceptance')
t = regex_once(t, r'Real Chrome: \d+/\d+ passed', 'Real Chrome: 31/31 passed', 'owner map Chrome')
row = '| R20g close | one-shot migration helper/workflow physical deletion | `6337f1a0...` / `34695825386` (30/30) |'
t = replace_once(t, row, row + f'\n| R20h | legacy algorithm CRUD + v30/v39/v42.2 shadowed algorithm generations retired; stable 414/423/429 local-state owners remain | `{VALIDATION[:8]}...` / `{VALIDATION_RUN}` (31/31) |', 'owner map R20h row')
evidence = f'''\nR20h product: `{PRODUCT}`; focused run `{FOCUSED_RUN}`; validation `{VALIDATION}` / run `{VALIDATION_RUN}`; frontend PASS; Real Chrome **31/31 passed**. The bounded base `renderAlgorithms()` compatibility delegate remains until older global render maps are retired, and the later report compatibility owner remains live by contract. R20h one-shot migration artifacts were deleted.  \n'''
t = replace_once(t, '\nR10 product:', evidence + '\nR10 product:', 'owner map R20h evidence')
write(p, t)

# frontend-legacy-audit.md
p = 'docs/frontend-legacy-audit.md'
t = read(p)
t = regex_once(t, r'commit:\s+[0-9a-f]{40}', f'commit:       {VALIDATION}', 'audit acceptance')
t = regex_once(t, r'run:\s+\d+', f'run:          {VALIDATION_RUN}', 'audit run')
t = regex_once(t, r'Real Chrome:\s+PASS \(\d+/\d+\)', 'Real Chrome:  PASS (31/31)', 'audit Chrome')
t = regex_once(t, r'app\.js\s+42\.25\.\d+', f'app.js                    {APP_CACHE}', 'audit app cache')
t = regex_once(t, r'main\.mjs\s+42\.25\.\d+', f'main.mjs                  {MAIN_CACHE}', 'audit main cache')
retired = '#modalBody normalization MutationObserver\n'
t = replace_once(t, retired, retired + '''base algorithm CRUD new/save/edit/saveEdit/view globals\nv30 oldRenderAlgorithms wrapper\nv39 oldViewAlgoV39 wrapper\nv42.2 renderAlgorithms422/openNewAlgorithm422/saveNewAlgorithm422 generation\n''', 'audit retired surfaces')
r20h_audit = f'''### R20h — algorithm CRUD / shadowed generation retirement\n\nR20h removed the broad-reload algorithm CRUD generation and three later shadowed algorithm compatibility layers after proving final routing ownership. Current create/edit/delete mutations use stable 414/423 owners and patch authoritative `state.algorithms` locally.\n\n```text\nproduct:        {PRODUCT}\nfocused run:    {FOCUSED_RUN}\nvalidation:     {VALIDATION}\nvalidation run: {VALIDATION_RUN}\nfrontend:       PASS\nReal Chrome:    31/31 PASS\n```\n\nPermanent proof:\n\n```text\ntests/frontend/legacy-algorithm-crud-owner.test.mjs\ntests/browser/algorithm-list-performance.spec.mjs\n```\n\nIntentional survivors are explicit: base `renderAlgorithms()` is now only a bounded delegate to `renderAlgorithms423` because older global render maps still evaluate the symbol; the later `window.showReport` compatibility owner remains live because `viewAlgorithm423/versionRows423` still references it. One-shot R20h migration artifacts are physically deleted.\n\n'''
t = replace_once(t, '## 7. Current live render topology', r20h_audit + '## 7. Current live render topology', 'audit R20h section')
write(p, t)

# Final cross-document guard.
for path in [
    'AGENTS.md',
    'docs/TECH_DEBT_CLOSURE_V42_25.md',
    'docs/CODEX_CURRENT_STATE.md',
    'docs/FRONTEND_OWNER_MAP_V42_25.md',
    'docs/frontend-legacy-audit.md',
]:
    text = read(path)
    if VALIDATION not in text or VALIDATION_RUN not in text:
        raise SystemExit(f'{path}: R20h accepted point missing after sync')

if Path('VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt changed unexpectedly')
if not Path('tests/frontend/legacy-algorithm-crud-owner.test.mjs').exists():
    raise SystemExit('R20h permanent frontend guard missing')
if 'algorithm create edit delete uses authoritative local state without broad refresh' not in Path('tests/browser/algorithm-list-performance.spec.mjs').read_text(encoding='utf-8'):
    raise SystemExit('R20h permanent browser contract missing')
if Path('tools/migrate_r20h_legacy_algorithm_crud.py').exists():
    raise SystemExit('R20h migration helper still exists')
if Path('.github/workflows/migrate-r20h-legacy-algorithm-crud.yml').exists():
    raise SystemExit('R20h migration workflow still exists')

print('R20h handoff synchronized across five authority surfaces')
