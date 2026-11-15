# 2D-2D1｜转换受限输入与只读 OS Handle 适配合同（2026-11-15）

仓库：jorsamj/aixunlianpingtai。唯一长期开发分支：`feature/external-algorithm-publishing`。
前置 2D-2C3 功能 SHA `12824cbf6e57ad6e434e7789f356bb493ab53a6c` 已核实全仓 **23/23 SUCCESS**；真实 Ubuntu 非 root Agent → 中央 HTTP → root Supervisor → systemd 固定 CPU 服务验收 PASS。生产仍 NO-GO。

## 本轮实际实现（默认不启用）

- 新增 `platform_core/os_supervisor_conversion_adapter.py`：独立、只读合同模块。生产 `node_agent.py`、`AgentConversionRunner`、`app.py` **不导入**。不会改变原中央 `tasks.attempt`、租约 owner、正式结果状态或 GPU 分配。
- `FrozenOnnxInput.from_lease` 只接受 `RemoteExecutionLease` 的 MODEL_CONVERSION/schema v1/object-storage v1/target onnx 受限冻结输入元数据，核验原 task/attempt/worker/node/lease SHA256、ONNX 文件名、精确字节长度和 source_trace 摘要一致性。拒绝 RKNN、PT、路径穿越、任意 argv/shell/cwd/env/unit/GPU/可执行路径字段。**不会访问外部 URL、读取任意本地路径或签发 OS grant。**
- `verify_source_stream` 对已由既有可信数据传输层获得的字节流再核对长度及 SHA256，允许 1 GiB 上界，产出 `VerifiedOnnxBytes` 的是**哈希一致证明**而非 ONNX 格式、推理准确性或运行安全证明。受信任系统不能直接将 Agent 提供的此对象视为 OS 启动凭据。
- `SupervisedConversionHandle.bind_isolated_cpu_pilot` 严格核对现有 `IsolatedCpuNetworkPilot` 原 task/attempt/node/租约及同一个 `SupervisedProcessHandle` 的身份。这一 pilot 真正执行的是 `fixed-cpu-v1` 固定 CPU 测试代码，**并未执行模型转换**。
- `observe` / `read_log_page` 只能读取原 OS 状态和原 InvocationID 日志游标；系统 `EXITED` 包括 exit_code=0 **不代表转换成功**。`request_stop`、`publish_result` 均在缺少可信停止/业务结果证据时明确 HOLD，不暴露 Popen 的 pid/kill/terminate 接口。
- 新增 `tests/unit/test_os_supervisor_conversion_adapter.py`，覆盖长度和哈希变化、任务代数/节点/租约不一致、命令字段注入、GPU/RKNN/PT 禁入、绑定不一致、UNKNOWN/HOLD、状态不误宣布业务成功、停止与发布拒绝。测试加入现有 Node Agent Ubuntu/Windows 合同矩阵；不新增并行 CI 工作流。

## 前端页面结论

**本阶段不修改前端**。尚没有合法可提供给用户的 Supervisor 模型转换开关、可信取消与自动重派能力；显示一个可点击但实际不安全的生产入口会误导。现有转换页继续呈现原中央任务状态，直到受保护业务链路和结果发布事务真正闭环后，再评估是否补只读执行边界状态。

## 不可越过的生产准入

1. 当前 `fixed-cpu-v1` 不能执行正式 ONNX 转换；本阶段仅是安全类型合同与只读适配，并非真正接管 `AgentConversionRunner`。
2. 尚无正式 OS handle 的持久化/重启重连、租约持续监督、可信 StopReceipt、业务模型验收与 prepare/upload/confirm/finalize/finish 闭环，禁止 `supervisor-required`、自动重派或将 OS exit_code 作为业务完成。
3. Ubuntu 22.04/systemd249 不支持现行固定 CPU profile 的 `ExitType=cgroup`，且 GPU/板卡设备 ACL 尚未验收。A800、双4070 不部署、不升级、不重启、不变更任务或素材数据。
4. 不触碰 main、Release/tag，不 force push，所有代码仅写入唯一长期开发分支。

## 准入与准确 SHA 的 CI 闸口

本文件随 2D-2D1 代码作为同一提交。准确新 SHA 的 Ubuntu/Windows/API、前端及全仓 CI 必须另核；不能把上一阶段 2D-2C3 的 23/23 算作本轮成功。

下一步 2D-2D2：由 root-owned 受信任配置建立真实 CPU-only 业务 profile、独立 OS-bound durable identity 和监控桥；对中央原任务租约、停止证明、下载 SHA、日志与原上传确认事务逐项补实测。未完成前不得启用生产执行。


## 首轮 CI 失败与最小修复（2026-11-15）

候选 SHA `a2945e0c4ec3a88dbe207f2e92604bc83a1b63ac` 的 Node Agent Ubuntu 合同测试 **656 passed / 2 skipped**，但既有 2D-2B2 真实 ONNX Runtime CPU 测试导入 `numpy._core._multiarray_umath.so` 时提示 `failed to map segment from shared object`。日志中的文件位于 `/run/changlian-onnxruntime-cpu-pilot/venv`，与挂载 `noexec` 的表现相符，但旧日志未打印实际 mount 选项，故不伪称已证明底层根因。

精确修复：将**仅用于 GitHub 隔离 CI 的 root-owned ORT venv** 迁移至 `/var/lib/changlian-onnxruntime-cpu-pilot/venv`；增加 `/var`、`/var/lib` 的逐级 root owner/权限校验，并在 CI 创建前使用 `findmnt -T` 显式拒绝 noexec。固定的 ONNXRuntime/NumPy 版本、root-only 文件审核、systemd Protected/Sandbox、可信 ONNX 输入存放在 `/run` 不变。继续运行真实 native import 和原 2 条 real ORT systemd 用例，不允许 skip。

本轮仅修改 CI-only runtime 配置、原 unit 断言、原 Node Agent CI 工作流及本文档；正式业务 Runner、前端、A800、4070 均未改变。**新 SHA 的全仓 CI 状态必须另核。**
