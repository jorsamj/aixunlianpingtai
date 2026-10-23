# AI 预标注、清洗范围与提示词创建体验实施计划

> 本计划以用户 2026-10-16 的专项修复指令为已确认设计；只在现有 v60 AI 标注、v47 CLEAN MaterialBatch 与 MaterialSelectionSpec Owner 内增量实现。

## 目标与边界

- AI 创建弹窗在用户点击后同步打开，不等待全量素材读取；异步数据采用弹窗内 loading/error/retry，并以打开代次隔离迟到响应。
- 清洗主范围支持全部图片、选定图片、选定标签；标签按 OR 命中，标注状态等次级条件与主范围取交集。
- AI 创建任务允许选择视觉模型、提示词模板、任务级提示词覆盖、恢复模板原文、后端预览，以及显式选择当前有效标签。
- 后端冻结模型配置、模板版本、任务级有效提示词和标签 schema；恢复及 Worker 执行只使用冻结输入。
- 不改变清洗的只读扫描/人工确认合同，不直接删除素材或修改正式标注。

## 实施步骤

1. 先补前端所有权、清洗 selection、提示词冻结与真实 Chrome 响应时延的失败测试，保存修复前证据。
2. 扩展 `annotation_runtime.prepare_request()`：校验任务级提示词长度与模板变量，生成并持久化有效提示词模板、来源、模板版本和预览；Worker 仅使用冻结的有效模板。
3. 扩展 v47 清洗请求：将主范围、次级过滤和标签 OR 规范化为现有 `MaterialSelectionSpec`，preflight/estimate/prepare/retry 共用同一规范化结果。
4. 重做现有两个创建弹窗的内部内容，不改变 modal/任务 Owner：同步首屏、异步 hydration、固定底部操作区、局部错误重试、搜索与分页/选择反馈。
5. 更新静态资源缓存键（不改 `VERSION.txt`），运行 Node、Python、Playwright 定向与全量回归。
6. 在 1366×768 和移动端真实 Chrome 验证并截图；核对 Network、重复监听、迟到响应、冻结 request.json。
7. 检查 diff、工作区、VERSION 后创建一个本地独立提交；不推送。

## 验收证据

- 点击到弹窗可见小于 300ms，且打开动作不请求全量 `/materials/ids`。
- 清洗标签 OR、状态交集、空范围拒绝、revision 冻结及远程 preflight 结果均有自动化测试。
- 修改模板/模型后，已创建任务的 request.json 与 Worker 仍使用原冻结值；浏览器响应中不暴露 secret。
- 关闭后重开时，第一次迟到 hydration 不覆盖第二次弹窗。
- 现有恢复、远程清洗、素材选择、模型配置和提示词 API 回归通过。
