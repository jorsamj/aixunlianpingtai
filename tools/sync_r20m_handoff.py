from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

BASELINE = '243bcb1b17074848d91c2c9c64d47dbed54e5e9b'
MIGRATION_RUN = '34724242632'
PRODUCT = '71cdb2ad192ec99b0e21bfe3c1f70bffca0f586e'
ACCEPT = '40a87bf70402dccfc0387950b6856a561ce1ebe1'
FRONTEND_RUN = '34724354775'
ACTION_RUN = '34724354790'
APP_CACHE = '42.25.92'
MAIN_CACHE = '42.25.89'


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def write(path, text):
    (ROOT / path).write_text(text, encoding='utf-8')


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exact marker once, got {count}')
    return text.replace(old, new, 1)


def sub_once(text, pattern, repl, label, flags=0):
    updated, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f'{label}: expected one replacement, got {count}')
    return updated


# Mechanical accepted-state checks before touching handoff docs.
if read('VERSION.txt').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt changed unexpectedly')
index = read('static/index.html')
if f'/static/app.js?v={APP_CACHE}' not in index or f'/static/main.mjs?v={MAIN_CACHE}' not in index:
    raise SystemExit('R20m cache markers are not accepted values')
app = read('static/app.js')
for retired in [
    'window.openNewAlgorithm423=async function(){',
    'window.saveNewAlgorithm423=async function(){',
    'window.saveEditAlgorithm423=async function(id)',
]:
    if retired in app:
        raise SystemExit(f'R20m retired owner survived: {retired}')
if app.count('window.openNewAlgorithm423=') != 1 or app.count('window.editAlgorithm423=') != 1:
    raise SystemExit('R20m final stable algorithm CRUD owner cardinality is wrong')
if not (ROOT / 'tests/frontend/shadowed-algorithm-crud-r20m.test.mjs').exists():
    raise SystemExit('R20m permanent unit guard missing')
if not (ROOT / 'tests/browser/algorithm-list-performance.spec.mjs').exists():
    raise SystemExit('R20m permanent Chrome behavior contract missing')
for temporary in [
    ROOT / 'tools/migrate_shadowed_algorithm_crud_r20m.py',
    ROOT / '.github/workflows/migrate-shadowed-algorithm-crud-r20m.yml',
]:
    if temporary.exists():
        raise SystemExit(f'R20m temporary artifact still exists: {temporary}')

# AGENTS.md
path = 'AGENTS.md'
text = read(path)
text = sub_once(
    text,
    r'latest full code acceptance: [0-9a-f]+\nFrontend Runtime run:\s+\d+\nformal VERSION\.txt:\s+42\.24\.0\nfrontend badge:\s+v42\.24\.0\napp\.js cache:\s+42\.25\.\d+\nmain\.mjs cache:\s+42\.25\.\d+\nNavigationStability:\s+422512',
    f'latest full code acceptance: {ACCEPT}\nFrontend Runtime run:        {FRONTEND_RUN}\nformal VERSION.txt:          42.24.0\nfrontend badge:              v42.24.0\napp.js cache:                {APP_CACHE}\nmain.mjs cache:              {MAIN_CACHE}\nNavigationStability:         422512',
    'AGENTS current state',
)
text = sub_once(
    text,
    r'`\d+` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 33/33。Navigation Action Fencing 永久 workflow `\d+` 全绿；Resource Discovery SQLite 永久 workflow `34700900542` 继续保持 Ubuntu \+ Windows 双平台通过。',
    f'`{FRONTEND_RUN}` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 33/33。Navigation Action Fencing 永久 workflow `{ACTION_RUN}` 全绿；Resource Discovery SQLite 永久 workflow `34700900542` 继续保持 Ubuntu + Windows 双平台通过。',
    'AGENTS acceptance sentence',
)
section = f'''### R20m — shadowed v423 algorithm CRUD generation retirement CLOSED

Source-order + Real Chrome 已证明旧 v423 create/edit generation 从运行时不可达：删除前 `algorithm-list-performance.spec.mjs` 已完整通过，真实 UI 一直解析到后面的 stable 414 owner。R20m 因此没有“迁移 broad refresh”，而是物理删除旧 `openNewAlgorithm423(async) / saveNewAlgorithm423 / editAlgorithm423(old modal) / saveEditAlgorithm423` generation；后面的 `saveNewAlgorithm414 / saveEditAlgorithm414` authoritative local-state owner 保持不变。

```text
baseline:                  {BASELINE}
baseline + migration run: {MIGRATION_RUN}
product:                   {PRODUCT}
cleanup / acceptance:      {ACCEPT}
Frontend Runtime:          {FRONTEND_RUN}
full Real Chrome:          33/33 PASS
Navigation Action Fencing: {ACTION_RUN} PASS
formal VERSION.txt:        42.24.0 unchanged
app.js cache:              {APP_CACHE}
main.mjs cache:            {MAIN_CACHE}
```

永久 source contract：`tests/frontend/shadowed-algorithm-crud-r20m.test.mjs`；行为合同复用现有 `tests/browser/algorithm-list-performance.spec.mjs`。一次性 migration helper/workflow 已物理删除。**R20m CLOSED；R20 全局 reload/request zero-point 仍为 IN PROGRESS。**

'''
marker = '### R20l — source-import terminal completion scoped refresh CLOSED\n'
if '### R20m — shadowed v423 algorithm CRUD generation retirement CLOSED' not in text:
    text = replace_once(text, marker, section + marker, 'AGENTS R20m section')
write(path, text)

# CODEX_CURRENT_STATE.md
path = 'docs/CODEX_CURRENT_STATE.md'
text = read(path)
text = sub_once(
    text,
    r'latest full code acceptance: [0-9a-f]+\nFrontend Runtime run:\s+\d+\nformal VERSION\.txt:\s+42\.24\.0\nvisible frontend version:\s+v42\.24\.0\ninternal UI build metadata:\s+42\.25\.0-dev\napp\.js cache:\s+42\.25\.\d+\nmain\.mjs cache:\s+42\.25\.\d+',
    f'latest full code acceptance: {ACCEPT}\nFrontend Runtime run:        {FRONTEND_RUN}\nformal VERSION.txt:          42.24.0\nvisible frontend version:    v42.24.0\ninternal UI build metadata:  42.25.0-dev\napp.js cache:                {APP_CACHE}\nmain.mjs cache:              {MAIN_CACHE}',
    'CODEX current state',
)
text = sub_once(
    text,
    r'Run `\d+` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after R20l permanentization and migration-artifact cleanup\. Browser navigation runs \*\*33 tests and passed 33/33\*\*\. Permanent Action Fencing workflow `\d+` is green;',
    f'Run `{FRONTEND_RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after R20m shadowed-owner retirement and migration-artifact cleanup. Browser navigation runs **33 tests and passed 33/33**. Permanent Action Fencing workflow `{ACTION_RUN}` is green;',
    'CODEX acceptance sentence',
)
codex_section = f'''### R20m — shadowed v423 algorithm CRUD generation retirement CLOSED

Liveness/source-order audit found two generations sharing `openNewAlgorithm423` / `editAlgorithm423`. The early v423 generation owned `saveNewAlgorithm423` / `saveEditAlgorithm423` and broad `loadRelated()`, but later stable 414 assignments overwrite the entrypoints before any final algorithm UI action can invoke them. The existing CRUD Real Chrome contract passed **before** retirement, proving the stable 414 generation was already live.

R20m physically removed only the unreachable early create/edit generation. Final create/edit/delete continue to patch authoritative `state.algorithms` locally and remain broad-refresh free.

```text
baseline:                  {BASELINE}
baseline + migration run: {MIGRATION_RUN}
product:                   {PRODUCT}
cleanup / acceptance:      {ACCEPT}
Frontend Runtime:          {FRONTEND_RUN}
full Real Chrome:          33/33 PASS
Action Fencing:            {ACTION_RUN} PASS
formal VERSION.txt:        42.24.0 unchanged
app.js cache:              {APP_CACHE}
main.mjs cache:            {MAIN_CACHE}
```

Permanent source contract: `tests/frontend/shadowed-algorithm-crud-r20m.test.mjs`. Browser behavior remains covered by `tests/browser/algorithm-list-performance.spec.mjs`. One-shot R20m migration artifacts are physically deleted. **R20m CLOSED; global R20 zero-point remains IN PROGRESS.**

'''
marker = '### R20l — source-import terminal completion scoped refresh CLOSED\n'
if '### R20m — shadowed v423 algorithm CRUD generation retirement CLOSED' not in text:
    text = replace_once(text, marker, codex_section + marker, 'CODEX R20m section')
write(path, text)

# TECH_DEBT_CLOSURE_V42_25.md
path = 'docs/TECH_DEBT_CLOSURE_V42_25.md'
text = read(path)
text = sub_once(text, r'\*\*最近完整代码验收点：`[0-9a-f]+`\*\*', f'**最近完整代码验收点：`{ACCEPT}`**', 'TECH acceptance')
text = sub_once(
    text,
    r'\*\*Frontend Runtime Stabilization：run `\d+`，frontend \+ Real Chrome 全绿，Real Chrome 33/33 passed；Navigation Action Fencing 永久 run `\d+` 全绿；Resource Discovery SQLite 永久跨平台 run `34700900542` Ubuntu \+ Windows 全绿。\*\*',
    f'**Frontend Runtime Stabilization：run `{FRONTEND_RUN}`，frontend + Real Chrome 全绿，Real Chrome 33/33 passed；Navigation Action Fencing 永久 run `{ACTION_RUN}` 全绿；Resource Discovery SQLite 永久跨平台 run `34700900542` Ubuntu + Windows 全绿。**',
    'TECH run line',
)
retired_marker = 'v42.2 `renderAlgorithms422/openNewAlgorithm422/saveNewAlgorithm422` shadowed algorithm page generation\n'
retired_line = 'v423 shadowed `openNewAlgorithm423(async)/saveNewAlgorithm423/editAlgorithm423(old modal)/saveEditAlgorithm423` create/edit generation\n'
if retired_line not in text:
    text = replace_once(text, retired_marker, retired_marker + retired_line, 'TECH retired R20m surface')
row_marker = '| source-import terminal completion broad refresh | labels + current paged materials only | **CLOSED (R20l)** |\n'
row = '| shadowed v423 algorithm create/edit broad-refresh generation | stable 414 authoritative local-state CRUD only | **CLOSED (R20m)** |\n'
if row not in text:
    text = replace_once(text, row_marker, row_marker + row, 'TECH R20m row')
tech_section = f'''## 2.0c R20m — shadowed v423 algorithm CRUD retirement

Source-order audit proved the early v423 create/edit generation is shadowed by the later stable 414 assignments. Its only `saveNewAlgorithm423` / `saveEditAlgorithm423` callsites lived inside those overwritten modal entrypoints. The existing algorithm CRUD Real Chrome test passed before deletion, proving current behavior did not depend on the old broad-refresh generation.

R20m physically removed that unreachable block and kept the stable 414/423/429 owners. No new runtime or refresh path was introduced.

```text
baseline:                  {BASELINE}
baseline + migration run: {MIGRATION_RUN}
product:                   {PRODUCT}
cleanup / acceptance:      {ACCEPT}
Frontend Runtime:          {FRONTEND_RUN}
full Real Chrome:          33/33 PASS
Action Fencing:            {ACTION_RUN} PASS
formal VERSION.txt:        42.24.0 unchanged
app.js cache:              {APP_CACHE}
main.mjs cache:            {MAIN_CACHE}
```

Permanent source contract: `tests/frontend/shadowed-algorithm-crud-r20m.test.mjs`; permanent behavior contract remains `tests/browser/algorithm-list-performance.spec.mjs`. One-shot migration helper/workflow are physically deleted. **R20m CLOSED; global R20 reload/request zero-point remains IN PROGRESS.**

'''
marker = '## 2.0b R20l — source-import terminal scoped refresh\n'
if '## 2.0c R20m — shadowed v423 algorithm CRUD retirement' not in text:
    text = replace_once(text, marker, tech_section + marker, 'TECH R20m section')
write(path, text)

# FRONTEND_OWNER_MAP_V42_25.md
path = 'docs/FRONTEND_OWNER_MAP_V42_25.md'
text = read(path)
text = sub_once(text, r'> Latest fully accepted code point: `[0-9a-f]+` / run `\d+`', f'> Latest fully accepted code point: `{ACCEPT}` / run `{FRONTEND_RUN}`', 'OWNER acceptance')
row_marker = '| R20l | live source-import terminal broad `loadRelated()` → labels + current paged materials only | `f8356bcf5e...` / `34723808299` (33/33) |\n'
row = f'| R20m | shadowed v423 algorithm create/edit generation physically retired; stable 414 CRUD remains final | `{ACCEPT[:10]}...` / `{FRONTEND_RUN}` (33/33) |\n'
if row not in text:
    text = replace_once(text, row_marker, row_marker + row, 'OWNER R20m row')
paragraph = f'''R20m baseline `{BASELINE}` / migration run `{MIGRATION_RUN}`; product `{PRODUCT}`; cleanup/final acceptance `{ACCEPT}` / Frontend Runtime `{FRONTEND_RUN}`; frontend PASS; Real Chrome **33/33 passed**; Action Fencing `{ACTION_RUN}` PASS. The early v423 algorithm create/edit generation was proven shadowed and physically deleted; stable 414 authoritative local-state CRUD remains the only final create/edit owner. Permanent source contract: `tests/frontend/shadowed-algorithm-crud-r20m.test.mjs`; browser behavior remains covered by `tests/browser/algorithm-list-performance.spec.mjs`. One-shot R20m migration artifacts are physically deleted.

'''
marker = 'R20l product:'
if paragraph.strip() not in text:
    text = replace_once(text, marker, paragraph + marker, 'OWNER R20m paragraph')
write(path, text)

# frontend-legacy-audit.md
path = 'docs/frontend-legacy-audit.md'
text = read(path)
text = sub_once(
    text,
    r'commit:\s+[0-9a-f]+\nrun:\s+\d+\nfrontend:\s+PASS\nReal Chrome:\s+PASS \(33/33\)',
    f'commit:       {ACCEPT}\nrun:          {FRONTEND_RUN}\nfrontend:     PASS\nReal Chrome:  PASS (33/33)',
    'AUDIT acceptance',
)
text = sub_once(text, r'app\.js\s+42\.25\.\d+', f'app.js                    {APP_CACHE}', 'AUDIT app cache')
retired_marker = 'v42.2 renderAlgorithms422/openNewAlgorithm422/saveNewAlgorithm422 generation\n'
retired_line = 'shadowed v423 openNewAlgorithm423(async)/saveNewAlgorithm423/editAlgorithm423(old modal)/saveEditAlgorithm423 generation\n'
if retired_line not in text:
    text = replace_once(text, retired_marker, retired_marker + retired_line, 'AUDIT R20m retired surface')
paragraph = f'''R20m physically retired the shadowed early v423 algorithm create/edit generation after source-order proof and a pre-retirement Real Chrome pass showed final CRUD already resolves to the later stable 414 owners. Baseline `{BASELINE}`, migration run `{MIGRATION_RUN}`, product `{PRODUCT}`, cleanup/final acceptance `{ACCEPT}` / run `{FRONTEND_RUN}`, Real Chrome **33/33**, Action Fencing `{ACTION_RUN}` PASS. `tests/frontend/shadowed-algorithm-crud-r20m.test.mjs` permanently locks owner cardinality/absence; existing `algorithm-list-performance.spec.mjs` locks live CRUD behavior. Global R20 zero-point remains open.

'''
marker = 'R20l kept the live `refreshSourceImportTasksV36` owner'
if paragraph.strip() not in text:
    text = replace_once(text, marker, paragraph + marker, 'AUDIT R20m paragraph')
write(path, text)

print('R20m handoff synchronized')
