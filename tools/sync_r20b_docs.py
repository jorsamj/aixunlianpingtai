from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path, old, new):
    p = ROOT / path
    s = p.read_text(encoding='utf-8')
    count = s.count(old)
    if count != 1:
        raise SystemExit(f'{path}: expected exactly 1 anchor, got {count}: {old[:90]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')


# CODEX_CURRENT_STATE
p = 'docs/CODEX_CURRENT_STATE.md'
replace_once(p,
"""latest full code acceptance: 103d630b24bd1aad77190149291c4c9f25e8ab75
Frontend Runtime run:        34677761599
formal VERSION.txt:          42.24.0
visible frontend version:    v42.24.0
internal UI build metadata:  42.25.0-dev
app.js cache:                42.25.77
main.mjs cache:              42.25.82""",
"""latest full code acceptance: d18044d3d98231affc7488974e04623dab6d2b10
Frontend Runtime run:        34679069872
formal VERSION.txt:          42.24.0
visible frontend version:    v42.24.0
internal UI build metadata:  42.25.0-dev
app.js cache:                42.25.78
main.mjs cache:              42.25.83""")
replace_once(p,
"Run `34677761599` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **21 tests and passed 21/21**.",
"Run `34679069872` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **22 tests and passed 22/22**.")
replace_once(p,
"This closes only the version-delete refresh path. R20/global reload debt remains **IN PROGRESS** and must continue mutation-domain by mutation-domain.\n",
"""This closes only the version-delete refresh path. R20/global reload debt remains **IN PROGRESS** and must continue mutation-domain by mutation-domain.

### R20b — model publish authoritative state update

The final live `saveAssign` owner was proven reachable from 测试发布. Its POST already returns the authoritative created `version`, so R20b removes the redundant global reload after publish. On success the owner prepends the returned version to the selected algorithm, removes the published model from `state.pending`, clears `state.assigningModel`, closes the modal and renders locally. The publish action itself now owns exactly one POST and zero follow-up GETs.

```text
initial baseline:   b41340d4ee292f7e8e268f4bd59206efe072d690 / run 34678815343 → 21/22
                    failure was a test-DOM mismatch: model name is an input value, not modal text
corrected baseline: b7043a5b780c9d0c4ca160c4bc7d7951a83198ff / focused run 34678924407 PASS
product:            4a2eb2a78869db0b91f1920ff4b7ba3b0dd45b89
focused migration:  34679011468 PASS
validation:         d18044d3d98231affc7488974e04623dab6d2b10
run:                34679069872
frontend:           PASS
Real Chrome:        22/22 PASS
app.js:             42.25.78
main.mjs:            42.25.83
```

R20/global reload debt remains **IN PROGRESS**; R20b closes only the live model-version publish path.
""")
replace_once(p,
"algorithm-version-refresh-owner.test.mjs\nnavigation-stability.test.mjs",
"algorithm-version-refresh-owner.test.mjs\nalgorithm-version-publish-owner.test.mjs\nnavigation-stability.test.mjs")
replace_once(p,
"Current accepted suite: **21/21**; this includes `base modal post-open content refresh stays functional` and `algorithm version deletion uses focused refresh without full reload`.",
"Current accepted suite: **22/22**; this includes `base modal post-open content refresh stays functional`, `algorithm version deletion uses focused refresh without full reload`, and the model-version publish authoritative-state/request-boundary contract.")

# frontend-legacy-audit
p = 'docs/frontend-legacy-audit.md'
replace_once(p,
"""commit:       103d630b24bd1aad77190149291c4c9f25e8ab75
run:          34677761599
frontend:     PASS
Real Chrome:  PASS (21/21)""",
"""commit:       d18044d3d98231affc7488974e04623dab6d2b10
run:          34679069872
frontend:     PASS
Real Chrome:  PASS (22/22)""")
replace_once(p,
"""app.js                    42.25.77
main.mjs                  42.25.82""",
"""app.js                    42.25.78
main.mjs                  42.25.83""")
replace_once(p,
"This closes only the version-delete refresh path. R20/global reload debt remains **IN PROGRESS** and must continue mutation-domain by mutation-domain.\n",
"""This closes only the version-delete refresh path. R20/global reload debt remains **IN PROGRESS** and must continue mutation-domain by mutation-domain.

### R20b — model-version publish local state ownership

The final live 测试发布 `saveAssign` owner previously performed a successful version POST and then invoked global `reload()`. The backend already returns the authoritative created `version`, so the owner now patches `state.algorithms`, removes the matching pending model, clears transient assignment state and renders locally. The permanent browser request contract requires exactly one publish POST and forbids bootstrap/algorithms/pending/jobs/models/training-resource reload fan-out from this action.

```text
initial baseline:   b41340d4ee292f7e8e268f4bd59206efe072d690 / 34678815343 → 21/22
corrected baseline: b7043a5b780c9d0c4ca160c4bc7d7951a83198ff / 34678924407 PASS
product:            4a2eb2a78869db0b91f1920ff4b7ba3b0dd45b89
validation:         d18044d3d98231affc7488974e04623dab6d2b10 / 34679069872
frontend:           PASS
Real Chrome:        22/22 PASS
```

The initial baseline failure was only an incorrect test assertion against modal text; the model name is rendered as a disabled input value. No product fix was hidden by that correction.
""")
replace_once(p,
"tests/frontend/algorithm-version-refresh-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs",
"tests/frontend/algorithm-version-refresh-owner.test.mjs\ntests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs")
replace_once(p,
"Current accepted Real Chrome suite: **21/21** in run `34677761599`.",
"Current accepted Real Chrome suite: **22/22** in run `34679069872`.")

# FRONTEND_OWNER_MAP
p = 'docs/FRONTEND_OWNER_MAP_V42_25.md'
replace_once(p,
"Latest fully accepted code point: `103d630b24bd1aad77190149291c4c9f25e8ab75` / run `34677761599`  \n> Real Chrome: 21/21 passed",
"Latest fully accepted code point: `d18044d3d98231affc7488974e04623dab6d2b10` / run `34679069872`  \n> Real Chrome: 22/22 passed")
replace_once(p,
"| R20a | algorithm version deletion full reload → `AlgorithmListRuntime.refresh` | `103d630b...` / `34677761599` |",
"| R20a | algorithm version deletion full reload → `AlgorithmListRuntime.refresh` | `103d630b...` / `34677761599` |\n| R20b | model-version publish full reload → authoritative POST result + local state patch | `d18044d3...` / `34679069872` |")
replace_once(p,
"This closes only the version-delete refresh path. R20/global reload debt remains **IN PROGRESS** and must continue mutation-domain by mutation-domain.\n",
"""This closes only the version-delete refresh path. R20/global reload debt remains **IN PROGRESS** and must continue mutation-domain by mutation-domain.

### R20b — model-version publish owner

The final live `saveAssign` owner now treats the version POST response as the authoritative mutation result. It updates the selected algorithm's `versions`, removes the published model from `state.pending`, clears `state.assigningModel`, closes the modal and locally renders. No global reload or follow-up GET belongs to this action.

```text
corrected baseline: b7043a5b780c9d0c4ca160c4bc7d7951a83198ff / focused run 34678924407 PASS
product:            4a2eb2a78869db0b91f1920ff4b7ba3b0dd45b89
focused migration:  34679011468 PASS
validation:         d18044d3d98231affc7488974e04623dab6d2b10
run:                34679069872
frontend:           PASS
Real Chrome:        22/22 PASS
```
""")
replace_once(p,
"| Algorithm version delete refresh | `delVersion → AlgorithmListRuntime.refresh` | DELETE + algorithms/jobs scoped refresh; no global reload fan-out | unit + Chrome request contract |",
"| Algorithm version delete refresh | `delVersion → AlgorithmListRuntime.refresh` | DELETE + algorithms/jobs scoped refresh; no global reload fan-out | unit + Chrome request contract |\n| Model-version publish | final `saveAssign` → authoritative POST result | one POST; local algorithm-version + pending-state patch; zero reload GETs | unit + Chrome request contract |")
replace_once(p,
"tests/frontend/algorithm-version-refresh-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs",
"tests/frontend/algorithm-version-refresh-owner.test.mjs\ntests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs")

# TECH_DEBT_CLOSURE
p = 'docs/TECH_DEBT_CLOSURE_V42_25.md'
replace_once(p,
"**最近完整代码验收点：`103d630b24bd1aad77190149291c4c9f25e8ab75`**  \n> **Frontend Runtime Stabilization：run `34677761599`，frontend + Real Chrome 全绿，Real Chrome 21/21 passed。**",
"**最近完整代码验收点：`d18044d3d98231affc7488974e04623dab6d2b10`**  \n> **Frontend Runtime Stabilization：run `34679069872`，frontend + Real Chrome 全绿，Real Chrome 22/22 passed。**")
replace_once(p,
"| algorithm version delete full reload | `AlgorithmListRuntime.refresh` (algorithms + jobs) | **CLOSED (R20a)** |\n| global reload / duplicate request | scoped refresh | **IN PROGRESS (R20)** |",
"| algorithm version delete full reload | `AlgorithmListRuntime.refresh` (algorithms + jobs) | **CLOSED (R20a)** |\n| model-version publish full reload | authoritative POST result + local state patch | **CLOSED (R20b)** |\n| global reload / duplicate request | scoped refresh | **IN PROGRESS (R20)** |")
replace_once(p,
"""app.js cache                     42.25.76
main.mjs cache                   42.25.81""",
"""app.js cache                     42.25.78
main.mjs cache                   42.25.83""")
replace_once(p,
"tests/frontend/lifecycle-event-ownership.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs",
"tests/frontend/lifecycle-event-ownership.test.mjs\ntests/frontend/algorithm-version-refresh-owner.test.mjs\ntests/frontend/algorithm-version-publish-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs")
replace_once(p,
"当前验收：run `34670989473`，frontend PASS，Real Chrome **20/20 passed**。",
"当前验收：run `34679069872`，frontend PASS，Real Chrome **22/22 passed**。")
replace_once(p,
"This closes only the version-delete refresh path. R20/global reload debt remains **IN PROGRESS** and must continue mutation-domain by mutation-domain.\n\n## 7. Recent render/lifecycle acceptance history",
"""This closes only the version-delete refresh path. R20/global reload debt remains **IN PROGRESS** and must continue mutation-domain by mutation-domain.

### R20b — model-version publish authoritative state update

The final live 测试发布 `saveAssign` owner no longer calls global `reload()` after a successful version publish. The API response's `version` is authoritative: it is inserted into the selected algorithm state, the matching pending model is removed, transient assignment state is cleared, and the current page is rendered locally. The publish action is permanently guarded as one POST with no reload GET fan-out.

```text
initial baseline:   b41340d4ee292f7e8e268f4bd59206efe072d690 / 34678815343 → 21/22
                    test assertion mismatch only: disabled input value was checked as modal text
corrected baseline: b7043a5b780c9d0c4ca160c4bc7d7951a83198ff / focused 34678924407 PASS
product:            4a2eb2a78869db0b91f1920ff4b7ba3b0dd45b89
focused migration:  34679011468 PASS
validation:         d18044d3d98231affc7488974e04623dab6d2b10
full run:           34679069872
frontend:           PASS
Real Chrome:        22/22 PASS
app.js:             42.25.78
main.mjs:            42.25.83
```

R20 remains **IN PROGRESS** for other live mutation owners.

## 7. Recent render/lifecycle acceptance history""")
replace_once(p,
"R17–R19 已把 active normalization observers 清零。R20a 已关闭算法版本删除的全量 reload：最终 owner 只做 DELETE + algorithms/jobs focused refresh。R20 仍需继续审计其他 live mutation owner，并逐域迁移 `reload() → loadAll() → loadRelated()` 全量刷新债务；不允许靠缓存或测试放宽掩盖重复请求。",
"R17–R19 已把 active normalization observers 清零。R20a 已关闭算法版本删除的全量 reload；R20b 又关闭测试发布模型归属版本后的全量 reload，并改为使用 POST 返回值直接更新算法版本与 pending state。R20 仍需继续审计其他 live mutation owner，并逐域迁移 `reload() → loadAll() → loadRelated()` 全量刷新债务；不允许靠缓存或测试放宽掩盖重复请求。")

if (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION changed during docs sync')
print('R20b ledgers synchronized')
