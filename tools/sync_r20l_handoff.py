from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

ACCEPT = 'f8356bcf5ec1ea128fb38db2820df38146b48cfd'
PRODUCT = 'f260127d2d41281bc1d996a172e7d4290536f24c'
PERMANENT = 'b17bd0c33bfb99e5557fc245a89a6c4444a8257e'
FRONTEND_RUN = '34723808299'
ACTION_RUN = '34723808298'
MIGRATION_RUN = '34723694735'
APP_CACHE = '42.25.91'
MAIN_CACHE = '42.25.89'


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def write(path, text):
    (ROOT / path).write_text(text, encoding='utf-8')


def sub_once(text, pattern, repl, label, flags=0):
    updated, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly one replacement, got {count}')
    return updated


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exact marker once, got {count}')
    return text.replace(old, new, 1)


# Mechanical repository invariants before handoff mutation.
if read('VERSION.txt').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt changed unexpectedly')
index = read('static/index.html')
if f'/static/app.js?v={APP_CACHE}' not in index or f'/static/main.mjs?v={MAIN_CACHE}' not in index:
    raise SystemExit('R20l cache markers are not the accepted values')
for required in [
    'tests/frontend/source-import-completion-scope.test.mjs',
    'tests/browser/source-import-completion-scope.spec.mjs',
    '.github/workflows/frontend-runtime-stabilization.yml',
]:
    if not (ROOT / required).exists():
        raise SystemExit(f'missing permanent R20l contract: {required}')
workflow = read('.github/workflows/frontend-runtime-stabilization.yml')
if 'tests/browser/source-import-completion-scope.spec.mjs' not in workflow:
    raise SystemExit('R20l browser contract is not permanent in Frontend Runtime workflow')
for retired in [
    'tools/migrate_source_import_completion_scope_r20l.py',
    '.github/workflows/migrate-source-import-completion-scope-r20l.yml',
]:
    if (ROOT / retired).exists():
        raise SystemExit(f'R20l migration artifact still exists: {retired}')

# AGENTS.md
path = 'AGENTS.md'
text = read(path)
text = sub_once(
    text,
    r'latest full code acceptance: [0-9a-f]+\nFrontend Runtime run:\s+\d+\nformal VERSION\.txt:\s+42\.24\.0\nfrontend badge:\s+v42\.24\.0\napp\.js cache:\s+[^\n]+\nmain\.mjs cache:\s+[^\n]+\nNavigationStability:\s+422512',
    f'latest full code acceptance: {ACCEPT}\nFrontend Runtime run:        {FRONTEND_RUN}\nformal VERSION.txt:          42.24.0\nfrontend badge:              v42.24.0\napp.js cache:                {APP_CACHE}\nmain.mjs cache:              {MAIN_CACHE}\nNavigationStability:         422512',
    'AGENTS current state',
)
text = sub_once(
    text,
    r'`\d+` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome \d+/\d+。Navigation Action Fencing 永久 workflow `\d+` 全绿；Resource Discovery SQLite 永久 workflow `34700900542` 继续保持 Ubuntu \+ Windows 双平台通过。',
    f'`{FRONTEND_RUN}` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 33/33。Navigation Action Fencing 永久 workflow `{ACTION_RUN}` 全绿；Resource Discovery SQLite 永久 workflow `34700900542` 继续保持 Ubuntu + Windows 双平台通过。',
    'AGENTS acceptance sentence',
)
old_header = '## 下一批准确范围：Navigation Action Fencing R2\n'
new_header = f'''## 下一批准确范围：R20 final global reload/request zero-point\n\n### R20l — source-import terminal completion scoped refresh CLOSED\n\n最终 live `refreshSourceImportTasksV36()` 在地址读取任务进入 terminal 状态后，已从 broad `loadRelated()` 改为只刷新标签 schema 和当前可见的数据集分页素材。任务 active 期间的 1.8s polling cadence、source-import API 和任务列表 UI 均保持不变。\n\n```text\nbaseline + migration run: {MIGRATION_RUN}\nproduct:                  {PRODUCT}\npermanent Chrome guard:   {PERMANENT}\ncleanup / acceptance:     {ACCEPT}\nFrontend Runtime:         {FRONTEND_RUN}\nfull Real Chrome:         33/33 PASS\nNavigation Action Fencing:{ACTION_RUN} PASS\nformal VERSION.txt:       42.24.0 unchanged\napp.js cache:             {APP_CACHE}\nmain.mjs cache:           {MAIN_CACHE}\n```\n\n永久合同：`tests/frontend/source-import-completion-scope.test.mjs` + `tests/browser/source-import-completion-scope.spec.mjs`；browser spec 已进入唯一长期 `Frontend Runtime Stabilization` Chrome 清单。一次性 R20l migration helper/workflow 已物理删除。**这只关闭 source-import terminal completion；R20 全局 reload/request zero-point 仍为 IN PROGRESS。**\n'''
if '### R20l — source-import terminal completion scoped refresh CLOSED' not in text:
    text = replace_once(text, old_header, new_header, 'AGENTS R20l header')
old_boundary = "**边界：整个 Navigation Action Fencing 仍为 IN PROGRESS。** R1 只关闭训练服务器/Paddle 与本批 direct-page-write surface；最终 Model Config 427、AI 标注/清洗确认、图片/ZIP/XHR upload completion、deployment mutation、其他 timer/callback family 尚未全部迁移，不能宣称 stale async UI side effect 全局为 0。下一批为 **R2：最终 Model Config / AI 清洗与 modal mutation completion**。"
new_boundary = "**边界：Navigation Action Fencing R1 + R2 已 CLOSED，但全局 stale-async zero-point 仍为 IN PROGRESS。** R2 已关闭最终 M4 Model Config、清洗确认和 v60 AI review completion；upload/ZIP/deployment/timer-callback completion family 仍留给 final scan，不能宣称 stale async UI side effect 全局为 0。"
if old_boundary in text:
    text = replace_once(text, old_boundary, new_boundary, 'AGENTS action-fencing boundary')
old_priority = '''```text
1. Navigation Action Fencing / stale mutation UI side-effect zero-point
2. R20 final global reload/request zero-point
3. External Algorithm Catalog read-only boundary
4. Resource Lifecycle production soak + remaining non-SQLite resource classes
5. ZIP 10k / Training Progress v2 / GPU Performance Tuner / Deployment Artifact E2E
6. app.js / app.py normalization + cache-busting / semantic naming / deterministic cleanup
7. technical-debt final zero-point + backend regression
8. A800 RC only after acceptance gates
```'''
new_priority = '''```text
1. R20 final global reload/request zero-point
2. Unified Task Progress + Durable Queue Runtime productionization
3. Navigation Action Fencing final scan (upload/ZIP/deployment/timer-callback completions)
4. External Algorithm Catalog read-only boundary
5. Resource Lifecycle production soak + remaining non-SQLite resource classes
6. ZIP 10k / Training Progress v2 / GPU Performance Tuner / Deployment Artifact E2E
7. app.js / app.py normalization + cache-busting / semantic naming / deterministic cleanup
8. technical-debt final zero-point + backend regression
9. A800 RC only after acceptance gates
```'''
if old_priority in text:
    text = replace_once(text, old_priority, new_priority, 'AGENTS priority')
write(path, text)

# CODEX_CURRENT_STATE.md
path = 'docs/CODEX_CURRENT_STATE.md'
text = read(path)
text = sub_once(
    text,
    r'latest full code acceptance: [0-9a-f]+\nFrontend Runtime run:\s+\d+\nformal VERSION\.txt:\s+42\.24\.0\nvisible frontend version:\s+v42\.24\.0\ninternal UI build metadata:\s+42\.25\.0-dev\napp\.js cache:\s+[^\n]+\nmain\.mjs cache:\s+[^\n]+',
    f'latest full code acceptance: {ACCEPT}\nFrontend Runtime run:        {FRONTEND_RUN}\nformal VERSION.txt:          42.24.0\nvisible frontend version:    v42.24.0\ninternal UI build metadata:  42.25.0-dev\napp.js cache:                {APP_CACHE}\nmain.mjs cache:              {MAIN_CACHE}',
    'CODEX current state',
)
text = sub_once(
    text,
    r'Run `\d+` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after Navigation Action Fencing R2 migration-artifact cleanup\. Browser navigation runs \*\*\d+ tests and passed \d+/\d+\*\*\. Permanent Action Fencing workflow `\d+` is green; permanent Resource Discovery SQLite workflow `34700900542` remains green on Ubuntu and Windows\.',
    f'Run `{FRONTEND_RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after R20l permanentization and migration-artifact cleanup. Browser navigation runs **33 tests and passed 33/33**. Permanent Action Fencing workflow `{ACTION_RUN}` is green; permanent Resource Discovery SQLite workflow `34700900542` remains green on Ubuntu and Windows.',
    'CODEX acceptance sentence',
)
r20l = f'''### R20l — source-import terminal completion scoped refresh CLOSED\n\nFinal liveness/source-order proof confirmed that `window.refreshSourceImportTasksV36()` is the live source-import polling owner. Its terminal branch used to call final broad `loadRelated()`, which fans out across project/datasets/full images/labels/algorithms/publish/test-models/model-configs/prompt-templates. Real Chrome baseline proved the fan-out before migration.\n\nThe terminal branch now owns only the domains actually changed by a completed source import:\n\n```text\nrefreshLabels414(false)\n+ if still on 数据集 → reloadMaterialPage61()\n```\n\nActive-task polling cadence and source-import API semantics are unchanged.\n\n```text\nbaseline + migration run: {MIGRATION_RUN}\nproduct:                  {PRODUCT}\npermanent Chrome guard:   {PERMANENT}\ncleanup / acceptance:     {ACCEPT}\nFrontend Runtime:         {FRONTEND_RUN}\nfull Real Chrome:         33/33 PASS\nAction Fencing:           {ACTION_RUN} PASS\nformal VERSION.txt:       42.24.0 unchanged\napp.js cache:             {APP_CACHE}\nmain.mjs cache:           {MAIN_CACHE}\n```\n\nPermanent contracts: `tests/frontend/source-import-completion-scope.test.mjs`, `tests/browser/source-import-completion-scope.spec.mjs`, and the browser spec is explicitly listed in `.github/workflows/frontend-runtime-stabilization.yml`. One-shot R20l migration artifacts are physically deleted. **R20l is CLOSED; global R20 zero-point remains IN PROGRESS.**\n\n'''
marker = 'A800 RC remains deferred.\n\n'
if '### R20l — source-import terminal completion scoped refresh CLOSED' not in text:
    text = replace_once(text, marker, marker + r20l, 'CODEX R20l section')
write(path, text)

# TECH_DEBT_CLOSURE_V42_25.md
path = 'docs/TECH_DEBT_CLOSURE_V42_25.md'
text = read(path)
text = sub_once(text, r'\*\*最近完整代码验收点：`[0-9a-f]+`\*\*', f'**最近完整代码验收点：`{ACCEPT}`**', 'TECH acceptance')
text = sub_once(
    text,
    r'\*\*Frontend Runtime Stabilization：run `\d+`，frontend \+ Real Chrome 全绿，Real Chrome \d+/\d+ passed；Navigation Action Fencing 永久 run `\d+` 全绿；Resource Discovery SQLite 永久跨平台 run `34700900542` Ubuntu \+ Windows 全绿。\*\*',
    f'**Frontend Runtime Stabilization：run `{FRONTEND_RUN}`，frontend + Real Chrome 全绿，Real Chrome 33/33 passed；Navigation Action Fencing 永久 run `{ACTION_RUN}` 全绿；Resource Discovery SQLite 永久跨平台 run `34700900542` Ubuntu + Windows 全绿。**',
    'TECH run line',
)
row_marker = '| live v18 `doImportData` success broad reload | labels + paged materials only | **CLOSED (R20k)** |\n'
r20l_row = '| source-import terminal completion broad refresh | labels + current paged materials only | **CLOSED (R20l)** |\n'
if r20l_row not in text:
    text = replace_once(text, row_marker, row_marker + r20l_row, 'TECH R20l row')
section = f'''## 2.0b R20l — source-import terminal scoped refresh\n\nSource-order/liveness audit proved that `refreshSourceImportTasksV36()` remains the final live owner for address/server source-import task polling. On terminal completion it still invoked final `loadRelated()`, causing a real broad GET fan-out. The dedicated Real Chrome baseline intercepted the terminal source-import jobs response and proved those broad project/dataset/image/algorithm/publish/test-model/config requests before migration.\n\nThe terminal owner now refreshes only label schema plus the current paged material domain when the user is still on 数据集. Active polling stays at 1800ms and the source-import task API/UI is unchanged.\n\n```text\nbaseline + migration run: {MIGRATION_RUN}\nproduct:                  {PRODUCT}\npermanent Chrome guard:   {PERMANENT}\ncleanup / acceptance:     {ACCEPT}\nFrontend Runtime:         {FRONTEND_RUN}\nfull Real Chrome:         33/33 PASS\nAction Fencing:           {ACTION_RUN} PASS\nformal VERSION.txt:       42.24.0 unchanged\napp.js cache:             {APP_CACHE}\nmain.mjs cache:           {MAIN_CACHE}\n```\n\nPermanent contracts: `tests/frontend/source-import-completion-scope.test.mjs` and `tests/browser/source-import-completion-scope.spec.mjs`; the Chrome contract is part of the permanent Frontend Runtime workflow. One-shot migration helper/workflow are physically deleted. **R20l CLOSED; global R20 reload/request zero-point stays IN PROGRESS.**\n\n'''
marker = '## 2.1 R20g — import completion scoped refresh'
if '## 2.0b R20l — source-import terminal scoped refresh' not in text:
    text = replace_once(text, marker, section + marker, 'TECH R20l section')
write(path, text)

# FRONTEND_OWNER_MAP_V42_25.md
path = 'docs/FRONTEND_OWNER_MAP_V42_25.md'
text = read(path)
text = sub_once(text, r'> Latest fully accepted code point: `[0-9a-f]+` / run `\d+`', f'> Latest fully accepted code point: `{ACCEPT}` / run `{FRONTEND_RUN}`', 'OWNER top acceptance')
text = sub_once(text, r'> Real Chrome: \d+/\d+ passed', '> Real Chrome: 33/33 passed', 'OWNER chrome count')
row_marker = '| R20k | live v18 import completion broad reload → labels + current paged materials only | `f51d44c089...` / `34700252041` (32/32) |\n'
r20l_row = f'| R20l | live source-import terminal broad `loadRelated()` → labels + current paged materials only | `{ACCEPT[:10]}...` / `{FRONTEND_RUN}` (33/33) |\n'
if r20l_row not in text:
    text = replace_once(text, row_marker, row_marker + r20l_row, 'OWNER R20l row')
paragraph = f'''R20l product: `{PRODUCT}`; baseline/migration run `{MIGRATION_RUN}`; permanent Chrome guard `{PERMANENT}`; cleanup/final acceptance `{ACCEPT}` / Frontend Runtime `{FRONTEND_RUN}`; frontend PASS; Real Chrome **33/33 passed**; Action Fencing `{ACTION_RUN}` PASS. The final live `refreshSourceImportTasksV36()` terminal branch no longer calls broad `loadRelated()`; it refreshes only labels and the current paged material domain. Active polling cadence/API semantics are unchanged. One-shot R20l migration artifacts are physically deleted.  \n\n'''
marker = 'Cross-cutting P0 checkpoint: Resource Discovery SQLite lifecycle product'
if paragraph.strip() not in text:
    text = replace_once(text, marker, paragraph + marker, 'OWNER R20l paragraph')
write(path, text)

# frontend-legacy-audit.md
path = 'docs/frontend-legacy-audit.md'
text = read(path)
text = sub_once(
    text,
    r'commit:\s+[0-9a-f]+\nrun:\s+\d+\nfrontend:\s+PASS\nReal Chrome:\s+PASS \(\d+/\d+\)',
    f'commit:       {ACCEPT}\nrun:          {FRONTEND_RUN}\nfrontend:     PASS\nReal Chrome:  PASS (33/33)',
    'AUDIT acceptance block',
)
text = sub_once(text, r'app\.js\s+42\.25\.\d+', f'app.js                    {APP_CACHE}', 'AUDIT app cache')
paragraph = f'''R20l kept the live `refreshSourceImportTasksV36` owner but removed its terminal broad refresh. Real Chrome baseline proved the old terminal `loadRelated()` fan-out; completion now calls only `refreshLabels414(false)` plus `reloadMaterialPage61()` when still on 数据集. Active source-import polling cadence remains unchanged. Product `{PRODUCT}`, migration run `{MIGRATION_RUN}`, permanentization `{PERMANENT}`, cleanup/final acceptance `{ACCEPT}` / run `{FRONTEND_RUN}`, Real Chrome **33/33**, Action Fencing `{ACTION_RUN}` PASS. Permanent contracts: `tests/frontend/source-import-completion-scope.test.mjs` and `tests/browser/source-import-completion-scope.spec.mjs`; one-shot migration artifacts are deleted. Global R20 zero-point remains open.\n\n'''
marker = 'Cross-cutting checkpoint after R20k: Resource Discovery SQLite code-level lifecycle'
if paragraph.strip() not in text:
    text = replace_once(text, marker, paragraph + marker, 'AUDIT R20l paragraph')
write(path, text)

print('R20l handoff synchronized')
