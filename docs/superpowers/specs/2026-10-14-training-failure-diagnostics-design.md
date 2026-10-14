# 训练失败智能诊断设计

## 范围与约束

本批只扩展现有 `failure.json → training_recovery_truth() → TrainingRecoveryRuntime` 链路。诊断事实仍由后端产生，前端只渲染；不新增 API、轮询器、任务 Owner、日志系统、自动重试或资源参数调整。`VERSION.txt` 保持 `42.24.356`。

## 事实模型

Recovery API 在既有返回体中增加 `diagnosis`：

- `code`：稳定错误类别，例如 `HOST_MEMORY_OOM`、`GPU_MEMORY_OOM`、`SIGKILL_CAUSE_UNKNOWN`。
- `certainty`：`confirmed`、`suspected` 或 `unknown`，由后端决定。
- `title`、`summary`：用户可理解的中文结论。
- `evidence`：有界、脱敏、与当前任务关联的证据摘要。
- `possible_causes`：仅在结论未确认时展示的可能原因，不伪装成事实。
- `suggestions`：只给操作建议，不自动改 Batch、Workers、图片尺寸或重新训练。

已有 `primary_error_code`、原始错误、返回码、握手信息、日志和 Checkpoint 合同保留，放入折叠的技术详情。历史任务不回写、不改状态；缺少证据时只能产生未知诊断。

## 证据与分类

优先使用结构化错误码。明确的 CUDA OOM 文本可作为 GPU 显存不足的确认依据。`SIGKILL/-9` 单独出现时只能归为 `SIGKILL_CAUSE_UNKNOWN`。

主机 OOM 只有在 `failure.json` 中存在当前任务生命周期内采集、且与训练进程 PID 关联的 Linux Kernel 证据时才确认为 `HOST_MEMORY_OOM`。采集发生在现有 Worker 发现训练进程异常退出的单次失败路径中，采用时间窗和 PID 精确匹配，只保存结构化摘要；打开详情页不会运行 `journalctl`。无法读取日志、无 PID 命中或只看到无关联的累计计数时不确认 OOM。

若未来已有运行时写入任务关联的 cgroup OOM 结构化证据，API 可识别 `CGROUP_MEMORY_OOM`；累计 `oom_kill > 0` 不作为本次任务的确认依据。

租约丢失、Worker 终止、意外退出、主动取消、准备失败沿用既有错误码，优先级高于通用进程症状，且不会归为 OOM。SQLite `database is locked` 作为独立 Worker 存储故障，不与 OOM 合并。

所有面向 UI 的证据先脱敏：隐藏绝对路径、URL 查询参数、Bearer/API key/token/password 等值，并限制条数与长度。原有工程日志权限边界不在本批扩大。

## UI 信息层级

现有训练详情顶部摘要和四个 Tab 不变。失败区改为：

1. 失败原因（标题、阶段、证据等级、说明）。
2. 诊断依据。
3. 原因未明时的可能原因。
4. 处理建议。
5. Checkpoint 恢复边界。
6. 默认折叠的技术详情。

无可信 Checkpoint 时固定显示“当前没有可恢复的训练断点，需要重新创建训练任务。”；有可信恢复合同才显示既有重新验证按钮。缺失指标继续显示“未生成/未记录”，不转换为零。

## 验收

Python 合同覆盖主机 OOM 证据、纯 SIGKILL、CUDA OOM、租约丢失、取消、历史任务、Checkpoint 和脱敏。Node 合同覆盖后端诊断的原样渲染及成功任务不受影响。Playwright 用真实 Chrome 打开失败详情，核验信息层级、折叠技术详情、无虚假恢复按钮与 1366×768 可用性，并保存截图。
