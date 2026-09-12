from pathlib import Path

PRODUCT = 'feeb98f441bb1fe5d0f8f409a1509c66606e59ef'
VALIDATION = '11131ca30c17809e016807aa6c75b0bf203fa6f8'
VALIDATION_RUN = '34698850495'
CLEANUP = 'a7116811adb26ebe5f0f9e621bf23df1dd1f605f'
CLEANUP_RUN = '34698983278'


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
if 'app.js?v=42.25.85' not in read('static/index.html'):
    raise SystemExit('R20i app.js cache acceptance missing')

# AGENTS.md
path = 'AGENTS.md'
t = read(path)
t = replace_once(t, 'latest full code acceptance: 210a9ad1f6271a8a8986db3f223f4813a6cce288', f'latest full code acceptance: {CLEANUP}', 'AGENTS acceptance')
t = replace_once(t, 'Frontend Runtime run:        34696729028', f'Frontend Runtime run:        {CLEANUP_RUN}', 'AGENTS run')
t = replace_once(t, 'app.js cache:                42.25.84', 'app.js cache:                42.25.85', 'AGENTS cache')
t = replace_once(t, '`34696729028` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 31/31。', f'`{CLEANUP_RUN}` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 31/31。', 'AGENTS acceptance prose')
start = t.index('## 下一批准确范围：R20 final zero-point')
end = t.index('## 不得回退的核心合同', start)
new_scope = f'''## 下一批准确范围：R20 final zero-point\n\nR20g、R20h、R20i 已 CLOSED。R20i 已物理退休旧 dataset-group CRUD、两代旧 dataset renderer body 与 `oldSelectDataset` persistence wrapper；最终数据集页面仍由 `renderDatasets424` 直接路由，历史 render map 只保留 bounded `renderDatasets() → renderDatasets424()` delegate。\n\n下一批继续做 **legacy dataset action generation liveness audit**，先证明 assignment/reference/source-order，再处理 proven-dead action；之后再迁移真实 live 的训练任务停止/删除 broad reload：\n\n```text\n优先证明并清理的 dead-shell 候选：\nuploadImages / autoSplit / buildYolo / checkDatasetQuality / setImageSplit\n旧 importData / doImportData generations（必须先证明最终 owner，不得整名删除）\n旧 saveAssign generation（保留 R20b 后代 local-state owner）\n\n明确 live、不得直接删除：\nstopJob / deleteJob → 当前训练任务页面仍调用，后续改 scoped jobs refresh / local patch\nrenderDatasets424 + MaterialPaginationRuntime61 → 当前数据页 owner\n```\n\n规则：先建 assignment/reference/liveness/semantic 表；shadowed generation 才允许物理删。live mutation 必须先补 permanent request contract，再做 authoritative result + local state patch / scoped refresh。不得回头重构已经 CLOSED 的 `setPage` / NavigationStability。\n\nR20i 验收：\n\n```text\nproduct:          {PRODUCT}\nfocused run:      34698742036 (all frontend unit + focused Real Chrome PASS)\nvalidation:       {VALIDATION}\nvalidation run:   {VALIDATION_RUN}\nvalidation Chrome: 31/31 PASS\ncleanup:          {CLEANUP}\ncleanup run:      {CLEANUP_RUN}\ncleanup Chrome:   31/31 PASS\napp.js cache:     42.25.85\nmain.mjs cache:   42.25.88\n```\n\n永久 guard：`tests/frontend/legacy-dataset-group-owner.test.mjs`。一次性 R20i migration helper/workflow 已物理删除。\n\n'''
t = t[:start] + new_scope + t[end:]
write(path, t)

# CODEX_CURRENT_STATE.md
path = 'docs/CODEX_CURRENT_STATE.md'
t = read(path)
t = replace_once(t, 'latest full code acceptance: 210a9ad1f6271a8a8986db3f223f4813a6cce288', f'latest full code acceptance: {CLEANUP}', 'CODEX acceptance')
t = replace_once(t, 'Frontend Runtime run:        34696729028', f'Frontend Runtime run:        {CLEANUP_RUN}', 'CODEX run')
t = replace_once(t, 'app.js cache:                42.25.84', 'app.js cache:                42.25.85', 'CODEX cache')
t = replace_once(t, 'Run `34696729028` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **31 tests and passed 31/31**.', f'Run `{CLEANUP_RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after R20i artifact cleanup. Browser navigation runs **31 tests and passed 31/31**.', 'CODEX run prose')
old_priority = '''app.js/global reload/request debt\n→ remaining dataset/job/publish mutation liveness audit + scoped refresh\n→ proven dead app.js/runtime shell cleanup'''
new_priority = '''app.js/global reload/request debt\n→ legacy dataset action-generation liveness audit / dead-shell retirement\n→ live training stop/delete scoped refresh\n→ proven dead app.js/runtime shell cleanup'''
t = replace_once(t, old_priority, new_priority, 'CODEX priority')
r20i = f'''### R20i — legacy dataset-group owner retirement\n\nThe final dataset route already bypasses the historical dataset-group pages and directly owns the page through `renderDatasets424`. R20i proved two old `renderDatasets` generations plus dataset-group CRUD and the later `oldSelectDataset` persistence wrapper were unreachable compatibility debt. They were physically removed; one bounded `renderDatasets() → renderDatasets424()` delegate remains only because older global render maps still eagerly reference the symbol.\n\nPhysically retired:\n\n```text\nselectDataset / newDataset / saveDataset / editDataset / saveEditDataset / delDataset\noldSelectDataset persistence wrapper\ncurrentDataset helper\ntwo historical dataset-group render bodies\n```\n\n```text\nproduct:          {PRODUCT}\nfocused run:      34698742036\nvalidation:       {VALIDATION}\nvalidation run:   {VALIDATION_RUN}\nvalidation Chrome: 31/31 PASS\ncleanup:          {CLEANUP}\ncleanup run:      {CLEANUP_RUN}\ncleanup Chrome:   31/31 PASS\napp.js cache:     42.25.85\n```\n\nPermanent proof: `tests/frontend/legacy-dataset-group-owner.test.mjs` plus the existing permanent material-pagination/navigation Chrome suite. One-shot R20i migration artifacts are physically deleted.\n\nCurrent exact next scope: prove liveness/source order for the remaining old dataset action generation (`uploadImages/autoSplit/buildYolo/checkDatasetQuality/setImageSplit` and historical `importData/doImportData`), then migrate the confirmed-live `stopJob/deleteJob` broad reload path with a focused browser request contract.\n\n'''
t = insert_before(t, 'Read in order:\n', r20i, 'CODEX R20i')
write(path, t)

# TECH_DEBT_CLOSURE_V42_25.md
path = 'docs/TECH_DEBT_CLOSURE_V42_25.md'
t = read(path)
t = replace_once(t, '> **最近完整代码验收点：`210a9ad1f6271a8a8986db3f223f4813a6cce288`**', f'> **最近完整代码验收点：`{CLEANUP}`**', 'TECH acceptance')
t = replace_once(t, '> **Frontend Runtime Stabilization：run `34696729028`，frontend + Real Chrome 全绿，Real Chrome 31/31 passed。**', f'> **Frontend Runtime Stabilization：run `{CLEANUP_RUN}`，frontend + Real Chrome 全绿，Real Chrome 31/31 passed。**', 'TECH run')
retired_anchor = 'v42.2 `renderAlgorithms422/openNewAlgorithm422/saveNewAlgorithm422` shadowed algorithm page generation\n```'
retired_new = '''v42.2 `renderAlgorithms422/openNewAlgorithm422/saveNewAlgorithm422` shadowed algorithm page generation\nlegacy dataset-group `selectDataset/newDataset/saveDataset/editDataset/saveEditDataset/delDataset`\n`oldSelectDataset` persistence compatibility wrapper\nlegacy `currentDataset()` helper\ntwo shadowed historical dataset-group render bodies\n```'''
t = replace_once(t, retired_anchor, retired_new, 'TECH retired R20i')
table_anchor = '| legacy algorithm CRUD + shadowed algorithm renderer generations | stable 414/423/429 owners + authoritative local `state.algorithms` patch | **CLOSED (R20h)** |\n'
table_new = table_anchor + '| legacy dataset-group CRUD + shadowed dataset render generations | final `renderDatasets424` route + bounded compatibility delegate | **CLOSED (R20i)** |\n'
t = replace_once(t, table_anchor, table_new, 'TECH table R20i')
r20i_tech = f'''## 2.3 R20i — legacy dataset-group owner retirement\n\nR20i 证明最终数据集路由已经直接执行 `renderDatasets424()`，不会再回落到两代旧 dataset-group renderer。旧分组 CRUD 与后续 `oldSelectDataset` persistence wrapper 因此是不可达 compatibility debt，已物理退休。为兼容仍会 eager-reference `renderDatasets` symbol 的旧 global render map，只保留一个 bounded delegate：\n\n```text\nfunction renderDatasets() → window.renderDatasets424?.()\nfinal 数据集 route → renderDatasets424()\n```\n\n永久 guard 禁止旧 `select/new/save/edit/delete dataset` owner、`oldSelectDataset`、`currentDataset()` 回归。\n\n```text\nproduct:          {PRODUCT}\nfocused run:      34698742036\nvalidation:       {VALIDATION}\nvalidation run:   {VALIDATION_RUN}\nReal Chrome:      31/31 PASS\ncleanup:          {CLEANUP}\ncleanup run:      {CLEANUP_RUN}\ncleanup Chrome:   31/31 PASS\napp.js cache:     42.25.85\n```\n\nR20 仍未整体 CLOSED。下一批先完成 legacy dataset action generation 的 liveness/source-order 证明，再处理 proven-dead action shell；`stopJob/deleteJob` 已确认仍被当前训练页调用，属于 live mutation，后续必须以 scoped jobs refresh/local patch 方式迁移，不能直接删除。\n\n'''
t = insert_before(t, '## 3. Canonical owners\n', r20i_tech, 'TECH R20i section')
write(path, t)

# FRONTEND_OWNER_MAP_V42_25.md
path = 'docs/FRONTEND_OWNER_MAP_V42_25.md'
t = read(path)
t = replace_once(t, '> Latest fully accepted code point: `210a9ad1f6271a8a8986db3f223f4813a6cce288` / run `34696729028`', f'> Latest fully accepted code point: `{CLEANUP}` / run `{CLEANUP_RUN}`', 'MAP acceptance')
row = '| R20h | legacy algorithm CRUD + v30/v39/v42.2 shadowed algorithm generations retired; stable 414/423/429 local-state owners remain | `210a9ad1...` / `34696729028` (31/31) |\n'
t = replace_once(t, row, row + f'| R20i | legacy dataset-group CRUD + two shadowed dataset render generations + persistence wrapper retired; bounded delegate remains | `{CLEANUP[:9]}...` / `{CLEANUP_RUN}` (31/31) |\n', 'MAP row')
paragraph = f'''R20i product: `{PRODUCT}`; validation `{VALIDATION}` / run `{VALIDATION_RUN}`; cleanup `{CLEANUP}` / run `{CLEANUP_RUN}`; frontend PASS; Real Chrome **31/31 passed**. Final dataset routing remains `renderDatasets424`; one bounded `renderDatasets()` delegate remains for historical render-map symbol compatibility. The dataset-group CRUD family, `oldSelectDataset`, `currentDataset()` and both shadowed dataset-group render bodies are physically retired and permanently guarded.  \n\n'''
t = insert_before(t, 'R10 product:', paragraph, 'MAP R20i paragraph')
write(path, t)

# frontend-legacy-audit.md
path = 'docs/frontend-legacy-audit.md'
t = read(path)
t = replace_once(t, 'commit:       210a9ad1f6271a8a8986db3f223f4813a6cce288', f'commit:       {CLEANUP}', 'AUDIT acceptance')
t = replace_once(t, 'run:          34696729028', f'run:          {CLEANUP_RUN}', 'AUDIT run')
t = replace_once(t, 'app.js                    42.25.84', 'app.js                    42.25.85', 'AUDIT cache')
retired_anchor = 'v42.2 renderAlgorithms422/openNewAlgorithm422/saveNewAlgorithm422 generation\n```'
retired_new = '''v42.2 renderAlgorithms422/openNewAlgorithm422/saveNewAlgorithm422 generation\nlegacy dataset-group select/new/save/edit/delete CRUD generation\noldSelectDataset persistence wrapper\ncurrentDataset helper\ntwo shadowed historical dataset-group render bodies\n```'''
t = replace_once(t, retired_anchor, retired_new, 'AUDIT retired R20i')
r20i_audit = f'''## R20i — legacy dataset-group owner retirement\n\nSource-order audit proved the late final route executes `renderDatasets424()` directly. Two older dataset-group page bodies and their CRUD/persistence helpers were therefore physically unreachable. R20i removed them while retaining one bounded `renderDatasets() → renderDatasets424()` delegate for historical render-map symbol compatibility.\n\n```text\nproduct:          {PRODUCT}\nvalidation:       {VALIDATION}\nvalidation run:   {VALIDATION_RUN}\ncleanup:          {CLEANUP}\ncleanup run:      {CLEANUP_RUN}\nfrontend:         PASS\nReal Chrome:      31/31 PASS\napp.js cache:     42.25.85\n```\n\nPermanent proof: `tests/frontend/legacy-dataset-group-owner.test.mjs`. Next audit target is the remaining legacy dataset action block; do not conflate it with live `renderDatasets424` / MaterialPagination behavior.\n\n'''
# append before final newline; this file is chronological and safe to append
if '## R20i — legacy dataset-group owner retirement' in t:
    raise SystemExit('AUDIT R20i section already present')
t = t.rstrip() + '\n\n' + r20i_audit
write(path, t)

print('R20i handoff synchronized across 5 authority files')
