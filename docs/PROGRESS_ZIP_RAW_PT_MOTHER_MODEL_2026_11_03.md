# 2026-11-03 开发进度｜原图 ZIP、母模型资产与首次训练

工作基线：`feature/external-algorithm-publishing`、开始时本地/远端 `5e708bc4fce5c0a0facaa02f1d6d426871fb40d6`。
本轮仅修改代码/文档；不触碰生产服务器、真实素材/模型、数据库或训练任务。此为**进行中交接记录，未达到整项 P0 完成标准**。

| 里程碑 | 当前状态 | 已写入代码的内容 | 尚未完成的阻断项 |
| --- | --- | --- | --- |
| P0-1 ZIP 扫描/原图 | 部分实现，待 Python 集成 | 全空 sidecar 与 schema hints 脱钩；原图无需正负样本确认；混合 `scan_kind`、空 GT 不转 `confirmed_empty`；COCO/VOC 漏清单原图补入 | 精确逐图异常分类/孤立 sidecar/冲突计数、1k/10k 真实性能、数据库集成验证 |
| P0-2 ZIP→AI/人工 | 部分实现 | ZIP 结果四路径操作；AI `source_batch_id` 后端解析并冻结待标注 ID；人工批次 150 张翻页；既有清洗整理入口 | 清洗结束自动衔接 AI、AI/人工全链路真机验收、AI 离线引导、批次修订与性能负载 |
| P0-3 母模型验证 | 部分实现 | 上传后登记内容地址资产；`asset_id`/SHA 状态；基于 bubblewrap 的可选隔离探测；原始 `names`/task；未通过校验禁止训练 | 真实官方/自定义 PT 与 Ultralytics 8.4.127 环境验证、沙箱目录兼容、跨进程持久校验队列及人机交互完善 |
| P0-4 跨节点发现/安装 | **未实现** | 管理端与 Agent 不会被虚假合并为同一路径 | Agent 执行器、白名单路径扫描、可移植部署、无 OSS 传输、节点副本持续验证及任务恢复 |
| P0-5 首训/视觉/性能 | 部分实现 | 高级“母模型管理”单层 Tab；训练下拉仅提供已验证资产；训练标签合同保留原始 names 并阻止同 nc 语义错位 | 远程 Worker 指定节点、重建检测头的真实版本适配、GPU 首训日志、真实 Chrome 三视口、冷热性能测量、最终 CI |

## 本轮具体变更

- `app.py`：v19 ZIP 分类、导入 GT 与完整图片集合、AI 按 ZIP 批次创建、人工分页；母模型登记/校验 API、首次训练安全挡板。
- `platform_core/mother_model_assets.py`：内容寻址登记/幂等、仅结构检查、可选 OS 沙箱 YOLO 验证；没有隔离能力时**拒绝校验**，绝不直接 Web 反序列化。
- `platform_core/training_label_tasks.py`：原始母模型有序标签/sha 与新算法 GT 的合同记录和错位阻断。
- `static/app.js`、`static/modules/zip-import-runtime.js`：ZIP 四操作、批次化 AI/人工工作台，不叠加第二层弹窗。
- `static/modules/advanced-navigation.js`、`static/modules/resource-discovery.js`、`static/modules/training-submit.js`、`static/styles.css`：高级母模型页面、校验入口、明确就绪状态与单层样式。
- 增加 API/前端测试；修订原有误把空 sidecar 当正式 GT 的过时断言。

## 已执行验证与限制

- `python3 -m py_compile app.py platform_core/mother_model_assets.py platform_core/training_label_tasks.py`：通过。
- `node --check` 涉及的 JS：通过。
- `node --test tests/frontend/zip-mother-workflows-p0.test.mjs tests/frontend/zip-import-durable-runtime.test.mjs`：37/37 通过。
- `node --test tests/frontend/advanced-navigation.test.mjs tests/frontend/training-submit.test.mjs`：64/64 通过。
- `npm test` 全量：当前执行容器缺 `@uppy/core` 依赖，出现 `ERR_MODULE_NOT_FOUND`；**不可宣称全绿**。
- Python API/pytest：当前执行容器缺 `fastapi`、`filelock`、`pytest`，无法运行 API/集成用例。
- 本机没有可用 GPU 和实际 A800/4070 Agent；未执行 PT 真正成功安全解码、Worker 首训、节点永久安装。当前容器 `bwrap` 无权限创建 namespace，验证应呈 `SANDBOX_UNAVAILABLE`，不是成功。
- 真实 Chrome 交互和目标 P95：**尚未验收**。不能把前端回归当成视觉/性能证据。

## 未完成前严禁的宣称与下一步

1. 不能标“全部完成”“正常可训练无堵点”“跨服务器模型部署就绪”或“CI 已全绿”。
2. 优先安装项目锁定依赖并执行 Python API/ZIP、母模型安全测试；据真实返回修复问题。
3. 补 Agent MODEL_DISCOVERY / MODEL_INSTALL 控制面及 allowlist、资产副本/调度节点约束，修复校验后台恢复。
4. 在隔离 YOLO 8.4.127 + GPU 下测同标签、不同标签、COCO 迁移与真实 Worker 加载，保留哈希/日志证据。
5. 完成真实浏览器、性能和 CI；正式变更/部署必须另获用户授权。
