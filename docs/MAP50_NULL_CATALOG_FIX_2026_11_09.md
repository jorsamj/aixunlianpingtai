# 2026-11-09｜算法列表当前 mAP50 误显示 0% 的最小修复

## 范围与复现

- 长期开发分支：`feature/external-algorithm-publishing`；开始时远端 HEAD `dffd6cde39867a3e060378802b7f7087c5e4588e`，本地无未提交改动。
- `AlgorithmSqlStore.read_all(summary_only=True)` 将缺少的顶层 `map50`/`mAP50` 显式投影为 JSON `null`，同时单独返回已保存的 `metrics` 和精简 `evaluation.metrics`。
- `algorithmVersionMap50()` 原实现直接 `Number(null) === 0` 并立即返回，故 `{map50:null,metrics:{'metrics/mAP50(B)':0.5851}}` 被错显示为 `0.0%`，真实值应为 `58.5%`（列表一位小数）。
- 仅确认了代码级误显示；尚未读取 4070 现场数据库，不能以列表 0% 断定模型真实精度为零或所有版本均有完整指标。

## 修复与边界

- 列表取值跳过 `null`、`undefined`、纯空白、布尔值、对象及非有限数字，再按既有次序读取顶层、训练 metrics 及独立 evaluation metrics 的 mAP50；保留合法数值 `0`，缺少全部来源时返回 `null` 并显示“暂无指标”。
- 未修改后端训练、Val/Test 评测、数据库字段、报告真值或业务任务；也没有把 mAP50 当业务准确率。列表在训练指标缺失且独立评测有值时可以显示兜底值，下一轮产品优化可单独增加指标来源标识。
- 调整 `static/main.mjs` 的算法列表模块缓存键及 `static/index.html` 的 main 引用键，避免部署后旧 JS 继续显示错误。
- 本轮明确不修改“选择本次训练素材”批量选择性能链路，该问题另立专项，不借本次小修进行重构。

## 验证与上线要求

- Node RED 回归：原解析函数将 `map50:null` + `metrics/mAP50(B)=0.5851` 返回 0；修复后预期 58.51、后续 UI 显示 `58.5%`。
- 回归覆盖 `map50:null`、`mAP50:null`、空白、无指标、真实 0、独立评测兜底、布尔值、一般 accuracy 不得冒充 mAP50。
- 先加新用例并验证 RED（原函数误返回 0），修复后算法列表模块定向 **21/21 通过**；Node 全部前端合同 **1580/1580 通过**，`node --check static/main.mjs` 与 `git diff --check` 通过。
- 部署前仍须核对准确提交的 CI；实际服务器更新后对照至少一条有训练报告的版本，同时检查未训练版本应显示“暂无指标”。本批不部署 4070 或改动正式训练数据。
