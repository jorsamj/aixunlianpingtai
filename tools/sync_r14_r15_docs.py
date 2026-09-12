from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def write(path, text):
    (ROOT / path).write_text(text, encoding='utf-8')


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected 1 match, found {count}')
    return text.replace(old, new, 1)


# docs/CODEX_CURRENT_STATE.md
path = 'docs/CODEX_CURRENT_STATE.md'
s = read(path)
s = replace_once(s,
'''latest full code acceptance: 43e31c7e683fbda4b9c36a3d35188262b6a9ff1b
Frontend Runtime run:        34666985800''',
'''latest full code acceptance: b6edea36296ab9548037457a124b4369776f6f5e
Frontend Runtime run:        34667776611''', 'codex acceptance')
s = replace_once(s, 'app.js cache:                42.25.70\nmain.mjs cache:              42.25.74', 'app.js cache:                42.25.72\nmain.mjs cache:              42.25.76', 'codex caches')
s = replace_once(s, 'Run `34666985800` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **18 tests and passed 18/18**.', 'Run `34667776611` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **18 tests and passed 18/18**.', 'codex run text')
s = replace_once(s, 'baseRenderV37 / baseModalV37 / cleanup+observer owner audit\n→ app.js/global reload/request debt', 'cleanup+observer lifecycle audit\n→ app.js/global reload/request debt', 'codex priority')
s = replace_once(s,
'''baseRenderV37 duplicate versionInfo wrapper
```''',
'''baseRenderV37 duplicate versionInfo wrapper
baseModalV37 autofocus compatibility wrapper
v35/v36/V37 80/100/120ms startup render/version timers
```''', 'codex retired additions')
anchor = '''```text
product:    928d2387d46a0472bd202bd4df84af8d1573b6c2
validation: 43e31c7e683fbda4b9c36a3d35188262b6a9ff1b
run:        34666985800
frontend:   PASS
Chrome:     18/18 PASS
```

## 5. Current live render owners — do not delete without proof
'''
insert = '''```text
product:    928d2387d46a0472bd202bd4df84af8d1573b6c2
validation: 43e31c7e683fbda4b9c36a3d35188262b6a9ff1b
run:        34666985800
frontend:   PASS
Chrome:     18/18 PASS
```

### R14 — baseModalV37 retirement

R14 moved the only live V37 modal semantic — first editable-field autofocus — into the base `modal()` owner, then physically removed the `baseModalV37` compatibility wrapper. The focused modal contracts passed. The first full suite exposed an unrelated low-probability `/materials` request race in `training-task-performance` (17/18); rerunning the same run passed 18/18, so the failure was retained as lifecycle evidence rather than dismissed.

```text
product:             6eafbe21c3c364a3e8099fd7ff3cdaf2a19e4829
validation:          8593516eb796f10fb43cea748bcc42b479e0a02e
initial full run:    34667341153 → 17/18, then rerun 18/18
diagnostic repeat:   training performance 10/10 PASS; only GET /jobs observed
```

### R15 — legacy startup render timer retirement

The race audit identified three historical startup compatibility timers as unowned render wakeups: v35 80ms, v36 100ms and V37 120ms. They were physically removed. Final startup dispatch remains `queueMicrotask → final __clInit`; the separate bounded `setTimeout(()=>{renderTop();cleanup(document);},100)` cleanup timer remains intentionally live.

```text
product:             280a31bf365b1a6646a57213dfa2dff97e10e0b5
focused acceptance:  startup readiness PASS + training performance 5/5 PASS
validation:          b6edea36296ab9548037457a124b4369776f6f5e
run:                 34667776611
frontend:            PASS
Real Chrome:         18/18 PASS
```

Permanent proof includes `tests/frontend/startup-render-owner.test.mjs` and the existing modal normalization/autofocus Chrome contract.

## 5. Current live render owners — do not delete without proof
'''
s = replace_once(s, anchor, insert, 'codex r14/r15 insert')
s = replace_once(s,
'''cleanup(root)
  page/modal post-render normalization
  table wrapping + file-input beautification

baseModalV37
  first editable modal field autofocus only
```''',
'''cleanup(root)
  page/modal post-render normalization
  table wrapping + file-input beautification

base modal()
  first editable modal field autofocus
```''', 'codex live modal')
s = replace_once(s,
'''baseModalV37 autofocus ownership
V37 120ms startup render/version timer
post-render cleanup wrapper + view/modalBody MutationObserver lifecycle''',
'''post-render cleanup wrapper + view/modalBody MutationObserver lifecycle''', 'codex remaining audit')
s = replace_once(s, '`baseRender417`, `render426base`, and `modal426` are permanently retired.', '`baseRender417`, `render426base`, `modal426`, `baseModalV37`, and the v35/v36/V37 startup render timers are permanently retired.', 'codex retired note')
s = replace_once(s, 'post-render-normalization-owner.test.mjs\nnavigation-stability.test.mjs', 'post-render-normalization-owner.test.mjs\nstartup-render-owner.test.mjs\nnavigation-stability.test.mjs', 'codex test list')
s = replace_once(s, '1. baseRenderV37 / baseModalV37 / cleanup+observer owner audit', '1. post-render cleanup wrapper + view/modalBody MutationObserver lifecycle audit', 'codex work order')
write(path, s)

# docs/frontend-legacy-audit.md
path = 'docs/frontend-legacy-audit.md'
s = read(path)
s = replace_once(s, 'commit:       43e31c7e683fbda4b9c36a3d35188262b6a9ff1b\nrun:          34666985800', 'commit:       b6edea36296ab9548037457a124b4369776f6f5e\nrun:          34667776611', 'legacy acceptance')
s = replace_once(s, 'app.js                    42.25.70\nmain.mjs                  42.25.74', 'app.js                    42.25.72\nmain.mjs                  42.25.76', 'legacy caches')
s = replace_once(s, 'baseRenderV37 duplicate versionInfo wrapper\n```', 'baseRenderV37 duplicate versionInfo wrapper\nbaseModalV37 autofocus compatibility wrapper\nv35/v36/V37 80/100/120ms startup render/version timers\n```', 'legacy retired additions')
s = replace_once(s,
'''`baseModalV37` autofocus remains live. The V37 120ms startup timer remains and was not part of R13.

## 7. Current live render topology''',
'''At R13, `baseModalV37` autofocus and the V37 120ms startup timer still remained; both were handled in the next two bounded batches.

### R14 — modal autofocus owner consolidation

The autofocus semantic moved into the base `modal()` function and `baseModalV37` was physically removed.

```text
product:    6eafbe21c3c364a3e8099fd7ff3cdaf2a19e4829
validation: 8593516eb796f10fb43cea748bcc42b479e0a02e
run:        34667341153
first pass: 17/18 due to training-task /materials race
rerun:      18/18 PASS
```

A dedicated diagnostic then repeated the focused training performance test 10 times. All 10 passed and each first refresh contained only `GET /jobs`, proving the training refresh owner itself was not issuing `/materials`.

### R15 — startup render timer retirement

Three historical startup compatibility wakeups were removed:

```text
v35  80ms  versionInfo + render
v36 100ms  versionInfo + render
V37 120ms  versionInfo + render
```

Final startup remains owned by `queueMicrotask → final __clInit`. The separate bounded cleanup timer that calls `renderTop(); cleanup(document);` at 100ms is intentionally retained.

```text
product:    280a31bf365b1a6646a57213dfa2dff97e10e0b5
focused:    startup readiness PASS; training performance 5/5 PASS
validation: b6edea36296ab9548037457a124b4369776f6f5e
run:        34667776611
frontend:   PASS
Chrome:     18/18 PASS
```

## 7. Current live render topology''', 'legacy r14/r15 insert')
s = replace_once(s,
'''cleanup(root)
  post-render DOM normalization
  table wrapping + page/modal file-input beautification

baseModalV37
  modal first-editable-field autofocus only
```''',
'''cleanup(root)
  post-render DOM normalization
  table wrapping + page/modal file-input beautification

base modal()
  modal first-editable-field autofocus
```''', 'legacy live modal')
s = replace_once(s,
'''baseModalV37 autofocus ownership
V37 120ms startup render/version timer
post-render cleanup wrapper + view/modalBody MutationObserver lifecycle''',
'''post-render cleanup wrapper + view/modalBody MutationObserver lifecycle''', 'legacy remaining audit')
s = replace_once(s, '`baseRender417`, `render426base`, `modal426`, `enhancePageV37`, and `baseRenderV37` are CLOSED and must not return.', '`baseRender417`, `render426base`, `modal426`, `enhancePageV37`, `baseRenderV37`, `baseModalV37`, and the v35/v36/V37 startup render timers are CLOSED and must not return.', 'legacy closed note')
s = replace_once(s, 'tests/frontend/post-render-normalization-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs', 'tests/frontend/post-render-normalization-owner.test.mjs\ntests/frontend/startup-render-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs', 'legacy tests')
s = replace_once(s, 'Current accepted Real Chrome suite: **18/18** in run `34666985800`.', 'Current accepted Real Chrome suite: **18/18** in run `34667776611`.', 'legacy accepted run')
s = replace_once(s, 'baseRenderV37 / baseModalV37 / cleanup+observer owner audit\nloadAll / loadRelated / loadCore412 ownership', 'cleanup+observer lifecycle audit\nloadAll / loadRelated / loadCore412 ownership', 'legacy debt targets')
s = replace_once(s, '10. `baseRender417`, `render426base`, `modal426`, and delayed visible-version writers stay retired.', '10. `baseRender417`, `render426base`, `modal426`, `baseModalV37`, legacy startup render timers, and delayed visible-version writers stay retired.', 'legacy rules')
s = replace_once(s, '1. baseRenderV37 / baseModalV37 / cleanup+observer audit', '1. post-render cleanup wrapper + view/modalBody MutationObserver lifecycle audit', 'legacy work order')
write(path, s)

# docs/FRONTEND_OWNER_MAP_V42_25.md
path = 'docs/FRONTEND_OWNER_MAP_V42_25.md'
s = read(path)
s = replace_once(s, 'Latest fully accepted code point: `43e31c7e683fbda4b9c36a3d35188262b6a9ff1b` / run `34666985800`', 'Latest fully accepted code point: `b6edea36296ab9548037457a124b4369776f6f5e` / run `34667776611`', 'owner acceptance')
s = replace_once(s, '| R13 | `baseRenderV37` duplicate versionInfo render wrapper | `43e31c7e...` / `34666985800` |', '| R13 | `baseRenderV37` duplicate versionInfo render wrapper | `43e31c7e...` / `34666985800` |\n| R14 | `baseModalV37` autofocus compatibility wrapper | `8593516e...` / `34667341153` (rerun 18/18) |\n| R15 | v35/v36/V37 80/100/120ms startup render/version timers | `b6edea36...` / `34667776611` |', 'owner table')
s = replace_once(s, 'R13 validation: `43e31c7e683fbda4b9c36a3d35188262b6a9ff1b` / run `34666985800`; **18/18 passed**. All one-shot migration helpers/workflows were removed after success.', 'R13 validation: `43e31c7e683fbda4b9c36a3d35188262b6a9ff1b` / run `34666985800`; **18/18 passed**.  \nR14 product: `6eafbe21c3c364a3e8099fd7ff3cdaf2a19e4829`; validation `8593516eb796f10fb43cea748bcc42b479e0a02e`. The first full pass exposed a lifecycle race at 17/18; rerunning the same run passed 18/18.  \nR15 product: `280a31bf365b1a6646a57213dfa2dff97e10e0b5`; validation `b6edea36296ab9548037457a124b4369776f6f5e` / run `34667776611`; focused training performance 5/5 and final Real Chrome **18/18 passed**. All one-shot migration helpers/workflows were removed after success.', 'owner history notes')
s = replace_once(s, '| V37 modal compatibility | `baseModalV37` | first editable modal field autofocus only | Chrome + unit guard |', '| Modal autofocus | base `modal()` | first editable modal field autofocus | Chrome + unit guard |', 'owner visible modal row')
s = replace_once(s,
'''baseModalV37       first editable modal field autofocus only
```''',
'''base modal()       first editable modal field autofocus
```''', 'owner confirmed live modal')
s = replace_once(s, 'baseRenderV37 duplicate versionInfo wrapper\n```', 'baseRenderV37 duplicate versionInfo wrapper\nbaseModalV37 autofocus compatibility wrapper\nv35/v36/V37 80/100/120ms startup render/version timers\n```', 'owner retired additions')
s = replace_once(s,
'''baseModalV37
  initial-focus wrapper only

V37 startup timer
  120ms state.versionInfo + render compatibility timer

post-render cleanup wrapper + view/modalBody MutationObserver lifecycle''',
'''post-render cleanup wrapper + view/modalBody MutationObserver lifecycle''', 'owner remaining targets')
s = replace_once(s, 'tests/frontend/post-render-normalization-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs', 'tests/frontend/post-render-normalization-owner.test.mjs\ntests/frontend/startup-render-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs', 'owner tests')
s = replace_once(s, 'Current accepted Real Chrome suite: **18/18** in run `34666985800`.', 'Current accepted Real Chrome suite: **18/18** in run `34667776611`.', 'owner accepted run')
write(path, s)

# docs/TECH_DEBT_CLOSURE_V42_25.md
path = 'docs/TECH_DEBT_CLOSURE_V42_25.md'
s = read(path)
s = replace_once(s, '**最近完整代码验收点：`43e31c7e683fbda4b9c36a3d35188262b6a9ff1b`**  \n> **Frontend Runtime Stabilization：run `34666985800`，frontend + Real Chrome 全绿，Real Chrome 18/18 passed。**', '**最近完整代码验收点：`b6edea36296ab9548037457a124b4369776f6f5e`**  \n> **Frontend Runtime Stabilization：run `34667776611`，frontend + Real Chrome 全绿，Real Chrome 18/18 passed。**', 'ledger acceptance')
s = replace_once(s, 'baseRenderV37 duplicate versionInfo wrapper\n```', 'baseRenderV37 duplicate versionInfo wrapper\nbaseModalV37 autofocus compatibility wrapper\nv35/v36/V37 80/100/120ms startup render/version timers\n```', 'ledger retired additions')
s = replace_once(s, '| `baseRenderV37` duplicate versionInfo wrapper | later `V42` render versionInfo owner | **CLOSED (R13)** |', '| `baseRenderV37` duplicate versionInfo wrapper | later `V42` render versionInfo owner | **CLOSED (R13)** |\n| `baseModalV37` autofocus compatibility wrapper | base `modal()` autofocus | **CLOSED (R14)** |\n| v35/v36/V37 startup render/version timers | final `queueMicrotask → __clInit` startup owner | **CLOSED (R15)** |', 'ledger table')
s = replace_once(s,
'''cleanup(root)     → post-render normalization + table wrapping + page/modal file-input beautification
baseModalV37       → modal first-editable-field autofocus only
```''',
'''cleanup(root)     → post-render normalization + table wrapping + page/modal file-input beautification
base modal()       → modal first-editable-field autofocus
```''', 'ledger live modal')
s = replace_once(s,
'''baseModalV37       autofocus only
V37 120ms startup render/version timer
post-render cleanup wrapper + view/modalBody MutationObserver lifecycle''',
'''post-render cleanup wrapper + view/modalBody MutationObserver lifecycle''', 'ledger remaining candidates')
s = replace_once(s, 'app.js cache                     42.25.70\nmain.mjs cache                   42.25.74', 'app.js cache                     42.25.72\nmain.mjs cache                   42.25.76', 'ledger caches')
s = replace_once(s, 'tests/frontend/post-render-normalization-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs', 'tests/frontend/post-render-normalization-owner.test.mjs\ntests/frontend/startup-render-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs', 'ledger tests')
s = replace_once(s,
'''- `baseModalV37` 当前只保留首个可编辑字段 autofocus，在独立证明前不得顺带删除；
- V37 `120ms` startup render/version timer 仍存在，属于独立 timer/lifecycle 债，R13 未删除。

当前验收：run `34666985800`，**18/18 passed**。''',
'''- `baseModalV37` 已在 R14 退休；首个可编辑字段 autofocus 由 base `modal()` 唯一承担；
- v35/v36/V37 的 80/100/120ms startup render/version timer 已在 R15 退休；
- startup dispatch 必须继续由 `queueMicrotask(()=>{if(window.__clInit)window.__clInit()})` 与 final `__clInit` 路径承担；
- bounded `setTimeout(()=>{renderTop();cleanup(document);},100)` 是独立 cleanup owner，不得与已退休 startup render timer 混淆。

当前验收：run `34667776611`，**18/18 passed**。''', 'ledger permanent r14/r15')
anchor = '''R13 final validation
  43e31c7e683fbda4b9c36a3d35188262b6a9ff1b / 34666985800
  frontend PASS / Real Chrome 18/18 PASS
```
'''
insert = '''R13 final validation
  43e31c7e683fbda4b9c36a3d35188262b6a9ff1b / 34666985800
  frontend PASS / Real Chrome 18/18 PASS

R14 baseModalV37 retirement
  product 6eafbe21c3c364a3e8099fd7ff3cdaf2a19e4829
  validation 8593516eb796f10fb43cea748bcc42b479e0a02e / 34667341153
  first full pass 17/18 due to training-task /materials race; rerun 18/18 PASS
  focused race diagnostic 10/10 PASS with only GET /jobs on first refresh

R15 startup render timer retirement
  product 280a31bf365b1a6646a57213dfa2dff97e10e0b5
  focused startup readiness PASS + training performance 5/5 PASS
  validation b6edea36296ab9548037457a124b4369776f6f5e / 34667776611
  frontend PASS / Real Chrome 18/18 PASS
```
'''
s = replace_once(s, anchor, insert, 'ledger history')
s = replace_once(s,
'''baseModalV37      modal first-field autofocus only
V37 startup timer  120ms versionInfo + render compatibility timer
cleanup wrapper   post-render cleanup + view/modalBody MutationObserver lifecycle''',
'''cleanup wrapper   post-render cleanup + view/modalBody MutationObserver lifecycle''', 'ledger next batch')
s = replace_once(s, 'A. baseRenderV37 / baseModalV37 / cleanup+observer owner audit', 'A. post-render cleanup wrapper + view/modalBody MutationObserver lifecycle audit', 'ledger later order')
write(path, s)

# Global sanity checks
for path in [
    'docs/CODEX_CURRENT_STATE.md',
    'docs/frontend-legacy-audit.md',
    'docs/FRONTEND_OWNER_MAP_V42_25.md',
    'docs/TECH_DEBT_CLOSURE_V42_25.md',
]:
    text = read(path)
    if '34667776611' not in text:
        raise SystemExit(f'{path}: final run missing')
    if 'b6edea36296ab9548037457a124b4369776f6f5e' not in text:
        raise SystemExit(f'{path}: final acceptance SHA missing')

if read('VERSION.txt').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt changed unexpectedly')

print('R14/R15 docs synchronized')
