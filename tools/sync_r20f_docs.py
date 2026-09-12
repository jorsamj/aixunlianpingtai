from pathlib import Path

ACCEPT = '94dbebb43d83b1d522ea4e3f6522154417f3e985'
PRODUCT = 'c9b7ab44192d38c37753643ee790fc2e089c8598'
RUN = '34690924552'
BASELINE = 'dddcd3f1eecf27c5b7447a16939e53473ff1d745'
READY = 'da3f3cee7565b75f0a2de926dfdbdb42f7b30ab9'
DIAG = '34690682894'

DOCS = [
    Path('docs/CODEX_CURRENT_STATE.md'),
    Path('docs/frontend-legacy-audit.md'),
    Path('docs/FRONTEND_OWNER_MAP_V42_25.md'),
    Path('docs/TECH_DEBT_CLOSURE_V42_25.md'),
]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f'{label}: expected exactly one anchor, found {n}')
    return text.replace(old, new, 1)


def ensure_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise SystemExit(f'{label}: missing {needle!r}')


# 1) CODEX_CURRENT_STATE
p = DOCS[0]
s = p.read_text(encoding='utf-8')
s = replace_once(s,
    'latest full code acceptance: 89327ded9da924753f5f900fc3b79e6df353927f\nFrontend Runtime run:        34684119911',
    f'latest full code acceptance: {ACCEPT}\nFrontend Runtime run:        {RUN}',
    'CODEX acceptance')
s = replace_once(s, 'app.js cache:                42.25.81\nmain.mjs cache:              42.25.86',
                 'app.js cache:                42.25.82\nmain.mjs cache:              42.25.87', 'CODEX caches')
s = replace_once(s,
    'Run `34684119911` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **27 tests and passed 27/27**.',
    f'Run `{RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **28 tests and passed 28/28**.',
    'CODEX current run')
s = replace_once(s,
    'paddle-resource-refresh-owner.test.mjs\nnavigation-stability.test.mjs',
    'paddle-resource-refresh-owner.test.mjs\nmodel-config-save-refresh-owner.test.mjs\nnavigation-stability.test.mjs',
    'CODEX permanent test list')
s = replace_once(s,
    'Real Chrome verifies navigation, readiness, stale-request fencing, managed polling, sidebar cleanup, current/historical auto-label canonicalization, persistence/reload, storage route, algorithm/training/material performance, formal-version stability, and page/modal file-input beautification. Current accepted suite: **24/24**; this includes algorithm-version delete focused refresh, model-version publish authoritative-state ownership, training-server scoped refresh, and both Paddle activation paths using training_options-only refresh with bootstrap=0.',
    f'Real Chrome verifies navigation, readiness, stale-request fencing, managed polling, sidebar cleanup, current/historical auto-label canonicalization, persistence/reload, storage route, algorithm/training/material performance, formal-version stability, page/modal file-input beautification, and R20 scoped mutation ownership. Current accepted suite: **28/28** in run `{RUN}`; this includes algorithm-version delete focused refresh, model-version publish authoritative-state ownership, training-server/Paddle scoped refresh, model-config/prompt local mutation ownership, and final M4 model-config save/edit local ownership.',
    'CODEX current suite')
if '### R20f — live M4 model-config save local ownership' not in s:
    s += f'''\n\n### R20f — live M4 model-config save local ownership\n\nR20f closed the remaining broad refresh on the visible model-configuration save/edit path. The first static source-order audit targeted `saveModelConfig427`, but a temporary Real Chrome runtime diagnostic proved that function is shadowed in the actual UI. M4 first captures its modal owner in `window.__m4OpenModelConfig`; a later compatibility layer textually redefines `openModelConfigModalV35`; the file-tail **M4 final activation** then restores `window.openModelConfigModalV35 = window.__m4OpenModelConfig`. Therefore the final visible save button calls `saveVisionModelM4`, not `saveModelConfig427`.\n\nBefore migration, `saveVisionModelM4` performed POST/PUT and then `loadRelated()`, producing the full project/datasets/materials/labels/algorithms/model-config request fan-out. It now treats the sanitized POST/PUT response as authoritative, upserts it into `state.modelConfigs`, closes the modal and renders locally with zero mutation-owned follow-up GETs.\n\n```text\nbaseline:              {BASELINE}\nreadiness alignment:   {READY}\nruntime diagnostic:    {DIAG} → proved final M4 save owner + broad loadRelated fan-out\nproduct:               {PRODUCT}\nvalidation:            {ACCEPT}\nfull run:              {RUN}\nfrontend:              PASS\nReal Chrome:           28/28 PASS\napp.js:                42.25.82\nmain.mjs:              42.25.87\nformal VERSION.txt:    42.24.0\n```\n\nPermanent proof is `tests/frontend/model-config-save-refresh-owner.test.mjs` plus the Chrome contract `model config save appears immediately without broad related refresh`. Future ownership audits must inspect capture/restore/final-activation semantics in addition to textual assignment order. R20/global mutation refresh debt remains **IN PROGRESS** pending the final-owner zero-point audit.\n'''
p.write_text(s, encoding='utf-8')

# 2) frontend-legacy-audit
p = DOCS[1]
s = p.read_text(encoding='utf-8')
s = replace_once(s,
    'commit:       89327ded9da924753f5f900fc3b79e6df353927f\nrun:          34684119911\nfrontend:     PASS\nReal Chrome:  PASS (27/27)',
    f'commit:       {ACCEPT}\nrun:          {RUN}\nfrontend:     PASS\nReal Chrome:  PASS (28/28)',
    'legacy acceptance')
s = replace_once(s, 'app.js                    42.25.81\nmain.mjs                  42.25.86',
                 'app.js                    42.25.82\nmain.mjs                  42.25.87', 'legacy caches')
s = replace_once(s,
    'tests/frontend/paddle-resource-refresh-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs',
    'tests/frontend/paddle-resource-refresh-owner.test.mjs\ntests/frontend/model-config-save-refresh-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs',
    'legacy permanent tests')
s = replace_once(s,
    'Current accepted Real Chrome suite: **27/27** in run `34684119911`.',
    f'Current accepted Real Chrome suite: **28/28** in run `{RUN}`.',
    'legacy current suite')
if '### R20f — final M4 model-config save ownership' not in s:
    s += f'''\n\n### R20f — final M4 model-config save ownership\n\nThe first R20f source-only audit selected `saveModelConfig427`, but runtime evidence showed that the visible modal is restored to the earlier M4 implementation by a capture/final-activation chain:\n\n```text\nM4 openModelConfigModalV35\n→ window.__m4OpenModelConfig capture\n→ later 427 compatibility overwrite\n→ file-tail M4 final activation\n→ openModelConfigModalV35 = __m4OpenModelConfig\n→ saveVisionModelM4\n```\n\nThe old live M4 save owner POSTed/PUT the model configuration and then called `loadRelated()`. The accepted owner now upserts the authoritative saved item directly into `state.modelConfigs` and renders locally; no bootstrap/project/dataset/material/label/algorithm/model-config GET fan-out belongs to the mutation.\n\n```text\nbaseline:            {BASELINE}\nreadiness alignment: {READY}\ndiagnostic run:      {DIAG}\nproduct:             {PRODUCT}\nvalidation:          {ACCEPT} / {RUN}\nfrontend:            PASS\nReal Chrome:         28/28 PASS\n```\n\nAudit rule added by R20f: **textual last assignment is insufficient when a runtime capture/restore or final-activation layer exists**. Inspect capture aliases and end-of-file restorations before classifying a function as final/live. R20 remains **IN PROGRESS** for the remaining global-refresh zero-point audit.\n'''
p.write_text(s, encoding='utf-8')

# 3) FRONTEND_OWNER_MAP
p = DOCS[2]
s = p.read_text(encoding='utf-8')
s = replace_once(s,
    'Latest fully accepted code point: `89327ded9da924753f5f900fc3b79e6df353927f` / run `34684119911`  \n> Real Chrome: 27/27 passed',
    f'Latest fully accepted code point: `{ACCEPT}` / run `{RUN}`  \n> Real Chrome: 28/28 passed',
    'owner map acceptance')
s = replace_once(s,
    '| R20e | model-config/prompt full reload + stale prompt UI → authoritative local state ownership | `89327ded...` / `34684119911` |',
    f'| R20e | model-config/prompt full reload + stale prompt UI → authoritative local state ownership | `89327ded...` / `34684119911` |\n| R20f | final M4 model-config save/edit broad `loadRelated` → authoritative saved item + local `modelConfigs` upsert | `{ACCEPT[:8]}...` / `{RUN}` |',
    'owner map R20 row')
s = replace_once(s,
    '| Model-config deletion | `deleteModelConfigV35` | DELETE + local `state.modelConfigs` removal; no follow-up GET | unit + Chrome request contract |',
    '| Model-config deletion | `deleteModelConfigV35` | DELETE + local `state.modelConfigs` removal; no follow-up GET | unit + Chrome request contract |\n| Model-config save/edit | M4 final activation → `openModelConfigModalV35` → `saveVisionModelM4` | POST/PUT authoritative item + local `state.modelConfigs` upsert; zero broad follow-up GETs | unit + Chrome request contract |',
    'owner map model config row')
s = replace_once(s,
    'tests/frontend/paddle-resource-refresh-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs',
    'tests/frontend/paddle-resource-refresh-owner.test.mjs\ntests/frontend/model-config-save-refresh-owner.test.mjs\ntests/frontend/navigation-stability.test.mjs',
    'owner map permanent tests')
s = replace_once(s,
    'algorithm version deletion uses focused refresh without full reload\n```',
    'algorithm version deletion uses focused refresh without full reload\nmodel config save appears immediately without broad related refresh\n```',
    'owner map browser contracts')
s = replace_once(s,
    'Current accepted Real Chrome suite: **20/20** in run `34670989473`.',
    f'Current accepted Real Chrome suite: **28/28** in run `{RUN}`.',
    'owner map current suite')
if '### R20f — M4 capture/final-activation model-config save owner' not in s:
    s += f'''\n\n### R20f — M4 capture/final-activation model-config save owner\n\nThe final model-configuration modal cannot be identified by textual assignment order alone. M4 captures its modal function in `window.__m4OpenModelConfig`, a later compatibility layer overwrites the public name, and the file-tail M4 final activation restores the captured function. The visible save button therefore reaches `saveVisionModelM4`.\n\n```text\n__m4OpenModelConfig capture\n→ later compatibility override\n→ M4 final activation restore\n→ saveVisionModelM4\n→ POST/PUT /api/v35/model-configs[...]\n→ authoritative saved item\n→ local state.modelConfigs upsert\n→ local render\n```\n\nAccepted at product `{PRODUCT}`, validation `{ACCEPT}`, run `{RUN}` with frontend PASS and Real Chrome **28/28**. The permanent owner guard checks the M4 capture + final activation chain and forbids `loadRelated/loadAll` inside the live save owner.\n'''
p.write_text(s, encoding='utf-8')

# 4) TECH_DEBT_CLOSURE
p = DOCS[3]
s = p.read_text(encoding='utf-8')
s = replace_once(s,
    '**最近完整代码验收点：`89327ded9da924753f5f900fc3b79e6df353927f`**  \n> **Frontend Runtime Stabilization：run `34684119911`，frontend + Real Chrome 全绿，Real Chrome 27/27 passed。**',
    f'**最近完整代码验收点：`{ACCEPT}`**  \n> **Frontend Runtime Stabilization：run `{RUN}`，frontend + Real Chrome 全绿，Real Chrome 28/28 passed。**',
    'debt acceptance')
s = replace_once(s,
    '| model-config / prompt-template mutation full reload + stale prompt UI | authoritative mutation result + local state patch | **CLOSED (R20e)** |',
    '| model-config / prompt-template mutation full reload + stale prompt UI | authoritative mutation result + local state patch | **CLOSED (R20e)** |\n| model-config save/edit broad related refresh | M4 `saveVisionModelM4` authoritative result + local `state.modelConfigs` upsert | **CLOSED (R20f)** |',
    'debt R20 row')
s = replace_once(s, 'app.js cache                     42.25.81\nmain.mjs cache                   42.25.86',
                 'app.js cache                     42.25.82\nmain.mjs cache                   42.25.87', 'debt caches')
s = replace_once(s,
    'tests/frontend/model-config-prompt-refresh-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs',
    'tests/frontend/model-config-prompt-refresh-owner.test.mjs\ntests/frontend/model-config-save-refresh-owner.test.mjs\ntests/frontend/auto-label-poll-runtime.test.mjs',
    'debt permanent tests')
s = replace_once(s,
    '当前验收：run `34684119911`，frontend PASS，Real Chrome **27/27 passed**。',
    f'当前验收：run `{RUN}`，frontend PASS，Real Chrome **28/28 passed**。',
    'debt current suite')
s = replace_once(s,
    'R17–R19 已把 active normalization observers 清零。R20a 关闭算法版本删除的全量 reload；R20b 关闭模型发布后的全量 reload；R20c 收敛训练服务器接入刷新；R20d 又把手动/一键飞桨激活后的 bootstrap+extras 刷新收敛为 training_options 单域刷新。R20 下一步做 zero-point 审计，只将 proven-live mutation 计为剩余请求债；用户显式完整刷新与 shadowed/dead code 分开处理。',
    'R17–R19 已把 active normalization observers 清零。R20a–R20d 依次关闭算法版本删除、模型发布、训练服务器接入和 Paddle 激活的宽刷新；R20e 关闭模型配置删除与提示词 mutation 宽刷新并修复 stale UI；R20f 又关闭最终 M4 模型配置保存/编辑的 `loadRelated()` fan-out。R20 下一步做 final-owner zero-point 审计，只将 proven-live mutation 计为剩余请求债；用户显式完整刷新、shadowed/dead code，以及 capture/final-activation 恢复链必须分开处理。',
    'debt next batch')
if '### R20f — 最终 M4 模型配置保存/编辑 local ownership' not in s:
    s += f'''\n\n### R20f — 最终 M4 模型配置保存/编辑 local ownership\n\nR20f 最初按文本 source order 锁定 `saveModelConfig427`，但临时 Real Chrome runtime diagnostic 证明可见 modal 实际由 M4 capture/final-activation 机制恢复：M4 先保存 `window.__m4OpenModelConfig`，后续 427 compatibility 虽然文本上重写了 `openModelConfigModalV35`，文件尾的 M4 final activation 又恢复 captured owner。因此真正 live 的保存动作是 `saveVisionModelM4`。\n\n旧 live owner 在 POST/PUT 成功后调用 `loadRelated()`，会继续请求 project、datasets、materials、labels、algorithms、pending/test models、model configs、prompt templates 等一整套相关数据。最终 owner 改为直接接收后端 sanitized authoritative item，按 `id` upsert 到 `state.modelConfigs` 并本地 render。\n\n```text\nbaseline:             {BASELINE}\nreadiness alignment:  {READY}\nruntime diagnostic:   {DIAG}\nproduct:              {PRODUCT}\nvalidation:           {ACCEPT}\nfull run:             {RUN}\nfrontend:             PASS\nReal Chrome:          28/28 PASS\napp.js:               42.25.82\nmain.mjs:             42.25.87\nformal VERSION.txt:   42.24.0\n```\n\n永久 owner guard：`tests/frontend/model-config-save-refresh-owner.test.mjs`。永久 Chrome 合同要求保存后立即可见且 mutation-owned broad GET fan-out 为零。R20f 还新增一条审计规则：**不能仅以“最后一个文本定义”认定最终 owner；必须同时检查 capture alias、restore 和 final activation。**\n\nR20/global reload debt 仍为 **IN PROGRESS**，下一步进入剩余 `reload/loadAll/loadRelated/loadCore412` 的 final-owner zero-point audit。\n'''
p.write_text(s, encoding='utf-8')

for p in DOCS:
    text = p.read_text(encoding='utf-8')
    ensure_contains(text, 'R20f', str(p))
    ensure_contains(text, RUN, str(p))
    ensure_contains(text, '28/28', str(p))
    ensure_contains(text, '42.24.0', str(p))

print('R20f docs synchronized:', ', '.join(str(p) for p in DOCS))
