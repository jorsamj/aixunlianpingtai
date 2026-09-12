from pathlib import Path

FILES = {
    'tech': Path('docs/TECH_DEBT_CLOSURE_V42_25.md'),
    'codex': Path('docs/CODEX_CURRENT_STATE.md'),
    'legacy': Path('docs/frontend-legacy-audit.md'),
    'map': Path('docs/FRONTEND_OWNER_MAP_V42_25.md'),
}


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly one match, found {count}')
    return text.replace(old, new, 1)

# TECH ledger
p = FILES['tech']; t = p.read_text(encoding='utf-8')
t = replace_once(t, '**最近完整代码验收点：`9bad939a70bc85c75b0897ee7b4d5a21fb2ab9d1`**', '**最近完整代码验收点：`60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29`**', 'tech acceptance')
t = replace_once(t, '**Frontend Runtime Stabilization：run `34665890699`，frontend + Real Chrome 全绿，Real Chrome 17/17 passed。**', '**Frontend Runtime Stabilization：run `34666673017`，frontend + Real Chrome 全绿，Real Chrome 18/18 passed。**', 'tech run')
t = replace_once(t, 'modal426 requestAnimationFrame modal beautification callback\n', 'modal426 requestAnimationFrame modal beautification callback\nenhancePageV37 compatibility helper\nrequestAnimationFrame(enhancePageV37) page callback\nenhancePageV37 modal normalization callback\n', 'tech retired surface')
t = replace_once(t, '| `modal426` modal post-render wrapper | `cleanup(root)` + `modalBody` MutationObserver | **CLOSED (R11)** |\n| remaining historical render/post-render overrides | bounded semantic owners | **IN PROGRESS** |', '| `modal426` modal post-render wrapper | `cleanup(root)` + `modalBody` MutationObserver | **CLOSED (R11)** |\n| `enhancePageV37` post-render normalization helper | `cleanup(root)` table/panel normalization | **CLOSED (R12)** |\n| remaining historical render/post-render overrides | bounded semantic owners | **IN PROGRESS** |', 'tech debt row')
t = replace_once(t, 'cleanup(root)     → post-render normalization + page/modal file-input beautification\n', 'cleanup(root)     → post-render normalization + table wrapping + page/modal file-input beautification\nbaseRenderV37      → state.versionInfo formal-version compatibility write only\nbaseModalV37       → modal first-editable-field autofocus only\n', 'tech owners')
t = replace_once(t, 'baseRenderV37\nbaseModalV37\npost-render cleanup wrapper + view/modalBody MutationObserver lifecycle', 'baseRenderV37      state.versionInfo compatibility write only\nbaseModalV37       autofocus only\npost-render cleanup wrapper + view/modalBody MutationObserver lifecycle', 'tech candidates')
t = replace_once(t, 'app.js cache                     42.25.68\nmain.mjs cache                   42.25.72', 'app.js cache                     42.25.69\nmain.mjs cache                   42.25.73', 'tech cache')
t = replace_once(t, 'tests/frontend/file-input-beautification-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs', 'tests/frontend/file-input-beautification-owner.test.mjs\ntests/frontend/post-render-normalization-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs', 'tech tests')
t = replace_once(t, '当前验收：run `34665890699`，**17/17 passed**。', 'R12 永久要求：\n\n- `enhancePageV37` 不得回归；\n- `requestAnimationFrame(enhancePageV37)` 不得回归；\n- `cleanup(root)` 必须继续统一处理 `table.table → .table-wrap`；\n- `cleanup(root)` 必须继续移除“使用建议”等历史提示 panel；\n- `baseRenderV37` 当前只保留 `state.versionInfo` 写入，在独立证明前不得顺带删除；\n- `baseModalV37` 当前只保留首个可编辑字段 autofocus，在独立证明前不得顺带删除。\n\n当前验收：run `34666673017`，**18/18 passed**。', 'tech browser')
t = replace_once(t, 'R11 final validation\n  9bad939a70bc85c75b0897ee7b4d5a21fb2ab9d1 / 34665890699\n  frontend PASS / Real Chrome 17/17 PASS\n```', 'R11 final validation\n  9bad939a70bc85c75b0897ee7b4d5a21fb2ab9d1 / 34665890699\n  frontend PASS / Real Chrome 17/17 PASS\n\nR12 post-render normalization behavior baseline\n  6ae19dc79abbf690371a71162c97a2df6322518b\n  focused Chrome PASS\n\nR12 product\n  202a5a82b0cb4629423ee0c6812f649031234daa\n\nR12 final validation\n  60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29 / 34666673017\n  frontend PASS / Real Chrome 18/18 PASS\n```', 'tech history')
t = replace_once(t, 'baseRenderV37     requestAnimationFrame page enhancement + versionInfo write\nbaseModalV37      modal enhance/focus wrapper', 'baseRenderV37     state.versionInfo compatibility write only\nbaseModalV37      modal first-field autofocus only', 'tech next')
p.write_text(t, encoding='utf-8')

# CODEX
p = FILES['codex']; t = p.read_text(encoding='utf-8')
t = replace_once(t, 'latest full code acceptance: 9bad939a70bc85c75b0897ee7b4d5a21fb2ab9d1\nFrontend Runtime run:        34665890699', 'latest full code acceptance: 60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29\nFrontend Runtime run:        34666673017', 'codex acceptance')
t = replace_once(t, 'app.js cache:                42.25.68\nmain.mjs cache:              42.25.72', 'app.js cache:                42.25.69\nmain.mjs cache:              42.25.73', 'codex cache')
t = replace_once(t, 'Run `34665890699` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation now runs **17 tests and passed 17/17**.', 'Run `34666673017` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation now runs **18 tests and passed 18/18**.', 'codex run')
t = replace_once(t, 'modal426 modal file-input beautification wrapper\n```', 'modal426 modal file-input beautification wrapper\nenhancePageV37 post-render normalization helper\n```', 'codex retired')
insert = '''\n### R12 — enhancePageV37 normalization helper retirement\n\nAudit proved `enhancePageV37()` still owned table wrapping and “使用建议” cleanup, while `baseModalV37` also used it before autofocus. R12 locked modal table wrapping + autofocus in Real Chrome, then moved normalization into the later `cleanup(root)` owner.\n\n```text\nbefore:\n  baseRenderV37/baseModalV37\n  → requestAnimationFrame(enhancePageV37)\n  → table wrapping / 使用建议 cleanup\n\nafter:\n  cleanup(root)\n  → table.table → .table-wrap\n  → panel/history cleanup\n\nbaseRenderV37 → state.versionInfo write only\nbaseModalV37  → first editable field autofocus only\n```\n\nR12 acceptance:\n\n```text\nbehavior baseline: 6ae19dc79abbf690371a71162c97a2df6322518b\nproduct:           202a5a82b0cb4629423ee0c6812f649031234daa\nvalidation:        60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29\nrun:               34666673017\nfrontend:          PASS\nReal Chrome:       18/18 PASS\n```\n\nPermanent proof: `tests/frontend/post-render-normalization-owner.test.mjs` plus the browser contract `modal table wrapping and first-field focus survive normalization ownership`.\n'''
t = replace_once(t, '\n## 5. Current live render owners — do not delete without proof\n', insert + '\n## 5. Current live render owners — do not delete without proof\n', 'codex r12 section')
t = replace_once(t, 'cleanup(root)\n  page/modal post-render normalization\n  file-input beautification\n```', 'cleanup(root)\n  page/modal post-render normalization\n  table wrapping + file-input beautification\n\nbaseRenderV37\n  state.versionInfo formal-version compatibility write only\n\nbaseModalV37\n  first editable modal field autofocus only\n```', 'codex live')
t = replace_once(t, 'baseRenderV37\nbaseModalV37\npost-render cleanup wrapper + view/modalBody MutationObserver lifecycle', 'baseRenderV37 versionInfo compatibility ownership\nbaseModalV37 autofocus ownership\npost-render cleanup wrapper + view/modalBody MutationObserver lifecycle', 'codex audit')
t = replace_once(t, 'file-input-beautification-owner.test.mjs\nnavigation-stability.test.mjs', 'file-input-beautification-owner.test.mjs\npost-render-normalization-owner.test.mjs\nnavigation-stability.test.mjs', 'codex tests')
t = replace_once(t, 'Current accepted suite: **17/17**.', 'Current accepted suite: **18/18**.', 'codex chrome')
p.write_text(t, encoding='utf-8')

# Legacy audit
p = FILES['legacy']; t = p.read_text(encoding='utf-8')
t = replace_once(t, 'commit:       9bad939a70bc85c75b0897ee7b4d5a21fb2ab9d1\nrun:          34665890699\nfrontend:     PASS\nReal Chrome:  PASS (17/17)', 'commit:       60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29\nrun:          34666673017\nfrontend:     PASS\nReal Chrome:  PASS (18/18)', 'legacy acceptance')
t = replace_once(t, 'app.js                    42.25.68\nmain.mjs                  42.25.72', 'app.js                    42.25.69\nmain.mjs                  42.25.73', 'legacy cache')
t = replace_once(t, 'modal426 modal file-input beautification wrapper\n```', 'modal426 modal file-input beautification wrapper\nenhancePageV37 post-render normalization helper\n```', 'legacy retired')
insert = '''\n## 6. R12 — post-render normalization consolidation\n\n`enhancePageV37()` was still live and owned table wrapping plus old “使用建议” panel removal. A permanent Chrome contract first locked modal table wrapping and first-field autofocus. Normalization then moved into the later cleanup owner:\n\n```text\ncleanup(root)\n→ wrap table.table in .table-wrap when needed\n→ remove historical guidance panels\n→ existing file-input/placeholder/empty-state cleanup\n```\n\n`enhancePageV37` and its RAF callbacks are now absent. `baseRenderV37` remains only for `state.versionInfo` compatibility; `baseModalV37` remains only for modal autofocus.\n\n```text\nbaseline:   6ae19dc79abbf690371a71162c97a2df6322518b\nproduct:    202a5a82b0cb4629423ee0c6812f649031234daa\nvalidation: 60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29\nrun:        34666673017\nChrome:     18/18 PASS\n```\n'''
t = replace_once(t, '\n## 6. Current live render topology\n', insert + '\n## 7. Current live render topology\n', 'legacy r12')
t = t.replace('\n## 7. Permanent contracts\n', '\n## 8. Permanent contracts\n', 1)
t = t.replace('\n## 8. Remaining technical-debt targets\n', '\n## 9. Remaining technical-debt targets\n', 1)
t = t.replace('\n## 9. Audit method\n', '\n## 10. Audit method\n', 1)
t = t.replace('\n## 10. Non-negotiable rules\n', '\n## 11. Non-negotiable rules\n', 1)
t = t.replace('\n## 11. Work order\n', '\n## 12. Work order\n', 1)
t = replace_once(t, 'cleanup(root)\n  post-render DOM normalization\n  page + modal file-input beautification\n```', 'cleanup(root)\n  post-render DOM normalization\n  table wrapping + page/modal file-input beautification\n\nbaseRenderV37\n  state.versionInfo compatibility write only\n\nbaseModalV37\n  modal first-editable-field autofocus only\n```', 'legacy live')
t = replace_once(t, 'baseRenderV37\nbaseModalV37\npost-render cleanup wrapper + view/modalBody MutationObserver lifecycle', 'baseRenderV37 versionInfo compatibility ownership\nbaseModalV37 autofocus ownership\npost-render cleanup wrapper + view/modalBody MutationObserver lifecycle', 'legacy remaining')
t = replace_once(t, 'tests/frontend/file-input-beautification-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs', 'tests/frontend/file-input-beautification-owner.test.mjs\ntests/frontend/post-render-normalization-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs', 'legacy tests')
t = replace_once(t, 'Current accepted Real Chrome suite: **17/17** in run `34665890699`.', 'Current accepted Real Chrome suite: **18/18** in run `34666673017`.', 'legacy chrome')
t = replace_once(t, '`baseRender417`, `render426base`, and `modal426` are CLOSED and must not return.', '`baseRender417`, `render426base`, `modal426`, and `enhancePageV37` are CLOSED and must not return.', 'legacy closed')
p.write_text(t, encoding='utf-8')

# Owner map
p = FILES['map']; t = p.read_text(encoding='utf-8')
t = replace_once(t, 'Latest fully accepted code point: `9bad939a70bc85c75b0897ee7b4d5a21fb2ab9d1` / run `34665890699`', 'Latest fully accepted code point: `60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29` / run `34666673017`', 'map acceptance')
t = replace_once(t, 'Real Chrome: 17/17 passed', 'Real Chrome: 18/18 passed', 'map chrome header')
t = replace_once(t, '| R11 | `modal426` modal file-input beautification wrapper | `9bad939a...` / `34665890699` |', '| R11 | `modal426` modal file-input beautification wrapper | `9bad939a...` / `34665890699` |\n| R12 | `enhancePageV37` post-render normalization helper + RAF callbacks | `60d87751...` / `34666673017` |', 'map batch')
t = replace_once(t, 'R11 final acceptance increased the browser suite to 17 tests; **17/17 passed**. All one-shot baseline/migration helpers/workflows were removed after success.', 'R11 final acceptance increased the browser suite to 17 tests; **17/17 passed**.  \nR12 baseline: `6ae19dc79abbf690371a71162c97a2df6322518b`.  \nR12 product: `202a5a82b0cb4629423ee0c6812f649031234daa`.  \nR12 final acceptance increased the browser suite to 18 tests; **18/18 passed**. All one-shot baseline/migration helpers/workflows were removed after success.', 'map history')
t = replace_once(t, '| Page post-render normalization | `cleanup(root)` + view observer | DOM cleanup + page file-input beautification | unit + Chrome |\n| Modal post-render normalization | `cleanup(root)` + modalBody observer | dynamic modal file-input beautification | unit + Chrome |', '| Page post-render normalization | `cleanup(root)` + view observer | DOM cleanup + table wrapping + page file-input beautification | unit + Chrome |\n| Modal post-render normalization | `cleanup(root)` + modalBody observer | table wrapping + dynamic modal file-input beautification | unit + Chrome |\n| V37 render compatibility | `baseRenderV37` | `state.versionInfo` formal-version compatibility write only | static/unit guard |\n| V37 modal compatibility | `baseModalV37` | first editable modal field autofocus only | Chrome + unit guard |', 'map table')
insert = '''\n## 8. R12 post-render normalization ownership\n\nPre-R12:\n\n```text\nbaseRenderV37 / baseModalV37\n→ requestAnimationFrame(enhancePageV37)\n→ wrap page/modal tables\n→ remove 使用建议 panel\n```\n\nFinal normalization owner:\n\n```text\ncleanup(root)\n→ wrap table.table in .table-wrap\n→ remove historical guidance panels\n→ existing file-input / empty-state / placeholder cleanup\n```\n\nRetired:\n\n```text\nenhancePageV37\nrequestAnimationFrame(enhancePageV37)\nmodal enhancePageV37 callback\n```\n\nRetained for separate proof:\n\n```text\nbaseRenderV37 → state.versionInfo write only\nbaseModalV37  → first editable modal field autofocus only\n```\n'''
t = replace_once(t, '\n## 8. Render topology — confirmed live / retired\n', insert + '\n## 9. Render topology — confirmed live / retired\n', 'map r12')
t = t.replace('\n## 9. Remaining render/lifecycle audit targets\n', '\n## 10. Remaining render/lifecycle audit targets\n', 1)
t = t.replace('\n## 10. Permanent proof currently active\n', '\n## 11. Permanent proof currently active\n', 1)
t = t.replace('\n## 11. Per-batch checklist\n', '\n## 12. Per-batch checklist\n', 1)
t = t.replace('\n## 12. Release boundary\n', '\n## 13. Release boundary\n', 1)
t = replace_once(t, 'cleanup(root)     post-render normalization + page/modal file-input beautification\n```', 'cleanup(root)     post-render normalization + table wrapping + page/modal file-input beautification\nbaseRenderV37      state.versionInfo compatibility write only\nbaseModalV37       first editable modal field autofocus only\n```', 'map live')
t = replace_once(t, 'modal426 modal wrapper\n```', 'modal426 modal wrapper\nenhancePageV37 normalization helper/RAF callbacks\n```', 'map retired')
t = replace_once(t, 'baseRenderV37\n  requestAnimationFrame page enhancement + state.versionInfo write\n\nbaseModalV37\n  modal enhancement + initial-focus wrapper', 'baseRenderV37\n  state.versionInfo compatibility write only\n\nbaseModalV37\n  initial-focus wrapper only', 'map remaining')
t = replace_once(t, 'tests/frontend/file-input-beautification-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs', 'tests/frontend/file-input-beautification-owner.test.mjs\ntests/frontend/post-render-normalization-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs', 'map tests')
t = replace_once(t, 'modal file input beautification survives modal lifecycle ownership\n```', 'modal file input beautification survives modal lifecycle ownership\nmodal table wrapping and first-field focus survive normalization ownership\n```', 'map browser contract')
t = replace_once(t, 'Current accepted Real Chrome suite: **17/17** in run `34665890699`.', 'Current accepted Real Chrome suite: **18/18** in run `34666673017`.', 'map accepted')
p.write_text(t, encoding='utf-8')

print('R12 docs synchronized')
