# 2026-11-10｜42.24.570 官方 YOLO11 母模型简化校验

## 问题及边界

官方 `yolo11n.pt` 上传后被默认登记为 `UNVERIFIED`，一旦目标服务器缺少 `bwrap` 或隔离 Python，首次训练的模型下拉框会过滤掉该权重。用户要求让官方模型的验证更简单，保持原资产登记、首次训练资格及自定义权重的隔离安全门槛，不建设第二套校验环境或模型管理中心。

## 实施

1. `platform_core/mother_model_assets.py` 固定 Ultralytics 官方 `assets` 仓库 `v8.4.0` 发布的 YOLO11n/s/m 权重文件名、字节数与 GitHub Releases 资产 SHA256。仅当实际文件内容完全匹配、结构为 PyTorch ZIP checkpoint 时，才允许不反序列化地赋予 `VERIFIED/trainable=true`，记录 `verification_method=official_release_sha256` 及 COCO80 类别。**文件名相同但摘要不匹配不视为官方模型**，仍沿用既有 `bwrap` 校验，不能绕过未知 `.pt`。
2. 原 v63 上传接口自动尝试官方精确校验；既有同内容的再次上传仍幂等，且可恢复之前被环境问题挡住的官方权重。原 `/assets/{id}/verify` 在已知可信权重上复用快速路径，其他权重仍 fail-closed。
3. 训练弹窗仍只允许真实就绪的母模型作为提交参数，但显示已上传且暂不可用的权重（禁用项及具体状态），并保留对应 `warning` 训练目标的只读可见性，不把安全阻断误表述成模型没有上传。
4. 母模型管理页区分官方 SHA 核对与自定义隔离环境状态，上传后即时刷新原训练资源数据；保留 SHA 再验证、节点安装与训练 Worker 前置检查。
5. 原训练标签冻结记录区分 `official_release_sha256` 与 `sandbox_verified` 证据来源，不把官方预训练 COCO 类别默认为新算法的实际训练标签。

## 可信官方资产来源（发布页可核验）

- 发布：https://github.com/ultralytics/assets/releases/tag/v8.4.0
- 资产 API：https://api.github.com/repos/ultralytics/assets/releases/tags/v8.4.0
- `yolo11n.pt`：5,613,764 字节；SHA256 `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`
- `yolo11s.pt`：19,313,732 字节；SHA256 `85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5`
- `yolo11m.pt`：40,684,120 字节；SHA256 `d5ffc1a674953a08e11a8d21e022781b1b23a19b730afc309290bd9fb5305b95`
- 原始 COCO 80 类别名称依据官方 `ultralytics/cfg/datasets/coco.yaml`，用于母模型来源审计，不替代当前算法的标签冻结。

## 适用范围与验收

- 已有官方文件若 SHA 不同于上述 `v8.4.0` 发布资产，**不会**自动通过；可能来自其他官方发布版，需要另行核实哈希来源，不按名字放行。
- 本地通过 JavaScript 语法检查、Python 编译与母模型前端定向测试；隔离单测模拟精确摘要通过和篡改拒绝。Python API 环境缺少 `filelock/FastAPI`，真实官方 `.pt` 资产文件和 4070/A800 当前部署状态未能现场验收，不能声称真实首训已完成。
- 4070 升级后验收：检查 `/api/health` 版本、官方 `yolo11n.pt` 的 SHA、首次上传自动 `VERIFIED`、下拉可选、训练创建返回成功；未知 PT 无隔离环境时保持不可训练并显示原因。
- 不合并 `main`、不发布 release、不强推、不部署、不修改生产模型或任务数据。
