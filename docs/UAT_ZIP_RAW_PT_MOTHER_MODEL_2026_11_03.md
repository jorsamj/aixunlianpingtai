# UAT 验收矩阵｜原图 ZIP / 母模型 / 首训（2026-11-03）

**基线**：长期分支新代码，尚未部署；**测试环境**：本地可用 Node、Python 3.12（未安装 API 依赖），无 GPU/远程 Agent/bwrap namespace 权限。
**证据限制**：没有生产图片、上传的真实 PT、A800/4070 连接与浏览器截图。以下“未执行”不代表失败已排除。

| 用例 | 预期 | 当前证据/状态 |
| --- | --- | --- |
| ZIP-01 原图无 sidecar | `unannotated` 入库，无强制分类 | 前端状态契约通过；后端待集成 |
| ZIP-02 data.yaml + 全空 txt | 保留标签提示、无确认空 GT | Python 回归已写；依赖缺失，未运行 |
| ZIP-03 空 COCO/VOC | 原图导入而非负样本 | 代码路径已调整；依赖缺失，未运行 |
| ZIP-04 混合有效/空/异常 | 分图状态、异常报告 | MIXED 扫描 + 空标注保护；异常分类仍不完整 |
| ZIP-05 COCO/VOC 清单外图片 | 额外原图不漏导 | 回归已写；待运行 |
| ZIP-06 跳过清洗→AI | 批次自动带入并生成候选 | 批次 API/JS 已连接，Node 契约通过；AI 真机未执行 |
| ZIP-07 AI 离线→人工 | 不丢原图，直接可标 | 人工分页入口已连接；真机未执行 |
| ZIP-08 失败/重试/跨算法 | 不重复、不污染 GT | 部分沿用旧保护；待集成 |
| PT-01 正常 YOLO Detect | 解析真实 names/nc/task | 沙箱探测代码已写，当前 bwrap namespace 不可用；未成功验证 |
| PT-02 同 nc 不同顺序 | 阻断静默错位 | 合同判别与拒绝分支；待隔离训练 |
| PT-03 类别数变化 | 兼容迁移并正确建头 | 尚未版本级实测 |
| PT-04 伪 PT/损坏 | 不能进入训练 | 登记后默认不允许；安全结构测试已写、依赖缺失 |
| PT-05 节点发现/安装 | 实际跨节点扫描、安装 | 新增授权目录只读发现与指定节点 MODEL_INSTALL 安装代码；静态与前端通过，新增 Python 合同测试待 CI，**真实 Agent HTTP 未验** |
| PT-06 自动调度仅选择可获得权重节点 | Agent 有真实 PT | 既有可移植存储链路存在，新增资产/指定节点证据尚未接通 |
| PT-07 离线/磁盘不足/Hash 变化 | 可恢复且不误报 | SHA 漂移选择拒绝已写；Agent 异常未测 |
| TR-01 首训自定义 PT | Worker 实际开始训练 | **未执行**，不得声称已完成 |
| TR-02 已有版本继承 | 无回归 | 既有路径未主动替换；待 Python CI |
| UI-01 多视口 / 生命周期 | 无嵌套、不卡顿 | 单层实现，未实际 Chrome 检查 |
| PERF-01 10k / 100PT / Agent | P50/P95/P99 实测 | 未执行 |

## 可重复验证命令

```bash
python3 -m py_compile app.py platform_core/mother_model_assets.py platform_core/training_label_tasks.py
node --test tests/frontend/zip-import-durable-runtime.test.mjs tests/frontend/zip-mother-workflows-p0.test.mjs
node --test tests/frontend/advanced-navigation.test.mjs tests/frontend/training-submit.test.mjs
# 完整依赖环境中执行
python3 -m pytest tests/api/test_v19_label_mapping.py tests/api/test_mother_model_preinstall.py tests/api/test_mother_model_registry_isolated.py -q
npm test
```

## 必须补齐的现场证据

1. 有效 YOLO11 Detect best.pt 与损坏 PT 的 `asset_id`、SHA、沙箱回执、`names` 原始顺序截图。
2. ZIP 纯原图 1k/10k、混合与空 COCO/VOC 的批次报告、正式 GT SQLite 记录及 AI 候选/审核凭证。
3. A800 与 4070 的 node_id、model sha、副本状态、Agent 安装任务、训练实际加载的同 SHA 模型与首 Epoch/Batch 日志。
4. 1366×768、1440×900、1920×1080、移动端截图、长任务与 P95 首屏/列表/弹窗计时。
5. 精确提交 SHA 对应的 GitHub Actions/隔离测试结果；若缺依赖/节点权限保持未测状态。

## 2026-11-04 新增节点发现用例

| 用例 | 实际结果 | 尚需验证 |
| --- | --- | --- |
| AGENT-INV-01 无根目录不全机扫描 | 独立 Python 测试通过 | 生产 Ubuntu 22 Agent 的配置路径 |
| AGENT-INV-02 `.pt` 发现、坏扩展与符号链接隔离 | 独立 Python 测试通过 | 节点真实软链接/挂载权限 |
| AGENT-INV-03 扫描深度、数量有界 | 独立 Python 测试通过 | 10k 模型场景 CPU、内存、P95 |
| AGENT-INV-04 离线节点与虚假 `trainable` 上报 | 独立 Python 测试通过，强制只显示待验证 | 控制端真实 HTTP/SQLite 集成 |
| CTRL-INV-01 从本机扫描缓存显式登记 | API 与 UI 已写 | 需要 FastAPI 依赖并创建真实扫描/上传临时目录验证 |

单独运行：`python3 tests/unit/test_mother_model_inventory.py`（无需 Torch、FastAPI、GPU）。

> CI 最新说明：上一远端提交 `653a33cd` 20 个工作流中 4 个失败，主要是母模型标签合同变量名错误、原图自愿分类及测试断言的导出协议变更。本轮已改代码/断言，但**新提交 CI 尚未执行**；验收状态不得升级为通过。

## 2026-11-04 新增指定节点安装用例（新代码，待 Python CI）

| 用例 | 代码/预期 | 当前状态 |
| --- | --- | --- |
| PT-INSTALL-01 选择节点 | `model-upload` 在线且双方授权，中心调度严格分配指定节点 | 新增 Python 合同测试，待 CI |
| PT-INSTALL-02 跨节点传输 | Agent 本租约从控制端鉴权流式读取，大小/哈希符合冻结 | Agent runner 与服务端端点已连接，真实网络待验 |
| PT-INSTALL-03 同 SHA 重试 | 已安装且重新核验 SHA，跳过重复传输 | 新增 Python 单测，待 CI |
| PT-INSTALL-04 字节变更 | Hash 错误不落地、不能生成回执/成功状态 | 新增 Python 单测，待 CI |
| PT-INSTALL-05 不安全路径 | 只安装到管理员目录、拒绝目标软链 | 新增 Python 单测，待 CI |
| PT-INSTALL-06 无回执成功 | 拒绝无有效当前执行代次回执的 `SUCCEEDED` | 新增执行服务单测，待 CI |
| PT-INSTALL-07 取消/重启 | 取消清理临时文件，服务端任务准确显示不成功 | 控制端取消/Agent 监听已实现，断线/重启实机待验 |
| PT-INSTALL-08 页面 | 模型/节点选择、状态进度、失败/取消，页面无嵌套 | 新增静态测试，真实 Chrome 待验 |

命令：`python3 -m pytest tests/unit/test_agent_model_install_runtime.py tests/unit/test_agent_execution.py tests/unit/test_node_agent_entrypoint.py -q`，以及文档前述 Node 回归。先核对 `4de9090` 的 20/20 GitHub Actions 已通过，**新模型安装提交的 CI 与 GPU 现场仍待验**。
