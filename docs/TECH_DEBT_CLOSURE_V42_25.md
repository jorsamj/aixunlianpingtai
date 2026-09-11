# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整代码验收点：`eb76e48adaafe3c71556918d42efc98cca5d8f2f`**  
> **Frontend Runtime Stabilization：run `34620286461`，frontend + Real Chrome 全绿。**  
> **更新日期：2026-09-11**

## 0. 接手入口

按顺序阅读：
1. `docs/TECH_DEBT_CLOSURE_V42_25.md`
2. `docs/CODEX_CURRENT_STATE.md`
3. `docs/frontend-legacy-audit.md`
4. `docs/FRONTEND_OWNER_MAP_V42_25.md`

先清技术债，再恢复 A800 RC；未经用户明确允许，不得 merge `main`、改正式 `VERSION.txt`、tag 或 release。

## 1. 永久退休 surface

不得恢复为 truth source、bootstrap fallback、timer owner、polling shell 或 compatibility wrapper：

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
baseSetPage (V37 duplicate mobile-sidebar wrapper)
oldSetV39
oldSet42
set422Base
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
| v42.3 pass-through + unused v42.4 base capture | later router | **CLOSED** |
| duplicate V37 mobile-sidebar setPage | V417 `baseSetPage417` | **CLOSED** |
| pre-v42.4 dead setPage family (`oldSetV39/oldSet42/set422Base`) | later direct reset | **CLOSED** |
| remaining historical render/setPage overrides | semantic final router + bounded render owners | **IN PROGRESS** |
| `app.js` dead code | bounded shell + named runtimes | **IN PROGRESS** |
| cache-busting | single strategy | **OPEN** |
| global reload / duplicate request | scoped refresh | **OPEN** |
| observer/timer/fetch/render lifecycle | explicit owner + destroy | **OPEN** |
| version-number business naming | semantic names | **OPEN** |
| A800 RC | acceptance runbook | **DEFERRED** |

## 3. Current canonical owners

### Training

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ POST /api/v12/projects/{project_id}/train/start
```

### Training polling

```text
classic render call site
→ replaceTrainingJobTimer()
→ PollRegistry(training-jobs)
→ TrainingTaskRuntime.refresh({source:'poll'})
→ focused /jobs update
```

### Navigation

最终 classic live chain 的受保护 owner：

```text
v42.7 route owner / later router semantics
→ setPageReady414   (startup snapshot/uiReady gate)
→ baseSetPage417    (mobile sidebar close)
→ NavigationStability (outer runtime coordinator)
```

V37 duplicate sidebar wrapper 已删；Real Chrome 明确验证 sidebar/backdrop 在最终导航时关闭。

### AutoLabel / Video / Sources

```text
renderOps427 → AutoLabelPollRuntime → PollRegistry(auto-label-v60)
renderVideo424 / refreshVideo424Delta → PollRegistry(video-frames)
renderSources422 → PollRegistry(sources)
```

## 4. Current cache/build facts

```text
app.js cache                     42.25.52
main.mjs cache                   42.25.53
navigation-stability.js          422506
poll-registry.js                 422511
training-draft-runtime.js        422516
training-labels.js               422513
auto-label-poll-runtime.js       422501
TrainingSubmitRuntime            training-submit-422504
TrainingTaskRuntime              training-task-runtime-422503
```

Cache-busting 仍未统一。

## 5. Permanent guards / tests

主 frontend workflow owner guards + `tests/frontend/*.test.mjs`。

新增永久静态合同：

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
```

浏览器合同：

```text
tests/browser/navigation-stability.spec.mjs
→ delayed request cannot jump back
→ managed polling stops on leave
→ final navigation closes mobile sidebar + backdrop
```

## 6. Latest acceptance

```text
commit: eb76e48adaafe3c71556918d42efc98cca5d8f2f
run:    34620286461

syntax                                       PASS
all permanent owner guards                   PASS
frontend unit incl. retired setPage guards   PASS
Real Chrome                                  PASS
```

该结果证明删除 `oldSetV39 / oldSet42 / set422Base` 后现有导航、训练、轮询、算法列表、素材分页等浏览器回归均未退化。

## 7. Current next task — pre-v42.7 direct-assignment family

删除上一批后，`static/app.js` 当前 `window.setPage=` 静态入口缩到 7 个。可见的赋值包括：

```text
initial function setPage(...) → window.setPage=setPage
old UI-state persistence direct assignment
v35 direct state.page/render assignment
v42.4 direct state.page/render assignment
v42.7 direct auto-label alias assignment
setPageReady414 async readiness wrapper
baseSetPage417 sidebar wrapper
```

关键控制流：v42.7 又执行一次**不调用 previous owner 的直接赋值**：

```js
window.setPage=function(p){
  state.page=p==='自动标注'?'自动标注及清洗':p;
  render();
};
```

所以 v42.7 之前的 UI-state direct assignment、v35 direct assignment、v42.4 direct assignment 很可能都已被同步覆盖，最终不在 live chain。

下一批不是直接删，而是先证明：

```text
1. 这些 direct assignment 之间没有在初始化阶段必须执行的 setPage 调用依赖
2. v42.7 assignment 确实在它们之后同步执行
3. 最终 saveUiState / page alias / route 行为由当前 owner 或 render lifecycle 持有
4. setPageReady414、baseSetPage417、NavigationStability 必须保留
5. 删除后全量 unit + Real Chrome 继续全绿
```

## 8. 后续顺序

```text
A. pre-v42.7 dead direct setPage assignments
B. remaining render/setPage obsolete layers
C. app.js dead code + global reload/request debt
D. cache-busting unification
E. MutationObserver/timer/fetch/render/setPage zero-point scan
F. semantic naming + deterministic test cleanup
G. technical-debt zero-point scan
H. A800 RC
```

## 9. 发布禁令

正式 `v42.25.0` 前必须：技术债无未解决 P0/P1、Frontend Runtime 与 Release Regression 全绿、A800 preflight/首训/迭代/worker fencing 实机全绿，并取得用户明确 merge/version/tag/release 授权。
