# 13C-04C｜隔离 Chrome 前端性能证据采样

基线：`9bac29fdfabc5f212f68b2aa77ad959e2a9843e4`，长期分支 `feature/external-algorithm-publishing`；仅添加 Chrome 诊断测试与 CI 附件，不动应用逻辑或数据存储。

## 现有证据

前轮已通过的 Chrome 隔离环境日志 `[page-loading-inventory]` 给出一次运行的启动至可见 526ms，进入算法列表 21ms、训练任务 24ms、素材库 101ms。它们不是生产 P95，也不能据此证明 `app.js` 执行是主因。

## 新增证据

`tests/browser/frontend-startup-profile.spec.mjs` 在 CI Chrome 中做五次完整页面导航：前 3 次清浏览器缓存，后 2 次保留缓存。记录 `uiReady` 时间、Navigation/Paint Timing、脚本资源压缩传输体量/解码体量、Long Tasks、CDP TaskDuration/ScriptDuration（如可用）。

另一次单独启用 Playwright/V8 代码覆盖率，输出 `app.js` 与 `main.mjs` 的已执行字符占比，并测训练任务、素材库页面切换。覆盖率会产生额外开销，**不混入首屏性能样本**。

产物：`frontend-startup-profile.json`、`frontend-script-coverage.json` 通过 GitHub Actions 上传；单测仅断言页面就绪、入口脚本存在、无页面异常，**不设不稳定的耗时阈值**。

## 解释与后续门槛

1. 如脚本装载、覆盖率证实首屏多余工作，按页面 Owner 做下一轮窄范围延迟加载；不得直接删除未执行函数。
2. 如网络/后端或大量 DOM 更新占主导，应优先针对对应的 API / 页面执行路径，而不是继续盲拆 `app.js`。
3. 本轮不会修改 `app.py`、数据库、GT、训练 Worker、A800、4070，也不创建 Release / 合并 main。
4. 非生产工作负载、固定 CI 机器差异、脚本缓存和 Chrome 覆盖率开销必须进入最终分析。没有现场数据不能宣称生产速度达标。
