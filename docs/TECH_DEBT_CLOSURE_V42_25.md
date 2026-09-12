# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整代码验收点：`e3f23f59a4e1513b807490465e94c5558f805c14`**  
> **Frontend Runtime Stabilization：run `34681236515`，frontend + Real Chrome 全绿，Real Chrome 23/23 passed。**  
> **更新日期：2026-09-12**

## 0. 接手入口

按顺序阅读：

1. `docs/TECH_DEBT_CLOSURE_V42_25.md`
2. `docs/CODEX_CURRENT_STATE.md`
3. `docs/frontend-legacy-audit.md`
4. `docs/FRONTEND_OWNER_MAP_V42_25.md`

当前优先级仍是技术债关闭；A800 RC 暂缓。未经用户明确允许，不得 merge `main`、改正式 `VERSION.txt`、tag 或 release。

## 1. 永久退休 surface

以下对象不得恢复为 truth source、bootstrap fallback、timer owner、polling shell、direct navigation owner、historical render owner 或 visible-version owner：

```text
trainingLabelSelected
trainSplitV3
train429Selected
train428AlgorithmId
train428Config
trainingDraftFromLegacyState
auto422Timer
ai60ListTimer
__videoFramePollTimer
__prelabelPollTimer
_oldSetupPollV33
source422Timer
jobPollTimer
setupPagePolling
installVideo424CreationBridge
installSourceCreationBridge
installPollingCreationBridge
__pollRegistryVideoWrapped
__pollRegistrySourceWrapped
__pollRegistryCreationWrapped
originalSetupPagePolling / wrappedSetupPagePolling
registry.adopt('training-jobs', ...)
adoptLegacy / rebindCreation
set423Base
setBase424
baseSetPage
oldSetV39
oldSet42
set422Base
v34/v35/v42.4 direct window.setPage owners
v42.7 direct window.setPage auto-label alias owner
setPageReady414
baseSetPage417
initial bootstrap setPage/window.setPage owner
v42.7 render-level state.page 自动标注 → 自动标注及清洗 mutation
oldRender429
previousRender61
render423Base
renderBase428 shadowed 算法列表 branch
v42.2 render422 legacy 自动标注 route branch
v42.4 renderBase424 legacy 自动标注 route branch
renderBase424 shadowed 算法列表 / 数据集 / 训练任务 branches
renderAutoLabel424 legacy 自动标注 self-refresh timeout/predicate
baseRender417 visible-version correction wrapper
baseRender417 120/600/1600ms version correction timers
12 historical app.js delayed versionBadge startup writers
main.mjs applyBuildVersion visible-version owner
main.mjs 80/500/1800/3600/8000ms visible-version writers
render426base page-render file-input beautification wrapper
render426base requestAnimationFrame page beautification callback
modal426 modal file-input beautification wrapper
modal426 requestAnimationFrame modal beautification callback
enhancePageV37 compatibility helper
requestAnimationFrame(enhancePageV37) page callback
enhancePageV37 modal normalization callback
baseRenderV37 duplicate versionInfo wrapper
baseModalV37 autofocus compatibility wrapper
v35/v36/V37 80/100/120ms startup render/version timers
bounded 100ms renderTop/cleanup startup timer
oldZip412 ZIP completion capture + body-wide ZIP-review MutationObserver
transport.mode-only material summary page guard / off-page summary request leakage
legacy baseRender + RAF page normalization wrapper
#view post-render MutationObserver
#modalBody normalization MutationObserver
```

## 2. 技术债状态

| 技术债 | 最终 owner / 目标 | 状态 |
|---|---|---|
| training 历史 mirror | `state.trainingDraft` | **CLOSED** |
| `/train/start` 多 owner / readiness | `TrainingSubmitRuntime` | **CLOSED** |
| `/jobs` 重复请求 race | `TrainingTaskRuntime` | **CLOSED** |
| metrics SQLite FD | deterministic close | **CLOSED** |
| training / AutoLabel / video / source polling | named runtime + `PollRegistry` | **CLOSED** |
| `setupPagePolling` / classic polling compatibility | direct managed owners | **CLOSED** |
| classic `setPage` owner family | `NavigationStability` | **CLOSED** |
| navigation alias/readiness/sidebar/apply/persistence | `NavigationStability` + `ui-state.js` | **CLOSED** |
| historical persisted `自动标注` alias | restore-boundary canonicalization | **CLOSED** |
| shadowed historical render generations/branches R2–R7 | bounded later render owners | **CLOSED** |
| legacy AutoLabel424 no-op self-refresh timer | `AutoLabelPollRuntime + PollRegistry` | **CLOSED** |
| visible version multi-owner / delayed writers | formal display owners + internal build metadata split | **CLOSED (R9)** |
| `render426base` page post-render wrapper | `cleanup(root)` page post-render owner | **CLOSED (R10)** |
| `modal426` modal post-render wrapper | `cleanup(root)` + `modalBody` MutationObserver | **CLOSED (R11)** |
| `enhancePageV37` post-render normalization helper | `cleanup(root)` table/panel normalization | **CLOSED (R12)** |
| `baseRenderV37` duplicate versionInfo wrapper | later `V42` render versionInfo owner | **CLOSED (R13)** |
| `baseModalV37` autofocus compatibility wrapper | base `modal()` autofocus | **CLOSED (R14)** |
| v35/v36/V37 startup render/version timers | final `queueMicrotask → __clInit` startup owner | **CLOSED (R15)** |
| body-wide ZIP review observer / persisted result race | `completeZipImportReview412` explicit completion owner | **CLOSED (R16)** |
| off-page material summary timer requests | page-scoped `refreshSummary61` | **CLOSED (R16)** |
| page normalization baseRender/RAF/view observer | final `PostRenderNormalizationRuntime.apply` | **CLOSED (R17)** |
| bounded 100ms startup cleanup timer | final `__clInit → render → PostRenderNormalizationRuntime` | **CLOSED (R18)** |
| `#modalBody` normalization observer | `ModalContentRuntime.replace` + synchronous `PostRenderNormalizationRuntime` | **CLOSED (R19)** |
| remaining historical render/post-render overrides | bounded semantic owners | **IN PROGRESS** |
| `app.js` dead code | bounded shell + named runtimes | **IN PROGRESS** |
| algorithm version delete full reload | `AlgorithmListRuntime.refresh` (algorithms + jobs) | **CLOSED (R20a)** |
| model-version publish full reload | authoritative POST result + local state patch | **CLOSED (R20b)** |
| training-server create full reload | POST + training_options-only target refresh | **CLOSED (R20c)** |
| global reload / duplicate request | scoped refresh | **IN PROGRESS (R20)** |
| cache-busting | single strategy | **OPEN** |
| observer/timer/fetch/render lifecycle | explicit owner + destroy | **OPEN** |
| version-number business naming | semantic names | **OPEN** |
| A800 RC | acceptance runbook | **DEFERRED** |

## 3. Canonical owners

### Training

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ POST /api/v12/projects/{project_id}/train/start
```

### Polling

```text
training-jobs → PollRegistry + TrainingTaskRuntime
AutoLabel      → AutoLabelPollRuntime + PollRegistry
video          → PollRegistry(video-frames)
sources        → PollRegistry(sources)
```

### Navigation

```text
window.setPage = NavigationStability.stableSetPage
  → normalizeNavigationPage()
  → PageRequestScope / navigation epoch
  → PollRegistry.beforeNavigate
  → waitForNavigationReady()
  → beforeInvokeNavigation()
  → performNavigation(page)
       state.page = page
       render()
  → PageRequestScope.alignPage
  → PollRegistry.afterNavigate
  → persistUiState()
```

`static/app.js` must contain zero classic `window.setPage=` owners.

### Visible version / build metadata — R9 final split

```text
formal VERSION.txt                    42.24.0
static/index.html initial badge       v42.24.0
top visible badge owner               top412 / V412 = 42.24.0
sidebar visible footer owner          nav426 / V426 = 42.24.0
internal UI build metadata            UI_BUILD_VERSION = 42.25.0-dev
internal metadata sink                document.documentElement.dataset.uiBuild
```

`UI_BUILD_VERSION` is not a user-visible version owner.

### File-input beautification — R10/R11 final owner

```text
page render
→ final render owner
→ PostRenderNormalizationRuntime.apply(#view)
→ cleanup(#view)
   → window.beautifyFileInputs426?.(root)

modal content write
→ ModalContentRuntime.replace(root, html)
→ if root.id === 'modalBody': PostRenderNormalizationRuntime.apply(root)
→ cleanup(root)
   → window.beautifyFileInputs426?.(root)
```

`render426base` 与 `modal426` 均已物理退休。文件选择器美化不再依赖两个历史 RAF compatibility wrapper。

## 4. Current live render / post-render owners

Confirmed live; do not remove as whole wrappers without a new semantic migration proof:

```text
oldRender412      → 算法列表 / 数据集
renderBase428     → 训练任务
renderTraining423 → 当前训练页 + direct PollRegistry activation
renderBase427     → 自动标注及清洗
renderBase424     → 质量中心 / 视频切帧
oldRenderV39      → deployment conversion/artifact/resource/plugin/component
render414Base     → 标签管理
finalRender       → 素材存储配置 + final page normalization dispatch
PostRenderNormalizationRuntime.apply / cleanup(root)
                  → page normalization + table/file-input cleanup
ModalContentRuntime.replace(root, html)
                  → explicit modal/preview/review content + #modalBody normalization
base modal()       → modal first-editable-field autofocus
completeZipImportReview412 → explicit successful ZIP completion review
refreshSummary61           → paged 数据集-only material summary requests
```

Remaining audit candidates:

```text
older base/global render generations still reachable through delegates
global reload / loadAll / loadRelated request ownership
```

`baseRender417`、`render426base`、`modal426` 均已退休，不再是 live audit candidate。

## 5. Current cache/build facts

```text
app.js cache                     42.25.79
main.mjs cache                   42.25.84
visible formal version           42.24.0
internal UI build metadata       42.25.0-dev
navigation-stability.js          422511
ui-state.js                      422500
poll-registry.js                 422511
training-draft-runtime.js        422516
training-labels.js               422513
auto-label-poll-runtime.js       422501
material-pagination-runtime.js   422206
TrainingSubmitRuntime            training-submit-422504
TrainingTaskRuntime              training-task-runtime-422503
```

Cache-busting 仍未统一；这与 visible version ownership 是不同技术债。

## 6. 永久合同

Frontend：

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
tests/frontend/ui-state.test.mjs
tests/frontend/render-alias-restore.test.mjs
tests/frontend/render-owner-retirement.test.mjs
tests/frontend/version-marker-owner.test.mjs
tests/frontend/file-input-beautification-owner.test.mjs
tests/frontend/post-render-normalization-owner.test.mjs
tests/frontend/startup-render-owner.test.mjs
tests/frontend/lifecycle-event-ownership.test.mjs
tests/frontend/algorithm-version-refresh-owner.test.mjs
tests/frontend/algorithm-version-publish-owner.test.mjs
tests/frontend/training-server-refresh-owner.test.mjs
tests/frontend/auto-label-poll-runtime.test.mjs
```

R9 永久要求：

- `baseRender417` 不得回归；
- classic delayed `versionBadge` startup writers 不得回归；
- `main.mjs` 不得通过 `UI_BUILD_VERSION` 写 `#versionBadge` 或 `.nav-footer b`；
- `applyBuildVersion` 不得回归；
- 初始可见版本必须是 `v42.24.0`；
- internal UI build metadata 可保留 `42.25.0-dev`，但只能作为内部 metadata。

R10/R11 永久要求：

- `render426base` 不得回归；
- `modal426` 不得回归；
- 两个历史 `requestAnimationFrame(...beautifyFileInputs426...)` callback 不得回归；
- `cleanup(root)` 必须继续调用 `window.beautifyFileInputs426?.(root)`；
- `#view` cleanup observer 已在 R17 退休，不得回归；页面 cleanup 必须保持 final-render-owned；
- `#modalBody` normalization observer 已在 R19 退休，不得回归；modal replacement 必须由 `ModalContentRuntime` 显式拥有；
- `测试发布` 的 `#predFile` 必须继续获得 `native-file426 + filepicker426` 行为；
- 动态 modal 中普通 file input 必须继续获得同等 filepicker 行为。

Browser：

Real Chrome 当前锁定 stale request fencing、managed polling、sidebar、页面持久化、legacy alias、AutoLabel polling、素材存储、算法/训练/素材性能路径、formal version 稳定性，以及 page/modal 文件选择器美化行为。

R12 永久要求：

- `enhancePageV37` 不得回归；
- `requestAnimationFrame(enhancePageV37)` 不得回归；
- `cleanup(root)` 必须继续统一处理 `table.table → .table-wrap`；
- `cleanup(root)` 必须继续移除“使用建议”等历史提示 panel；
- `baseRenderV37` 已在 R13 退休，不得回归；
- later `V42` render 继续承担 render-path formal `state.versionInfo.version=42.24.0`；
- `baseModalV37` 已在 R14 退休；首个可编辑字段 autofocus 由 base `modal()` 唯一承担；
- v35/v36/V37 的 80/100/120ms startup render/version timer 已在 R15 退休；
- startup dispatch 必须继续由 `queueMicrotask(()=>{if(window.__clInit)window.__clInit()})` 与 final `__clInit` 路径承担；
- bounded `setTimeout(()=>{renderTop();cleanup(document);},100)` 已在 R18 退休，不得回归；startup/page normalization 均由 readiness-aware final render owner 承担。

当前验收：run `34681236515`，frontend PASS，Real Chrome **23/23 passed**。

### R16 — event-owned ZIP completion + page-scoped material summary

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

### R17 — final page normalization ownership

R17 removed the remaining page-side triple ownership (`baseRender` wrapper + page RAF cleanup + `#view` MutationObserver). Source-order proof showed the storage wrapper is the final `render` assignment in `static/app.js`, so page normalization now runs exactly once after the final render path through the named `PostRenderNormalizationRuntime`. Modal normalization remains independently owned by the `#modalBody` observer and was intentionally not changed in this batch.

```text
product:         4fc5d90a15ef2fc2dc22aa00f39967deba6f53f8
validation:      c3301d065fa820539873a4fa2f739992ef63f3d2
guard alignment: f5b8ff8789de0f51d2a03bcabe126191005ba24c
full run:        34669152742
frontend:        PASS (179/179)
Real Chrome:     19/19 PASS
```

The first full validation correctly exposed one stale structure-bound storage-owner unit assertion; the product behavior was not reverted. The guard was tightened to require one storage route owner plus one final page-normalization call, then the full suite passed.

### R18 — bounded startup cleanup timer retirement

R18 retired the remaining readiness-bypassing `setTimeout(()=>{renderTop();cleanup(document);},100)` wakeup. Final startup already waits for the v53 snapshot/current-page refresh and then calls the final `render()`, while R17 made that final render the sole page-normalization dispatch. The modal observer was deliberately left untouched because post-open base-modal body mutations still depend on normalization.

```text
product:    1572fdf4fad6e0fe8d10b5253a236722e85b3495
validation: 954e9dba9c891ecd5c7f21144cf00d8664c11620
run:        34670319479
frontend:   PASS
Real Chrome: 19/19 PASS
```


### R19 — explicit modal content ownership

R19 retired the last active DOM normalization observer. A permanent Real Chrome baseline first locked a real post-open base-modal refresh path (后台导入任务 → 刷新). Modal content writes now go through `ModalContentRuntime.replace(root, html)`. When `root.id === 'modalBody'`, that owner synchronously invokes `PostRenderNormalizationRuntime.apply(root)`; preview/review rewrites also route through the same content replacement owner. `static/app.js` now contains zero active `MutationObserver` constructions.

```text
baseline:   6f5fac4313d23083c6bbe9e2a3b8a5284cd49583
product:    1bb210fbb10a7bee9f5b875d0dd6016187c1ef72
validation: f60d00096a0929a63d0370494ef1f1d489f54ca3
run:        34670989473
frontend:   PASS
Real Chrome: 20/20 PASS
```


### R20a — algorithm version deletion scoped refresh

R20 started the global `reload() → loadAll() → loadRelated()` request-debt migration with one proven-live mutation path. The algorithm version delete modal behavior was locked first. The final `delVersion` owner now performs the DELETE and delegates refresh to `AlgorithmListRuntime.refresh({render:true})`, which owns only algorithms + jobs. The browser contract permanently forbids the datasets/images/labels/training-environment/bootstrap request fan-out on this path while allowing unrelated background owners such as the import-job poll to run independently.

```text
baseline:   55f21733121d1280be66548ef4bb13c1c3810737
product:    22c552d27928375dd51081eb152dc25b1554ec18
validation: 103d630b24bd1aad77190149291c4c9f25e8ab75
run:        34677761599
frontend:   PASS
Real Chrome: 21/21 PASS
app.js:     42.25.77
main.mjs:   42.25.82
```

This closes only the version-delete refresh path. R20/global reload debt remains **IN PROGRESS** and must continue mutation-domain by mutation-domain.

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

## 7. Recent render/lifecycle acceptance history

```text
alias restore-boundary fix
  e35a29b0... / 34656747269 PASS

oldRender429 retirement
  0455eeef... / 34659041402 PASS

previousRender61 retirement
  69732d9e... / 34659543452 PASS

render423Base retirement
  58ece59e... / 34659775870 PASS

renderBase428 algorithm branch retirement
  6be679b6... / 34660269685 PASS

legacy 自动标注 render route retirement
  66339fc0... / 34663089996
  Chrome 14/14 PASS

renderBase424 shadowed route retirement
  2d9bc0b3... / 34663389819
  Chrome 14/14 PASS

legacy AutoLabel424 self-refresh timer retirement
  70b6f755... / 34663768606
  Chrome 14/14 PASS

R9 version-marker final validation
  36fd25c48a2251d1b4a85583921c00dd98bf33fb / 34664755130
  frontend PASS / Real Chrome 15/15 PASS

R10 file-input page-owner behavior baseline
  6b67497ae43a32edf343fc7dec49f7b3824c1088
  focused Chrome PASS

R10 product
  b9d25955c185aaabb4108f3d37cfecd9f876390a

R10 final validation
  0dacf581da4acb52312f75eb7e85e6b334e060db / 34665470320
  frontend PASS / Real Chrome 16/16 PASS

R11 modal file-input behavior baseline
  d2aa614870a52864e991502c2218134943afb14f
  focused Chrome PASS

R11 product
  8ff8e7fd9dc055b6e413c273cc030e7f20a2f0c1

R11 final validation
  9bad939a70bc85c75b0897ee7b4d5a21fb2ab9d1 / 34665890699
  frontend PASS / Real Chrome 17/17 PASS

R12 post-render normalization behavior baseline
  6ae19dc79abbf690371a71162c97a2df6322518b
  focused Chrome PASS

R12 product
  202a5a82b0cb4629423ee0c6812f649031234daa

R12 final validation
  60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29 / 34666673017
  frontend PASS / Real Chrome 18/18 PASS

R13 product
  928d2387d46a0472bd202bd4df84af8d1573b6c2

R13 final validation
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

所有对应一次性 baseline/migration helper/workflow 均已在验收后物理删除；永久 tests 保留。

## 8. 下一批：global reload / request ownership audit

R17–R19 已把 active normalization observers 清零。R20a 已关闭算法版本删除的全量 reload；R20b 关闭测试发布模型归属版本后的全量 reload；R20c 又把训练服务器接入后的 bootstrap+extras 刷新收敛为 training_options 单域刷新。R20 仍需继续审计其他 live mutation owner，并逐域迁移全量刷新债务；不允许靠缓存或测试放宽掩盖重复请求。

`oldRenderV39` 与 `render414Base` 已确认 live，不得因为版本号旧就直接删。

执行规则：

1. 先证明 exact source order、capture/reference 和 page/modal coverage；
2. 对 live 语义先补 unit/Chrome；
3. 只删除 fully shadowed generation/branch，或先迁移 live 语义再删除；
4. 语义迁移必须先有行为合同；
5. 每刀 full frontend + Real Chrome；
6. 不允许通过放宽测试换取删除成功。

## 9. 后续顺序

```text
A. continue R20 global reload / loadAll / loadRelated mutation-domain migration
B. proven dead app.js/runtime-shell cleanup
C. cache-busting unification
D. MutationObserver/timer/fetch/render/setPage zero-point scan
E. semantic naming + deterministic test cleanup
F. technical-debt zero-point scan
G. A800 RC
```

## 10. 发布禁令

正式 `v42.25.0` 前必须：技术债无未解决 P0/P1、Frontend Runtime 与 Release Regression 全绿、A800 preflight/首训/迭代/worker fencing 实机全绿，并取得用户明确 merge/version/tag/release 授权。