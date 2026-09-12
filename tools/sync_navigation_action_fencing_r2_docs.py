from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'

ACCEPTED = '3a8781dccf6704fe76d35d99c05b80590dc507c3'
PRODUCT = '9f6df85b994f23b5408759fb64485b9477c75936'
MIGRATION_RUN = '34721629224'
FRONTEND_RUN = '34721755310'
ACTION_RUN = '34721755316'


def update(path: Path, replacements: list[tuple[str, str]]) -> None:
    text = path.read_text(encoding='utf-8')
    for old, new in replacements:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f'{path}: expected exactly one match, got {count}: {old[:120]!r}')
        text = text.replace(old, new, 1)
    path.write_text(text, encoding='utf-8')


tech = DOCS / 'TECH_DEBT_CLOSURE_V42_25.md'
update(tech, [
    (
        '> **最近完整代码验收点：`7fcfcaec0b088a851dbcd580ac226b3dd892fa83`**  ',
        f'> **最近完整代码验收点：`{ACCEPTED}`**  ',
    ),
    (
        '> **Frontend Runtime Stabilization：run `34702374386`，frontend + Real Chrome 全绿，Real Chrome 32/32 passed；Navigation Action Fencing 永久 run `34702374346` 全绿；Resource Discovery SQLite 永久跨平台 run `34700900542` Ubuntu + Windows 全绿。**  ',
        f'> **Frontend Runtime Stabilization：run `{FRONTEND_RUN}`，frontend + Real Chrome 全绿，Real Chrome 32/32 passed；Navigation Action Fencing 永久 run `{ACTION_RUN}` 全绿；Resource Discovery SQLite 永久跨平台 run `34700900542` Ubuntu + Windows 全绿。**  ',
    ),
    (
        '| Navigation Action Fencing R1 — training-server/Paddle + targeted direct page writes | `NavigationStability.action` + epoch/token fence | **CLOSED (R1); overall action fencing IN PROGRESS** |',
        '| Navigation Action Fencing R1 — training-server/Paddle + targeted direct page writes | `NavigationStability.action` + epoch/token fence | **CLOSED (R1)** |\n| Navigation Action Fencing R2 — final M4 model save/test + clean confirm + v60 AI review completion | live owner action fence before UI/state commit | **CLOSED (R2)** |\n| Navigation Action Fencing remaining upload/deployment/timer/callback completions | final async-action zero-point | **IN PROGRESS** |',
    ),
    (
        '**边界：整个 Navigation Action Fencing 仍为 IN PROGRESS。** R1 只关闭训练服务器/Paddle 与本批 direct-page-write surface；最终 Model Config 427、AI 标注/清洗确认、图片/ZIP/XHR upload completion、deployment mutation、其他 timer/callback family 尚未全部迁移，不能宣称 stale async UI side effect 全局为 0。下一批为 **R2：最终 Model Config / AI 清洗与 modal mutation completion**。',
        f'''**R1 边界已由 R2 继续收口。** R2 已关闭最终模型配置、清洗确认与 v60 AI review completion；图片/ZIP/XHR upload completion、deployment mutation、其他 timer/callback family 仍需 final scan，因此全局 stale-async zero-point 仍为 IN PROGRESS。\n\n### Navigation Action Fencing R2 — final Model Config / clean / v60 AI completion CLOSED\n\n真实 source-order/liveness 审计确认最终 owner 不是历史命名：模型配置保存由 `saveVisionModelM4` 负责；清洗确认最终为 `confirmClean429`，`confirmClean427` 仅兼容别名；AI 最终提交由 v60 `completeAiReview60(mode)` 负责，`confirmAiLabel427` 仅兼容到 `completeAiReview60('partial')`。\n\n旧代码 Real Chrome baseline 真实复现了慢 mutation 完成后关闭/覆盖新页面 modal 的问题（M4 保存、最终清洗确认、v60 AI review completion）；模型连接测试 completion 同批通过 source contract 迁移并永久锁定。最终所有这些 owner 都在请求前捕获 `NavigationStability.action(state.page)`，并在 `await` 返回后、任何 state/DOM/modal/render/toast side effect 前检查 `action.isCurrent()`。\n\n清洗确认不再 `loadRelated()` broad refresh，而是使用后端 authoritative `deleted_ids + processed_ids` 精确更新本地素材。v60 AI review 保持 durable `/api/v60/.../annotation-tasks/{{id}}/decisions` + `commit:true` 合同，只有当前 action 仍有效时才执行 `applyTaskResult/closeModal/toast/renderOps427`。\n\n```text\nbaseline / migration run: {MIGRATION_RUN}\nproduct:                  {PRODUCT}\ncleanup / permanentize:   {ACCEPTED}\nFrontend Runtime:         {FRONTEND_RUN}\nfull Real Chrome:         32/32 PASS\npermanent Action Fencing: {ACTION_RUN} PASS\nformal VERSION.txt:       42.24.0 unchanged\napp.js cache:             42.25.90\nmain.mjs cache:           42.25.89\nNavigationStability:      422512\n```\n\n永久合同：\n\n```text\ntests/frontend/navigation-action-fencing-r2.test.mjs\ntests/browser/navigation-action-fencing-r2.spec.mjs\n.github/workflows/navigation-action-fencing.yml\n```\n\nR2 一次性 migration helper/workflow 已物理删除。**R2 本批 CLOSED；整个 Navigation Action Fencing final zero-point 仍未 CLOSED。**''',
    ),
])

state = DOCS / 'CODEX_CURRENT_STATE.md'
update(state, [
    ('latest full code acceptance: 7fcfcaec0b088a851dbcd580ac226b3dd892fa83', f'latest full code acceptance: {ACCEPTED}'),
    ('Frontend Runtime run:        34702374386', f'Frontend Runtime run:        {FRONTEND_RUN}'),
    ('app.js cache:                42.25.88', 'app.js cache:                42.25.90'),
    (
        'Run `34702374386` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after Navigation Action Fencing R1 migration-artifact cleanup. Browser navigation runs **32 tests and passed 32/32**. Permanent Action Fencing workflow `34702374346` is green; permanent Resource Discovery SQLite workflow `34700900542` remains green on Ubuntu and Windows. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.',
        f'Run `{FRONTEND_RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after Navigation Action Fencing R2 migration-artifact cleanup. Browser navigation runs **32 tests and passed 32/32**. Permanent Action Fencing workflow `{ACTION_RUN}` is green; permanent Resource Discovery SQLite workflow `34700900542` remains green on Ubuntu and Windows. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.',
    ),
    (
        'Navigation Action Fencing R2 — final Model Config / AI-cleaning modal mutations\n→ resume R20 final global reload/request zero-point\n→ external algorithm catalog read-only boundary\n→ separate Resource Lifecycle production soak / non-SQLite resource classes\n→ ZIP 10k / training progress / GPU tuner / deployment artifact E2E\n→ app.js/app.py normalization\n→ backend regression\n→ A800 RC',
        'R20 final global reload/request zero-point\n→ Unified Task Progress + Durable Queue Runtime productionization\n→ Navigation Action Fencing final scan (upload/ZIP/deployment/timer-callback completions)\n→ external algorithm catalog read-only boundary\n→ separate Resource Lifecycle production soak / non-SQLite resource classes\n→ ZIP 10k / training progress / GPU tuner / deployment artifact E2E\n→ app.js/app.py normalization\n→ backend regression\n→ A800 RC',
    ),
    (
        '**边界：整个 Navigation Action Fencing 仍为 IN PROGRESS。** R1 只关闭训练服务器/Paddle 与本批 direct-page-write surface；最终 Model Config 427、AI 标注/清洗确认、图片/ZIP/XHR upload completion、deployment mutation、其他 timer/callback family 尚未全部迁移，不能宣称 stale async UI side effect 全局为 0。下一批为 **R2：最终 Model Config / AI 清洗与 modal mutation completion**。',
        f'''**R1 已由 R2 继续收口。** R2 关闭最终 M4 模型保存/连接测试、最终清洗确认和 v60 AI review completion；upload/ZIP/deployment/timer-callback completion 仍留给 final scan，因此全局 stale-async zero-point 仍为 IN PROGRESS。\n\n### Navigation Action Fencing R2 — final Model Config / clean / v60 AI completion CLOSED\n\n最终 live owner：\n\n```text\nsaveVisionModelM4\ntestModelConfigV35\nconfirmClean429  (confirmClean427 compatibility alias)\ncompleteAiReview60(mode)  (confirmAiLabel427 compatibility alias)\n```\n\n所有 completion 在异步请求前捕获 `NavigationStability.action(state.page)`，在请求返回后、提交 state/DOM/modal/render/toast 前拒绝 stale action。`confirmClean429` 使用 authoritative `deleted_ids + processed_ids` 做 local patch，已移除 broad `loadRelated()`；v60 AI review 保持 `taskApi(review.id)/decisions` + `commit:true` durable contract。\n\n```text\nbaseline / migration run: {MIGRATION_RUN}\nproduct:                  {PRODUCT}\ncleanup / permanentize:   {ACCEPTED}\nFrontend Runtime:         {FRONTEND_RUN}\nfull Real Chrome:         32/32 PASS\npermanent Action Fencing: {ACTION_RUN} PASS\nformal VERSION.txt:       42.24.0 unchanged\napp.js cache:             42.25.90\nmain.mjs cache:           42.25.89\n```\n\n永久合同为 `tests/frontend/navigation-action-fencing-r2.test.mjs`、`tests/browser/navigation-action-fencing-r2.spec.mjs`，并已合并进唯一长期 `.github/workflows/navigation-action-fencing.yml`。一次性 R2 helper/workflow 已物理删除。''',
    ),
])

legacy = DOCS / 'frontend-legacy-audit.md'
update(legacy, [
    ('commit:       7fcfcaec0b088a851dbcd580ac226b3dd892fa83', f'commit:       {ACCEPTED}'),
    ('run:          34702374386', f'run:          {FRONTEND_RUN}'),
    ('app.js                    42.25.88', 'app.js                    42.25.90'),
    (
        'R1 action fencing adds `NavigationStability.action(ownerPage) → token/isCurrent/commit` for mutation-completion ownership. Real Chrome proved the old `saveServer` could close a modal created after navigation; that stale side effect is now fenced. Product `8269eb0cca84ea310f48ee13af34ab09dd1bfeff`, follow-up `01234ef186f3e57bef2d29ac19420952beef6c36`, cleanup `7fcfcaec0b088a851dbcd580ac226b3dd892fa83`, full run `34702374386` **32/32**, permanent Action Fencing run `34702374346` PASS. R1 is closed; global stale-async zero-point is not. R2 targets final Model Config / AI-cleaning modal mutation families.',
        f'R1 action fencing adds `NavigationStability.action(ownerPage) → token/isCurrent/commit` for mutation-completion ownership. R2 extends the same commit fence to the true final `saveVisionModelM4`, `testModelConfigV35`, `confirmClean429`, and v60 `completeAiReview60` owners. Clean confirmation now uses authoritative `deleted_ids + processed_ids` local patching instead of broad `loadRelated()`, and v60 AI review keeps the durable `taskApi(review.id)/decisions` + `commit:true` contract. R2 product `{PRODUCT}`, cleanup/permanentization `{ACCEPTED}`, full run `{FRONTEND_RUN}` **32/32**, permanent Action Fencing run `{ACTION_RUN}` PASS. R1 and R2 are closed; global stale-async zero-point is still not closed because upload/ZIP/deployment/timer-callback completion families remain for the final scan.',
    ),
])

owners = DOCS / 'FRONTEND_OWNER_MAP_V42_25.md'
update(owners, [
    ('> Latest fully accepted code point: `7fcfcaec0b088a851dbcd580ac226b3dd892fa83` / run `34702374386`  ', f'> Latest fully accepted code point: `{ACCEPTED}` / run `{FRONTEND_RUN}`  '),
    (
        'Navigation Action Fencing R1 is also accepted: `NavigationStability.action(ownerPage)` owns stale mutation commit checks for the migrated surface. `saveServer` no longer closes/redraws UI after leaving its owner page; targeted direct fixed-page business writes are zero. Product `8269eb0cca84ea310f48ee13af34ab09dd1bfeff`, follow-up `01234ef186f3e57bef2d29ac19420952beef6c36`, cleanup `7fcfcaec0b088a851dbcd580ac226b3dd892fa83`; permanent run `34702374346` PASS; full Real Chrome `34702374386` **32/32**. Overall async-action zero-point remains IN PROGRESS; R2 targets final Model Config / AI-cleaning modal mutations.',
        f'Navigation Action Fencing R1+R2 are accepted. `NavigationStability.action(ownerPage)` owns stale mutation commit checks for the migrated surfaces. R2 locks the true final model/config and review owners: `saveVisionModelM4`, `testModelConfigV35`, `confirmClean429` (`confirmClean427` compatibility alias), and v60 `completeAiReview60` (`confirmAiLabel427` compatibility alias). Clean confirmation is local-state-only from authoritative `deleted_ids + processed_ids`; v60 AI commit remains `taskApi(review.id)/decisions` with `commit:true`. Product `{PRODUCT}`, cleanup/permanentization `{ACCEPTED}`; permanent run `{ACTION_RUN}` PASS; full Real Chrome `{FRONTEND_RUN}` **32/32**. Overall async-action zero-point remains IN PROGRESS only for the remaining upload/ZIP/deployment/timer-callback completion families.',
    ),
])

print('R2 docs synchronized')
