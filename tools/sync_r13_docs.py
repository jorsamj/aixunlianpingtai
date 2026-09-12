from pathlib import Path

paths = [
    Path('docs/TECH_DEBT_CLOSURE_V42_25.md'),
    Path('docs/CODEX_CURRENT_STATE.md'),
    Path('docs/frontend-legacy-audit.md'),
    Path('docs/FRONTEND_OWNER_MAP_V42_25.md'),
]


def one(text, old, new, name):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f'{name}: expected 1 match, found {n}')
    return text.replace(old, new, 1)

# TECH
p = paths[0]; t = p.read_text(encoding='utf-8')
t = one(t, '**最近完整代码验收点：`60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29`**', '**最近完整代码验收点：`43e31c7e683fbda4b9c36a3d35188262b6a9ff1b`**', 'tech acceptance')
t = one(t, '**Frontend Runtime Stabilization：run `34666673017`，frontend + Real Chrome 全绿，Real Chrome 18/18 passed。**', '**Frontend Runtime Stabilization：run `34666985800`，frontend + Real Chrome 全绿，Real Chrome 18/18 passed。**', 'tech run')
t = one(t, 'enhancePageV37 modal normalization callback\n', 'enhancePageV37 modal normalization callback\nbaseRenderV37 duplicate versionInfo wrapper\n', 'tech retired')
t = one(t, '| `enhancePageV37` post-render normalization helper | `cleanup(root)` table/panel normalization | **CLOSED (R12)** |\n| remaining historical render/post-render overrides | bounded semantic owners | **IN PROGRESS** |', '| `enhancePageV37` post-render normalization helper | `cleanup(root)` table/panel normalization | **CLOSED (R12)** |\n| `baseRenderV37` duplicate versionInfo wrapper | later `V42` render versionInfo owner | **CLOSED (R13)** |\n| remaining historical render/post-render overrides | bounded semantic owners | **IN PROGRESS** |', 'tech debt')
t = one(t, 'baseRenderV37      → state.versionInfo formal-version compatibility write only\nbaseModalV37       → modal first-editable-field autofocus only\n', 'baseModalV37       → modal first-editable-field autofocus only\n', 'tech owners')
t = one(t, 'baseRenderV37      state.versionInfo compatibility write only\nbaseModalV37       autofocus only\npost-render cleanup wrapper + view/modalBody MutationObserver lifecycle', 'baseModalV37       autofocus only\nV37 120ms startup render/version timer\npost-render cleanup wrapper + view/modalBody MutationObserver lifecycle', 'tech candidates')
t = one(t, 'app.js cache                     42.25.69\nmain.mjs cache                   42.25.73', 'app.js cache                     42.25.70\nmain.mjs cache                   42.25.74', 'tech caches')
t = one(t, '- `baseRenderV37` 当前只保留 `state.versionInfo` 写入，在独立证明前不得顺带删除；\n- `baseModalV37` 当前只保留首个可编辑字段 autofocus，在独立证明前不得顺带删除。', '- `baseRenderV37` 已在 R13 退休，不得回归；\n- later `V42` render 继续承担 render-path formal `state.versionInfo.version=42.24.0`；\n- `baseModalV37` 当前只保留首个可编辑字段 autofocus，在独立证明前不得顺带删除；\n- V37 `120ms` startup render/version timer 仍存在，属于独立 timer/lifecycle 债，R13 未删除。', 'tech requirements')
t = one(t, '当前验收：run `34666673017`，**18/18 passed**。', '当前验收：run `34666985800`，**18/18 passed**。', 'tech accepted')
t = one(t, 'R12 final validation\n  60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29 / 34666673017\n  frontend PASS / Real Chrome 18/18 PASS\n```', 'R12 final validation\n  60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29 / 34666673017\n  frontend PASS / Real Chrome 18/18 PASS\n\nR13 product\n  928d2387d46a0472bd202bd4df84af8d1573b6c2\n\nR13 final validation\n  43e31c7e683fbda4b9c36a3d35188262b6a9ff1b / 34666985800\n  frontend PASS / Real Chrome 18/18 PASS\n```', 'tech history')
t = one(t, 'baseRenderV37     state.versionInfo compatibility write only\nbaseModalV37      modal first-field autofocus only', 'baseModalV37      modal first-field autofocus only\nV37 startup timer  120ms versionInfo + render compatibility timer', 'tech next')
p.write_text(t, encoding='utf-8')

# CODEX
p = paths[1]; t = p.read_text(encoding='utf-8')
t = one(t, 'latest full code acceptance: 60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29\nFrontend Runtime run:        34666673017', 'latest full code acceptance: 43e31c7e683fbda4b9c36a3d35188262b6a9ff1b\nFrontend Runtime run:        34666985800', 'codex acceptance')
t = one(t, 'app.js cache:                42.25.69\nmain.mjs cache:              42.25.73', 'app.js cache:                42.25.70\nmain.mjs cache:              42.25.74', 'codex caches')
t = one(t, 'Run `34666673017` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation now runs **18 tests and passed 18/18**.', 'Run `34666985800` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **18 tests and passed 18/18**.', 'codex run')
t = one(t, 'enhancePageV37 post-render normalization helper\n```', 'enhancePageV37 post-render normalization helper\nbaseRenderV37 duplicate versionInfo wrapper\n```', 'codex retired')
needle = 'Permanent proof: `tests/frontend/post-render-normalization-owner.test.mjs` plus the browser contract `modal table wrapping and first-field focus survive normalization ownership`.\n'
section = '''Permanent proof: `tests/frontend/post-render-normalization-owner.test.mjs` plus the browser contract `modal table wrapping and first-field focus survive normalization ownership`.\n\n### R13 — baseRenderV37 retirement\n\nR13 proved the remaining V37 render wrapper was only a duplicate formal-version write:\n\n```text\nbaseRenderV37\n→ state.versionInfo.version = 42.24.0\n→ delegate\n\nlater V42 render owner\n→ state.versionInfo.version = 42.24.0\n→ oldRender42()\n```\n\nBecause the later V42 owner writes the same value before delegating into the old chain, `baseRenderV37` was physically removed. `baseModalV37` was intentionally untouched. The V37 120ms startup timer also remains and is a separate lifecycle target.\n\n```text\nproduct:    928d2387d46a0472bd202bd4df84af8d1573b6c2\nvalidation: 43e31c7e683fbda4b9c36a3d35188262b6a9ff1b\nrun:        34666985800\nfrontend:   PASS\nChrome:     18/18 PASS\n```\n'''
t = one(t, needle, section, 'codex r13 section')
t = one(t, 'baseRenderV37\n  state.versionInfo formal-version compatibility write only\n\nbaseModalV37\n  first editable modal field autofocus only', 'baseModalV37\n  first editable modal field autofocus only', 'codex live')
t = one(t, 'baseRenderV37 versionInfo compatibility ownership\nbaseModalV37 autofocus ownership\npost-render cleanup wrapper + view/modalBody MutationObserver lifecycle', 'baseModalV37 autofocus ownership\nV37 120ms startup render/version timer\npost-render cleanup wrapper + view/modalBody MutationObserver lifecycle', 'codex audit')
p.write_text(t, encoding='utf-8')

# legacy audit
p = paths[2]; t = p.read_text(encoding='utf-8')
t = one(t, 'commit:       60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29\nrun:          34666673017\nfrontend:     PASS\nReal Chrome:  PASS (18/18)', 'commit:       43e31c7e683fbda4b9c36a3d35188262b6a9ff1b\nrun:          34666985800\nfrontend:     PASS\nReal Chrome:  PASS (18/18)', 'legacy acceptance')
t = one(t, 'app.js                    42.25.69\nmain.mjs                  42.25.73', 'app.js                    42.25.70\nmain.mjs                  42.25.74', 'legacy caches')
t = one(t, 'enhancePageV37 post-render normalization helper\n```', 'enhancePageV37 post-render normalization helper\nbaseRenderV37 duplicate versionInfo wrapper\n```', 'legacy retired')
anchor = '''```text\nbaseline:   6ae19dc79abbf690371a71162c97a2df6322518b\nproduct:    202a5a82b0cb4629423ee0c6812f649031234daa\nvalidation: 60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29\nrun:        34666673017\nChrome:     18/18 PASS\n```\n'''
addition = anchor + '''\n### R13 — duplicate V37 render version write\n\n`baseRenderV37` was reduced by R12 to a single `state.versionInfo.version=42.24.0` write. A later V42 render owner writes the same formal version before delegating into the old render chain, so R13 removed the duplicate wrapper without moving any UI behavior.\n\n```text\nproduct:    928d2387d46a0472bd202bd4df84af8d1573b6c2\nvalidation: 43e31c7e683fbda4b9c36a3d35188262b6a9ff1b\nrun:        34666985800\nChrome:     18/18 PASS\n```\n\n`baseModalV37` autofocus remains live. The V37 120ms startup timer remains and was not part of R13.\n'''
t = one(t, anchor, addition, 'legacy R13')
t = one(t, 'baseRenderV37\n  state.versionInfo compatibility write only\n\nbaseModalV37\n  modal first-editable-field autofocus only', 'baseModalV37\n  modal first-editable-field autofocus only', 'legacy live')
t = one(t, 'baseRenderV37 versionInfo compatibility ownership\nbaseModalV37 autofocus ownership\npost-render cleanup wrapper + view/modalBody MutationObserver lifecycle', 'baseModalV37 autofocus ownership\nV37 120ms startup render/version timer\npost-render cleanup wrapper + view/modalBody MutationObserver lifecycle', 'legacy targets')
t = one(t, '`baseRender417`, `render426base`, `modal426`, and `enhancePageV37` are CLOSED and must not return.', '`baseRender417`, `render426base`, `modal426`, `enhancePageV37`, and `baseRenderV37` are CLOSED and must not return.', 'legacy closed')
t = one(t, 'Current accepted Real Chrome suite: **18/18** in run `34666673017`.', 'Current accepted Real Chrome suite: **18/18** in run `34666985800`.', 'legacy run')
p.write_text(t, encoding='utf-8')

# owner map
p = paths[3]; t = p.read_text(encoding='utf-8')
t = one(t, 'Latest fully accepted code point: `60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29` / run `34666673017`', 'Latest fully accepted code point: `43e31c7e683fbda4b9c36a3d35188262b6a9ff1b` / run `34666985800`', 'map acceptance')
t = one(t, '| R12 | `enhancePageV37` post-render normalization helper + RAF callbacks | `60d87751...` / `34666673017` |', '| R12 | `enhancePageV37` post-render normalization helper + RAF callbacks | `60d87751...` / `34666673017` |\n| R13 | `baseRenderV37` duplicate versionInfo render wrapper | `43e31c7e...` / `34666985800` |', 'map batch')
t = one(t, 'R12 final acceptance increased the browser suite to 18 tests; **18/18 passed**. All one-shot baseline/migration helpers/workflows were removed after success.', 'R12 final acceptance increased the browser suite to 18 tests; **18/18 passed**.  \nR13 product: `928d2387d46a0472bd202bd4df84af8d1573b6c2`.  \nR13 validation: `43e31c7e683fbda4b9c36a3d35188262b6a9ff1b` / run `34666985800`; **18/18 passed**. All one-shot migration helpers/workflows were removed after success.', 'map history')
t = one(t, '| V37 render compatibility | `baseRenderV37` | `state.versionInfo` formal-version compatibility write only | static/unit guard |\n| V37 modal compatibility | `baseModalV37` | first editable modal field autofocus only | Chrome + unit guard |', '| Render-path formal versionInfo | later `V42` render owner | `state.versionInfo.version = 42.24.0` before delegate | unit + Chrome |\n| V37 modal compatibility | `baseModalV37` | first editable modal field autofocus only | Chrome + unit guard |', 'map owner row')
t = one(t, 'baseRenderV37      state.versionInfo compatibility write only\nbaseModalV37       first editable modal field autofocus only\n```', 'baseModalV37       first editable modal field autofocus only\n```', 'map live')
t = one(t, 'enhancePageV37 normalization helper/RAF callbacks\n```', 'enhancePageV37 normalization helper/RAF callbacks\nbaseRenderV37 duplicate versionInfo wrapper\n```', 'map retired')
t = one(t, 'baseRenderV37\n  state.versionInfo compatibility write only\n\nbaseModalV37\n  initial-focus wrapper only', 'baseModalV37\n  initial-focus wrapper only\n\nV37 startup timer\n  120ms state.versionInfo + render compatibility timer', 'map remaining')
t = one(t, 'Current accepted Real Chrome suite: **18/18** in run `34666673017`.', 'Current accepted Real Chrome suite: **18/18** in run `34666985800`.', 'map accepted')
p.write_text(t, encoding='utf-8')

print('R13 docs synchronized')
