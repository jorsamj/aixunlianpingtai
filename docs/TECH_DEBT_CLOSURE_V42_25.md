# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **工作分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整前端验收代码点：`7dbe7414767ed2808d17cc61a85c4897054391b1`。**  
> **Frontend Runtime Stabilization run `34609355389`：syntax + 永久 guards + 全量 frontend unit + Real Chrome 全绿。**  
> **更新日期：2026-09-11**

## 0. 后续 AI / Codex 强制入口

阅读顺序：

1. `docs/TECH_DEBT_CLOSURE_V42_25.md`
2. `docs/CODEX_CURRENT_STATE.md`
3. `docs/frontend-legacy-audit.md`

规则：先清技术债，再恢复 A800 RC；未经用户允许不得 merge `main` / bump `VERSION.txt` / tag / release。

永久退休、不得恢复为 truth source 或 bootstrap fallback：

```text
trainingLabelSelected
trainSplitV3
train429Selected
train428AlgorithmId
train428Config
trainingDraftFromLegacyState
```

永久禁止：

- TrainingDraftRuntime 重新接管 classic function wrapper；
- TrainingLabelRuntime 重新接管 start/refresh classic wrapper；
- 用 `setTimeout` fan-out / rebind timer 修训练标签 UI；
- DraftRuntime 从 `.training-label-contract` 控件事件做 generic sync；
- AutoLabelPollRuntime 包装 `renderOps427`、自建 rebind timer 或恢复 `auto422Timer / ai60ListTimer`。

## 1. 技术债总表

| ID | 技术债 | 最终 owner / 目标 | 状态 | 当前证据 / 下一步 |
|---|---|---|---|---|
| TD-01 | `trainingLabelSelected` | `trainingDraft.newLabelCodes` | **CLOSED** | active app + core modules 零引用；CI + Chrome |
| TD-02 | `trainSplitV3` | `trainingDraft` split/material fields | **CLOSED** | canonical-only |
| TD-03 | `train429Selected` | `TrainingDraftRuntime.materialIds` | **CLOSED** | picker/质量/计数 canonical-only |
| TD-04 | `train428AlgorithmId` | `trainingDraft.algorithmId` | **CLOSED** | 无 bootstrap fallback |
| TD-05 | `train428Config` | `trainingDraft.config/resource` | **CLOSED** | settings canonical-only |
| TD-06 | `/train/start` 多 owner | `TrainingSubmitRuntime` | **CLOSED** | classic 直发清零；永久 guard |
| TD-07 | submit readiness 多 owner | `TrainingSubmitRuntime` | **CLOSED** | Chrome 真提交通过 |
| TD-08 | `/jobs` poll/manual 双请求 | `TrainingTaskRuntime` | **CLOSED** | 120ms coalescing；mutation force-fresh |
| TD-09 | metrics SQLite FD | deterministic close | **CLOSED** | unit + Linux FD regression |
| TD-10 | training task polling lifecycle | `TrainingTaskRuntime + PollRegistry` | **CLOSED** | 单 owner |
| TD-11 | auto-label polling lifecycle | `AutoLabelPollRuntime + PollRegistry` | **CLOSED** | `auto422Timer/ai60ListTimer` 零残留；Runtime wrapper/timer-free；Chrome PASS |
| TD-12 | video legacy polling | VideoTasks / PollRegistry | **OPEN** | `__videoFramePollTimer` 待退役 |
| TD-13 | `auto422Timer` / prelabel / `setupPagePolling` | named runtimes | **IN PROGRESS** | `auto422Timer` CLOSED；prelabel/setupPagePolling 待清 |
| TD-14 | historical render/setPage overrides | 每页面单 owner | **OPEN** | owner 表待建 |
| TD-15 | `app.js` 历史死代码 | named runtimes + bounded shell | **IN PROGRESS** | training + AutoLabel owner 已收口 |
| TD-16 | 一次性 migration helper | 无长期 owner | **CLOSED** | 用完即删 |
| TD-17 | cache-busting 不统一 | 单一策略 | **OPEN** | app `42.25.44`; main `42.25.49` |
| TD-18 | 全局 reload/重复请求 | scoped refresh | **OPEN** | 扫 `loadAll/loadRelated/loadCore412` |
| TD-19 | observer/timer/fetch/render 生命周期 | 明确 owner + destroy | **OPEN** | zero-point 扫描待做 |
| TD-20 | 版本号业务命名 | semantic names | **OPEN** | owner 收口后迁移 |
| TD-21 | 测试历史债 | deterministic tests | **IN PROGRESS** | owner/race/DOM/polling deterministic tests 已补 |
| TD-22 | 文档漂移 | 三份权威文档 | **IN PROGRESS** | 每 runtime 批次同步 |
| TD-23 | A800 RC | A800 acceptance runbook | **DEFERRED** | 技术债阶段后恢复 |
| TD-24 | TrainingDraft/TrainingLabel classic wrappers | direct canonical UI lifecycle | **CLOSED** | Draft + Label 均 wrapper-free；Label timer-free；Chrome PASS |

## 2. 当前 canonical training owner

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ POST /api/v12/projects/{project_id}/train/start
```

版本事实：

```text
app.js cache                     42.25.44
main.mjs cache                   42.25.49
training-draft.js                422506
TrainingDraftRuntime             422516 / training-draft-runtime-422516
TrainingLabelRuntime             422513 / module-422513
TrainingSubmitRuntime            training-submit-422504
TrainingTaskRuntime              training-task-runtime-422503
AutoLabelPollRuntime             422501 / auto-label-poll-422501
```

## 3. TrainingDraft / TrainingLabel：CLOSED

TrainingDraftRuntime：wrapper-free、`networkOwner=false`、`classicWrapperOwner=false`。`.training-label-contract` 事件明确不进入 generic Draft sync。

TrainingLabelRuntime：wrapper-free、timer-free、canonical-only。只读写 `trainingDraft.materialIds / newLabelCodes`；纯标签勾选只更新 canonical state 与计数，不重建正在操作的 checkbox DOM。MutationObserver 仅用于外层 modal DOM 被旧代码重绘时恢复面板。

Chrome 已覆盖：素材选择、标签切换、最终 submit payload、第二次同算法训练 session reset。

## 4. AutoLabel polling：CLOSED

最终 owner：

```text
app renderOps427
  ├─ label tab render complete → AutoLabelPollRuntime.activate(annotationTasks60)
  └─ clean tab              → AutoLabelPollRuntime.deactivate()
AutoLabelPollRuntime
→ PollRegistry key: auto-label-v60
→ one-shot refreshRows()
→ active task only re-arm
```

物理退役：

```text
auto422Timer (2500ms interval)
ai60ListTimer (1800ms timeout)
AutoLabelPollRuntime renderOps427 wrapper
__autoLabelPollRuntimeWrapped
originalRenderOps / wrappedRenderOps
100/400/1000ms rebind timers
```

Runtime diagnostics：

```text
classicWrapperOwner=false
timerOwner=false
```

永久 CI `AutoLabel PollRegistry owner guard` 要求：

- `static/app.js` 中 `auto422Timer / ai60ListTimer` 为 0；
- v60 renderer 必须显式 `activate()`；clean tab 必须显式 `deactivate()`；
- Runtime 不得出现 renderer wrapper、rebind timer、`setTimeout/clearTimeout`；
- build 保持 `auto-label-poll-422501` 契约，除非同步升级测试/cache。

Real Chrome 继续验证：任务行局部更新、`#view` 不被 polling 替换、PollRegistry delay=1800、切页立即清除 `auto-label-v60`。

## 5. 最近完整验收

```text
acceptance commit: 7dbe7414767ed2808d17cc61a85c4897054391b1
Frontend Runtime Stabilization: 34609355389
syntax: PASS
retired-mirror guard: PASS
canonical network-owner guard: PASS
TrainingDraft wrapper/owner guard: PASS
TrainingLabel canonical lifecycle guard: PASS
AutoLabel PollRegistry owner guard: PASS
frontend unit: PASS
Real Chrome runtime regressions: PASS
```

## 6. 当前清理顺序

```text
A. __videoFramePollTimer → PollRegistry / named video lifecycle owner
B. prelabel legacy timer + old setupPagePolling
C. renderer/setPage owner table + old override physical deletion
D. app.js dead code + global reload/request debt
E. cache-busting 统一
F. observer/timer/fetch/render/setPage zero-point
G. semantic naming + deterministic tests + docs
H. 技术债 zero-point scan
I. A800 RC
```

已确认下一批事实：v33 `setupPagePolling` 会叠加 `__videoFramePollTimer=setInterval(refreshVideoTasksOnly,2500)`；`__prelabelPollTimer` 当前只发现 legacy clear 引用。不要把 video/prelabel 混成盲删，先分别证明最终 owner。

每批必须：owner 证明 → regression → 物理删除 → syntax/unit → Real Chrome（行为受影响时）→ 更新总账。

## 7. 发布禁令

正式 `v42.25.0` 前必须全部满足：

- 本总账无未解决 P0/P1；
- Frontend Runtime Stabilization 全绿；
- Release Regression 全绿；
- A800 preflight PASS；
- A800 首训 + verify-job PASS；
- A800 迭代 + verify PASS；
- Worker lifecycle/fencing 实机 PASS；
- 用户明确允许 merge/version/tag/release。
