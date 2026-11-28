# 训练创建与后台准备 P0 堵点收敛（2026-11-03）

## 用户最终需求

正常完成算法训练的「选择素材 → 提交 → 后台核验 → GPU 调度 → Worker 训练」闭环。**不应被无关项目修订、资源选项后台刷新、父子任务半提交、设备遥测短暂缺失等非业务因素误拦截**。仍须严格阻止真实数据缺失、训练/Test 泄漏、GT 与素材真值变更、用户未授权的训练范围以及不满足硬件配置的任务。不能以“无堵点”为由绕过安全检查。

## 本批修复（42.24.515）

| 风险/入口 | 原行为 | 本批行为 | 证据和边界 |
| --- | --- | --- | --- |
| 后台人工确认 | 用户提交后，任何**其他素材**上传或 GT 编辑都会使整个项目修订号变化，Worker 在启动前错误拒绝训练 | 新创建请求签发 `schema_version=2` 的**所选训练+独立 Test** 素材/正式 GT 指纹。Worker 仍在原素材/标注生命周期锁内核对；无关变更不影响，所选真值变更拒绝并不写回执 | `training_label_tasks.py`、`test_training_request.py`；历史在途 v1 凭据继续执行原严格修订号规则，绝不放松既有凭据 |
| 训练创建弹窗 | 已缓存有效目标时，新一轮资源 `loading/error` 导致按钮被禁用，甚至早期阻断 POST | 仅在本次选中的资源目标确实不存在/不可用时阻断；后台选项重读不再无条件覆盖已可用状态 | `training-submit.js`、`training-submit.test.mjs`；模型/引擎/设备/素材真实校验不变 |
| 父子持久任务 | `TRAINING_PREPARE` 已结束而父任务仍为不可认领 `QUEUED`，或 Web 半提交只留父任务 | 原 Worker 维护循环以短批次修复 45 秒后缺少确定性子任务的父任务，复用同一个子任务构造器与相同创建锁；子任务终止而父任务未激活则原子收敛终态，保留失败类别 | `training_prepare_child.py`、`repository.py`、`training_workspace_lifecycle.py`；不触碰已领取 GPU lease、已运行任务或其他任务类型 |
| 取消训练 | 停止父任务时，准备子任务可能继续扫描 GT/素材 | v62 统一任务取消和 v48 训练任务停止同时传递取消至匹配的准备子任务 | `app.py`；不终止身份不匹配的子任务、不停止其他训练 |
| GPU AUTO | 准备期未读到 GPU 遥测时将资源直接冻结为 CPU，而后续 GPU Scheduler 仍按 AUTO 分配 | 自动资源配置改为**延后 GPU 分配**并保留证据；无遥测候选数为零、等待 GPU 回报。不能安全延后的手动 AUTO 配置明确返回 `RESOURCE_GPU_TELEMETRY_UNAVAILABLE`，不静默改成 CPU | `remote_training_tasks.py`、`test_local_auto_resource_admission.py`；仍需实际 A800/GPU Agent 验证 |

## 验收项目与进度

- [x] 后台确认：无关素材变更通过；所选素材/正式 GT 变更阻断；不批量污染原始 GT；旧 v1 规则兼容（新增 API 回归，CI 待跑）。
- [x] 弹窗已缓存可用目标与资源重读竞态：训练提交模块 Node 回归 64/64 通过。
- [x] 父任务缺子任务的 45s 超时恢复、子任务取消后父任务终态收敛：新增隔离单测，CI 待跑。
- [x] GPU AUTO 无遥测延后调度：新增隔离单测，CI 待跑。
- [x] Python `compileall` 与 `git diff --check`。
- [ ] 远端 GitHub Actions 在本批准确提交 SHA 上全绿：推送后检查。
- [ ] 生产 A800 使用真实 fire/smoke 任务完成完整训练、保存权重、质量评测、历史 Test 隔离验收：**尚未执行，不能宣称生产零堵点**。
- [ ] 实际页面首屏、素材选择器 30s Stalled 与下载/缓存成本的性能测量：本批用户要求暂不进行性能专项，独立跟进。

## 本地验证说明

此工作容器没有 `pytest`、`filelock` 等 Python 运行依赖，因此新增后端回归仅可静态编译，不能声称 Python 用例本地全绿。完整前端 Node 运行 1506 项，1500 通过，6 项因缺失 `@uppy/core` 或未安装的 Annotorious/Uppy 官方依赖无法本地运行；训练提交模块 64/64 通过。本批不得把环境缺依赖写成业务通过，也不得关闭 CI/生产待办。

## 风险控制与操作约束

只在 `feature/external-algorithm-publishing` 分支提交；不 merge main、不 tag/release、不 force push；不运行生产素材迁移、清理、训练、Worker 重启、GT 写入或数据修复。未完成的真实生产闭环验收由部署后的可观测日志/实际样本证据决定，而非仅由代码提交决定。
