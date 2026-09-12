from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'docs/CODEX_CURRENT_STATE.md'
AUDIT = ROOT / 'docs/frontend-legacy-audit.md'
MAP = ROOT / 'docs/FRONTEND_OWNER_MAP_V42_25.md'
DEBT = ROOT / 'docs/TECH_DEBT_CLOSURE_V42_25.md'

BASELINE = '6f5fac4313d23083c6bbe9e2a3b8a5284cd49583'
PRODUCT = '1bb210fbb10a7bee9f5b875d0dd6016187c1ef72'
ACCEPT = 'f60d00096a0929a63d0370494ef1f1d489f54ca3'
RUN = '34670989473'


def one(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f'{label}: expected 1, got {n}')
    return text.replace(old, new, 1)


def add_after(text, anchor, addition, label):
    if '### R19 — explicit modal content ownership' in text:
        return text
    if anchor not in text:
        raise SystemExit(f'{label}: anchor missing')
    return text.replace(anchor, anchor + addition, 1)

r19 = f'''\n\n### R19 — explicit modal content ownership\n\nR19 retired the last active DOM normalization observer. A permanent Real Chrome baseline first locked a real post-open base-modal refresh path (后台导入任务 → 刷新). Modal content writes now go through `ModalContentRuntime.replace(root, html)`. When `root.id === 'modalBody'`, that owner synchronously invokes `PostRenderNormalizationRuntime.apply(root)`; preview/review rewrites also route through the same content replacement owner. `static/app.js` now contains zero active `MutationObserver` constructions.\n\n```text\nbaseline:   {BASELINE}\nproduct:    {PRODUCT}\nvalidation: {ACCEPT}\nrun:        {RUN}\nfrontend:   PASS\nReal Chrome: 20/20 PASS\n```\n'''

# CODEX_CURRENT_STATE
p = STATE; t = p.read_text(encoding='utf-8')
t = one(t, 'latest full code acceptance: 954e9dba9c891ecd5c7f21144cf00d8664c11620', f'latest full code acceptance: {ACCEPT}', 'state accept')
t = one(t, 'Frontend Runtime run:        34670319479', f'Frontend Runtime run:        {RUN}', 'state run')
t = one(t, 'app.js cache:                42.25.75', 'app.js cache:                42.25.76', 'state app cache')
t = one(t, 'main.mjs cache:              42.25.80', 'main.mjs cache:              42.25.81', 'state main cache')
t = one(t, 'Run `34670319479` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **19 tests and passed 19/19**.', f'Run `{RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **20 tests and passed 20/20**.', 'state acceptance sentence')
t = one(t, 'modal observer lifecycle audit\n→ app.js/global reload/request debt', 'app.js/global reload/request debt\n→ proven dead app.js/runtime shell cleanup', 'state priority')
t = one(t, '#view post-render MutationObserver\n```', '#view post-render MutationObserver\n#modalBody normalization MutationObserver\n```', 'state retired modal observer')
t = add_after(t, 'Real Chrome: 19/19 PASS\n```\n', r19, 'state R19')
t = one(t, 'PostRenderNormalizationRuntime.apply / cleanup(root)\n  final-render page normalization\n  modal observer normalization target\n  table wrapping + file-input beautification\n\nbase modal()\n  first editable modal field autofocus', "PostRenderNormalizationRuntime.apply / cleanup(root)\n  final-render page normalization\n  table wrapping + file-input beautification\n\nModalContentRuntime.replace(root, html)\n  explicit modal/preview/review content replacement\n  applies PostRenderNormalizationRuntime synchronously for #modalBody\n\nbase modal()\n  first editable modal field autofocus", 'state live modal owner')
t = one(t, 'Still requiring independent liveness analysis:\n\n```text\nmodalBody MutationObserver lifecycle\nolder base/global render generations still reachable through delegates\n```', 'Still requiring independent liveness analysis:\n\n```text\nolder base/global render generations still reachable through delegates\nglobal reload / loadAll / loadRelated request ownership\n```', 'state remaining')
t = one(t, 'lifecycle-event-ownership.test.mjs\nnavigation-stability.test.mjs', 'lifecycle-event-ownership.test.mjs\nmodal-content-owner.test.mjs\nnavigation-stability.test.mjs', 'state permanent test')
t = one(t, '- `#view` observer remains retired; page normalization must stay final-render-owned;\n- `#modalBody` observer remains until its modal lifecycle ownership is explicitly migrated.', '- `#view` observer remains retired; page normalization must stay final-render-owned;\n- `#modalBody` normalization observer is retired and must not return; modal content replacement must stay `ModalContentRuntime`-owned.', 'state file contract')
t = one(t, 'Current accepted suite: **19/19**.', 'Current accepted suite: **20/20**; this includes `base modal post-open content refresh stays functional`.', 'state browser count')
t = one(t, '1. modalBody MutationObserver lifecycle audit\n2. proven dead app.js + global reload/request debt\n3. cache-busting unification\n4. zero-point MutationObserver/timer/fetch/render/setPage scan\n5. semantic naming + deterministic tests + dead-code cleanup\n6. technical-debt zero-point scan\n7. resume A800 RC', '1. global reload / loadAll / loadRelated duplicate-request ownership audit\n2. proven dead app.js/runtime-shell cleanup\n3. cache-busting unification\n4. zero-point MutationObserver/timer/fetch/render/setPage scan\n5. semantic naming + deterministic tests + dead-code cleanup\n6. technical-debt zero-point scan\n7. resume A800 RC', 'state work order')
p.write_text(t, encoding='utf-8')

# frontend-legacy-audit
p = AUDIT; t = p.read_text(encoding='utf-8')
t = one(t, 'commit:       954e9dba9c891ecd5c7f21144cf00d8664c11620', f'commit:       {ACCEPT}', 'audit accept')
t = one(t, 'run:          34670319479', f'run:          {RUN}', 'audit run')
t = one(t, 'Real Chrome:  PASS (19/19)', 'Real Chrome:  PASS (20/20)', 'audit chrome')
t = one(t, 'app.js                    42.25.75', 'app.js                    42.25.76', 'audit app cache')
t = one(t, 'main.mjs                  42.25.80', 'main.mjs                  42.25.81', 'audit main cache')
t = one(t, '#view post-render MutationObserver\n```', '#view post-render MutationObserver\n#modalBody normalization MutationObserver\n```', 'audit retired observer')
t = add_after(t, 'Real Chrome: 19/19 PASS\n```\n', r19, 'audit R19')
t = one(t, 'PostRenderNormalizationRuntime.apply / cleanup(root)\n  final-render page normalization\n  modal observer normalization target\n  table wrapping + page/modal file-input beautification\n\nbase modal()\n  modal first-editable-field autofocus', "PostRenderNormalizationRuntime.apply / cleanup(root)\n  final-render page normalization\n  table wrapping + page/modal file-input beautification\n\nModalContentRuntime.replace(root, html)\n  explicit base-modal and modal-like content replacement\n  applies normalization synchronously for #modalBody\n\nbase modal()\n  modal first-editable-field autofocus", 'audit live modal owner')
t = one(t, 'Still under audit:\n\n```text\nmodalBody MutationObserver lifecycle\nolder base/global render generations reached through delegates\n```', 'Still under audit:\n\n```text\nolder base/global render generations reached through delegates\nglobal reload / loadAll / loadRelated request ownership\n```', 'audit remaining')
t = one(t, 'lifecycle-event-ownership.test.mjs\nauto-label-poll-runtime.test.mjs', 'lifecycle-event-ownership.test.mjs\nmodal-content-owner.test.mjs\nauto-label-poll-runtime.test.mjs', 'audit permanent test')
t = one(t, '#view observer remains retired; modalBody observer remains until explicit modal lifecycle migration', '#view observer remains retired; #modalBody normalization observer is retired; ModalContentRuntime owns modal content replacement', 'audit modal contract')
t = one(t, 'Current accepted Real Chrome suite: **19/19** in run `34670319479`.', f'Current accepted Real Chrome suite: **20/20** in run `{RUN}`.', 'audit accepted suite')
t = one(t, 'modal observer lifecycle audit\nloadAll / loadRelated / loadCore412 ownership\nproven dead app.js code\nglobal reload / duplicate requests', 'loadAll / loadRelated / loadCore412 ownership\nglobal reload / duplicate requests\nproven dead app.js/runtime shell', 'audit targets')
p.write_text(t, encoding='utf-8')

# OWNER MAP
p = MAP; t = p.read_text(encoding='utf-8')
t = one(t, 'Latest fully accepted code point: `954e9dba9c891ecd5c7f21144cf00d8664c11620` / run `34670319479`', f'Latest fully accepted code point: `{ACCEPT}` / run `{RUN}`', 'map accept')
t = one(t, '> Real Chrome: 19/19 passed', '> Real Chrome: 20/20 passed', 'map chrome header')
t = one(t, '| R18 | bounded 100ms `renderTop/cleanup` startup wakeup | `954e9dba...` / `34670319479` |', '| R18 | bounded 100ms `renderTop/cleanup` startup wakeup | `954e9dba...` / `34670319479` |\n| R19 | `#modalBody` normalization observer → explicit `ModalContentRuntime` | `f60d0009...` / `34670989473` |', 'map R19 row')
t = add_after(t, 'Real Chrome: 19/19 PASS\n```\n', r19, 'map R19')
t = one(t, '| Modal post-render normalization | `cleanup(root)` + modalBody observer | table wrapping + dynamic modal file-input beautification | unit + Chrome |', '| Modal content + normalization | `ModalContentRuntime.replace` → `PostRenderNormalizationRuntime.apply` for `#modalBody` | explicit replacement, table wrapping + dynamic modal file-input beautification | unit + Chrome |', 'map modal row')
t = one(t, 'Final modal ownership:\n\n```text\nmodalBody DOM mutation\n→ MutationObserver\n→ cleanup(addedNode)\n→ beautifyFileInputs426(root)\n```', 'R11 interim modal ownership (superseded by R19):\n\n```text\nmodalBody DOM mutation\n→ MutationObserver\n→ cleanup(addedNode)\n→ beautifyFileInputs426(root)\n```\n\nR19 final ownership is explicit `ModalContentRuntime.replace` with synchronous normalization for `#modalBody`.', 'map R11 historical')
t = one(t, 'modalBody observer wiring only\n```\n\nThe observer lifecycle itself is still a later audit target; current behavior is locked by permanent unit + Chrome contracts.', 'ModalContentRuntime explicit replacement owner\n```\n\nThe observer lifecycle was closed in R19; current behavior is locked by permanent unit + Chrome contracts.', 'map retained modal')
t = one(t, 'PostRenderNormalizationRuntime.apply / cleanup(root)\n                  page normalization + modal observer target + table/file-input cleanup\nbase modal()       first editable modal field autofocus', 'PostRenderNormalizationRuntime.apply / cleanup(root)\n                  page normalization + table/file-input cleanup\nModalContentRuntime.replace(root, html)\n                  explicit modal/preview/review replacement + #modalBody normalization\nbase modal()       first editable modal field autofocus', 'map live topology')
t = one(t, '#view post-render MutationObserver\nbounded 100ms renderTop/cleanup startup timer', '#view post-render MutationObserver\n#modalBody normalization MutationObserver\nbounded 100ms renderTop/cleanup startup timer', 'map retired observer')
t = one(t, 'Independent proof is still required for:\n\n```text\nmodalBody MutationObserver lifecycle\nolder base/global render generations still reachable through delegates\n```', 'Independent proof is still required for:\n\n```text\nolder base/global render generations still reachable through delegates\nglobal reload / loadAll / loadRelated request ownership\n```', 'map remaining')
t = one(t, 'lifecycle-event-ownership.test.mjs\nnavigation-stability.test.mjs', 'lifecycle-event-ownership.test.mjs\nmodal-content-owner.test.mjs\nnavigation-stability.test.mjs', 'map permanent test')
t = one(t, 'modal table wrapping and first-field focus survive normalization ownership\n```', 'modal table wrapping and first-field focus survive normalization ownership\nbase modal post-open content refresh stays functional\n```', 'map browser contract')
t = one(t, 'Current accepted Real Chrome suite: **19/19** in run `34670319479`.', f'Current accepted Real Chrome suite: **20/20** in run `{RUN}`.', 'map accepted suite')
p.write_text(t, encoding='utf-8')

# TECH DEBT LEDGER
p = DEBT; t = p.read_text(encoding='utf-8')
t = one(t, '**最近完整代码验收点：`954e9dba9c891ecd5c7f21144cf00d8664c11620`**', f'**最近完整代码验收点：`{ACCEPT}`**', 'debt accept')
t = one(t, '**Frontend Runtime Stabilization：run `34670319479`，frontend + Real Chrome 全绿，Real Chrome 19/19 passed。**', f'**Frontend Runtime Stabilization：run `{RUN}`，frontend + Real Chrome 全绿，Real Chrome 20/20 passed。**', 'debt run')
t = one(t, '#view post-render MutationObserver\n```', '#view post-render MutationObserver\n#modalBody normalization MutationObserver\n```', 'debt retired observer')
t = one(t, '| bounded 100ms startup cleanup timer | final `__clInit → render → PostRenderNormalizationRuntime` | **CLOSED (R18)** |', '| bounded 100ms startup cleanup timer | final `__clInit → render → PostRenderNormalizationRuntime` | **CLOSED (R18)** |\n| `#modalBody` normalization observer | `ModalContentRuntime.replace` + synchronous `PostRenderNormalizationRuntime` | **CLOSED (R19)** |', 'debt status row')
t = one(t, 'modal body mutation\n→ modalBody MutationObserver\n→ cleanup(addedNode)\n   → window.beautifyFileInputs426?.(root)', "modal content write\n→ ModalContentRuntime.replace(root, html)\n→ if root.id === 'modalBody': PostRenderNormalizationRuntime.apply(root)\n→ cleanup(root)\n   → window.beautifyFileInputs426?.(root)", 'debt modal path')
t = one(t, 'PostRenderNormalizationRuntime.apply / cleanup(root)\n                  → page normalization + modal observer target + table/file-input cleanup\nbase modal()       → modal first-editable-field autofocus', 'PostRenderNormalizationRuntime.apply / cleanup(root)\n                  → page normalization + table/file-input cleanup\nModalContentRuntime.replace(root, html)\n                  → explicit modal/preview/review content + #modalBody normalization\nbase modal()       → modal first-editable-field autofocus', 'debt live modal')
t = one(t, 'Remaining audit candidates:\n\n```text\nmodalBody MutationObserver lifecycle\nolder base/global render generations still reachable through delegates\n```', 'Remaining audit candidates:\n\n```text\nolder base/global render generations still reachable through delegates\nglobal reload / loadAll / loadRelated request ownership\n```', 'debt remaining')
t = one(t, 'app.js cache                     42.25.75', 'app.js cache                     42.25.76', 'debt app cache')
t = one(t, 'main.mjs cache                   42.25.80', 'main.mjs cache                   42.25.81', 'debt main cache')
t = one(t, '- `modalBody` cleanup observer 暂时保留，待独立 modal lifecycle 迁移；', '- `#modalBody` normalization observer 已在 R19 退休，不得回归；modal replacement 必须由 `ModalContentRuntime` 显式拥有；', 'debt permanent modal contract')
t = one(t, '当前验收：run `34669152742`，frontend **179/179**，Real Chrome **19/19 passed**。', f'当前验收：run `{RUN}`，frontend PASS，Real Chrome **20/20 passed**。', 'debt current acceptance')
t = add_after(t, 'Real Chrome: 19/19 PASS\n```\n', r19, 'debt R19')
t = one(t, '## 8. 下一批：remaining render/lifecycle owner audit\n\n优先独立审计：\n\n```text\ncleanup wrapper   post-render cleanup + view/modalBody MutationObserver lifecycle\nbody observer     ZIP import review MutationObserver\n```\n\n`oldRenderV39` 与 `render414Base` 已确认 live，不得因为版本号旧就直接删。', '## 8. 下一批：global reload / request ownership audit\n\nR17–R19 已把 active normalization observers 清零；下一批优先处理高频 mutation 后仍调用 `reload() → loadAll() → loadRelated()` 的全量刷新债务。目标是先量化调用面和网络请求，再按 mutation 语义迁移为 scoped refresh，不允许靠缓存或测试放宽掩盖重复请求。\n\n`oldRenderV39` 与 `render414Base` 已确认 live，不得因为版本号旧就直接删。', 'debt next batch')
t = one(t, 'A. post-render cleanup wrapper + view/modalBody MutationObserver lifecycle audit\nB. app.js dead code + global reload/request debt\nC. cache-busting unification\nD. MutationObserver/timer/fetch/render/setPage zero-point scan\nE. semantic naming + deterministic test cleanup\nF. technical-debt zero-point scan\nG. A800 RC', 'A. global reload / loadAll / loadRelated duplicate-request ownership audit\nB. proven dead app.js/runtime-shell cleanup\nC. cache-busting unification\nD. MutationObserver/timer/fetch/render/setPage zero-point scan\nE. semantic naming + deterministic test cleanup\nF. technical-debt zero-point scan\nG. A800 RC', 'debt order')
p.write_text(t, encoding='utf-8')

if (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt changed unexpectedly')
for p in (STATE, AUDIT, MAP, DEBT):
    text = p.read_text(encoding='utf-8')
    if ACCEPT not in text or RUN not in text or 'R19' not in text or '20/20' not in text:
        raise SystemExit(f'R19 ledger sync incomplete: {p}')
print('R19 ledgers synchronized')
