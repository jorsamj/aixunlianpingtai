# 13C-04E｜组件检测模块首访按需加载

基线：`5f19d231fef233d338f36b6525d2ea21c38d0604`；唯一分支：`feature/external-algorithm-publishing`。

- 已核对组件检测原有 v40 页面 Owner、缓存、GET latest、POST scan、轮询和按钮回调。它位于 app.js 约 2263–2313 行，静态源码约 8.3 KB。
- 从经典脚本迁到 `static/modules/component-scan-runtime.js`。仅在首次打开组件检测时 import，保持 `window.renderComponentCheckV40` / `startComponentScanV40` / `pollComponentScanV40` 原签名和 `PollRegistryRuntime` 原键。
- 旧缓存 `cl_component_scan_v40_snapshot` 仍然使用相同的安全字段形状，改为组件首次进入时恢复；其他页面无须先读取组件缓存。
- 复用主路由正式 Page Owner，不新增 Store、任务调度器、HTTP 层；异步加载采用单飞、导航 token、项目身份、序号保护和失败重试。
- 新增 Node 断言和 Chrome 资源按需检查；保留原组件检测进度、缓存、轮询、算能远程测试。
- 首屏减载为优化目标，不预先声称启动 P95 改善。以准确代码 SHA 的 CI 为准；未验证生产 A800、4070、GT 和训练 Worker。
