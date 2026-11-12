# 冻结 Test 异常图片 SNAPSHOT_MISSING 精准修复（2026-11-12）

## 生产故障事实（只读核验，未更改生产数据）

- A800 Web 环境使用 `MC_TRAIN_DATA_DIR=/data/platform-data`；项目 `f1fb1e6fa373`。
- 算法 `ext_chang_lian_72d63086777561b7`、版本 `d41f57bf9cb8`。
- HTTP 409：`SNAPSHOT_MISSING` / “冻结快照文件不存在”。
- Evaluation ID：`ba43c11f0fa658b75ff36f2ae63a646f7d21b1a8433b29ce882e0a288ff30e24`。
- Snapshot ID：`9931d3fdfe0296705652a5ff801ce66134c5499acd4566de68e396375e126f49`。
- 训练 Task：`train_fe6364e183a74e5482a21db0`。
- 项目 `projects/f1fb1e6fa373/snapshots` 目录不存在；原任务 `task_runtime/artifacts/<task>/snapshot.json` 存在（19.6MB），其声明 ID 与重算 SHA256 一致，Test 包含 3015 张；归档 `evidence/bundle/snapshot.json` 和 `manifest.json` 均存在；`work/bundle` 已回收。
- 检查生产代码：`training_tasks.py`、`remote_training_tasks.py` 未调用 `persist_snapshot`。

## 根因

本地及远程训练仅在 task artifact 和 Dataset Revision 中保存冻结证据，未在项目 `snapshots/<snapshot_id>.json` 持久化；预览端直接依赖该项目级文件存在，因而在图片/GT/归档读取前拒绝。该问题不依赖 UI 和图片实际字节是否仍存在。

## 范围：只在长期开发分支改代码

1. 本地训练和远程训练的 indices-only、bundle preparation 路径，复用现有 `persist_snapshot(project / "snapshots", snapshot)`，保持任务级冻结文件、Dataset Revision 及其他 Owner 不变。
2. 历史项目级 Snapshot 不存在时，`evaluation_diagnostic_image_v1` 允许从**同一项目、同一 TRAINING 任务**的 `snapshot.json` 获取只读身份索引。以下任一条件不成立则拒绝：
   - Evaluation、版本和血缘中的非空 Task ID 必须一致，版本声明的 Snapshot ID 不得冲突；
   - TaskRepository 中的任务必须归属当前项目且类型为 TRAINING；
   - 任务 Snapshot 不得为符号链接，必须确实存在；
   - 对冻结 Snapshot 的规范化完整 payload 重新 SHA256，必须等于 evaluation.snapshot_id；
   - 冻结 Test Image ID 和内容 SHA、归档 Manifest 来源哈希、实际图像字节哈希仍按原有逻辑再次验证。
3. 验证过的 Snapshot 元数据采用原受限缓存，额外的初始摘要计算以读锁避免 24 张缩略图同时重复解码大型 JSON；不缓存图片字节，不替代原 GT。
4. 预览响应附带 `X-Evaluation-Snapshot-Source`：`project` 或 `verified-task-artifact`，便于无路径泄漏地诊断。
5. **不自动回填历史生产目录**，不调用当前可变素材/标注重建 Snapshot，不删除/覆盖训练结果，不放松图片身份校验。

## 验证

- `tests/unit/test_snapshots.py`：Snapshot 内容摘要、持久化幂等、内容冲突不得覆盖。
- `tests/integration/test_training_task_worker.py`：本地训练持久化项目 Snapshot，并在训练 Work Bundle 回收后继续保留。
- `tests/integration/test_remote_training_prepare_task.py`：远程 indices-only 准备写入同一不可变项目 Snapshot。
- `tests/api/test_evaluation_diagnostic_image.py`：历史快照缺失时，验证任务级 fallback 可读原图、不会写生产；内容篡改、任务冲突、缺少任务文件均拒绝；保留的归档归一化图片优先按精确 SHA 读取。

## 部署/验收限制

本次仅推送 `feature/external-algorithm-publishing`，**未部署 A800/4070、未写入生产 Snapshot、未重启任何服务、未改数据库**。

未来部署后使用同一算法版本的原失败 URL 验证响应为 200 且响应头 `X-Evaluation-Snapshot-Source: verified-task-artifact`；随后核对图像尺寸、GT/预测框、真实归档字节及其他历史异常图。若依旧 409/图片不可读，按真实错误码继续审查，不能伪造成功。

回退代码可撤销上述文件变更，历史数据与权重保持不变。完整项目级 Snapshot 的生产回填必须通过另一次有授权且有摘要/任务血缘验证的恢复流程。
