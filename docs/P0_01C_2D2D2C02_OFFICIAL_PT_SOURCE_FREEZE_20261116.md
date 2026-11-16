# 2C-02｜模型 PT 来源白名单与 root-owned 冻结验收（2026-11-16）

## 原仓审计与风险边界

- 平台现有 mother_model_assets.py 已包含母模型资产记录，以及官方 YOLO11n/s/m 检测权重的代码内固定发行版本 SHA256 和字节数。上传资产的 registry VERIFIED 是模型能在隔离沙箱解析的证据，并不能证明该 PT pickle 可由 Supervisor 直接反序列化。
- 现有 node_agent_conversion_runtime.py 的 AgentConversionRunner 具有源对象 GET、SHA/size 验证、结果 prepare/upload/confirm/finalize/finish 的生命周期；不得另建第二个业务调度与上传系统。
- 既有 2C-01 功能代码 27875df1fabfa2bb10dd62d9c08c53ebc181980a 已在独立 CI 内完成原中央任务/lease→Ed25519 新签名→原 journal CAS→CPU/systemd 真实 PT→ONNX 测试。唯一 PT 是 CI 本地生成随机模型，尚未实际测试官方远端权重。

## 本轮实施

1. 新增 platform_core/os_supervisor_pt_official_source.py，直接复用母模型资产内的官方 SHA/size 白名单。仅允许 **source_name/source_sha256/source_size_bytes 三元组全部精确匹配固定官方版本**。不能由 Agent 自己提交一个哈希就创建“可信版本”。
2. 文件预检：O_NOFOLLOW、安全普通文件/唯一 inode、完整字节数量与 hash、读前读后元数据稳定性、ZIP/PT 容器结构。只检查字节，不执行 torch.load 或 Ultralytics；文件路径本身不构成授权。
3. 仅隔离 CPU/systemd pilot 新增 stage_pinned_official_checkpoint：将已按固定 SHA 验证的官方源码从不可信下载缓存**流式复制到 root-owned 隔离目录**，再次对复制后源校验，记录来源 origin 和只读 manifest，0444 + fsync。rebind/launch 继续复核完整只读文件与固定来源。
4. 2C-01 的 CI-only bridge 保留原中央 task/attempt/lease/source、单次新签名与原 journal CAS，只允许 central.source_name 与已验证的冻结来源名称一致。不会扩大 OS 固定执行命令、参数、输出发布权限，不支持 Agent 自定义地址/命令/运行时。
5. CI 将通过固定 GitHub release tag 下载官方 yolo11n.pt，在任何模型加载之前依照代码白名单验证 SHA256/size；再完成真实 systemd CPU YOLO11n PT→ONNX + ORT 数值对照、唯一单位身份、拒绝重放和源文件篡改；保留原可信 CI 随机模型回归。

## 不能混淆的信任边界

- 普通上传 .pt 即使哈希一致、zip 文件合规、在 bwrap 中能加载或母模型资产标记 VERIFIED，也不自动得到受保护的直接执行权限。
- 平台自行训练模型还需要具备可信训练流水线、可信 checkpoint 出处及原 Task/attempt 证明的独立签名来源合同；未完成前一律不能走新保护执行器。
- 未接入正式 AgentConversionRunner、中央生产 API、模型发布事务、StopReceipt/断电/失联恢复、Ubuntu22.04/systemd249；生产仍 NO-GO。A800 和双4070 不部署、不重启、不更改任务和数据。
- 本轮所有代码在单一长期分支 feature/external-algorithm-publishing，无大重构，不引入第二套调度器/上传器，也不改前端。

## CI 验收记录

待填：本轮代码 SHA、实测官方 release SHA/size、systemd E2E 运行、CPU/ORT 差值、失败边界测试、全仓各 CI 最终结果。不得沿用上一阶段的 24/24。


## 真实官方权重已验收的完整证据

**代码 SHA：373466e8b1b34b9276ffdf06ac339426b65fbf81**。

独立 Ubuntu24.04/systemd255 实际运行（不是 mock）：
https://github.com/jorsamj/aixunlianpingtai/actions/runs/43793371849 —— **SUCCESS**。

- 旧平台已有的 Ultralytics 官方来源白名单：v8.4.0 / yolo11n.pt，源字节数 **5,613,764**，SHA256 **0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1**。代码 SHA/size 白名单与本次真实 GitHub Release 下载内容完全一致；源码在 Web/Supervisor root 中绝未 pickle 反序列化。
- 官方文件经过 O_NOFOLLOW 和大小/SHA/ZIP 预检、root-owned staged source 0444+fsync、manifest 和 source 重读核验、原中央存储任务 request 与 task/lease/attempt 新签名、原 journal 一次性 CAS、非 root systemd unit（network off、GPU device off）执行真实 PT→ONNX。
- 实际 ONNX **10,534,119 bytes**；SHA256 **87cadf21a519912dd549780c7c837d1b207adee43b8418002d76db2981bf98f3**，opset 12，输入 [1,3,32,32]、输出 [1,84,21]，ORT **CPUExecutionProvider**；与原 PyTorch 输出最大绝对误差 **1.9073486328125e-05**。ONNX checker 验证和 original systemd invocation 绑定通过。
- **29/29 纯安全合同测试通过；10/10 真实 systemd 集成测试通过**，包括源文件内容修改、原文件/软链接替换、固定 central contract 错误、原租约撤销、CAS 后 OS 故障不能再次启动等拒绝验证。
- 失败修复保留：第一次 CI 真实隔离测试因 sudo 清除指定 CI 下载路径环境变量拒绝启动；第二次因重绑定后没有携带官方来源身份，安全检查正确拒绝启动。两项均最小修复，未改动任何生产执行接口或放宽来源校验。当前代码提交在相同真实测试场景通过。

**这个 SUCCESS 只证明官方固定 SHA 白名单模型的隔离执行路径；平台自行训练的用户 PT（包括 registry VERIFIED）仍不能安全地采用同样的直接受保护反序列化信任级别。**

其他 24 项全仓 CI 的最终终态尚需以代码 SHA 373466e8 的实际查询结果核实。
