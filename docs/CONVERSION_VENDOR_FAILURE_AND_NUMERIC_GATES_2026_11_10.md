# 42.24.580｜算能 / 瑞芯微转换失败诊断和数值门禁专项

日期：2026-11-10。唯一开发分支：`feature/external-algorithm-publishing`。

## 问题与需求

- 用户反馈：更新平台版本后，原本能够转换的算能模型显示“官方编译数值对照失败，已拒绝发布 BMODEL”，服务器环境未变。
- 代码确认：`deployment_worker.build_sophon()` 在 SDK 提供 `--compare_all` 时自动启用，并把所有 `model_deploy` 命令异常都归类为数值对照失败；提示与真实故障不一定一致。
- 举一反三：RKNN 原执行器的 `config/load_onnx/build/export_rknn` 不同失败阶段统一变成外层通用异常；旧 `.rknn` 文件在失败重试前未主动清理。

## 最小范围修复

1. 算能继续要求官方 `--test_input` + `--test_reference` 数值对照；`--compare_all` 改为明确请求的深度诊断开关，不再自动扩大常规发布门禁。SDK 无能力时拒绝该开关。
2. 算能将超时、明确数值失败、其他编译/验证命令失败分别归类；不再用数值不一致覆盖所有非零退出码。原始 SDK 日志继续保留在现有 `convert.log`。
3. 修正 `sophon_validation.json` 的 `offline_reference.compare_all`，准确记录**实际启用**的值，并注明输出级或全部中间层比较范围。
4. 瑞芯微独立执行器输出稳定阶段标识，主转换器映射到已有 `ConversionError`/`error_code`/`solution`；无需新增第二套后端任务或请求机制。
5. 任何新的 RKNN 转换之前清除同名旧文件；成功返回仍执行非空产物与 SHA256 记录。RKNN 编译成功不声称数值/硬件验证已通过，继续为 `converted_unverified`。

## 不改变的行为

- 真实失败均不发布产物；无法取得数值证据不能标为已通过。
- 不更换 SDK、容差阈值、ONNX 导出合同、模型版本身份校验、任务幂等和正式发布机制。
- 无需硬件/实机才能编译 RKNN；真正硬件验证仍独立进行。
- 不修改生产数据，不部署 4070/A800，不 Merge main，不创建 Release。

## 验收进度与边界

- 代码语法检查：通过。
- 标准库隔离检查：算能失败分类/超时、瑞芯微阶段分类、旧产物保护共 10 条检查通过。
- 增补 `tests/unit/test_sophon_conversion.py` 和 `tests/unit/test_vendor_conversion_failure_classification.py` 的针对性回归。
- 当前本地运行环境无 pytest / 厂商 SDK，pytest 结果以推送后的 GitHub CI 为准，官方 SDK 的真实数值对照仍需部署到对应转换节点后用真实任务验收。
- 用户此次失败的**具体根因尚需原始 `model_deploy` 末尾日志**确认；本次修复消除已证实的代码回归风险，并明确异常类别，但不声称已经重现现场失败。
