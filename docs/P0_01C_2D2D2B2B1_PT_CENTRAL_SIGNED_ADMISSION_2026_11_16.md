# 2D-2D2B2B-1｜PT→ONNX 中央专用短期签名准入（2026-11-16）

## 一、目的与基线

唯一开发分支：feature/external-algorithm-publishing。

前序 2D-2D2B2A 功能 SHA d5e0dc56326d962a49861bb89e6ce93992d8589f，同 SHA GitHub Actions 已独立核实 23/23 completed/success；文档 SHA 69fa52296c958b59782c1724f073ea337a75c0b8。

2B2A 仅有不可执行的中央 lease 输入冻结、源 hash/size 验证。原 fixed-cpu-v1 中央授权不能被用来授权 PT 反序列化。2B2B-1 只新增**专用 admission 签名合同**，不执行 PT 加载、不启动 systemd、不发布结果。

## 二、本轮实际开发边界

1. 新增 platform_core/os_supervisor_pt_export_grant.py。新的 PT admission purpose/domain/profile 与原 os_supervisor_authorization.py 的 fixed-cpu-v1 完全不同，旧授权校验器不承认新的签名。
2. 复用**原** TaskRepository 的 tasks.attempt、原 execution lease、worker_id、service_nodes Bearer token / heartbeat / conversion 能力与同一 Ed25519 控制平面密钥注入。签发前在中心读取同一个 DB 快照和中心持有的任务 payload_ref 对应 remote_execution.conversion 文件。Agent 不能传入 source SHA、转换配置、manifest、密钥或命令给签名器。
3. 只允许预留 CPU 隔离测试 resource_key supervisor-pt-export-cpu-v1 + RUNNING/running + MODEL_CONVERSION + target onnx + object-storage-v1。普通线上模型转换 resource_key 不能进入此阶段的 issuer。
4. 只允许 .pt 源、精确 source SHA256/size/source_trace 与限定参数（input_size 白名单、batch=1、opset=12、dynamic=false、simplify=false）；拒绝额外 conversion 字段与任意 command/env/shell、RKNN/GPU/校准。转换输入仍需由下一阶段受保护 OS 侧核对实际字节。
5. 使用既有 FrozenPtExportAdmission.freeze_nonexecutable_manifest 生成无下载 URL、token 和密钥的规范清单，并**从中央证据**计算清单 SHA256。PT 另签：task/attempt/node/worker/lease_SHA256/boot_id/challenge/CPU_ONLY/source_SHA256/size/name/output_name/params/manifest_SHA256/issued_at/expires_at。
6. 签名最长 15 秒，不超过中央原始执行租约；验证时严格字段、Ed25519、公钥 pin、nonce/boot、期限、绑定对象及隔离 purpose/domain。验证结果只有 launch_authorized=false、result_publish_allowed=false。
7. CentralPtExportAdmissionIssuer(..., pt_trial_enabled=False) 默认禁用；生产 Node Agent、中央 FastAPI、SupervisorService、journal、Runner **均没有导入或接线**，不存在可由网络请求开启的本轮转换启动能力。

## 三、测试与门槛

- 新增 tests/unit/test_os_supervisor_pt_export_grant.py：真实 TaskRepository/ArtifactStore/ServiceNodeRepository 的任务/节点数据，核对签名及现有冻结清单 digest；中央任务变更、取消、代数变化、租约轮换、节点停用、非法参数、源摘要篡改、nonce/boot 错误、签名篡改与过期均 HOLD。
- 将模块与测试纳入现有 .github/workflows/node-agent-executor.yml 的 push/PR paths、py_compile 及 Ubuntu/Windows/API 对应单测；不增加同类重复 workflow。
- **提交时只可记录代码已提交，CI 必须按新代码 SHA 的最终 run 状态单独验收；未完成不可标记全绿。**

## 四、下一步的硬闸口（2D-2D2B2B-2）

1. 在**原 root-owned ExecutionJournal** 扩展 PT 独立 profile 的原 task/attempt + manifest digest + 一次性 nonce launch CAS，且防止同任务代数与 fixed-cpu journal 双启动。不能用 B2B-1 admission 签名直接绕开独立的中央启动前 recheck 授权。
2. 中央再次读取原任务/lease，在 root-owned Supervisor 预留 handle 并签发**新的短期 launch 专用授权**；签发时必须核对中心已取消、租约轮换及模型清单不变。失联/未知 fail-closed。
3. 受保护 staging：源 hash/size 与签名一致，root-owned 固定可信 Python/Ultralytics 运行时，完全独立的非 root CPU systemd workload、无 GPU/网络/任意 argv/env/cwd；PT pickle **只能来自经过明确认证的测试权重**。哈希不证明 pickle 可信。
4. 在 Ubuntu systemd >=250 的隔离 CI 真实执行**可信小模型 PT→ONNX**，验证 ONNX 格式、ORT 数值及 SHA，注入过期/撤销/重复启动、服务崩溃、系统重启、恶意 PT/错误路径。先得到 OS 实证，后续另做 StopReceipt/日志恢复与原 prepare/upload/confirm/finalize/finish。
5. Ubuntu 22.04/systemd249、GPU 权限隔离、真实转换 Runner 替换、中心自动恢复、生产启用仍 NO-GO。A800 和双4070 禁止部署、重启、停任务、删数据或更改调度状态。前端本轮无需修改。

## 五、风险提示

- 中央的 payload_ref 是中央持有的任务文件，但它与 SQLite 的读事务没有原生跨文件原子性；**本轮仅签署当前可信服务端读取的证据，不构成长期持久模型来源证明**。下一阶段须对 staging 及源存储对象再次校验。
- 隔离的 PT admission **不能**证明加载一个来源未知的 pickle 是安全的，也不能证明 systemd stop 已有可信 StopReceipt。
- 后续应遵循一次新增一个业务能力，不增加第二个中央调度器、不修改旧 fixed-cpu-v1 签名含义、不假装已有正式模型转换。

## 六、本轮验收结果

待按新提交 SHA 与实际 GitHub CI 工作流填写；不得沿用 2B2A 的 23/23。
