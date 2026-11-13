# 第十五轮 13C-02：质量中心高级评测按需加载

2026-11-13，唯一允许长期开发分支：`feature/external-algorithm-publishing`。

## 前置验收

13C-01 提交 `bd0e5fbedbf9a8c55eef8d8442e61fdb3be0795f` 的 GitHub Actions **37/37 成功**，包括旧素材兼容页面的真实 Chrome 测试；当前仍非 A800/4070 部署验收。

## 源码审计

`main.mjs` 首屏静态导入 `advanced-evaluation.js`（约 31 KB）。该模块仅由经典 `app.js` 的质量中心“高级评测”页签触发 `window.AdvancedEvaluationRuntime.mount()`，并在切页签、离开质量中心时触发 `deactivate()`。评测模块内部已有正式 Test 证据、错误样本、版本比较、复核与迭代逻辑；这些业务不可重写。

`scenario-evaluation.js` 同时被快速实测模块使用，本轮不承诺它也从首屏依赖中移出；只减少高级评测脚本本身的不必要请求和解析。

## 最小变更

- 不修改 `advanced-evaluation.js` 的 GT、评测、样本、模型绑定和 API。
- 在 `main.mjs` 的原入口改用轻量 `lazy-advanced-evaluation.js` 代理，保留全局 `AdvancedEvaluationRuntime`、`mount/deactivate`。
- 进入“高级评测”才动态导入原模块，成功后复用；失败在原页面给重试按钮。
- 同步创建 `[data-advanced-evaluation]` 容器，保证 `app.js` 在模块加载中插入的质量中心页签栏不会被稍后清除。
- 用当前加载代次、项目 ID、活动页签和现有 `NavigationStability.action` 拒绝切页、换项目后的旧加载回写。
- HTML app.js/main.mjs/styles.css 的统一纯数字缓存键变为 `42.25.599`；正式 VERSION 不变。
- 补充模块单测和 Chrome 首次加载、复用、迟到模块隔离用例；保留原评测完整业务回归。

## 边界

该提交不能等同已达到首屏 P95 性能指标；没有 A800/4070 部署、GT 更改、Worker 操作、Release 或 main 合并。以准确提交的完整 CI 决定是否验收。
