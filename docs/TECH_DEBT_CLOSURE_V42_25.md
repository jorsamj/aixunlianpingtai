# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整代码验收点：`ceab780b8f3d8314061d852bf2eccc8db9235f54`**  
> **Frontend Runtime Stabilization：run `34644092284`，frontend + Real Chrome 全绿。**  
> **更新日期：2026-09-12**

## 0. 接手入口

按顺序阅读：
1. `docs/TECH_DEBT_CLOSURE_V42_25.md`
2. `docs/CODEX_CURRENT_STATE.md`
3. `docs/frontend-legacy-audit.md`
4. `docs/FRONTEND_OWNER_MAP_V42_25.md`

先清技术债，再恢复 A800 RC；未经用户明确允许，不得 merge `main`、改正式 `VERSION.txt`、tag 或 release。

## 1. 永久退休 surface

不得恢复为 truth source、bootstrap fallback、timer owner、polling shell、direct navigation owner 或 compatibility wrapper：

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
v34 window.setPage(...saveUiState...)
v35 window.setPage(state.page/render)
v42.4 window.setPage(state.page/render)
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
| pre-v42.7 direct setPage family (v34/v35/v42.4) | v42.7 route + final navigation runtime | **CLOSED** |
| navigation UI state persistence | `NavigationStability` + `ui-state.js` | **CLOSED** |
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

当前受保护语义链：

```text
initial bootstrap setPage binding
→ v42.7 route/alias owner
→ setPageReady414        startup snapshot/uiReady gate
→ baseSetPage417         mobile sidebar close
→ NavigationStability    outer runtime coordinator
   ├─ PageRequestScope / navigation epoch
   ├─ PollRegistry before/after navigation
   └─ persistUiState() → ui-state.js
```

已确认的真实语义：

- `自动标注` → `自动标注及清洗` alias 仍由 v42.7 owner 持有；
- `setPageReady414` 在 `uiReady=false` 时等待 `__v53InitPromise`；
- `baseSetPage417` 关闭 mobile sidebar/backdrop；
- `NavigationStability` 对 Promise 型导航必须等实际导航完成后才执行 align / afterNavigate / persist；
- `ui-state.js` 是当前页面持久化语义 owner；旧 v34 `setPage(...saveUiState...)` 已退休。

Real Chrome 已验证：sidebar/backdrop 关闭、旧页面请求不得跳回、导航到“数据集”后 localStorage 保存“数据集”且刷新后仍恢复“数据集”。

### AutoLabel / Video / Sources

```text
renderOps427 → AutoLabelPollRuntime → PollRegistry(auto-label-v60)
renderVideo424 / refreshVideo424Delta → PollRegistry(video-frames)
renderSources422 → PollRegistry(sources)
```

## 4. Current cache/build facts

```text
app.js cache                     42.25.53
main.mjs cache                   42.25.54
navigation-stability.js          422507
ui-state.js                      422500
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

永久静态/语义合同：

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
  # 文件名保留历史，但当前语义已升级为 pre-v42.7 direct owner retirement guard
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
tests/frontend/ui-state.test.mjs
```

浏览器合同：

```text
tests/browser/navigation-stability.spec.mjs
→ delayed request cannot jump back
→ managed polling stops on leave
→ final navigation closes mobile sidebar + backdrop
→ selected page persists to localStorage and restores after reload
```

不得为了删除历史代码而放宽上述合同。

## 6. Latest acceptance

```text
commit: ceab780b8f3d8314061d852bf2eccc8db9235f54
run:    34644092284

syntax + ui-state syntax                         PASS
all permanent owner guards                       PASS
pre-v42.7 retirement guard                       PASS
all frontend unit tests                          PASS
Real Chrome runtime regressions                  PASS
```

该验收点证明：

1. v34 persistence direct `setPage`、v35 direct `setPage`、v42.4 direct `setPage` 已物理删除；
2. v42.7 alias、`setPageReady414`、`baseSetPage417` 仍存在；
3. 页面持久化已迁移至最终 `NavigationStability + ui-state.js`；
4. 临时 AST audit / migration helper / workflow 均已物理删除；
5. 删除后导航、轮询、训练、算法列表、素材分页等 Real Chrome 回归均未退化。

### 本批 liveness 证据

临时 Acorn AST 审计在删除前证明：

```text
v34 persist → v35 plain       load-time immediate setPage calls = 0
v35 plain   → v42.4 plain     load-time immediate setPage calls = 0
v42.4 plain → v42.7 alias     load-time immediate setPage calls = 0
```

因此三个 earlier direct owner 在同步脚本完成后均被 v42.7 覆盖，不承担 live-chain 语义。

## 7. Current next task — remaining setPage semantic chain

现在不要再按版本号盲删。剩余需要逐项证明的 setPage 层是：

```text
initial function setPage(...) → window.setPage=setPage
v42.7 alias direct owner
setPageReady414 async readiness wrapper
baseSetPage417 sidebar wrapper
NavigationStability final module wrapper
```

下一批先做 owner/语义表，不直接删除：

```text
A. 初始 bootstrap binding 是否被任何初始化 closure / historical function 捕获并在 v42.7 之后实际使用
B. 将 “自动标注 → 自动标注及清洗” alias 迁入语义化 route owner 是否可行
C. readiness 是否可进入 NavigationStability，而不改变 startup snapshot fencing
D. sidebar close 是否可进入 final navigation runtime，而不改变移动端行为
E. 每迁移一个语义，先补/保留 unit + Real Chrome，再删除对应 classic layer
```

特别注意：alias、readiness、sidebar 三项都有真实业务语义，不得因为 wrapper 数量多就一次性删除。

## 8. 后续顺序

```text
A. remaining setPage semantic-chain consolidation
B. remaining render override owner audit / obsolete layer deletion
C. app.js dead code + global reload/request debt
D. cache-busting unification
E. MutationObserver/timer/fetch/render/setPage zero-point scan
F. semantic naming + deterministic test cleanup
G. technical-debt zero-point scan
H. A800 RC
```

## 9. 发布禁令

正式 `v42.25.0` 前必须：技术债无未解决 P0/P1、Frontend Runtime 与 Release Regression 全绿、A800 preflight/首训/迭代/worker fencing 实机全绿，并取得用户明确 merge/version/tag/release 授权。
