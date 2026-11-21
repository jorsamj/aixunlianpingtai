# P2D 异构节点与执行环境证据基线

本轮只核源码与设计；不连接节点、不执行探针、不安装驱动/SDK、不运行训练/转换。本地 CI 合同不代表现场 GPU/NPU 验收。

## 已有 Owner

- node_agent.py / node_agent_runtime.py：原 Agent 能力注册、主机 architecture、资源报告及归一化，service_nodes.py 保存心跳事实；配置允许能力和实际可执行能力不同。
- task_runtime/worker.py、repository.py、worker_instances.py：原 claim、attempt、lease_token、fenced repository、进程启动门禁；本轮不改。
- gpu_resources.py：已有 CUDA logical index/UUID/Worker 资源预约合同，**并非**已完成的通用 Ascend/RKNN/Sophon 资源管理器。保留其原合同；未来单独适配，不把 NPU 编号塞成 CUDA 下标。
- resource_discovery/{scanner,probe,candidates,model_resolver,tasks}.py：已有发现/检查 Owner；不从 Vue 触发额外主动扫描。
- compute_platform_catalog.py、conversion_resource_detection.py、node_agent_conversion_runtime.py、remote_conversion_runtime.py、rknn_runtime.py、sophon_runtime.py：原模板/实际资源证据/目标芯片参数、Agent 与远端转换执行；implemented 模板不证明当前节点 SDK 就绪。
- os_supervisor_conversion_adapter.py、os_supervisor_cpu_systemd.py、os_supervisor_central_api.py：原受控执行适配、中央授权与 OS 证据，不是可以绕过的另一调度器。没有发现可直接宣称覆盖全部设备的统一 RuntimeAdapter 类；现状为上述具体适配模块。

## 各目标当前证据边界

| 目标 | 已有源码基础 | 本轮可声称 / 未验证 |
|---|---|---|
| linux/amd64、linux/arm64 | architecture 字段、Agent/远端进程与离线节点设计 | 保留扩展接口；不代表所有 Python/native wheel、系统库、驱动均双架构可用 |
| NVIDIA CUDA | gpu_resources 与原训练/Agent CUDA 资源合同 | 已有实现；本轮没有设备、驱动、训练实测 |
| Ascend | atlas-atc 模板、ascend 目标检测与转换路径 | 目标合同存在；CANN/驱动/真实 NPU 推理本轮未验证 |
| Rockchip RKNN | rknn 模板、Toolkit/board runtime、Agent RKNN 路径 | 编译 SDK 与板端 Runtime 分离；不能从 RKNN 文件扩展名认定板端兼容 |
| Sophon BMODEL | TPU-MLIR 模板、sophon_runtime、原 durable/远端路径 | BM 芯片精度与编译证据按原合同；BMODEL 生成不代表 BM1688 实机精度 |
| CPU | 原 CPU/ONNX/ORT/systemd 受控路径 | 不假定具备 GPU；本轮只源码核查，无执行结果 |

## 统一描述草案（文档，未引入新 DTO 或数据库）

节点身份 node_id/worker_id、os_name/os_version/architecture；运行时证据按 runtime kind/sdk version/driver version/device identity 分组。每项携带 status、observed_at、配置 revision、执行环境身份、证据来源及不可用原因；缺失为 unknown，过期为 stale。能力只引用原 Agent/资源 Owner 的实际记录，不由前端建立 SDK 白名单。

分别保存、分别显示七个事实：

1. 架构/操作系统有实现路径。
2. SDK 已安装且版本可识别。
3. 驱动可访问、权限正确。
4. 设备被实际发现并具有稳定身份。
5. 该来源模型/Shape/精度/目标具备转换准入证据。
6. 数值一致性验证的执行身份、输入输出 SHA 和结果。
7. 目标设备真实推理的设备/Runtime/模型 SHA、时间与结果。

转换执行终态、文件存在/完整性、数值验证、设备验证和发布回执仍是独立字段。前一项不能自动推导后一项；ONNX 导出成功不等于 Ascend/RKNN/Sophon 编译成功；未验证不显示通过。历史 source_trace、版本 ID、SHA 原样引用。

后续如统一描述，先在现有资源 Owner 增量只读归一化，保留原字段与 status_label，缺证据不补造；不新增心跳轮询、不改变 capability admission 或 lease/fencing。真实设备适配/Schema 变更须另行授权。

## 离线环境设计

Vue JS/CSS/Chunk 为架构无关静态资产；Python、Node、native wheels、ORT/OpenCV、SDK/驱动必须按 linux/amd64、linux/arm64 与 Runtime 单独锁版本/清单，禁止复制开发机 node_modules 或 CUDA 环境冒充 ARM64 安装包。现有第三方 Annotorious/Uppy/ECharts/Panzoom 及 LICENSE/NOTICE/map 继续本地 vendor；无 CDN。

本轮仅交付动态前端离线闭包校验和源码+CI 制品组合工具；双架构 Python 安装介质、NPU SDK 授权包、驱动安装及现场离线部署全部未验证。A800/4070 演示服务不变。
