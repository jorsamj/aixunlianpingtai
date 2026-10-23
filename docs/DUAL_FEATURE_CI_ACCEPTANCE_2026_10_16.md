# 2026-10-16 双功能推送与 CI 验收

## 已推送业务提交

- `1de328cce343265e3b32f19eb361ae45a5afa062`：AI 创建、任务提示词冻结、自动清洗范围。
- `36a62b015b23df72ca1dba6c6f041557112c7661`：独立评测图片恢复和只读诊断。
- 初次推送前远端为 `ca10efd53fb65a78bd8871cdb5d33ad66db88be8`，工作区干净，ahead=2/behind=0；普通 Fast-forward 后远端与本地均为 `36a62b01`。
- 正式 VERSION 42.24.356；静态入口缓存 42.25.384。

## Storage 已知失败的合同裁决

- 用例：`tests/unit/storage/test_yolo_import.py::test_yolo_text_identity_rejects_known_hash_change_with_same_size`。
- 修改前本地与独立干净 `1de328cc` 工作树均在第 168 行以 `DID NOT RAISE YoloImportError` 失败；相同 Windows、Python 3.12.7 和 pytest 参数。
- 既有正式合同在 `docs/codex-handoff.md` 的 YOLO source fencing 章节：同尺寸但已有可信 SHA 不同，必须抛 `YOLO_SOURCE_CHANGED`，禁止覆盖旧 evidence。
- 根因：`_record_text_identity` 正确抛出，但 `scan_annotations` 的通用 StorageError 捕获把它转成普通 invalid 记录。修复仅对该安全异常重新抛出，终止本轮扫描；普通格式问题仍按既有 invalid 流程处理。
- 原异常断言保留，并增加旧 SHA 不被覆盖、受影响图片未被接受为 annotated、无已接受框的断言。
- 修复后该文件 12/12，Storage 全目录 367 passed / 2 skipped。初次 Remote Material Import 工作流只编译该测试而未运行，现将它加入已有 Ubuntu/Windows 运行清单。

## 三项业务的本地交叉回归

- AI annotation API/runtime、清洗范围 API、评测图片 API/评分：113 passed。
- Chrome 联合：21/21，覆盖 AI 创建 50k 分页/失败保留/重复提交、跨页清洗范围及 OR 状态交集、独立评测 20k/24 图片/错误诊断/四视口/图层对齐。
- 共享 app.py/app.js 的增量提交顺序保持，正式 Owner/Worker/队列不变，未引入额外轮询。Node 24 全量仍需以最终提交回归结果和远端 CI 终态核验。

## 验收边界

- 首轮业务 SHA 36a62b01 实际触发 47 个 Actions，47 success / 0 failure / 0 queued或运行中。此状态不代替后续修复提交的最终 CI。
- 覆盖审查补齐原 AI Annotation Recovery 的 annotation_runtime 文件路径触发与实际提示词冻结单测，以及原 Frontend Runtime 的 ai-create-experience.spec.mjs 真实 Chrome 清单；没有新建工作流。

- 所有 Actions 统计按实际检出的最终 SHA；queued/in_progress/cancelled/skipped 不记为 success。
- 生产 OSS/S3、A800/Linux 主机和历史图片完整性为受控 UAT，隔离数据不代表生产恢复。
- 不部署、不修改 VERSION、不修改 main、正式数据库或历史 Snapshot。
