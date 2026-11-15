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

**本阶段不新增 Supervisor 生产开关或新业务页面**。现有模型转换页仍以中央任务为权威；此前不应提供可点击但无可信停止证据的生产入口。随后在全仓浏览器回归中确实定位到独立的 Annotorious 首画缺陷，因此对已有标注组件进行了范围明确的前端运行时修复与真实 Chrome 回归；未改标注 GT API、审核提交流程或任务页面状态所有权。

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


## 第二次精确 CI 路径合同修复（2026-11-15）

代码 SHA `c3062b2eeaec0ce6a9549ca0c9a06c7c19bda8a9` 的 Ubuntu CI 已通过 /var/lib 新目录创建、findmnt 挂载检查、固定版本包安装，但在 `sudo chown -R root:root /run/changlian-onnxruntime-cpu-pilot` 阶段发现两处未同步的旧 chown/chmod 目标，报文件不存在。**仍未执行原生 NumPy/ORT 导入与真实推理，不能声称迁移验收。** 本轮仅将同一步骤残留的两处权限目标修正到受信任的 /var/lib 目录，保留所有 root 权限、安全启动和真推理验证。新 SHA 再验。


## CI 前端历史问题的真实根因与精准修复（2026-11-15）

代码 SHA `4734f8e2cf3e23d3b321bf14be110b82cc9d77a9`：23 个 GitHub Actions 中 22 成功，Frontend Runtime Stabilization 唯一失败；失败 Job `132860731622`（browser-navigation shard 1）为 130 passed / 1 failed：`tests/browser/annotorious-poc.spec.mjs:48` 在 5 秒内未收到 `createAnnotation`。

通过失败 Job 上传的实际 Playwright `trace.zip` 确认，在**第一次鼠标画框松开**时，浏览器发生真实 `pageError`：

`TypeError: Cannot read properties of undefined (reading 'created')`
发生在官方离线 Annotorious 3.9.5 的历史合并函数 `fs`，其调用者在 `performance.now() <= 250 ms` 且历史数组为空时，试图与不存在的历史记录合并。标注几何数据已创建、但 `createAnnotation` 事件链中断，因此不是单纯的测试等待时长问题。

**处理原则：修根因，不掩盖红灯，不升级不审计的新版本。**

- 保持已固定的 Annotorious 3.9.5 与许可证。仅在 `tools/vendor_annotorious.mjs` 从**精确核验上游 SHA256** 的发行文件生成本地资产时，补一条 `o.length===0` 的空历史守卫；历史非空时保持原 250 ms 合并行为。Vendor 文件变更量仅一条表达式，其他源文件及许可证原样保留。
- `static/vendor/annotorious/manifest.json` 明确记录上游原始 SHA256、唯一 patch site、原/新表达式及补丁后文件长度/摘要；NOTICE 明示本地补丁，不再声称与官方 JS 字节完全一致。`annotorious.js.map` 保留官方原文件并明确标注补丁后的偏移可能与源映射不同。
- `tests/frontend/annotorious-assets.test.mjs` 继续通过真实离线 `vendor_annotorious.mjs --check` 核验可重现性，并验证补丁出处、哈希、长度及新 JS 缓存键。
- `tests/browser/annotorious-poc.spec.mjs` 新增**真实 Chrome 快速首画**回归，在独立 PoC 页面明确把第一笔历史时钟固定在 100 ms（小于 250 ms），仍通过真实鼠标事件创建矩形、要求对外 `createAnnotation` 事件且无 JS pageError。不改变业务 GT / 候选审核语义。
- 正式浏览器入口 `static/modules/annotorious-editor.js` 的 vendor JS URL 仅变更缓存标识为 `?v=3.9.5-history1`，确保后续部署更新时不会沿用旧已缓存脚本，CSS/生产任务无变化。

本修复仅涉及前端离线三方组件的**一个历史空栈边界**及回归测试；没有把测试超时改大、跳过/删除失败用例，也没有修改 `AgentConversionRunner`、GT API、中央任务、GPU、A800 或 4070。**新的完整 CI 需按实际准确 SHA 再验，不可借先前 2D-2C3 23/23 宣称本次全绿。**


## 2D-2D1 最终验收决定（2026-11-15）

**最终准确功能代码 SHA：`aaaf108fccfc9a6cfd257e7bac98aaa02f029f41`。** 已逐项从 GitHub Actions API 核验：本 SHA 触发的 **22 项 workflow 全部 `completed/success`（22/22，失败 0）**；不同提交的工作流触发数可因路径过滤不同，不得把之前 2D-2C3 的 23/23 当成本轮数据。

- Node Agent Executor：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43731887384 — **Windows / Ubuntu / API 3 个 Job 全部成功**。Windows 651 passed / 7 skipped；Ubuntu 核心合同 **656 passed / 2 skipped**，另有实际固定 CPU systemd、真实 ORT CPU 推理、非 root Agent→HTTP→root Unix→systemd 的隔离集成测试均成功。
- Frontend Runtime Stabilization：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43731880003 — **frontend + 三个 Chrome browser-navigation Job 全部成功**。Browser shard 1：128 passed；shard 2：130 passed；shard 3：125 passed。shard 1 明确运行新增 `first rectangle during an empty history under 250ms still emits createAnnotation` 回归，且成功；旧完整画框/移动/缩放/几何像素回归也成功。
- 远程转换业务回归：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43731887406 — SUCCESS；远程训练业务回归：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43731887387 — SUCCESS；其余本 SHA 工作流也全部成功。
- 本轮 vendor JS 为本地**审计单点补丁**，并非完全原样的官方 dist：固定上游 SHA256 `66a2ac75...`，补丁后 SHA256 `9bdfd343...`；可通过 `tools/vendor_annotorious.mjs --check` 重建验证，完整审计字段保存在 manifest/NOTICE 中。未经审计不得引入新的第三方版本或移除这条保护。

**阶段结论：2D-2D1（只读适配合同与受控输入预检）PASS，关闭。** 这是开发和 CI 验收，不是生产操作确认；`AgentConversionRunner` 仍使用既有 legacy 机制，未接入真实 Supervisor 模型转换；无 GPU StopReceipt/自动重派、无 Ubuntu 22.04/systemd249 兼容保证，`supervisor-required` 生产仍禁止打开。A800、双4070 没有操作。

**下一阶段 2D-2D2：** 基于这版已通过的合同，再做独立的可信 CPU 模型执行 profile、OS handle 持久化、原中央租约与运行期停止/结果上传事务的完整真实联调；坚持最小范围修改，先验收再考虑前端可见状态或生产部署。
