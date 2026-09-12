from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'docs/CODEX_CURRENT_STATE.md'
AUDIT = ROOT / 'docs/frontend-legacy-audit.md'
MAP = ROOT / 'docs/FRONTEND_OWNER_MAP_V42_25.md'
DEBT = ROOT / 'docs/TECH_DEBT_CLOSURE_V42_25.md'

BASELINE = '55f21733121d1280be66548ef4bb13c1c3810737'
PRODUCT = '22c552d27928375dd51081eb152dc25b1554ec18'
ACCEPT = '103d630b24bd1aad77190149291c4c9f25e8ab75'
RUN = '34677761599'


def one(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f'{label}: expected 1, got {n}')
    return text.replace(old, new, 1)

r20 = f'''### R20a — algorithm version deletion scoped refresh\n\nR20 started the global `reload() → loadAll() → loadRelated()` request-debt migration with one proven-live mutation path. The algorithm version delete modal behavior was locked first. The final `delVersion` owner now performs the DELETE and delegates refresh to `AlgorithmListRuntime.refresh({{render:true}})`, which owns only algorithms + jobs. The browser contract permanently forbids the datasets/images/labels/training-environment/bootstrap request fan-out on this path while allowing unrelated background owners such as the import-job poll to run independently.\n\n```text\nbaseline:   {BASELINE}\nproduct:    {PRODUCT}\nvalidation: {ACCEPT}\nrun:        {RUN}\nfrontend:   PASS\nReal Chrome: 21/21 PASS\napp.js:     42.25.77\nmain.mjs:   42.25.82\n```\n\nThis closes only the version-delete refresh path. R20/global reload debt remains **IN PROGRESS** and must continue mutation-domain by mutation-domain.\n\n'''

# Current state
p = STATE; t = p.read_text(encoding='utf-8')
t = one(t, 'latest full code acceptance: f60d00096a0929a63d0370494ef1f1d489f54ca3', f'latest full code acceptance: {ACCEPT}', 'state acceptance')
t = one(t, 'Frontend Runtime run:        34670989473', f'Frontend Runtime run:        {RUN}', 'state run')
t = one(t, 'app.js cache:                42.25.76', 'app.js cache:                42.25.77', 'state app cache')
t = one(t, 'main.mjs cache:              42.25.81', 'main.mjs cache:              42.25.82', 'state main cache')
t = one(t, 'Run `34670989473` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **20 tests and passed 20/20**.', f'Run `{RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **21 tests and passed 21/21**.', 'state acceptance sentence')
t = one(t, "Real Chrome: 20/20 PASS\n```\n\n\n\n## 5. Current live render owners", "Real Chrome: 20/20 PASS\n```\n\n\n" + r20 + "## 5. Current live render owners", 'state R20 insertion')
t = one(t, 'modal-content-owner.test.mjs\nnavigation-stability.test.mjs', 'modal-content-owner.test.mjs\nalgorithm-version-refresh-owner.test.mjs\nnavigation-stability.test.mjs', 'state permanent unit')
t = one(t, 'Current accepted suite: **20/20**; this includes `base modal post-open content refresh stays functional`.', 'Current accepted suite: **21/21**; this includes `base modal post-open content refresh stays functional` and `algorithm version deletion uses focused refresh without full reload`.', 'state chrome suite')
t = one(t, '1. global reload / loadAll / loadRelated duplicate-request ownership audit', '1. continue R20 global reload / loadAll / loadRelated mutation-domain migration', 'state work order')
p.write_text(t, encoding='utf-8')

# Legacy audit
p = AUDIT; t = p.read_text(encoding='utf-8')
t = one(t, 'commit:       f60d00096a0929a63d0370494ef1f1d489f54ca3', f'commit:       {ACCEPT}', 'audit acceptance')
t = one(t, 'run:          34670989473', f'run:          {RUN}', 'audit run')
t = one(t, 'Real Chrome:  PASS (20/20)', 'Real Chrome:  PASS (21/21)', 'audit chrome')
t = one(t, 'app.js                    42.25.76', 'app.js                    42.25.77', 'audit app cache')
t = one(t, 'main.mjs                  42.25.81', 'main.mjs                  42.25.82', 'audit main cache')
t = one(t, "Real Chrome: 20/20 PASS\n```\n\n\n\n## 7. Current live render topology", "Real Chrome: 20/20 PASS\n```\n\n\n" + r20 + "## 7. Current live render topology", 'audit R20 insertion')
t = one(t, 'tests/frontend/modal-content-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs', 'tests/frontend/modal-content-owner.test.mjs\ntests/frontend/algorithm-version-refresh-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs', 'audit unit')
t = one(t, 'Current accepted Real Chrome suite: **20/20** in run `34670989473`.', f'Current accepted Real Chrome suite: **21/21** in run `{RUN}`.', 'audit chrome suite')
t = one(t, '1. modalBody MutationObserver lifecycle audit\n2. app.js dead code + global reload/request debt', '1. continue R20 global reload/request mutation-domain migration\n2. app.js dead code/runtime-shell cleanup', 'audit stale work order')
p.write_text(t, encoding='utf-8')

# Owner map
p = MAP; t = p.read_text(encoding='utf-8')
t = one(t, 'Latest fully accepted code point: `f60d00096a0929a63d0370494ef1f1d489f54ca3` / run `34670989473`', f'Latest fully accepted code point: `{ACCEPT}` / run `{RUN}`', 'map acceptance')
t = one(t, '> Real Chrome: 20/20 passed', '> Real Chrome: 21/21 passed', 'map chrome')
t = one(t, '| R19 | `#modalBody` normalization observer → explicit `ModalContentRuntime` | `f60d0009...` / `34670989473` |', '| R19 | `#modalBody` normalization observer → explicit `ModalContentRuntime` | `f60d0009...` / `34670989473` |\n| R20a | algorithm version deletion full reload → `AlgorithmListRuntime.refresh` | `103d630b...` / `34677761599` |', 'map table row')
t = one(t, "Real Chrome: 20/20 PASS\n```\n\n\n## 4. Current final navigation owner", "Real Chrome: 20/20 PASS\n```\n\n\n" + r20 + "## 4. Current final navigation owner", 'map R20 insertion')
t = one(t, '| Algorithm list route | `oldRender412 → renderAlgorithms423()` | sole outer algorithm route | browser performance + guard |', '| Algorithm list route | `oldRender412 → renderAlgorithms423()` | sole outer algorithm route | browser performance + guard |\n| Algorithm version delete refresh | `delVersion → AlgorithmListRuntime.refresh` | DELETE + algorithms/jobs scoped refresh; no global reload fan-out | unit + Chrome request contract |', 'map owner row')
t = one(t, 'tests/frontend/modal-content-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs', 'tests/frontend/modal-content-owner.test.mjs\ntests/frontend/algorithm-version-refresh-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs', 'map unit')
t = one(t, 'base modal post-open content refresh stays functional\n```', 'base modal post-open content refresh stays functional\nalgorithm version deletion uses focused refresh without full reload\n```', 'map browser contract')
p.write_text(t, encoding='utf-8')

# Debt ledger
p = DEBT; t = p.read_text(encoding='utf-8')
t = one(t, '**最近完整代码验收点：`f60d00096a0929a63d0370494ef1f1d489f54ca3`**', f'**最近完整代码验收点：`{ACCEPT}`**', 'debt acceptance')
t = one(t, '**Frontend Runtime Stabilization：run `34670989473`，frontend + Real Chrome 全绿，Real Chrome 20/20 passed。**', f'**Frontend Runtime Stabilization：run `{RUN}`，frontend + Real Chrome 全绿，Real Chrome 21/21 passed。**', 'debt run')
t = one(t, '| global reload / duplicate request | scoped refresh | **OPEN** |', '| algorithm version delete full reload | `AlgorithmListRuntime.refresh` (algorithms + jobs) | **CLOSED (R20a)** |\n| global reload / duplicate request | scoped refresh | **IN PROGRESS (R20)** |', 'debt status')
t = one(t, "Real Chrome: 20/20 PASS\n```\n\n\n\n\n## 7. Recent render/lifecycle acceptance history", "Real Chrome: 20/20 PASS\n```\n\n\n" + r20 + "## 7. Recent render/lifecycle acceptance history", 'debt R20 insertion')
t = one(t, 'R17–R19 已把 active normalization observers 清零；下一批优先处理高频 mutation 后仍调用 `reload() → loadAll() → loadRelated()` 的全量刷新债务。目标是先量化调用面和网络请求，再按 mutation 语义迁移为 scoped refresh，不允许靠缓存或测试放宽掩盖重复请求。', 'R17–R19 已把 active normalization observers 清零。R20a 已关闭算法版本删除的全量 reload：最终 owner 只做 DELETE + algorithms/jobs focused refresh。R20 仍需继续审计其他 live mutation owner，并逐域迁移 `reload() → loadAll() → loadRelated()` 全量刷新债务；不允许靠缓存或测试放宽掩盖重复请求。', 'debt next batch')
t = one(t, 'A. global reload / loadAll / loadRelated duplicate-request ownership audit', 'A. continue R20 global reload / loadAll / loadRelated mutation-domain migration', 'debt order')
p.write_text(t, encoding='utf-8')

if (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt changed unexpectedly')
for p in (STATE, AUDIT, MAP, DEBT):
    s = p.read_text(encoding='utf-8')
    if ACCEPT not in s or RUN not in s or 'R20a' not in s or '21/21' not in s:
        raise SystemExit(f'R20a ledger sync incomplete: {p}')
print('R20a ledgers synchronized')
