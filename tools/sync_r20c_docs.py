from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path, old, new):
    p = ROOT / path
    s = p.read_text(encoding='utf-8')
    count = s.count(old)
    if count != 1:
        raise SystemExit(f'{path}: expected exactly 1 anchor, got {count}: {old[:100]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')


# CODEX_CURRENT_STATE
p = 'docs/CODEX_CURRENT_STATE.md'
replace_once(p,
"""latest full code acceptance: d18044d3d98231affc7488974e04623dab6d2b10
Frontend Runtime run:        34679069872
formal VERSION.txt:          42.24.0
visible frontend version:    v42.24.0
internal UI build metadata:  42.25.0-dev
app.js cache:                42.25.78
main.mjs cache:              42.25.83""",
"""latest full code acceptance: e3f23f59a4e1513b807490465e94c5558f805c14
Frontend Runtime run:        34681236515
formal VERSION.txt:          42.24.0
visible frontend version:    v42.24.0
internal UI build metadata:  42.25.0-dev
app.js cache:                42.25.79
main.mjs cache:              42.25.84""")
replace_once(p,
"Run `34679069872` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **22 tests and passed 22/22**.",
"Run `34681236515` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **23 tests and passed 23/23**.")
replace_once(p,
"R20/global reload debt remains **IN PROGRESS**; R20b closes only the live model-version publish path.\n",
"""R20/global reload debt remains **IN PROGRESS**; R20b closes only the live model-version publish path.

### R20c — training-server scoped target refresh

The final live `saveServer` owner is still reached from 训练资源 → 接入服务器. Before R20c it POSTed `/api/train_servers` and then called global `reload()`, whose current final binding is `refreshCurrentPage413`: bootstrap snapshot plus current-page extras. On 训练资源 that meant an unnecessary bootstrap snapshot in addition to `/api/training_options`.

The backend POST returns only the saved server item, while canonical `state.targets` is built by `/api/training_options`. R20c therefore keeps the necessary normalization request but removes the bootstrap fan-out: POST server → GET training_options → replace `state.targets` → local render. The permanent Chrome contract requires bootstrap=0 on this action.

```text
baseline:           63de3724ff794dd8712b359a806cd86eb5e3476b / run 34679508471 PASS
product:            b790c53e1a766d617c6b834ee69f1335b2e17010
focused migration:  34679584971 PASS
validation:         e3f23f59a4e1513b807490465e94c5558f805c14
run:                34681236515
frontend:           PASS
Real Chrome:        23/23 PASS
app.js:             42.25.79
main.mjs:            42.25.84
```

R20/global reload debt remains **IN PROGRESS**; R20c closes only training-server creation refresh ownership.
""")
replace_once(p,
"algorithm-version-publish-owner.test.mjs\nnavigation-stability.test.mjs",
"algorithm-version-publish-owner.test.mjs\ntraining-server-refresh-owner.test.mjs\nnavigation-stability.test.mjs")
replace_once(p,
"Current accepted suite: **22/22**; this includes `base modal post-open content refresh stays functional`, `algorithm version deletion uses focused refresh without full reload`, and the model-version publish authoritative-state/request-boundary contract.",
"Current accepted suite: **23/23**; this includes `base modal post-open content refresh stays functional`, algorithm-version delete focused refresh, model-version publish authoritative-state ownership, and training-server scoped target refresh with bootstrap=0.")

# frontend-legacy-audit
p = 'docs/frontend-legacy-audit.md'
replace_once(p,
"""commit:       d18044d3d98231affc7488974e04623dab6d2b10
run:          34679069872
frontend:     PASS
Real Chrome:  PASS (22/22)""",
"""commit:       e3f23f59a4e1513b807490465e94c5558f805c14
run:          34681236515
frontend:     PASS
Real Chrome:  PASS (23/23)""")
replace_once(p,
"""app.js                    42.25.78
main.mjs                  42.25.83""",
"""app.js                    42.25.79
main.mjs                  42.25.84""")
replace_once(p,
"The initial baseline failure was only an incorrect test assertion against modal text; the model name is rendered as a disabled input value. No product fix was hidden by that correction.\n",
"""The initial baseline failure was only an incorrect test assertion against modal text; the model name is rendered as a disabled input value. No product fix was hidden by that correction.

### R20c — training-server refresh ownership

`saveServer` is a proven-live final owner from the training-resource server connection flow. Its former `await reload()` reached the final `refreshCurrentPage413` binding, so a server POST caused a bootstrap snapshot plus 训练资源 extras. Because canonical training targets come from `/api/training_options`, R20c narrows the mutation to exactly the required refresh domain: POST `/api/train_servers`, GET `/api/training_options?project_id=...`, replace `state.targets`, local render. No bootstrap snapshot belongs to this mutation.

```text
baseline:           63de3724ff794dd8712b359a806cd86eb5e3476b / 34679508471 PASS
product:            b790c53e1a766d617c6b834ee69f1335b2e17010
focused migration:  34679584971 PASS
validation:         e3f23f59a4e1513b807490465e94c5558f805c14 / 34681236515
frontend:           PASS
Real Chrome:        23/23 PASS
```
""")
replace_once(p,
"tests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs",
"tests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/training-server-refresh-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs")
replace_once(p,
"Current accepted Real Chrome suite: **22/22** in run `34679069872`.",
"Current accepted Real Chrome suite: **23/23** in run `34681236515`.")

# FRONTEND_OWNER_MAP
p = 'docs/FRONTEND_OWNER_MAP_V42_25.md'
replace_once(p,
"Latest fully accepted code point: `d18044d3d98231affc7488974e04623dab6d2b10` / run `34679069872`  \n> Real Chrome: 22/22 passed",
"Latest fully accepted code point: `e3f23f59a4e1513b807490465e94c5558f805c14` / run `34681236515`  \n> Real Chrome: 23/23 passed")
replace_once(p,
"| R20b | model-version publish full reload → authoritative POST result + local state patch | `d18044d3...` / `34679069872` |",
"| R20b | model-version publish full reload → authoritative POST result + local state patch | `d18044d3...` / `34679069872` |\n| R20c | training-server full reload → POST + training_options-only target refresh | `e3f23f59...` / `34681236515` |")
replace_once(p,
"""run:                34679069872
frontend:           PASS
Real Chrome:        22/22 PASS
```

## 4. Current final navigation owner""",
"""run:                34679069872
frontend:           PASS
Real Chrome:        22/22 PASS
```

### R20c — training-server target refresh owner

The live `saveServer` mutation no longer invokes global `reload()`. The server POST result is not sufficient to construct canonical training targets, so the owner performs the one required domain refresh: `/api/training_options?project_id=...`. `state.targets` is then replaced and the page rendered locally. The request contract forbids a bootstrap snapshot from this action.

```text
baseline:           63de3724ff794dd8712b359a806cd86eb5e3476b / 34679508471 PASS
product:            b790c53e1a766d617c6b834ee69f1335b2e17010
focused migration:  34679584971 PASS
validation:         e3f23f59a4e1513b807490465e94c5558f805c14
run:                34681236515
frontend:           PASS
Real Chrome:        23/23 PASS
```

## 4. Current final navigation owner""")
replace_once(p,
"| Model-version publish | final `saveAssign` → authoritative POST result | one POST; local algorithm-version + pending-state patch; zero reload GETs | unit + Chrome request contract |",
"| Model-version publish | final `saveAssign` → authoritative POST result | one POST; local algorithm-version + pending-state patch; zero reload GETs | unit + Chrome request contract |\n| Training-server creation | final `saveServer` → training_options scoped refresh | POST server + GET training_options; replace targets; bootstrap=0 | unit + Chrome request contract |")
replace_once(p,
"tests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs",
"tests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/training-server-refresh-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs")

# TECH_DEBT_CLOSURE
p = 'docs/TECH_DEBT_CLOSURE_V42_25.md'
replace_once(p,
"**最近完整代码验收点：`d18044d3d98231affc7488974e04623dab6d2b10`**  \n> **Frontend Runtime Stabilization：run `34679069872`，frontend + Real Chrome 全绿，Real Chrome 22/22 passed。**",
"**最近完整代码验收点：`e3f23f59a4e1513b807490465e94c5558f805c14`**  \n> **Frontend Runtime Stabilization：run `34681236515`，frontend + Real Chrome 全绿，Real Chrome 23/23 passed。**")
replace_once(p,
"| model-version publish full reload | authoritative POST result + local state patch | **CLOSED (R20b)** |\n| global reload / duplicate request | scoped refresh | **IN PROGRESS (R20)** |",
"| model-version publish full reload | authoritative POST result + local state patch | **CLOSED (R20b)** |\n| training-server create full reload | POST + training_options-only target refresh | **CLOSED (R20c)** |\n| global reload / duplicate request | scoped refresh | **IN PROGRESS (R20)** |")
replace_once(p,
"""app.js cache                     42.25.78
main.mjs cache                   42.25.83""",
"""app.js cache                     42.25.79
main.mjs cache                   42.25.84""")
replace_once(p,
"tests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs",
"tests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/training-server-refresh-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs")
replace_once(p,
"当前验收：run `34679069872`，frontend PASS，Real Chrome **22/22 passed**。",
"当前验收：run `34681236515`，frontend PASS，Real Chrome **23/23 passed**。")
replace_once(p,
"R20 remains **IN PROGRESS** for other live mutation owners.\n\n## 7. Recent render/lifecycle acceptance history",
"""R20 remains **IN PROGRESS** for other live mutation owners.

### R20c — training-server scoped target refresh

训练资源页的最终 `saveServer` owner 已证明 live。R20c 前，服务器保存成功后调用全局 `reload()`；当前 `reload()` 已重绑到 `refreshCurrentPage413`，因此该动作会重新请求 bootstrap snapshot，再加载训练资源页 extras。后端 `/api/train_servers` POST 只返回 server item，而规范化 `state.targets` 必须来自 `/api/training_options`，所以不能做不可靠的纯本地拼装。

R20c 将该 mutation 收敛为：POST `/api/train_servers` → GET `/api/training_options?project_id=...` → 更新 `state.targets` → 本地 render。永久 Chrome 合同要求该动作 bootstrap snapshot 请求为 0。

```text
baseline:           63de3724ff794dd8712b359a806cd86eb5e3476b / 34679508471 PASS
product:            b790c53e1a766d617c6b834ee69f1335b2e17010
focused migration:  34679584971 PASS
validation:         e3f23f59a4e1513b807490465e94c5558f805c14
full run:           34681236515
frontend:           PASS
Real Chrome:        23/23 PASS
app.js:             42.25.79
main.mjs:            42.25.84
```

R20 remains **IN PROGRESS** for other proven-live mutation owners.

## 7. Recent render/lifecycle acceptance history""")
replace_once(p,
"R17–R19 已把 active normalization observers 清零。R20a 已关闭算法版本删除的全量 reload；R20b 又关闭测试发布模型归属版本后的全量 reload，并改为使用 POST 返回值直接更新算法版本与 pending state。R20 仍需继续审计其他 live mutation owner，并逐域迁移 `reload() → loadAll() → loadRelated()` 全量刷新债务；不允许靠缓存或测试放宽掩盖重复请求。",
"R17–R19 已把 active normalization observers 清零。R20a 已关闭算法版本删除的全量 reload；R20b 关闭测试发布模型归属版本后的全量 reload；R20c 又把训练服务器接入后的 bootstrap+extras 刷新收敛为 training_options 单域刷新。R20 仍需继续审计其他 live mutation owner，并逐域迁移全量刷新债务；不允许靠缓存或测试放宽掩盖重复请求。")

if (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION changed during docs sync')
print('R20c ledgers synchronized')
