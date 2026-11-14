# 42.24.589｜远程转换空配置路径 Errno 21 专项修复

日期：2026-11-12；基线：42.24.588 / `0953dc3ba0a72a2ecb9b1b39c6491c7a416ff424`。

## 真实故障与根因

原日志：`远程转换失败：[Errno 21] Is a directory: '.'`。
旧远程转换入口 `app.py::_sync_remote_deploy_job` 使用
`Path(str(params.get("config_path") or ""))`，空值变成当前目录 `.`；
仅用 `exists()` 判断，使目录也进入 `open("rb")`，导致
`IsADirectoryError`。该入口服务于 remote 模式非 Sophon 目标。

## 修复

- 空值、未提供或空白配置路径：不发送可选 `config_file`；
- 非空配置路径：须为存在的文件，目录/不存在的路径明确失败；
- 冻结源模型路径：先验证存在且为文件，避免类似目录误读；
- 保留现有请求参数、multipart 上传格式和原有任务/产物处理路径。

不修改 Sophon 独立 Worker 路径、SDK、训练/GT、模型权重、
ONNX 拓扑/数值一致性校验或生产状态。

## 回归与验收

新增 `tests/api/test_remote_conversion_optional_config.py`：验证配置缺省、
None、空串、空白、合法配置文件、显式目录/点号、不存在文件及空模型路径。
网络与返回产物为隔离替身，绝不调用真实远程服务器。
已挂入原 `Remote Conversion Runtime` GitHub Actions 流程，
需按最终提交 SHA 独立复核 CI。

该修复不代表生产升级或真实硬件转换验收。未操作 A800、4070、
生产数据库、历史任务和训练运行资源。
