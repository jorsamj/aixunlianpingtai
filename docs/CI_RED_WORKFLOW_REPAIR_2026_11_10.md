# 42.24.575｜CI 红灯归因与专项修复（2026-11-10）

## 准确 SHA 与失败基线

- 42.24.572（`461cef277c373c062e820f5f8f7119b51a7eb509`）：47 成功、2 失败。失败工作流为 `Frontend Runtime Stabilization`、`Training Task Visibility`。
- 42.24.573（`ef7b7befa0a2ffbe6c6488464d809c1792f6be6e`）：39 成功、2 失败，仍为上述两条工作流。
- 42.24.574（`a5a8dcec9493a462684d1f148094805e1b227d0f`）：本轮检查已确认 `Training Task Visibility` 失败，`Frontend Runtime Stabilization` 的前端/浏览器子任务亦失败；其余执行中的工作流结果以 GitHub 实际页面为准。

上述红灯始于新增批量消歧功能之前；这不意味着可以忽略失败直接生产部署。

## 最小修复范围

1. `tests/api/test_training_job_visibility.py`：恢复测试替身对 `list_algorithms_internal(..., algorithm_id=...)` 的关键字参数兼容性；保留实际算法名、删除后回退与历史项目隔离断言。不修改按算法定向查询的生产实现。
2. `tests/frontend/training-draft-direct-write.test.mjs`：接受训练新建时同时清空 `trainSelectionRef/trainSelectionCount` 的正式草稿合同；仍要求冻结选择重置先于弹窗显示。
3. `static/index.html`：入口三类资源统一切到 `42.25.585`，避免 app/main/styles 使用不同缓存键；`tests/frontend/version-marker-owner.test.mjs` 将过期的训练标签硬编码旧版本检查改成动态资源版本格式检查，保留模块 build 合同。
4. `static/app.js`：编辑已保存模型时，当前内存配置若因延迟刷新丢失或缺少有效地址，则从已有 `/api/v35/model-configs` 端点读取并按 ID 恢复；读取失败或不存在时显式提示，禁止把空白默认配置当成已保存配置覆盖。浏览器测试增加 API 持久值断言与状态丢失重现。
5. `tests/browser/ai-review-api-roundtrip.spec.mjs`：按稳定 `data-ai-export-format=csv` 合同点击“导出全部问题 CSV”，保留下载文件名及逐图 HTTP 422 验证；错误 CSV 实际按钮已不叫“导出本页错误 CSV”。
6. `tests/browser/annotorious-workbench.spec.mjs`：官方标注编辑器切图/刷新瞬间 `state.ann=null` 时，将读取视为“尚未就绪”而继续轮询，仍严格要求 100 / 300 个正式检测框，无放宽验收数量。

## 验收与部署门禁

- 静态 JS 语法已解析；完整 Python/Chrome 测试需以本提交的 GitHub Actions 为准。
- 只有准确新 SHA 的失败 CI 完成复核并恢复绿色，才建议生成离线部署包并安排 4070 更新；若存在独立不稳定运行或环境失败，必须列出原因和影响后再做人工风险评估。
- 不执行生产数据迁移、模型 Worker 改造、版本发布、合并 main、release、force push、4070/A800 现场部署。

## 42.24.576｜保留 M4 入口既有同步合同

42.24.575 的 GitHub Actions 发现新引入的源码契约失败：`Remote Conversion Runtime` 的 `agent-contract`（Linux/Windows）以及 `Frontend Runtime Stabilization` 的四个源码守卫都要求 `window.openModelConfigM4=function(id='')`。将原异步声明改回同步函数，并仅在未命中已保存配置时通过 Promise 异步补读，然后递归调用已有同步入口。保留单一模型弹窗所有权，不更改模型服务地址、训练链路或转换协议；准确 576 CI 待验，未部署。

## 42.24.576｜CSV 导出文件名回归断言补齐

现有导出器的完整文件名合同为 `annotation-errors-<task-id>-<失败张数>.csv`，而历史浏览器断言仍要求已退役的固定名 `annotation-errors.csv`。仅更新隔离回归用例，以 `browser-review-failed` 任务的 1 张失败图为例，要求 `annotation-errors-browser-review-failed-1.csv`；保留完整行导出、下载事件、HTTP 422 验证，不改产品文件名及 API。此次属于同版本测试合同补齐，不再提高产品 VERSION。
