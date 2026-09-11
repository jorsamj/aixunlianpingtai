# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **工作分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整前端验收代码点：`4a86f4b497abb024daa9927c7be54e75fcea3692`。**  
> **Frontend Runtime Stabilization run `34610390049`：syntax + 永久 guards + 全量 frontend unit + Real Chrome 全绿。**  
> **更新日期：2026-09-11**

## 0. 后续 AI / Codex 强制入口

阅读顺序：

1. `docs/TECH_DEBT_CLOSURE_V42_25.md`
2. `docs/CODEX_CURRENT_STATE.md`
3. `docs/frontend-legacy-audit.md`

规则：先清技术债，再恢复 A800 RC；未经用户允许不得 merge `main` / bump `VERSION.txt` / tag / release。

永久退休、不得恢复为 truth source / bootstrap fallback / timer compatibility：

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
```

永久禁止：

- TrainingDraftRuntime 重新接管 classic function wrapper；
- TrainingLabelRuntime 重新接管 start/refresh classic wrapper；
- 用 timer fan-out/rebind 修训练标签 UI；
- DraftRuntime 从 `.training-label-contract` 控件事件做 generic sync；
- AutoLabelPollRuntime 包装 `renderOps427`、自建 rebind timer；
- PollRegistry / NavigationStability 再为已退休的 auto-label/video/prelabel timer 名称做兼容清理。

## 1. 技术债总表

| ID | 技术债 | 最终 owner / 目标 | 状态 | 当前证据 / 下一步 |
|---|---|---|---|---|
| TD-01 | `trainingLabelSelected` | `trainingDraft.newLabelCodes` | **CLOSED** | active app + core modules 零引用 |
| TD-02 | `trainSplitV3` | canonical split/material fields | **CLOSED** | canonical-only |
| TD-03 | `train429Selected` | `TrainingDraftRuntime.materialIds` | **CLOSED** | picker/质量/计数 canonical-only |
| TD-04 | `train428AlgorithmId` | `trainingDraft.algorithmId` | **CLOSED** | 无 fallback |
| TD-05 | `train428Config` | `trainingDraft.config/resource` | **CLOSED** | settings canonical-only |
| TD-06 | `/train/start` 多 owner | `TrainingSubmitRuntime` | **CLOSED** | classic 直发清零；永久 guard |
| TD-07 | submit readiness 多 owner | `TrainingSubmitRuntime` | **CLOSED** | Chrome 真提交通过 |
| TD-08 | `/jobs` poll/manual 双请求 | `TrainingTaskRuntime` | **CLOSED** | 120ms coalescing；mutation force-fresh |
| TD-09 | metrics SQLite FD | deterministic close | **CLOSED** | unit + Linux FD regression |
| TD-10 | training task polling lifecycle | `TrainingTaskRuntime + PollRegistry` | **CLOSED** | 单 owner |
| TD-11 | AutoLabel polling lifecycle | `AutoLabelPollRuntime + PollRegistry` | **CLOSED** | legacy timers/wrapper/rebind 全退役；Chrome PASS |
| TD-12 | video legacy polling | `video424Timer → PollRegistry(video-frames)` | **CLOSED** | `__videoFramePollTimer` 物理退役；Chrome one-shot PASS |
| TD-13 | auto-label/prelabel/v33 timer compatibility | named runtime + PollRegistry | **CLOSED** | `auto422Timer/__prelabelPollTimer/_oldSetupPollV33` 零残留 |
| TD-14 | historical render/setPage/setupPagePolling overrides | 每页面单 owner | **IN PROGRESS** | 当前下一批：PollRegistry creation bridges + old setupPagePolling |
| TD-15 | `app.js` 历史死代码 | named runtimes + bounded shell | **IN PROGRESS** | training/AutoLabel/v33 timer层已收口 |
| TD-16 | 一次性 migration helper | 无长期 owner | **CLOSED** | 用完即删 |
| TD-17 | cache-busting 不统一 | 单一策略 | **OPEN** | app `42.25.45`; main `42.25.50` |
| TD-18 | 全局 reload/重复请求 | scoped refresh | **OPEN** | 扫 `loadAll/loadRelated/loadCore412` |
| TD-19 | observer/timer/fetch/render 生命周期 | 明确 owner + destroy | **OPEN** | zero-point 扫描待做 |
| TD-20 | 版本号业务命名 | semantic names | **OPEN** | owner 收口后迁移 |
| TD-21 | 测试历史债 | deterministic tests | **IN PROGRESS** | owner/race/DOM/polling tests 已补 |
| TD-22 | 文档漂移 | 三份权威文档 | **IN PROGRESS** | 每批同步 |
| TD-23 | A800 RC | A800 acceptance runbook | **DEFERRED** | 技术债阶段后恢复 |
| TD-24 | TrainingDraft/TrainingLabel classic wrappers | direct canonical lifecycle | **CLOSED** | wrapper-free；Chrome PASS |

## 2. 当前关键 owners

### Training

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /api/v12/projects/{project_id}/train/start
```

### AutoLabel

```text
renderOps427 label tab
→ AutoLabelPollRuntime.activate()
→ PollRegistry(auto-label-v60)
→ one-shot refreshRows()
```

### Video frame tasks

```text
renderVideo424 / refreshVideo424Delta
→ state.video424Timer
→ PollRegistry(video-frames)
→ managed one-shot 2000 ms
```

旧 `__videoFramePollTimer` 已不存在。视频 Real Chrome 验证：表格行局部更新、`#view` 不替换、切页清除 managed key。

## 3. 当前版本事实

```text
app.js cache                     42.25.45
main.mjs cache                   42.25.50
navigation-stability.js          422504
poll-registry.js                 422508
training-draft-runtime.js        422516
training-labels.js               422513
auto-label-poll-runtime.js       422501
TrainingSubmitRuntime            training-submit-422504
TrainingTaskRuntime              training-task-runtime-422503
```

## 4. 本轮关闭：legacy poll timer compatibility

已从产品运行代码物理删除：

```text
auto422Timer
__videoFramePollTimer
__prelabelPollTimer
_oldSetupPollV33
```

同步删除：

- PollRegistry 对这些名字的 adopt/clear/retire compatibility；
- NavigationStability fallback 对这些名字的 clear；
- v33 `setupPagePolling` 仅用于 video/prelabel interval 的覆盖层；
- 对应测试 fixture/历史断言。

永久 CI `Retired legacy poll timer compatibility guard` 要求上述 token 在：

```text
static/app.js
static/modules/poll-registry.js
static/modules/navigation-stability.js
```

全部为 0，同时要求当前 `replaceVideo424Timer` managed owner 仍存在。

## 5. 最近完整验收

```text
acceptance commit: 4a86f4b497abb024daa9927c7be54e75fcea3692
Frontend Runtime Stabilization: 34610390049
syntax: PASS
retired training mirror guard: PASS
canonical network-owner guard: PASS
TrainingDraft wrapper/owner guard: PASS
TrainingLabel canonical lifecycle guard: PASS
AutoLabel PollRegistry owner guard: PASS
retired legacy poll timer compatibility guard: PASS
frontend unit: PASS
Real Chrome runtime regressions: PASS
```

## 6. 下一清理顺序

```text
A. old setupPagePolling / PollRegistry creation bridges：逐 owner 改成显式 lifecycle
B. render/setPage final-owner table + obsolete override physical deletion
C. app.js dead code + global reload/request debt
D. cache-busting 统一
E. MutationObserver/timer/fetch/render/setPage zero-point
F. semantic naming + deterministic tests + docs
G. 技术债 zero-point scan
H. A800 RC
```

当前 PollRegistry 仍有历史 bridge：

```text
installPollingCreationBridge()   → wraps setupPagePolling
installVideo424CreationBridge()  → wraps renderVideo424 / refreshVideo424Delta
installSourceCreationBridge()    → wraps renderSources422
rebindCreation()
```

下一步必须逐 owner 证明后改成显式 handoff，不可一次性盲删。

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
