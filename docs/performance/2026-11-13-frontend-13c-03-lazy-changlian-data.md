# 畅联云算法训练平台｜13C-03 畅联云数据页面按需加载

时间：2026-11-13；唯一长期分支：`feature/external-algorithm-publishing`。

## 已完成验收的前置基线

13C-02 提交 `77c49b67cf0aad298b0e0cd7dcedd7f224aa1da8`，GitHub Actions **37/37 通过**，包括真实 Chrome 回归。非 A800/4070 生产验收。

## 根因和边界

`main.mjs` 首屏静态导入 `changlian-data-browser.js`（约 24 KB），然而它只在“畅联云数据”独立页面使用。原模块具有 `render/refresh/leave/destroy` 机制，且进入页面**不会自动访问远端数据**；只有用户主动刷新或点击详情才读取算法产品、版本、权重和 Tags。

## 修复设计

- 用轻量 `lazy-changlian-data-browser.js` 取代 `main.mjs` 的直接业务模块 import；首次进入页面才动态加载，成功后复用。
- 保持 `PlatformCore.runtime.changLianDataBrowserRuntime` 的 `render/leave/destroy/refresh/snapshot/detailSnapshot/openWeightDetails` 合同；保留全局 `ChangLianDataBrowserRuntime`。
- 仍让原 `changlian-data-browser.js` 拥有所有远端 API、身份核对、权重详情、缓存和页面操作；不改原模块本身。
- 新增导航代次、当前页面、项目身份及现有 NavigationStability owner 检查，避免迟到模块加载影响新页面。
- 加载失败仅影响当前页面；重试使用不同的 import URL 查询参数避开浏览器对失败模块的缓存。
- 不触发自动 Provider 请求，不增加新的轮询或大素材池扫描。
- HTML 三入口数字缓存版本一致升级至 `42.25.600`，同步原断言，正式 VERSION 不变。
- 单元测试涵盖未打开页面不加载、首进、重复打开、用户刷新边界、切页、切项目和可恢复重试；Chrome 用例覆盖实际网络请求及切页时的模块竞态。

## 约束与验收

仅能宣称将本业务模块移出首屏静态依赖，不宣称全站 P95 显著下降。不得操作 A800、4070 生产环境、正式 GT、数据库、Worker、main 或 Release。准确提交 CI 通过前不可部署。

## 2026-11-13 开发后独立 CI 核验快照

- 代码提交 `a0997c98d30dc4d9d63ba91092e7b27a23185ced` 已推送长期分支。GitHub Actions 37项截至本次查询：**36/37 工作流成功、1 仍在执行或排队、0 已失败（2026-11-13 查询快照；不得视为最终通过）**；可打开 https://github.com/jorsamj/aixunlianpingtai/actions/runs/43401136199 查询准确最终结论。
- 不得将仍在进行的 CI 归类为“已验收”或据此部署。后续执行状态及13C-04计划统一在 [前端治理当前进度](./FRONTEND_GOVERNANCE_CURRENT.md)。
