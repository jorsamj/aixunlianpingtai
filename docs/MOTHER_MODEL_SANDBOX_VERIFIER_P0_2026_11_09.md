# 2026-11-09｜42.24.566 母模型安全校验诊断和中断恢复 P0

## 本轮需求与授权边界

- 现场现象：上传 `.pt` 母模型后提示等待安全校验；手动执行又提示“校验环境不可用”，母模型无法进入首次训练。
- 用户授权修复现有校验链路的问题：Python 路径兼容、轻量环境预检、错误分类、校验中断/重复恢复、执行资源有界。**明确不包含提供正式的独立安全校验环境**。
- 本轮只涉及原 `mother_model_assets`、`/api/v63/base-models/assets` 与 `/verify`、原资源页和针对性测试。保留显式手动校验、原资产 JSON/SHA/训练资格/节点安装、原有 bwrap fail-closed；不新增 API、任务中心、缓存、模型服务或安装脚本，未访问生产数据/4070/A800。

## 证据与最小修复

| 问题 | 原实现证据 | 改动 |
| --- | --- | --- |
| Python 依赖及路径不可用 | 校验默认 `sys.executable`；bwrap 屏蔽 `/data`、`/home` 等路径 | 允许管理员通过 `MC_MOTHER_MODEL_VERIFY_PYTHON` 选择**现有、符合隔离约束**的 Python（默认仍是 Web Python）；同时校验入口与 symlink 目标，不放宽屏蔽目录；保持 `venv/bin/python` 原路径以保留 venv 依赖。**不创建新的环境** |
| 环境能力不明确 | 直接点击验证才见 `SANDBOX_UNAVAILABLE` | 原 GET assets 仅附加廉价 `verification_environment` 配置状态，不加载 torch/扫描 PT；UI 同页告知“配置已发现，实际隔离启动仍需实测” |
| 错误混淆 | 依赖导入/模型失败都可能显示 `PT_MODEL_LOAD_FAILED`；超时误判 sandbox 无法执行 | 隔离 Python 导入阶段区分依赖异常；另分 `PT_VERIFY_TIMEOUT`、`PT_VERIFY_OUTPUT_LIMIT`、`PT_SANDBOX_NOT_EXECUTABLE`、模型内容错误；UI 显示中文原因和原错误码 |
| `CHECKING` 卡住与并发 | `_active` 只在当前 Web 进程，daemon 线程随重启丢失 | 复用原 FileLock，同资产按系统文件锁跨进程单执行；`CHECKING` 超过 180s 且无回执按只读展示为 `INTERRUPTED`，重新点击同一资产走原 SHA 检验和重试，无 GET 写库 |
| 子进程资源缺乏界限 | `subprocess.run(capture_output=True, timeout=35)` 可聚集大量输出 | 单独进程组、Linux 隔离、无网络、只读输入、UID/GID 65534、Python `resource` 的 CPU/虚拟内存限制、60s 总超时、最多 128KiB 输出；超限/超时可靠停止，不直接在 Web 加载 PT |

## 现有环境的运维检查（未执行）

在目标 **Linux** 运维维护窗口、经用户批准后：

1. 检查现有 `bubblewrap` 是否存在，Linux 是否允许所需 namespace，当前 Web Python 是否位于被屏蔽的目录，以及当前隔离可见的 Python 是否已经有与 PT 兼容的 PyTorch、Ultralytics 依赖。
2. 如果服务当前 Python 位于隔离屏蔽目录，可由运维自行选择**已有**可信 Python，通过 `MC_MOTHER_MODEL_VERIFY_PYTHON=/现有可用Python绝对路径` 配置。该路径必须在允许目录内，实际依赖必须在 bwrap 下可用。代码不自动迁移依赖、不安装 Python、不改变系统级环境。
3. 如果没有满足条件的现成工具和运行时，状态继续 `SANDBOX_UNAVAILABLE`，不得绕过隔离，也不能宣称本轮已解决环境缺失。本轮不交付独立环境或安装包；后续若要引入，需要另行授权。
4. 服务升级后先看原母模型管理页轻量状态，再显式点击“安全校验”。用真实可信的 `yolo11n.pt` 检查 `VERIFIED` 与 `names/nc/task=detect`；真实隔离启动、依赖与文件挂载均须现场验证，不能只信“已配置”。

## 必须保持的不变量

- PT 上传后仍 `UNVERIFIED/trainable=false`；结构/隔离/模型校验任何一步失败，都不能转为可训练。
- 只有实际受控 bwrap 隔离子进程成功返回且标签/架构合法时，才能 `VERIFIED`。不提供关闭校验、无沙箱反序列化、放宽标签或假成功选项。
- 已上传资产 SHA、原始 PT、模型标签、训练/GT/Worker 数据均不迁移、不覆盖；重试复用资产 ID，最终训练选择仍会验 SHA。
- GET assets 只提供原登记快照及廉价环境信息，不能触发 Torch import、模型扫描、文件解码或写库；UI 不泄露内部 Python 绝对路径或敏感日志。

## 回归及现场待验

- `tests/api/test_mother_model_registry_isolated.py` 新增现有 Python 配置判定、屏蔽目录、断点状态投影、子进程限输出/超时终止、依赖与 namespace 分类、模拟 `detect` 元数据完整输出。原未验证文件及哈希改动拒绝继续保留。
- `tests/frontend/mother-model-preinstall.test.mjs` 检查同一管理页新增中文环境/错误状态，不创建新弹窗。
- 当前容器不具备 `filelock`/Ultralytics/bwrap，因此只能运行有界命令的模拟安全合同和相关前端/语法检查；**未实际使用不可信 PT，也未运行 4070 的 bwrap 实机测试**。
- 本版 GitHub Actions 结果、目标机隔离工具、现有 Python 依赖、`venv/bin/python` 在 bwrap 内实际导入、并发 Web/掉电/大模型 CPU 真实加载仍待现场验证。不得声称母模型实际可训练或部署已完成。
