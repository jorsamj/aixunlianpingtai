from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    'state': ROOT / 'docs/CODEX_CURRENT_STATE.md',
    'audit': ROOT / 'docs/frontend-legacy-audit.md',
    'map': ROOT / 'docs/FRONTEND_OWNER_MAP_V42_25.md',
    'debt': ROOT / 'docs/TECH_DEBT_CLOSURE_V42_25.md',
}

ACCEPT = 'f5b8ff8789de0f51d2a03bcabe126191005ba24c'
RUN = '34669152742'


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected 1 match, found {count}')
    return text.replace(old, new, 1)


def insert_after(text, anchor, addition, label):
    if addition.strip() in text:
        return text
    if anchor not in text:
        raise SystemExit(f'{label}: anchor missing')
    return text.replace(anchor, anchor + addition, 1)

# CODEX current state
p = FILES['state']; t = p.read_text(encoding='utf-8')
t = replace_once(t, 'latest full code acceptance: 540c0944f45030ea198af2be153c1505f71e62f0', f'latest full code acceptance: {ACCEPT}', 'state accept')
t = replace_once(t, 'Frontend Runtime run:        34668702371', f'Frontend Runtime run:        {RUN}', 'state run')
t = replace_once(t, 'app.js cache:                42.25.73', 'app.js cache:                42.25.74', 'state app cache')
t = replace_once(t, 'main.mjs cache:              42.25.78', 'main.mjs cache:              42.25.79', 'state main cache')
t = replace_once(t, 'Run `34668702371` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions.', f'Run `{RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions.', 'state accepted run sentence')
t = replace_once(t, 'cleanup+observer lifecycle audit\n→ app.js/global reload/request debt', 'modal observer + bounded cleanup timer lifecycle audit\n→ app.js/global reload/request debt', 'state priority')
t = replace_once(t, 'transport.mode-only material summary page guard / off-page summary request leakage\n```', 'transport.mode-only material summary page guard / off-page summary request leakage\nlegacy baseRender + RAF page normalization wrapper\n#view post-render MutationObserver\n```', 'state retired list')
r17 = f'''\n\n### R17 — final page normalization ownership\n\nR17 removed the remaining page-side triple ownership (`baseRender` wrapper + page RAF cleanup + `#view` MutationObserver). Source-order proof showed the storage wrapper is the final `render` assignment in `static/app.js`, so page normalization now runs exactly once after the final render path through the named `PostRenderNormalizationRuntime`. Modal normalization remains independently owned by the `#modalBody` observer and was intentionally not changed in this batch.\n\n```text\nproduct:         4fc5d90a15ef2fc2dc22aa00f39967deba6f53f8\nvalidation:      c3301d065fa820539873a4fa2f739992ef63f3d2\nguard alignment: {ACCEPT}\nfull run:        {RUN}\nfrontend:        PASS (179/179)\nReal Chrome:     19/19 PASS\n```\n\nThe first full validation correctly exposed one stale structure-bound storage-owner unit assertion; the product behavior was not reverted. The guard was tightened to require one storage route owner plus one final page-normalization call, then the full suite passed.\n'''
t = insert_after(t, 'Permanent proof: `tests/frontend/lifecycle-event-ownership.test.mjs` plus the browser contract `ZIP import completion surfaces review action and auto-opens review`.', r17, 'state R17 insert')
t = replace_once(t, 'finalRender\n  素材存储配置 final route owner', 'finalRender\n  素材存储配置 final route owner\n  final page normalization dispatch', 'state finalRender owner')
t = replace_once(t, 'cleanup(root)\n  page/modal post-render normalization\n  table wrapping + file-input beautification', 'PostRenderNormalizationRuntime.apply / cleanup(root)\n  final-render page normalization\n  modal observer normalization target\n  table wrapping + file-input beautification', 'state cleanup owner')
t = replace_once(t, 'post-render cleanup wrapper + view/modalBody MutationObserver lifecycle\nolder base/global render generations still reachable through delegates', 'modalBody MutationObserver lifecycle + bounded 100ms cleanup timer\nolder base/global render generations still reachable through delegates', 'state remaining audit')
t = replace_once(t, '- `view` and `modalBody` observer wiring remains until lifecycle ownership is explicitly migrated.', '- `#view` observer remains retired; page normalization must stay final-render-owned;\n- `#modalBody` observer remains until its modal lifecycle ownership is explicitly migrated.', 'state observer contract')
t = replace_once(t, '1. post-render cleanup wrapper + view/modalBody MutationObserver lifecycle audit', '1. modalBody MutationObserver + bounded 100ms cleanup timer lifecycle audit', 'state work order')
p.write_text(t, encoding='utf-8')

# Legacy audit
p = FILES['audit']; t = p.read_text(encoding='utf-8')
t = replace_once(t, 'commit:       540c0944f45030ea198af2be153c1505f71e62f0', f'commit:       {ACCEPT}', 'audit accept')
t = replace_once(t, 'run:          34668702371', f'run:          {RUN}', 'audit run')
t = replace_once(t, 'app.js                    42.25.73', 'app.js                    42.25.74', 'audit app cache')
t = replace_once(t, 'main.mjs                  42.25.78', 'main.mjs                  42.25.79', 'audit main cache')
t = replace_once(t, 'transport.mode-only material summary page guard / off-page summary request leakage\n```', 'transport.mode-only material summary page guard / off-page summary request leakage\nlegacy baseRender + RAF page normalization wrapper\n#view post-render MutationObserver\n```', 'audit retired list')
t = insert_after(t, 'Permanent proof: `tests/frontend/lifecycle-event-ownership.test.mjs` plus the browser contract `ZIP import completion surfaces review action and auto-opens review`.', r17, 'audit R17 insert')
t = replace_once(t, 'finalRender\n  素材存储配置 final route owner', 'finalRender\n  素材存储配置 final route owner + final page normalization dispatch', 'audit finalRender')
t = replace_once(t, 'cleanup(root)\n  post-render DOM normalization\n  table wrapping + page/modal file-input beautification', 'PostRenderNormalizationRuntime.apply / cleanup(root)\n  final-render page normalization\n  modal observer normalization target\n  table wrapping + page/modal file-input beautification', 'audit cleanup')
t = replace_once(t, 'post-render cleanup wrapper + view/modalBody MutationObserver lifecycle\nolder base/global render generations reached through delegates', 'modalBody MutationObserver lifecycle + bounded 100ms cleanup timer\nolder base/global render generations reached through delegates', 'audit remaining')
t = replace_once(t, 'view + modalBody observer wiring remains until explicit lifecycle migration', '#view observer remains retired; modalBody observer remains until explicit modal lifecycle migration', 'audit observer contract')
t = replace_once(t, 'Current accepted Real Chrome suite: **19/19** in run `34668702371`.', f'Current accepted Real Chrome suite: **19/19** in run `{RUN}`.', 'audit current run')
t = replace_once(t, 'cleanup+observer lifecycle audit\nloadAll / loadRelated / loadCore412 ownership', 'modal observer + bounded cleanup timer lifecycle audit\nloadAll / loadRelated / loadCore412 ownership', 'audit targets')
t = replace_once(t, '1. post-render cleanup wrapper + view/modalBody MutationObserver lifecycle audit', '1. modalBody MutationObserver + bounded 100ms cleanup timer lifecycle audit', 'audit work order')
p.write_text(t, encoding='utf-8')

# Owner map
p = FILES['map']; t = p.read_text(encoding='utf-8')
t = replace_once(t, 'Latest fully accepted code point: `540c0944f45030ea198af2be153c1505f71e62f0` / run `34668702371`', f'Latest fully accepted code point: `{ACCEPT}` / run `{RUN}`', 'map accept')
t = replace_once(t, '| R16 | body-wide ZIP review observer + off-page material summary leakage | `540c0944...` / `34668702371` |', '| R16 | body-wide ZIP review observer + off-page material summary leakage | `540c0944...` / `34668702371` |\n| R17 | page baseRender/RAF wrapper + `#view` normalization observer | `f5b8ff87...` / `34669152742` |', 'map table R17')
t = insert_after(t, 'R16 baseline: `540de6aef4ddbf82a6cf36994a31a73937abca73` / run `34668429941` exposed ZIP persisted-review loss and the remaining training-page `/materials` race. R16 product: `12df27e2af9155e3a1b9f745e46605396e321815`; focused run `34668639496` passed ZIP completion and training isolation 5/5; validation `540c0944f45030ea198af2be153c1505f71e62f0` / run `34668702371`; Real Chrome **19/19 passed**. All R16 one-shot migration artifacts were removed.', f'  \nR17 product: `4fc5d90a15ef2fc2dc22aa00f39967deba6f53f8`; validation `c3301d065fa820539873a4fa2f739992ef63f3d2`; guard alignment `{ACCEPT}` / run `{RUN}`; frontend **179/179 passed**, Real Chrome **19/19 passed**. The early page normalization wrapper, RAF cleanup and `#view` observer are permanently retired; `#modalBody` remains independent.', 'map R17 note')
t = replace_once(t, '| Storage configuration route | `finalRender` | `renderStorageSources61()` | dedicated Chrome contract |', '| Storage configuration route | `finalRender` | `renderStorageSources61()` + final page normalization dispatch | dedicated Chrome contract |', 'map storage')
t = replace_once(t, '| Page post-render normalization | `cleanup(root)` + view observer | DOM cleanup + table wrapping + page file-input beautification | unit + Chrome |', '| Page post-render normalization | `finalRender` → `PostRenderNormalizationRuntime.apply` → `cleanup(root)` | exactly one final-render cleanup; no view observer/RAF wrapper | unit + Chrome |', 'map page normalization row')
t = replace_once(t, 'render chain\n→ cleanup wrapper\n→ cleanup(#view)', 'final render chain\n→ PostRenderNormalizationRuntime.apply(#view)\n→ cleanup(#view)', 'map R10 final path')
t = replace_once(t, 'beautifyFileInputs426 implementation/export\ncleanup(root)\nview + modalBody observer wiring', 'beautifyFileInputs426 implementation/export\ncleanup(root)\nPostRenderNormalizationRuntime final-render page dispatch\nmodalBody observer wiring only', 'map retained')
t = replace_once(t, 'finalRender       素材存储配置\ncleanup(root)     post-render normalization + table wrapping + page/modal file-input beautification', 'finalRender       素材存储配置 + final page normalization dispatch\nPostRenderNormalizationRuntime.apply / cleanup(root)\n                  page normalization + modal observer target + table/file-input cleanup', 'map live topology')
t = replace_once(t, 'transport.mode-only material summary page guard / off-page summary request leakage\n```', 'transport.mode-only material summary page guard / off-page summary request leakage\nlegacy baseRender + RAF page normalization wrapper\n#view post-render MutationObserver\n```', 'map retired')
t = replace_once(t, 'post-render cleanup wrapper + view/modalBody MutationObserver lifecycle\nolder base/global render generations still reachable through delegates', 'modalBody MutationObserver lifecycle + bounded 100ms cleanup timer\nolder base/global render generations still reachable through delegates', 'map remaining')
t = replace_once(t, 'Current accepted Real Chrome suite: **19/19** in run `34668702371`.', f'Current accepted Real Chrome suite: **19/19** in run `{RUN}`.', 'map run')
p.write_text(t, encoding='utf-8')

# Debt ledger
p = FILES['debt']; t = p.read_text(encoding='utf-8')
t = replace_once(t, '**最近完整代码验收点：`540c0944f45030ea198af2be153c1505f71e62f0`**', f'**最近完整代码验收点：`{ACCEPT}`**', 'debt accept')
t = replace_once(t, '**Frontend Runtime Stabilization：run `34668702371`，frontend + Real Chrome 全绿，Real Chrome 19/19 passed。**', f'**Frontend Runtime Stabilization：run `{RUN}`，frontend 179/179 + Real Chrome 19/19 全绿。**', 'debt run')
t = replace_once(t, 'transport.mode-only material summary page guard / off-page summary request leakage\n```', 'transport.mode-only material summary page guard / off-page summary request leakage\nlegacy baseRender + RAF page normalization wrapper\n#view post-render MutationObserver\n```', 'debt retired')
t = replace_once(t, '| off-page material summary timer requests | page-scoped `refreshSummary61` | **CLOSED (R16)** |', '| off-page material summary timer requests | page-scoped `refreshSummary61` | **CLOSED (R16)** |\n| page normalization baseRender/RAF/view observer | final `PostRenderNormalizationRuntime.apply` | **CLOSED (R17)** |', 'debt status R17')
t = replace_once(t, 'page render\n→ later post-render cleanup wrapper\n→ cleanup(#view)', 'page render\n→ final render owner\n→ PostRenderNormalizationRuntime.apply(#view)\n→ cleanup(#view)', 'debt file input page path')
t = replace_once(t, 'finalRender       → 素材存储配置\ncleanup(root)     → post-render normalization + table wrapping + page/modal file-input beautification', 'finalRender       → 素材存储配置 + final page normalization dispatch\nPostRenderNormalizationRuntime.apply / cleanup(root)\n                  → page normalization + modal observer target + table/file-input cleanup', 'debt live owners')
t = replace_once(t, 'post-render cleanup wrapper + view/modalBody MutationObserver lifecycle\nolder base/global render generations still reachable through delegates', 'modalBody MutationObserver lifecycle + bounded 100ms cleanup timer\nolder base/global render generations still reachable through delegates', 'debt candidates')
t = replace_once(t, 'app.js cache                     42.25.73', 'app.js cache                     42.25.74', 'debt app cache')
t = replace_once(t, 'main.mjs cache                   42.25.78', 'main.mjs cache                   42.25.79', 'debt main cache')
t = replace_once(t, '- `view` 与 `modalBody` 的 cleanup observer contract 在生命周期重构完成前必须保持；', '- `#view` cleanup observer 已在 R17 退休，不得回归；页面 cleanup 必须保持 final-render-owned；\n- `modalBody` cleanup observer 暂时保留，待独立 modal lifecycle 迁移；', 'debt observer contract')
t = replace_once(t, '当前验收：run `34667776611`，**18/18 passed**。', f'当前验收：run `{RUN}`，frontend **179/179**，Real Chrome **19/19 passed**。', 'debt acceptance')
t = insert_after(t, 'Permanent proof: `tests/frontend/lifecycle-event-ownership.test.mjs` plus the browser contract `ZIP import completion surfaces review action and auto-opens review`.', r17, 'debt R17 insert')
p.write_text(t, encoding='utf-8')

if (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt changed unexpectedly')

for key, path in FILES.items():
    text = path.read_text(encoding='utf-8')
    if ACCEPT not in text or RUN not in text:
        raise SystemExit(f'{key}: acceptance point not synchronized')

print('R17 ledgers synchronized')
