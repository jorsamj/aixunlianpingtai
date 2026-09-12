from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path, old, new):
    p = ROOT / path
    s = p.read_text(encoding='utf-8')
    count = s.count(old)
    if count != 1:
        raise SystemExit(f'{path}: expected exactly 1 anchor, got {count}: {old[:110]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')


# CODEX_CURRENT_STATE
p='docs/CODEX_CURRENT_STATE.md'
replace_once(p,
"""latest full code acceptance: e3f23f59a4e1513b807490465e94c5558f805c14
Frontend Runtime run:        34681236515
formal VERSION.txt:          42.24.0
visible frontend version:    v42.24.0
internal UI build metadata:  42.25.0-dev
app.js cache:                42.25.79
main.mjs cache:              42.25.84""",
"""latest full code acceptance: a21846c33d79612f9ab4a47e2a69195da29caa3b
Frontend Runtime run:        34681966242
formal VERSION.txt:          42.24.0
visible frontend version:    v42.24.0
internal UI build metadata:  42.25.0-dev
app.js cache:                42.25.80
main.mjs cache:              42.25.85""")
replace_once(p,
"Run `34681236515` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **23 tests and passed 23/23**.",
"Run `34681966242` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **24 tests and passed 24/24**.")
replace_once(p,
"R20/global reload debt remains **IN PROGRESS**; R20c closes only training-server creation refresh ownership.\n\n## 5. Current live render owners — do not delete without proof",
"""R20/global reload debt remains **IN PROGRESS**; R20c closes only training-server creation refresh ownership.

### R20d — Paddle environment activation scoped target refresh

The final live `detectPaddle` and `quickPaddleDetect` owners are both reached from 训练资源. Before R20d, both successful activation paths called the final `loadAll()` binding after their Paddle POSTs, causing a bootstrap snapshot before the page-specific resource extras. `/api/paddle_env/select` returns the active environment, but canonical training-resource targets still come from `/api/training_options`, so the safe minimal refresh remains a training-options fetch rather than a hand-built local target.

R20d introduces `refreshPaddleTrainingTargets20d()`: manual activation now runs select POST → test POST → training_options GET → replace `state.targets` → local render; quick activation runs detect POST → select POST → training_options GET → replace targets → local render. The permanent Chrome contract requires bootstrap=0 for both actions.

```text
baseline:                    53411a7d26bfd2a9e20f4fd9723d87e5b67a5920 / 34681755467 PASS
first migration attempt:     34681841986 STOPPED before product commit
                             generated unit had a JS syntax error from Python string escaping
helper-generator fix:        e90cfeeb927df7331aa5ca52631f6dd618068f9d
product:                     d4cb8851de061436d030c2a677c009b43d208fc6
focused migration:           34681905173 PASS
validation:                  a21846c33d79612f9ab4a47e2a69195da29caa3b
full run:                    34681966242
frontend:                    PASS
Real Chrome:                 24/24 PASS
app.js:                      42.25.80
main.mjs:                    42.25.85
```

The failed first migration run did not commit product code; it exposed only the new unit generator escaping defect. R20 remains **IN PROGRESS** pending a zero-point audit of any other proven-live mutation full-refresh owners.

## 5. Current live render owners — do not delete without proof""")
replace_once(p,
"algorithm-version-publish-owner.test.mjs\ntraining-server-refresh-owner.test.mjs\nnavigation-stability.test.mjs",
"algorithm-version-publish-owner.test.mjs\ntraining-server-refresh-owner.test.mjs\npaddle-resource-refresh-owner.test.mjs\nnavigation-stability.test.mjs")
replace_once(p,
"Current accepted suite: **23/23**; this includes `base modal post-open content refresh stays functional`, algorithm-version delete focused refresh, model-version publish authoritative-state ownership, and training-server scoped target refresh with bootstrap=0.",
"Current accepted suite: **24/24**; this includes algorithm-version delete focused refresh, model-version publish authoritative-state ownership, training-server scoped refresh, and both Paddle activation paths using training_options-only refresh with bootstrap=0.")

# frontend-legacy-audit
p='docs/frontend-legacy-audit.md'
replace_once(p,
"""commit:       e3f23f59a4e1513b807490465e94c5558f805c14
run:          34681236515
frontend:     PASS
Real Chrome:  PASS (23/23)""",
"""commit:       a21846c33d79612f9ab4a47e2a69195da29caa3b
run:          34681966242
frontend:     PASS
Real Chrome:  PASS (24/24)""")
replace_once(p,
"""app.js                    42.25.79
main.mjs                  42.25.84""",
"""app.js                    42.25.80
main.mjs                  42.25.85""")
replace_once(p,
"""Real Chrome:        23/23 PASS
```

## 7. Current live render topology""",
"""Real Chrome:        23/23 PASS
```

### R20d — Paddle resource refresh ownership

The final late resource-runtime overrides of `detectPaddle` and `quickPaddleDetect` were proven live. Both previously ended in `loadAll()`, whose final binding includes a bootstrap snapshot. The new named helper `refreshPaddleTrainingTargets20d()` fetches only `/api/training_options?project_id=...` and replaces `state.targets`; manual and quick Paddle activation both delegate to it after their required POST sequence.

```text
baseline:                53411a7d26bfd2a9e20f4fd9723d87e5b67a5920 / 34681755467 PASS
first migration run:     34681841986 stopped before commit because the generated unit file had invalid JS newline escaping
helper fix:              e90cfeeb927df7331aa5ca52631f6dd618068f9d
product:                 d4cb8851de061436d030c2a677c009b43d208fc6
focused migration:       34681905173 PASS
validation:              a21846c33d79612f9ab4a47e2a69195da29caa3b / 34681966242
frontend:                PASS
Real Chrome:             24/24 PASS
```

No product was committed by the failed first migration run. Permanent proof now locks select/test/detect payload semantics, canonical target refresh, and bootstrap=0.

## 7. Current live render topology""")
replace_once(p,
"tests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/training-server-refresh-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs",
"tests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/training-server-refresh-owner.test.mjs\ntests/frontend/paddle-resource-refresh-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs")
replace_once(p,
"Current accepted Real Chrome suite: **23/23** in run `34681236515`.",
"Current accepted Real Chrome suite: **24/24** in run `34681966242`.")

# FRONTEND_OWNER_MAP
p='docs/FRONTEND_OWNER_MAP_V42_25.md'
replace_once(p,
"Latest fully accepted code point: `e3f23f59a4e1513b807490465e94c5558f805c14` / run `34681236515`  \n> Real Chrome: 23/23 passed",
"Latest fully accepted code point: `a21846c33d79612f9ab4a47e2a69195da29caa3b` / run `34681966242`  \n> Real Chrome: 24/24 passed")
replace_once(p,
"| R20c | training-server full reload → POST + training_options-only target refresh | `e3f23f59...` / `34681236515` |",
"| R20c | training-server full reload → POST + training_options-only target refresh | `e3f23f59...` / `34681236515` |\n| R20d | Paddle activation full reload → training_options-only target refresh | `a21846c3...` / `34681966242` |")
replace_once(p,
"""Real Chrome:        23/23 PASS
```

## 4. Current final navigation owner""",
"""Real Chrome:        23/23 PASS
```

### R20d — Paddle environment activation owner

The final `detectPaddle` / `quickPaddleDetect` owners now delegate their post-activation state refresh to `refreshPaddleTrainingTargets20d()`. Required Paddle POSTs remain unchanged; the only follow-up GET is `/api/training_options?project_id=...`, which replaces `state.targets`. A bootstrap snapshot is forbidden by the permanent browser contract.

```text
baseline:            53411a7d26bfd2a9e20f4fd9723d87e5b67a5920 / 34681755467 PASS
first migration:     34681841986 stopped pre-commit on generated-unit escaping syntax error
helper fix:          e90cfeeb927df7331aa5ca52631f6dd618068f9d
product:             d4cb8851de061436d030c2a677c009b43d208fc6
focused migration:   34681905173 PASS
validation:          a21846c33d79612f9ab4a47e2a69195da29caa3b
run:                 34681966242
frontend:            PASS
Real Chrome:         24/24 PASS
```

## 4. Current final navigation owner""")
replace_once(p,
"| Training-server creation | final `saveServer` → training_options scoped refresh | POST server + GET training_options; replace targets; bootstrap=0 | unit + Chrome request contract |",
"| Training-server creation | final `saveServer` → training_options scoped refresh | POST server + GET training_options; replace targets; bootstrap=0 | unit + Chrome request contract |\n| Paddle environment activation | final `detectPaddle` / `quickPaddleDetect` → `refreshPaddleTrainingTargets20d` | required POSTs + one training_options GET per activation; bootstrap=0 | unit + Chrome request contract |")
replace_once(p,
"tests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/training-server-refresh-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs",
"tests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/training-server-refresh-owner.test.mjs\ntests/frontend/paddle-resource-refresh-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs")

# TECH_DEBT_CLOSURE
p='docs/TECH_DEBT_CLOSURE_V42_25.md'
replace_once(p,
"**最近完整代码验收点：`e3f23f59a4e1513b807490465e94c5558f805c14`**  \n> **Frontend Runtime Stabilization：run `34681236515`，frontend + Real Chrome 全绿，Real Chrome 23/23 passed。**",
"**最近完整代码验收点：`a21846c33d79612f9ab4a47e2a69195da29caa3b`**  \n> **Frontend Runtime Stabilization：run `34681966242`，frontend + Real Chrome 全绿，Real Chrome 24/24 passed。**")
replace_once(p,
"| training-server create full reload | POST + training_options-only target refresh | **CLOSED (R20c)** |\n| global reload / duplicate request | scoped refresh | **IN PROGRESS (R20)** |",
"| training-server create full reload | POST + training_options-only target refresh | **CLOSED (R20c)** |\n| Paddle environment activation full reload | `refreshPaddleTrainingTargets20d` + training_options-only target refresh | **CLOSED (R20d)** |\n| global reload / duplicate request | scoped refresh / zero-point proof | **IN PROGRESS (R20)** |")
replace_once(p,
"""app.js cache                     42.25.79
main.mjs cache                   42.25.84""",
"""app.js cache                     42.25.80
main.mjs cache                   42.25.85""")
replace_once(p,
"tests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/training-server-refresh-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs",
"tests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/training-server-refresh-owner.test.mjs\ntests/frontend/paddle-resource-refresh-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs")
replace_once(p,
"当前验收：run `34681236515`，frontend PASS，Real Chrome **23/23 passed**。",
"当前验收：run `34681966242`，frontend PASS，Real Chrome **24/24 passed**。")
replace_once(p,
"""R20 remains **IN PROGRESS** for other proven-live mutation owners.

## 7. Recent render/lifecycle acceptance history""",
"""R20 remains **IN PROGRESS** for other proven-live mutation owners.

### R20d — Paddle environment activation scoped refresh

最终资源运行时中的 `detectPaddle` 与 `quickPaddleDetect` 已证明 live。R20d 前，两条成功路径都会调用当前 `loadAll()`，从而重新请求 bootstrap snapshot。由于规范化训练资源仍必须由 `/api/training_options` 构造，R20d 新增 `refreshPaddleTrainingTargets20d()`，两条激活路径保留各自必要 POST，仅以 training_options GET 更新 `state.targets` 并本地 render；永久 Chrome 合同要求 bootstrap=0。

```text
baseline:                53411a7d26bfd2a9e20f4fd9723d87e5b67a5920 / 34681755467 PASS
first migration run:     34681841986 STOPPED before product commit
                         generated unit JS syntax error caused by helper string escaping
helper-generator fix:    e90cfeeb927df7331aa5ca52631f6dd618068f9d
product:                 d4cb8851de061436d030c2a677c009b43d208fc6
focused migration:       34681905173 PASS
validation:              a21846c33d79612f9ab4a47e2a69195da29caa3b
full run:                34681966242
frontend:                PASS
Real Chrome:             24/24 PASS
app.js:                  42.25.80
main.mjs:                42.25.85
```

首轮失败发生在 product commit 之前，没有接受或落库产品代码。R20 下一步应做剩余全量刷新 owner 的 zero-point 审计：将 live mutation、用户显式“完整刷新”与 shadowed/dead code 分开证明。

## 7. Recent render/lifecycle acceptance history""")
replace_once(p,
"R17–R19 已把 active normalization observers 清零。R20a 已关闭算法版本删除的全量 reload；R20b 关闭测试发布模型归属版本后的全量 reload；R20c 又把训练服务器接入后的 bootstrap+extras 刷新收敛为 training_options 单域刷新。R20 仍需继续审计其他 live mutation owner，并逐域迁移全量刷新债务；不允许靠缓存或测试放宽掩盖重复请求。",
"R17–R19 已把 active normalization observers 清零。R20a 关闭算法版本删除的全量 reload；R20b 关闭模型发布后的全量 reload；R20c 收敛训练服务器接入刷新；R20d 又把手动/一键飞桨激活后的 bootstrap+extras 刷新收敛为 training_options 单域刷新。R20 下一步做 zero-point 审计，只将 proven-live mutation 计为剩余请求债；用户显式完整刷新与 shadowed/dead code 分开处理。")

if (ROOT/'VERSION.txt').read_text(encoding='utf-8').strip()!='42.24.0':
    raise SystemExit('formal VERSION changed during R20d docs sync')
print('R20d ledgers synchronized')
