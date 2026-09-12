from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATION = '89327ded9da924753f5f900fc3b79e6df353927f'
PRODUCT = 'febece523b462692cc857431cb901fc5a863d091'
BASELINE = 'afa2bfcb474cc9970129723af5589ab74a26eca7'
GUARD_FIX = 'becabf102d10520db52fdac9af1d5238357aa3f3'
FULL_RUN = '34684119911'
BASELINE_RUN = '34683803977'
FIRST_MIGRATION_RUN = '34683969019'
FOCUSED_RUN = '34684037005'


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected one anchor, found {count}: {old[:120]!r}')
    return text.replace(old, new, 1)


def append_once(text: str, marker: str, block: str, label: str) -> str:
    if marker in text:
        raise SystemExit(f'{label}: section already present')
    return text.rstrip() + '\n\n' + block.strip() + '\n'

# CODEX_CURRENT_STATE
p = ROOT / 'docs/CODEX_CURRENT_STATE.md'
s = p.read_text(encoding='utf-8')
s = replace_once(s, 'latest full code acceptance: a21846c33d79612f9ab4a47e2a69195da29caa3b', f'latest full code acceptance: {VALIDATION}', 'codex acceptance')
s = replace_once(s, 'Frontend Runtime run:        34681966242', f'Frontend Runtime run:        {FULL_RUN}', 'codex run')
s = replace_once(s, 'app.js cache:                42.25.80', 'app.js cache:                42.25.81', 'codex app cache')
s = replace_once(s, 'main.mjs cache:              42.25.85', 'main.mjs cache:              42.25.86', 'codex main cache')
s = replace_once(s, 'Run `34681966242` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **24 tests and passed 24/24**.', f'Run `{FULL_RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation runs **27 tests and passed 27/27**.', 'codex acceptance sentence')
if 'tests/frontend/model-config-prompt-refresh-owner.test.mjs' not in s:
    anchor = 'tests/frontend/paddle-resource-refresh-owner.test.mjs'
    if anchor in s:
        s = s.replace(anchor, anchor + '\ntests/frontend/model-config-prompt-refresh-owner.test.mjs', 1)
block = f'''### R20e — model configuration / prompt mutation local ownership

The zero-point audit found three still-live mutation success paths in 模型配置: `deleteModelConfigV35`, `savePromptTemplateV35`, and `deletePromptTemplateV35`. All three used global `loadAll()` after mutation. The prompt paths also exposed a real correctness bug: the current model-page extras reload model configs but not prompt templates, so a successful prompt save/delete left the visible prompt list stale.

```text
baseline:             {BASELINE}
baseline run:         {BASELINE_RUN} → 1/3 PASS
                       model-config delete PASS
                       prompt save failed to appear immediately
                       prompt delete failed to disappear immediately
first migration run:  {FIRST_MIGRATION_RUN} → unit 3/4; wiring guard escaping only; no product commit
guard fix:            {GUARD_FIX}
focused run:          {FOCUSED_RUN} → unit 4/4 + Real Chrome 3/3 PASS
product:              {PRODUCT}
validation:           {VALIDATION}
full run:             {FULL_RUN}
frontend:             PASS
Real Chrome:          27/27 PASS
app.js:               42.25.81
main.mjs:             42.25.86
formal VERSION.txt:   42.24.0
```

Final mutation ownership:

```text
deleteModelConfigV35
  → DELETE model config
  → local state.modelConfigs filter
  → local render

savePromptTemplateV35
  → authoritative POST/PUT response
  → local state.promptTemplates upsert
  → local render

deletePromptTemplateV35
  → DELETE prompt template
  → local state.promptTemplates filter
  → local render
```

Permanent request contracts require zero bootstrap, model-config GET, or prompt-template GET fan-out from these actions. R20/global mutation refresh debt remains **IN PROGRESS** until the next source-order zero-point audit proves no additional live mutation success owner still uses global refresh.

The full R20e Chrome run also logged one non-fatal `sqlite3.OperationalError: database is locked` while initializing the resource-discovery cache. All 27 browser contracts still passed. Treat that as a separate resource-discovery concurrency diagnostic, not as an R20e acceptance failure.'''
s = append_once(s, '### R20e — model configuration / prompt mutation local ownership', block, 'codex R20e')
p.write_text(s, encoding='utf-8')

# TECH_DEBT_CLOSURE
p = ROOT / 'docs/TECH_DEBT_CLOSURE_V42_25.md'
s = p.read_text(encoding='utf-8')
s = replace_once(s, '**最近完整代码验收点：`a21846c33d79612f9ab4a47e2a69195da29caa3b`**', f'**最近完整代码验收点：`{VALIDATION}`**', 'tech acceptance')
s = replace_once(s, '**Frontend Runtime Stabilization：run `34681966242`，frontend + Real Chrome 全绿，Real Chrome 24/24 passed。**', f'**Frontend Runtime Stabilization：run `{FULL_RUN}`，frontend + Real Chrome 全绿，Real Chrome 27/27 passed。**', 'tech run')
s = replace_once(s, '| Paddle environment activation full reload | `refreshPaddleTrainingTargets20d` + training_options-only target refresh | **CLOSED (R20d)** |', '| Paddle environment activation full reload | `refreshPaddleTrainingTargets20d` + training_options-only target refresh | **CLOSED (R20d)** |\n| model-config / prompt-template mutation full reload + stale prompt UI | authoritative mutation result + local state patch | **CLOSED (R20e)** |\n| resource-discovery SQLite concurrent cache initialization | lock-safe/single-owner cache initialization | **OPEN — R20e validation diagnostic** |', 'tech R20 row')
s = replace_once(s, 'app.js cache                     42.25.80', 'app.js cache                     42.25.81', 'tech app cache')
s = replace_once(s, 'main.mjs cache                   42.25.85', 'main.mjs cache                   42.25.86', 'tech main cache')
s = replace_once(s, '当前验收：run `34681966242`，frontend PASS，Real Chrome **24/24 passed**。', f'当前验收：run `{FULL_RUN}`，frontend PASS，Real Chrome **27/27 passed**。', 'tech current acceptance')
if 'tests/frontend/model-config-prompt-refresh-owner.test.mjs' not in s:
    anchor = 'tests/frontend/paddle-resource-refresh-owner.test.mjs'
    if anchor in s:
        s = s.replace(anchor, anchor + '\ntests/frontend/model-config-prompt-refresh-owner.test.mjs', 1)
block = f'''### R20e — 模型配置 / 提示词 mutation local ownership

R20e 的 source-order audit 证明三条 mutation 仍为最终可达 owner：删除模型配置、保存/编辑提示词模板、删除提示词模板。旧实现均在 mutation 成功后执行 `loadAll()`。其中提示词路径存在真实状态同步错误：当前模型配置页的 loadAll extras 会重载 `modelConfigs`，但不会重载 `promptTemplates`，因此 POST/DELETE 成功后页面仍显示旧提示词状态。

```text
baseline:             {BASELINE}
baseline run:         {BASELINE_RUN} → 1/3 PASS
                       prompt save：成功后新模板未出现在页面
                       prompt delete：成功后旧模板仍留在页面
first migration run:  {FIRST_MIGRATION_RUN} → unit 3/4；仅 wiring guard 转义错误；未提交产品
guard fix:            {GUARD_FIX}
focused run:          {FOCUSED_RUN} → unit 4/4 + Chrome 3/3 PASS
product:              {PRODUCT}
validation:           {VALIDATION}
full run:             {FULL_RUN}
frontend:             PASS
Real Chrome:          27/27 PASS
```

最终 owner：

```text
deleteModelConfigV35     → DELETE → state.modelConfigs local filter → render
savePromptTemplateV35    → POST/PUT authoritative item → state.promptTemplates local upsert → render
deletePromptTemplateV35  → DELETE → state.promptTemplates local filter → render
```

三条永久 Chrome 合同均要求 action 期间 bootstrap=0、model-config GET=0、prompt-template GET=0。R20 mutation refresh debt 继续 **IN PROGRESS**，下一批必须做剩余 `reload/loadAll/loadRelated` 的 final-owner zero-point audit；历史 shadowed code 和用户显式“完整刷新”按钮不得误计为 mutation debt。

附带诊断：full run 中 resource-discovery cache 初始化曾记录一次 `sqlite3.OperationalError: database is locked`，但 27/27 Chrome 全部通过。该问题单独列入 resource-discovery 并发技术债，不影响 R20e 验收结论。'''
s = append_once(s, '### R20e — 模型配置 / 提示词 mutation local ownership', block, 'tech R20e')
p.write_text(s, encoding='utf-8')

# frontend-legacy-audit
p = ROOT / 'docs/frontend-legacy-audit.md'
s = p.read_text(encoding='utf-8')
s = replace_once(s, 'commit:       a21846c33d79612f9ab4a47e2a69195da29caa3b', f'commit:       {VALIDATION}', 'audit acceptance')
s = replace_once(s, 'run:          34681966242', f'run:          {FULL_RUN}', 'audit run')
s = replace_once(s, 'Real Chrome:  PASS (24/24)', 'Real Chrome:  PASS (27/27)', 'audit chrome')
s = replace_once(s, 'app.js                    42.25.80', 'app.js                    42.25.81', 'audit app cache')
s = replace_once(s, 'main.mjs                  42.25.85', 'main.mjs                  42.25.86', 'audit main cache')
s = replace_once(s, 'Current accepted Real Chrome suite: **24/24** in run `34681966242`.', f'Current accepted Real Chrome suite: **27/27** in run `{FULL_RUN}`.', 'audit suite')
block = f'''### R20e — live model-config / prompt mutation refresh retirement

The next source-order audit found three genuinely live mutation owners in the final 模型配置 surface. The old prompt save/delete path was not merely expensive: because model-page extras reload model configs but not prompt templates, its global refresh left prompt UI stale.

```text
baseline:             {BASELINE} / {BASELINE_RUN} → 1/3 PASS
first migration run:  {FIRST_MIGRATION_RUN} → unit 3/4, over-escaped wiring assertion only; no product commit
guard fix:            {GUARD_FIX}
focused:              {FOCUSED_RUN} → unit 4/4 + Chrome 3/3 PASS
product:              {PRODUCT}
validation:           {VALIDATION} / {FULL_RUN}
frontend:             PASS
Real Chrome:          27/27 PASS
```

Live mutation topology is now local/authoritative: model-config delete filters `state.modelConfigs`; prompt save upserts the POST/PUT result into `state.promptTemplates`; prompt delete filters that collection. None of these actions may issue bootstrap/model-config/prompt-template follow-up GETs.

The full run also emitted one non-fatal resource-discovery SQLite `database is locked` during cache initialization. Keep that as a separate concurrency audit target.'''
s = append_once(s, '### R20e — live model-config / prompt mutation refresh retirement', block, 'audit R20e')
p.write_text(s, encoding='utf-8')

# FRONTEND_OWNER_MAP
p = ROOT / 'docs/FRONTEND_OWNER_MAP_V42_25.md'
s = p.read_text(encoding='utf-8')
s = replace_once(s, '> Latest fully accepted code point: `a21846c33d79612f9ab4a47e2a69195da29caa3b` / run `34681966242`', f'> Latest fully accepted code point: `{VALIDATION}` / run `{FULL_RUN}`', 'owner acceptance')
s = replace_once(s, '> Real Chrome: 24/24 passed', '> Real Chrome: 27/27 passed', 'owner chrome')
s = replace_once(s, '| R20d | Paddle activation full reload → training_options-only target refresh | `a21846c3...` / `34681966242` |', f'| R20d | Paddle activation full reload → training_options-only target refresh | `a21846c3...` / `34681966242` |\n| R20e | model-config/prompt full reload + stale prompt UI → authoritative local state ownership | `{VALIDATION[:8]}...` / `{FULL_RUN}` |', 'owner R20 table')
# Add visible owner rows when the expected table exists.
anchor = '| Training-server creation | final `saveServer` → training_options scoped refresh | POST server + GET training_options; replace targets; bootstrap=0 | unit + Chrome request contract |'
if anchor in s and '| Model-config deletion |' not in s:
    addition = anchor + '\n| Model-config deletion | `deleteModelConfigV35` | DELETE + local `state.modelConfigs` removal; no follow-up GET | unit + Chrome request contract |\n| Prompt-template save/edit | `savePromptTemplateV35` | authoritative POST/PUT item + local upsert; no follow-up GET | unit + Chrome request contract |\n| Prompt-template deletion | `deletePromptTemplateV35` | DELETE + local `state.promptTemplates` removal; no follow-up GET | unit + Chrome request contract |'
    s = s.replace(anchor, addition, 1)
block = f'''### R20e — model configuration mutation owners

```text
deleteModelConfigV35
  → DELETE
  → filter state.modelConfigs
  → render

savePromptTemplateV35
  → POST/PUT returns authoritative template
  → upsert state.promptTemplates
  → render

deletePromptTemplateV35
  → DELETE
  → filter state.promptTemplates
  → render
```

Acceptance chain:

```text
baseline:             {BASELINE} / {BASELINE_RUN} → 1/3 PASS, exposed stale prompt UI
first migration run:  {FIRST_MIGRATION_RUN} → product not committed; generated wiring assertion escaped incorrectly
guard fix:            {GUARD_FIX}
focused:              {FOCUSED_RUN} → unit 4/4 + Chrome 3/3 PASS
product:              {PRODUCT}
validation:           {VALIDATION}
full run:             {FULL_RUN}
frontend:             PASS
Real Chrome:          27/27 PASS
```

These mutation owners now have zero bootstrap/model-config/prompt-template follow-up GET fan-out. R20 remains open only pending final zero-point proof across the remaining source-order `reload/loadAll/loadRelated` sites.'''
s = append_once(s, '### R20e — model configuration mutation owners', block, 'owner R20e')
p.write_text(s, encoding='utf-8')

if (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION changed')

print('R20e ledgers synchronized; VERSION remains 42.24.0')
