# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整代码验收点：`60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29`**  
> **Frontend Runtime Stabilization：run `34666673017`，frontend + Real Chrome 全绿，Real Chrome 18/18 passed。**  
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
| remaining historical render/post-render overrides | bounded semantic owners | **IN PROGRESS** |
| `app.js` dead code | bounded shell + named runtimes | **IN PROGRESS** |
| global reload / duplicate request | scoped refresh | **OPEN** |
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
→ later post-render cleanup wrapper
→ cleanup(#view)
   → window.beautifyFileInputs426?.(root)

modal body mutation
→ modalBody MutationObserver
→ cleanup(addedNode)
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
finalRender       → 素材存储配置
cleanup(root)     → post-render normalization + table wrapping + page/modal file-input beautification
baseRenderV37      → state.versionInfo formal-version compatibility write only
baseModalV37       → modal first-editable-field autofocus only
```

Remaining audit candidates:

```text
baseRenderV37      state.versionInfo compatibility write only
baseModalV37       autofocus only
post-render cleanup wrapper + view/modalBody MutationObserver lifecycle
body-wide ZIP-review MutationObserver
older base/global render generations still reachable through delegates
```

`baseRender417`、`render426base`、`modal426` 均已退休，不再是 live audit candidate。

## 5. Current cache/build facts

```text
app.js cache                     42.25.69
main.mjs cache                   42.25.73
visible formal version           42.24.0
internal UI build metadata       42.25.0-dev
navigation-stability.js          422511
ui-state.js                      422500
poll-registry.js                 422511
training-draft-runtime.js        422516
training-labels.js               422513
auto-label-poll-runtime.js       422501
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
- `view` 与 `modalBody` 的 cleanup observer contract 在生命周期重构完成前必须保持；
- `测试发布` 的 `#predFile` 必须继续获得 `native-file426 + filepicker426` 行为；
- 动态 modal 中普通 file input 必须继续获得同等 filepicker 行为。

Browser：

Real Chrome 当前锁定 stale request fencing、managed polling、sidebar、页面持久化、legacy alias、AutoLabel polling、素材存储、算法/训练/素材性能路径、formal version 稳定性，以及 page/modal 文件选择器美化行为。

R12 永久要求：

- `enhancePageV37` 不得回归；
- `requestAnimationFrame(enhancePageV37)` 不得回归；
- `cleanup(root)` 必须继续统一处理 `table.table → .table-wrap`；
- `cleanup(root)` 必须继续移除“使用建议”等历史提示 panel；
- `baseRenderV37` 当前只保留 `state.versionInfo` 写入，在独立证明前不得顺带删除；
- `baseModalV37` 当前只保留首个可编辑字段 autofocus，在独立证明前不得顺带删除。

当前验收：run `34666673017`，**18/18 passed**。

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
```

所有对应一次性 baseline/migration helper/workflow 均已在验收后物理删除；永久 tests 保留。

## 8. 下一批：remaining render/lifecycle owner audit

优先独立审计：

```text
baseRenderV37     state.versionInfo compatibility write only
baseModalV37      modal first-field autofocus only
cleanup wrapper   post-render cleanup + view/modalBody MutationObserver lifecycle
body observer     ZIP import review MutationObserver
```

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
A. baseRenderV37 / baseModalV37 / cleanup+observer owner audit
B. app.js dead code + global reload/request debt
C. cache-busting unification
D. MutationObserver/timer/fetch/render/setPage zero-point scan
E. semantic naming + deterministic test cleanup
F. technical-debt zero-point scan
G. A800 RC
```

## 10. 发布禁令

正式 `v42.25.0` 前必须：技术债无未解决 P0/P1、Frontend Runtime 与 Release Regression 全绿、A800 preflight/首训/迭代/worker fencing 实机全绿，并取得用户明确 merge/version/tag/release 授权。