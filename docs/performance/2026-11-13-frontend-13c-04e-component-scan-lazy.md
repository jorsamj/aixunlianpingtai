# 13C-04E｜组件检测模块首访按需加载

基线：`5f19d231fef233d338f36b6525d2ea21c38d0604`；唯一分支：`feature/external-algorithm-publishing`。

- 已核对组件检测原有 v40 页面 Owner、缓存、GET latest、POST scan、轮询和按钮回调。它位于 app.js 约 2263–2313 行，静态源码约 8.3 KB。
- 从经典脚本迁到 `static/modules/component-scan-runtime.js`。仅在首次打开组件检测时 import，保持 `window.renderComponentCheckV40` / `startComponentScanV40` / `pollComponentScanV40` 原签名和 `PollRegistryRuntime` 原键。
- 旧缓存 `cl_component_scan_v40_snapshot` 仍然使用相同的安全字段形状，改为组件首次进入时恢复；其他页面无须先读取组件缓存。
- 复用主路由正式 Page Owner，不新增 Store、任务调度器、HTTP 层；异步加载采用单飞、导航 token、项目身份、序号保护和失败重试。
- 新增 Node 断言和 Chrome 资源按需检查；保留原组件检测进度、缓存、轮询、算能远程测试。
- 首屏减载为优化目标，不预先声称启动 P95 改善。以准确代码 SHA 的 CI 为准；未验证生产 A800、4070、GT 和训练 Worker。

## 2026-11-13 结果补记

- 代码/测试提交链：`ab30f40` → `5faab637` → `a58bda75` → `c61e82d`（只修历史 Online Feedback 浏览器测试异步就绪）。
- `app.js` UTF-8：1,394,659 B → 1,386,275 B，减少 8,384 B（0.60%），未将这些静态字节直接解释为用户启动耗时下降。
- `a58bda75` 前端单元测试 1661/1661 通过、Chrome 3/3 分片成功、前端 Job 4/4 成功。准确前端 CI：https://github.com/jorsamj/aixunlianpingtai/actions/runs/43426627830 。
- 13C-04E 之前的 Online Feedback Runtime 也出现两项 Chrome 失败（`5f19d231` 旧基线）；`c61e82d` 在测试夹具中等待动态模块初始化和 DOM 就绪后再构造检测记录，**未修改业务代码**。新提交的两组 Online Feedback Runtime 已通过；`c61e82d20d398652dad1724ba2af58df02db7b63` 的全仓 CI **22/22 工作流成功**。
- 13C-04F 只读预审：原 v39 约 45 KB，至少 8 个 `window.*` 入口在其他代码段被引用，禁止未经审计整体延迟加载；相关生产、GT、Worker、Safari、P95 仍未验收。
