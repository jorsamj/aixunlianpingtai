from pathlib import Path

PRODUCT = 'e6398f7d8ae665079c82d64217c434af4a73073c'
FOCUSED_RUN = '34699354229'
VALIDATION = '693a2fa2c3d39378782ac2270a95924eff5ca5ec'
VALIDATION_RUN = '34699442423'
CLEANUP = '9c7a3497b9acf69364d83e5cf778ec4139bdbc69'
CLEANUP_RUN = '34699599796'


def read(path):
    return Path(path).read_text(encoding='utf-8')


def write(path, text):
    Path(path).write_text(text, encoding='utf-8')


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected anchor once, got {count}')
    return text.replace(old, new, 1)


def insert_before(text, marker, block, label):
    if block.strip() in text:
        raise SystemExit(f'{label}: block already present')
    count = text.count(marker)
    if count != 1:
        raise SystemExit(f'{label}: marker expected once, got {count}')
    return text.replace(marker, block + marker, 1)

if read('VERSION.txt').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt changed unexpectedly')
if 'app.js?v=42.25.86' not in read('static/index.html'):
    raise SystemExit('R20j app.js cache acceptance missing')
for artifact in ('tools/migrate_r20j_dead_dataset_actions.py', '.github/workflows/migrate-r20j-dead-dataset-actions.yml'):
    if Path(artifact).exists():
        raise SystemExit(f'R20j one-shot artifact still present: {artifact}')

# AGENTS.md
path = 'AGENTS.md'
t = read(path)
t = replace_once(t, 'latest full code acceptance: a7116811adb26ebe5f0f9e621bf23df1dd1f605f', f'latest full code acceptance: {CLEANUP}', 'AGENTS acceptance')
t = replace_once(t, 'Frontend Runtime run:        34698983278', f'Frontend Runtime run:        {CLEANUP_RUN}', 'AGENTS run')
t = replace_once(t, 'app.js cache:                42.25.85', 'app.js cache:                42.25.86', 'AGENTS cache')
t = replace_once(t, '`34698983278` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 31/31。', f'`{CLEANUP_RUN}` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 31/31。', 'AGENTS acceptance prose')
start = t.index('## 下一批准确范围：R20 final zero-point')
end = t.index('## 不得回退的核心合同', start)
new_scope = f'''## 下一批准确范围：R20 final zero-point\n\nR20g、R20h、R20i、R20j 已 CLOSED。R20j 通过全局引用证明物理退休了 5 个 zero-reference dataset action owner：`uploadImages / autoSplit / buildYolo / checkDatasetQuality / setImageSplit`。最终 `renderDatasets424 + MaterialPaginationRuntime61` 与 live import owner 均未误删。\n\n下一批准确目标是 **R20k：live v18 `doImportData` completion scoped refresh**。它是当前最终 v36 import UI 仍会调用的真实 owner，成功路径现在仍执行 `await reload()`，不得按 dead shell 删除。\n\n```text\nfinal renderDatasets424\n→ importData()（最终 v36 modal owner）\n→ doImportData()（唯一 live v18 XHR owner）\n→ POST /api/v18/projects/{{project}}/datasets/{{dataset}}/import\n→ 当前：await reload()   ← R20k 目标\n\n目标语义：\n→ 导入成功结果/进度 UI 保持不变\n→ refreshLabels414(false)\n→ 仅当 state.page === '数据集' 时 reloadMaterialPage61()\n→ 禁止 loadAll/loadRelated/reload bootstrap fan-out\n```\n\nR20k 必须先加 permanent unit/request contract，并把 Real Chrome 导入成功测试并入现有 `material-pagination-performance.spec.mjs`，避免修改永久 workflow。之后再处理 live `stopJob/deleteJob` broad reload。\n\nR20j 验收：\n\n```text\nproduct:            {PRODUCT}\nfocused run:        {FOCUSED_RUN}\nvalidation:         {VALIDATION}\nvalidation run:     {VALIDATION_RUN}\nvalidation Chrome:  31/31 PASS\ncleanup:            {CLEANUP}\ncleanup run:        {CLEANUP_RUN}\ncleanup Chrome:     31/31 PASS\napp.js cache:       42.25.86\nmain.mjs cache:     42.25.88\n```\n\n永久 guard：`tests/frontend/legacy-dataset-action-shell.test.mjs`。一次性 R20j migration helper/workflow 已物理删除。\n\n'''
t = t[:start] + new_scope + t[end:]
write(path, t)

# CODEX_CURRENT_STATE.md
path = 'docs/CODEX_CURRENT_STATE.md'
t = read(path)
t = replace_once(t, 'latest full code acceptance: a7116811adb26ebe5f0f9e621bf23df1dd1f605f', f'latest full code acceptance: {CLEANUP}', 'CODEX acceptance')
t = replace_once(t, 'Frontend Runtime run:        34698983278', f'Frontend Runtime run:        {CLEANUP_RUN}', 'CODEX run')
t = replace_once(t, 'app.js cache:                42.25.85', 'app.js cache:                42.25.86', 'CODEX cache')
t = replace_once(t, 'Run `34698983278` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after R20i artifact cleanup. Browser navigation runs **31 tests and passed 31/31**.', f'Run `{CLEANUP_RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after R20j artifact cleanup. Browser navigation runs **31 tests and passed 31/31**.', 'CODEX run prose')
old_priority = '''app.js/global reload/request debt\n→ legacy dataset action-generation liveness audit / dead-shell retirement\n→ live training stop/delete scoped refresh\n→ proven dead app.js/runtime shell cleanup'''
new_priority = '''app.js/global reload/request debt\n→ live v18 doImportData completion scoped refresh\n→ live training stop/delete scoped refresh\n→ historical import/saveAssign generation liveness cleanup\n→ proven dead app.js/runtime shell cleanup'''
t = replace_once(t, old_priority, new_priority, 'CODEX priority')
r20j = f'''### R20j — zero-reference legacy dataset action retirement\n\nSource-wide assignment/reference audit proved five old dataset actions had exactly one assignment and zero call sites. They were physically removed without touching the final dataset route, MaterialPagination runtime or the live import flow.\n\nPhysically retired:\n\n```text\nuploadImages\nautoSplit\nbuildYolo\ncheckDatasetQuality\nsetImageSplit\n```\n\nImportant boundary: `doImportData` is **live** and intentionally preserved. The final v36 `importData` modal calls it; its success path still broad-refreshes through `await reload()` and is the next migration target.\n\n```text\nproduct:            {PRODUCT}\nfocused run:        {FOCUSED_RUN}\nvalidation:         {VALIDATION}\nvalidation run:     {VALIDATION_RUN}\nvalidation Chrome:  31/31 PASS\ncleanup:            {CLEANUP}\ncleanup run:        {CLEANUP_RUN}\ncleanup Chrome:     31/31 PASS\napp.js cache:       42.25.86\n```\n\nPermanent proof: `tests/frontend/legacy-dataset-action-shell.test.mjs`. R20j one-shot migration artifacts are physically deleted.\n\nCurrent exact next scope is **R20k: live v18 `doImportData` success-path scoped refresh**. Preserve its modal/progress/result semantics, replace broad reload with label refresh plus paged-material refresh only while on 数据集, and lock the request boundary in Real Chrome.\n\n'''
t = insert_before(t, 'Read in order:\n', r20j, 'CODEX R20j')
write(path, t)

# TECH_DEBT_CLOSURE_V42_25.md
path = 'docs/TECH_DEBT_CLOSURE_V42_25.md'
t = read(path)
t = replace_once(t, '> **最近完整代码验收点：`a7116811adb26ebe5f0f9e621bf23df1dd1f605f`**', f'> **最近完整代码验收点：`{CLEANUP}`**', 'TECH acceptance')
t = replace_once(t, '> **Frontend Runtime Stabilization：run `34698983278`，frontend + Real Chrome 全绿，Real Chrome 31/31 passed。**', f'> **Frontend Runtime Stabilization：run `{CLEANUP_RUN}`，frontend + Real Chrome 全绿，Real Chrome 31/31 passed。**', 'TECH run')
retired_anchor = 'two shadowed historical dataset-group render bodies\n```'
retired_new = '''two shadowed historical dataset-group render bodies\nzero-reference dataset actions `uploadImages/autoSplit/buildYolo/checkDatasetQuality/setImageSplit`\n```'''
t = replace_once(t, retired_anchor, retired_new, 'TECH retired R20j')
table_anchor = '| legacy dataset-group CRUD + shadowed dataset render generations | final `renderDatasets424` route + bounded compatibility delegate | **CLOSED (R20i)** |\n'
table_new = table_anchor + '| zero-reference legacy dataset actions | physically retired, final `renderDatasets424` / import owners preserved | **CLOSED (R20j)** |\n| live v18 `doImportData` success broad reload | labels + paged materials only | **OPEN — R20k** |\n'
t = replace_once(t, table_anchor, table_new, 'TECH table R20j')
r20j_tech = f'''## 2.4 R20j — zero-reference legacy dataset actions\n\nR20j 对旧 dataset action generation 做了全局 assignment/reference proof。以下函数在当前 `static/app.js` 中均只有一个 assignment、且调用形式为 0，因此属于 proven-dead action shell，并已物理删除：\n\n```text\nwindow.uploadImages\nwindow.autoSplit\nwindow.buildYolo\nwindow.checkDatasetQuality\nwindow.setImageSplit\n```\n\n边界刻意保留：`window.doImportData` 只有一个 owner，但最终 v36 `importData()` 仍真实调用它，因此它不是 dead code。其 v18 XHR 成功路径中的 `await reload()` 留给 R20k 做 scoped refresh。\n\n```text\nproduct:            {PRODUCT}\nfocused run:        {FOCUSED_RUN}\nvalidation:         {VALIDATION}\nvalidation run:     {VALIDATION_RUN}\nReal Chrome:        31/31 PASS\ncleanup:            {CLEANUP}\ncleanup run:        {CLEANUP_RUN}\ncleanup Chrome:     31/31 PASS\napp.js cache:       42.25.86\n```\n\n永久 guard：`tests/frontend/legacy-dataset-action-shell.test.mjs`。一次性 R20j migration helper/workflow 已物理删除。R20 尚未整体 CLOSED；下一批 R20k 先迁 live `doImportData`，之后再处理 `stopJob/deleteJob`。\n\n'''
t = insert_before(t, '## 3. Canonical owners\n', r20j_tech, 'TECH R20j section')
write(path, t)

# FRONTEND_OWNER_MAP_V42_25.md
path = 'docs/FRONTEND_OWNER_MAP_V42_25.md'
t = read(path)
t = replace_once(t, '> Latest fully accepted code point: `a7116811adb26ebe5f0f9e621bf23df1dd1f605f` / run `34698983278`', f'> Latest fully accepted code point: `{CLEANUP}` / run `{CLEANUP_RUN}`', 'MAP acceptance')
row = '| R20i | legacy dataset-group CRUD + two shadowed dataset render generations + persistence wrapper retired; bounded delegate remains | `a7116811a...` / `34698983278` (31/31) |\n'
t = replace_once(t, row, row + f'| R20j | zero-reference dataset actions retired; live import and MaterialPagination owners preserved | `{CLEANUP[:10]}...` / `{CLEANUP_RUN}` (31/31) |\n', 'MAP row')
paragraph = f'''R20j product: `{PRODUCT}`; focused run `{FOCUSED_RUN}`; validation `{VALIDATION}` / run `{VALIDATION_RUN}`; cleanup `{CLEANUP}` / run `{CLEANUP_RUN}`; frontend PASS; Real Chrome **31/31 passed**. Five globally zero-reference dataset actions were physically retired. `doImportData` is explicitly preserved as live and becomes R20k because its successful v18 import path still invokes broad `reload()`.  \n\n'''
t = insert_before(t, 'R10 product:', paragraph, 'MAP R20j paragraph')
write(path, t)

# frontend-legacy-audit.md
path = 'docs/frontend-legacy-audit.md'
t = read(path)
t = replace_once(t, 'commit:       a7116811adb26ebe5f0f9e621bf23df1dd1f605f', f'commit:       {CLEANUP}', 'AUDIT acceptance')
t = replace_once(t, 'run:          34698983278', f'run:          {CLEANUP_RUN}', 'AUDIT run')
t = replace_once(t, 'app.js                    42.25.85', 'app.js                    42.25.86', 'AUDIT cache')
retired_anchor = 'two shadowed historical dataset-group render bodies\n```'
retired_new = '''two shadowed historical dataset-group render bodies\nzero-reference uploadImages / autoSplit / buildYolo / checkDatasetQuality / setImageSplit owners\n```'''
t = replace_once(t, retired_anchor, retired_new, 'AUDIT retired R20j')
r20j_audit = f'''## R20j — zero-reference legacy dataset actions\n\nThe current-source liveness audit found exactly one assignment and no caller for each of `uploadImages`, `autoSplit`, `buildYolo`, `checkDatasetQuality` and `setImageSplit`. They were physically removed and permanently guarded. The audit deliberately excluded `doImportData`: final v36 `importData()` still calls that unique v18 XHR owner.\n\n```text\nproduct:            {PRODUCT}\nfocused run:        {FOCUSED_RUN}\nvalidation:         {VALIDATION}\nvalidation run:     {VALIDATION_RUN}\ncleanup:            {CLEANUP}\ncleanup run:        {CLEANUP_RUN}\nfrontend:           PASS\nReal Chrome:        31/31 PASS\napp.js cache:       42.25.86\n```\n\nPermanent proof: `tests/frontend/legacy-dataset-action-shell.test.mjs`. Next audit/migration target: live `doImportData` completion request scope; do not delete it as historical shell.\n\n'''
if '## R20j — zero-reference legacy dataset actions' in t:
    raise SystemExit('AUDIT R20j section already present')
t = t.rstrip() + '\n\n' + r20j_audit
write(path, t)

print('R20j handoff synchronized across 5 authority files')
