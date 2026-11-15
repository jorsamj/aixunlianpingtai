# 2D-2D2B2A｜PT→ONNX CPU 真正转换的输入准入合同（2026-11-16）

## 一、前置与准确范围

长期开发分支 `feature/external-algorithm-publishing`，最新已验收功能 SHA `4495a44fb44f6ed6903b20cd1f659263bf3aa32b`（GitHub Actions 23/23 成功）；前一轮最终文档提交 `3a238eed37564eb1a79e335aa956e30b00dd4a8b`。

此轮将 2D-2D2B2 拆成先验收的 **2B2A：PT 训练权重到 ONNX 导出的不可执行输入合同**。与之前 2B1“已存在 ONNX→ORT CPU 运行验证”严格区分，不能把 ONNX 推理称作 PT 模型转换。本阶段不会真正执行 PT 反序列化或导出，**不代表真实转换已安全投入使用**。

## 二、实际代码改动

1. 新增 `platform_core/os_supervisor_cpu_pt_export_admission.py`，只导入正式的 `RemoteExecutionLease` 数据结构读取既有中央任务权威，不接入正式 `AgentConversionRunner`、`SupervisorService`、`app.py` 或 GPU Runner。
2. `FrozenPtExportAdmission.from_central_lease` 明确限定 MODEL_CONVERSION/schema v1/object-storage-v1/target onnx，原 task_id / `tasks.attempt` / agent worker/node / lease token SHA256 身份；将中央 JSON 中可能携带的下载 URL、凭据等丢弃，不下传 root 侧。
3. 源仅接受明确大小上界内的单份 `.pt`，校验源 SHA256 与 source_trace 一致、HTTPS 下载协议、不可注入额外命令字段；拒绝 `.pth`、`.onnx`、路径穿越、伪造 bool 长度等。
4. 参数严格锁定为 CPU PoC 子集：input_size 属于固定白名单、batch=1、opset=12、dynamic=false、simplify=false；拒绝任意 shell、env、argv、GPU、RKNN、INT8、网络命令或可执行路径。
5. `verify_downloaded_stream` 对**已经通过原合法传输层下载**的字节计算准确长度和 SHA256，不解开 PT pickle、不从 URL 下载、不运行 Python/Ultralytics。哈希一致 **不等于 PT 文件可安全反序列化**；真实权重必须先有受信任来源与受控 runtime 安全约束。
6. `freeze_nonexecutable_manifest` 形成确定顺序、无 URL/密钥/命令的只读输入清单；状态 `execution_authorized=false`、`untrusted_pt_pickle=true`、`result_publish_allowed=false`。还未与 root-owned durable staging、中央短期签名和 journal CAS 绑定。
7. `request_systemd_launch`、`request_result_publish` **始终明确 HOLD**，绝不复用此前 `fixed-cpu-v1` 的签名执行 PT 导出。没有另一套 Agent 内调度器、没有 root 命令拼接、没有直接切换 Supervisor。
8. 新增 `tests/unit/test_os_supervisor_cpu_pt_export_admission.py`：真实 RemoteExecutionLease 数据合同、原租约身份、不可信下载 URL/headers/文件名、禁止任意命令、固定 CPU 参数、任意 hash/size 篡改、pickle 不安全标志、恒定禁启动/禁发布等多类负向用例，进入既有 Node Agent Ubuntu/Windows CI，且 py_compile 同时验证。

## 三、前端与线上影响

本阶段后台无新增用户操作需求，**不改前端页面**，避免提供虚假的“Supervisor 转换已可启用”按钮；任务状态依然以中央 tasks / Runner 为权威。生产 A800、双4070、训练/转换服务和数据库均未接入本模块，也不会重启、部署或修改数据。

## 四、不可越过的闸口

- `fixed-cpu-v1` 现有中央 Ed25519 grant 只签和验证固定 CPU 试运行，**不能被提升为 PT→ONNX profile**。需要另行审计并扩展由**同一个中央任务权威**签发、含 source hash/runner profile/worker 及有效期的授权合同，root journal 绑定且只允许一个 OS handle；不能创造新的调度所有权。
- PT 常含 Python pickle，可加载任意代码；哈希证明仅证明源未改变，不证明 pickle 安全。正式 CPU 运行必须限定受信任权重来源与 root-owned Python/worker/runtime、只读输入、输出隔离、设备和网络限制，先经过 CI 真正的 PT→ONNX 导出及失败注入。
- 中央 lease 失效与取消不能被假定已经停机，必须补真实可信的 StopReceipt、崩溃重连以及原 `prepare/upload/confirm/finalize/finish` 一致性证明，才讨论生产切换。
- Ubuntu 22.04/systemd249、GPU 设备治理仍独立 NO-GO；不改生产开关、不 force-push、不合并 main、不发 Release/tag。

## 五、验收要求与后续

本轮代码的 GitHub CI 需以**本轮新 SHA** 核对 Ubuntu/Windows/API、含真实 systemd ORT E2E 和全仓浏览器回归的终态；不能继承 2B1 的 23/23。

下一步 **2D-2D2B2B**：在相同中央任务发行者和 root 可信身份边界上设计 PT→ONNX 专用 Ed25519 grant（不得复用原 fixed-cpu-v1）、源 SHA 及参数绑定、挑战 nonce 及 journal CAS；然后由独立 root-owned sandbox 执行真实的小型可信 PT 模型导出，在 Ubuntu systemd250+ 隔离 CI 实证，最后考虑 StopReceipt/上传事务。所有启动权仍保持关闭直到这些证据完成。


## 六、最终隔离 CI 验收（2026-11-16）

**代码验收基线：d5e0dc56326d962a49861bb89e6ce93992d8589f。**
GitHub Actions 按完全相同的 head_sha 核查：**23 项工作流全部 completed/success（23/23），失败 0、排队 0、运行中 0**。这是新代码本身的验证结果，不能借用此前 2D-2D2B1 的 23/23。

- Node Agent Executor 主工作流：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43775716044 —— Ubuntu、Windows、API 三个 Job 全部 SUCCESS。同 SHA 第二组：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43775721751，三个 Job 也成功。
- Ubuntu 单元/合同 **791 passed / 2 skipped**；Windows 单元/合同 **786 passed / 7 skipped**；涵盖新增 PT 冻结输入、危险参数拒绝、输入哈希/长度、下载协议与密钥剔除，以及永久禁止启动/发布。另有 Windows Portable cgroup 合同 30 passed / 1 skipped。
- Ubuntu 真实 ORT CPU/systemd 2 passed、固定 CPU systemd 4 passed、非 root Agent→HTTP→root Supervisor→systemd 联调 1 passed；这仍是原有的固定 CPU/现成 ONNX 验证流程，**不是新的 PT→ONNX 导出执行**。
- Remote Conversion Runtime、Remote Training Runtime、AI Annotation Recovery、Remote Cleaning Runtime、数据集/素材、调度等此 SHA 工作流全部成功。
- Frontend Runtime Stabilization：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43775716050 —— frontend + Chrome 三个分组全部成功。Chrome shard1 **128 passed**、shard2 **130 passed**、shard3 **125 passed**。本阶段未修改前端 JS 或 UI 页面。

### 准入决定

**2D-2D2B2A 的 PT→ONNX 原中央租约、已下载源证据、固定 CPU 参数与不可执行清单合同：PASS，关闭最小阶段。**

这**不是** PT→ONNX 真实模型导出验收：request_systemd_launch 仍无条件 HOLD，现有中央签名只承认 fixed-cpu-v1，不能运行真实 PT 反序列化或取代 AgentConversionRunner。更不能以此承诺可信停止、自动重派、模型上传成功、systemd249 兼容或生产部署。

下一步独立实施 2D-2D2B2B：从同一个中央 tasks.attempt/lease 权威扩展严格区分 profile 的短期签名合同与 root-owned journal 预备/启动 CAS，独立测试签名过期、撤销、source hash 不匹配及重复启动，然后在 root-owned CPU sandbox 中进行可信小模型 PT→ONNX **真实**导出；后续再做 StopReceipt 和输出事务。生产 A800/4070 禁止接管或升级。
