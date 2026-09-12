from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    'docs/CODEX_CURRENT_STATE.md',
    'docs/frontend-legacy-audit.md',
    'docs/FRONTEND_OWNER_MAP_V42_25.md',
    'docs/TECH_DEBT_CLOSURE_V42_25.md',
]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def write(path, text):
    (ROOT / path).write_text(text, encoding='utf-8')


def once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected 1 match, found {count}')
    return text.replace(old, new, 1)


R16 = '''### R16 — event-owned ZIP completion + page-scoped material summary

R16 converted two asynchronous lifecycle guesses into explicit/scoped owners. The former body-wide ZIP review `MutationObserver` could fire after `pollImport411()` exposed `stage=导入完成` but before the final completion `resultHtml` write, so its persisted review action could be overwritten even though the DOM button and auto-open had already appeared. ZIP review is now invoked explicitly after the final successful completion state is written.

The second failure source was `refreshSummary61()`: its 250/1200ms startup timers only checked stale `transport.mode==='paged'`. Because final navigation no longer uses the early material-aware `setPage` wrapper, those timers could issue `/materials` after navigation to 训练任务. `refreshSummary61()` is now strictly gated by the live paged 数据集 page both before and after its requests.

```text
baseline:        540de6aef4ddbf82a6cf36994a31a73937abca73
baseline run:    34668429941 → 17/19
                 ZIP persisted review false
                 training-task unexpected /materials request
product:         12df27e2af9155e3a1b9f745e46605396e321815
focused run:     34668639496
                 ZIP completion PASS
                 training refresh isolation 5/5 PASS
validation:      540c0944f45030ea198af2be153c1505f71e62f0
full run:        34668702371
frontend:        PASS
Real Chrome:     19/19 PASS
```

Permanent proof: `tests/frontend/lifecycle-event-ownership.test.mjs` plus the browser contract `ZIP import completion surfaces review action and auto-opens review`.
'''

# CODEX_CURRENT_STATE
p = 'docs/CODEX_CURRENT_STATE.md'
s = read(p)
s = once(s, 'latest full code acceptance: b6edea36296ab9548037457a124b4369776f6f5e', 'latest full code acceptance: 540c0944f45030ea198af2be153c1505f71e62f0', 'codex acceptance')
s = once(s, 'Frontend Runtime run:        34667776611', 'Frontend Runtime run:        34668702371', 'codex run')
s = once(s, 'app.js cache:                42.25.72\nmain.mjs cache:              42.25.76', 'app.js cache:                42.25.73\nmain.mjs cache:              42.25.78', 'codex caches')
s = once(s, 'Run `34667776611` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **18 tests and passed 18/18**.', 'Run `34668702371` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **19 tests and passed 19/19**.', 'codex acceptance sentence')
s = once(s, 'v35/v36/V37 80/100/120ms startup render/version timers\n```', 'v35/v36/V37 80/100/120ms startup render/version timers\noldZip412 ZIP completion capture + body-wide ZIP-review MutationObserver\ntransport.mode-only material summary page guard / off-page summary request leakage\n```', 'codex retired')
anchor = 'Permanent proof includes `tests/frontend/startup-render-owner.test.mjs` and the existing modal normalization/autofocus Chrome contract.\n\n## 5. Current live render owners — do not delete without proof'
s = once(s, anchor, 'Permanent proof includes `tests/frontend/startup-render-owner.test.mjs` and the existing modal normalization/autofocus Chrome contract.\n\n' + R16 + '\n## 5. Current live render owners — do not delete without proof', 'codex R16 insert')
s = once(s, 'base modal()\n  first editable modal field autofocus\n```', 'base modal()\n  first editable modal field autofocus\n\ncompleteZipImportReview412\n  explicit successful ZIP completion review owner\n\nrefreshSummary61\n  material summary owner; live only on paged 数据集\n```', 'codex live owners')
s = once(s, 'post-render cleanup wrapper + view/modalBody MutationObserver lifecycle\nbody-wide ZIP-review MutationObserver\nolder base/global render generations still reachable through delegates', 'post-render cleanup wrapper + view/modalBody MutationObserver lifecycle\nolder base/global render generations still reachable through delegates', 'codex remaining')
s = once(s, 'startup-render-owner.test.mjs\nnavigation-stability.test.mjs', 'startup-render-owner.test.mjs\nlifecycle-event-ownership.test.mjs\nnavigation-stability.test.mjs', 'codex tests')
s = once(s, 'Current accepted suite: **18/18**.', 'Current accepted suite: **19/19**.', 'codex suite')
write(p, s)

# frontend-legacy-audit
p = 'docs/frontend-legacy-audit.md'
s = read(p)
s = once(s, 'commit:       b6edea36296ab9548037457a124b4369776f6f5e\nrun:          34667776611\nfrontend:     PASS\nReal Chrome:  PASS (18/18)', 'commit:       540c0944f45030ea198af2be153c1505f71e62f0\nrun:          34668702371\nfrontend:     PASS\nReal Chrome:  PASS (19/19)', 'legacy acceptance')
s = once(s, 'app.js                    42.25.72\nmain.mjs                  42.25.76', 'app.js                    42.25.73\nmain.mjs                  42.25.78', 'legacy caches')
s = once(s, 'v35/v36/V37 80/100/120ms startup render/version timers\n```', 'v35/v36/V37 80/100/120ms startup render/version timers\noldZip412 ZIP completion capture + body-wide ZIP-review MutationObserver\ntransport.mode-only material summary page guard / off-page summary request leakage\n```', 'legacy retired')
anchor = '```text\nproduct:    280a31bf365b1a6646a57213dfa2dff97e10e0b5\nfocused:    startup readiness PASS; training performance 5/5 PASS\nvalidation: b6edea36296ab9548037457a124b4369776f6f5e\nrun:        34667776611\nfrontend:   PASS\nChrome:     18/18 PASS\n```\n\n## 7. Current live render topology'
s = once(s, anchor, anchor.replace('\n\n## 7. Current live render topology', '\n\n' + R16 + '\n## 7. Current live render topology'), 'legacy R16 insert')
s = once(s, 'base modal()\n  modal first-editable-field autofocus\n```', 'base modal()\n  modal first-editable-field autofocus\n\ncompleteZipImportReview412\n  explicit successful ZIP completion review owner\n\nrefreshSummary61\n  material summary owner scoped to paged 数据集\n```', 'legacy live owners')
s = once(s, 'post-render cleanup wrapper + view/modalBody MutationObserver lifecycle\nbody-wide ZIP-review MutationObserver lifecycle\nolder base/global render generations reached through delegates', 'post-render cleanup wrapper + view/modalBody MutationObserver lifecycle\nolder base/global render generations reached through delegates', 'legacy remaining')
s = once(s, 'tests/frontend/startup-render-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs', 'tests/frontend/startup-render-owner.test.mjs\ntests/frontend/lifecycle-event-ownership.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs', 'legacy tests')
s = once(s, 'Current accepted Real Chrome suite: **18/18** in run `34667776611`.', 'Current accepted Real Chrome suite: **19/19** in run `34668702371`.', 'legacy suite')
write(p, s)

# OWNER MAP
p = 'docs/FRONTEND_OWNER_MAP_V42_25.md'
s = read(p)
s = once(s, 'Latest fully accepted code point: `b6edea36296ab9548037457a124b4369776f6f5e` / run `34667776611`  \n> Real Chrome: 18/18 passed', 'Latest fully accepted code point: `540c0944f45030ea198af2be153c1505f71e62f0` / run `34668702371`  \n> Real Chrome: 19/19 passed', 'owner acceptance')
s = once(s, '| R15 | v35/v36/V37 80/100/120ms startup render/version timers | `b6edea36...` / `34667776611` |', '| R15 | v35/v36/V37 80/100/120ms startup render/version timers | `b6edea36...` / `34667776611` |\n| R16 | body-wide ZIP review observer + off-page material summary leakage | `540c0944...` / `34668702371` |', 'owner batch table')
s = once(s, 'R15 product: `280a31bf365b1a6646a57213dfa2dff97e10e0b5`; validation `b6edea36296ab9548037457a124b4369776f6f5e` / run `34667776611`; focused training performance 5/5 and final Real Chrome **18/18 passed**. All one-shot migration helpers/workflows were removed after success.', 'R15 product: `280a31bf365b1a6646a57213dfa2dff97e10e0b5`; validation `b6edea36296ab9548037457a124b4369776f6f5e` / run `34667776611`; focused training performance 5/5 and final Real Chrome **18/18 passed**.  \nR16 baseline: `540de6aef4ddbf82a6cf36994a31a73937abca73` / run `34668429941` exposed ZIP persisted-review loss and the remaining training-page `/materials` race. R16 product: `12df27e2af9155e3a1b9f745e46605396e321815`; focused run `34668639496` passed ZIP completion and training isolation 5/5; validation `540c0944f45030ea198af2be153c1505f71e62f0` / run `34668702371`; Real Chrome **19/19 passed**. All R16 one-shot migration artifacts were removed.', 'owner history')
s = once(s, '| Internal UI build metadata | `UI_BUILD_VERSION` → `document.documentElement.dataset.uiBuild` | `42.25.0-dev`, non-visible | unit guard |', '| ZIP completion review | `completeZipImportReview412` | persistent review action + one auto-open after successful completion | unit + Chrome |\n| Material summary | `refreshSummary61` | requests only while current page is paged 数据集 | unit + browser performance |\n| Internal UI build metadata | `UI_BUILD_VERSION` → `document.documentElement.dataset.uiBuild` | `42.25.0-dev`, non-visible | unit guard |', 'owner visible map')
s = once(s, 'v35/v36/V37 80/100/120ms startup render/version timers\n```', 'v35/v36/V37 80/100/120ms startup render/version timers\noldZip412 ZIP completion capture + body-wide ZIP-review MutationObserver\ntransport.mode-only material summary page guard / off-page summary request leakage\n```', 'owner retired list')
s = once(s, 'post-render cleanup wrapper + view/modalBody MutationObserver lifecycle\nbody-wide ZIP-review MutationObserver\nolder base/global render generations still reachable through delegates', 'post-render cleanup wrapper + view/modalBody MutationObserver lifecycle\nolder base/global render generations still reachable through delegates', 'owner remaining')
s = once(s, 'tests/frontend/startup-render-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs', 'tests/frontend/startup-render-owner.test.mjs\ntests/frontend/lifecycle-event-ownership.test.mjs\ntests/frontend/navigation-stability.test.mjs', 'owner tests')
s = once(s, 'Current accepted Real Chrome suite: **18/18** in run `34667776611`.', 'Current accepted Real Chrome suite: **19/19** in run `34668702371`.', 'owner suite')
write(p, s)

# TECH DEBT LEDGER
p = 'docs/TECH_DEBT_CLOSURE_V42_25.md'
s = read(p)
s = once(s, '**最近完整代码验收点：`b6edea36296ab9548037457a124b4369776f6f5e`**  \n> **Frontend Runtime Stabilization：run `34667776611`，frontend + Real Chrome 全绿，Real Chrome 18/18 passed。**', '**最近完整代码验收点：`540c0944f45030ea198af2be153c1505f71e62f0`**  \n> **Frontend Runtime Stabilization：run `34668702371`，frontend + Real Chrome 全绿，Real Chrome 19/19 passed。**', 'ledger acceptance')
s = once(s, 'v35/v36/V37 80/100/120ms startup render/version timers\n```', 'v35/v36/V37 80/100/120ms startup render/version timers\noldZip412 ZIP completion capture + body-wide ZIP-review MutationObserver\ntransport.mode-only material summary page guard / off-page summary request leakage\n```', 'ledger retired')
s = once(s, '| v35/v36/V37 startup render/version timers | final `queueMicrotask → __clInit` startup owner | **CLOSED (R15)** |', '| v35/v36/V37 startup render/version timers | final `queueMicrotask → __clInit` startup owner | **CLOSED (R15)** |\n| body-wide ZIP review observer / persisted result race | `completeZipImportReview412` explicit completion owner | **CLOSED (R16)** |\n| off-page material summary timer requests | page-scoped `refreshSummary61` | **CLOSED (R16)** |', 'ledger table')
s = once(s, 'base modal()       → modal first-editable-field autofocus\n```', 'base modal()       → modal first-editable-field autofocus\ncompleteZipImportReview412 → explicit successful ZIP completion review\nrefreshSummary61           → paged 数据集-only material summary requests\n```', 'ledger live')
s = once(s, 'post-render cleanup wrapper + view/modalBody MutationObserver lifecycle\nbody-wide ZIP-review MutationObserver\nolder base/global render generations still reachable through delegates', 'post-render cleanup wrapper + view/modalBody MutationObserver lifecycle\nolder base/global render generations still reachable through delegates', 'ledger remaining')
s = once(s, 'app.js cache                     42.25.72\nmain.mjs cache                   42.25.76', 'app.js cache                     42.25.73\nmain.mjs cache                   42.25.78', 'ledger caches')
s = once(s, 'auto-label-poll-runtime.js       422501', 'auto-label-poll-runtime.js       422501\nmaterial-pagination-runtime.js   422206', 'ledger material build')
s = once(s, 'tests/frontend/startup-render-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs', 'tests/frontend/startup-render-owner.test.mjs\ntests/frontend/lifecycle-event-ownership.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs', 'ledger tests')
anchor = '当前验收：run `34667776611`，**18/18 passed**。'
s = once(s, anchor, anchor + '\n\n' + R16.replace('### R16', '### R16'), 'ledger R16 insert')
write(p, s)

for path in DOCS:
    text = read(path)
    if '34668702371' not in text:
        raise SystemExit(f'{path}: R16 run missing')
    if '540c0944f45030ea198af2be153c1505f71e62f0' not in text:
        raise SystemExit(f'{path}: R16 validation missing')
    if '19/19' not in text:
        raise SystemExit(f'{path}: 19/19 missing')

if read('VERSION.txt').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt changed unexpectedly')

print('R16 docs synchronized')
