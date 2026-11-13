# 13C-04B：训练资源卡片的低风险展示抽取

- 基线：`a8d015c6f99d68946a1472c6dd7aa5e9100250de`；唯一分支 `feature/external-algorithm-publishing`。
- 边界：仅将 `static/app.js` 的 `trainingResourceCardsHtmlV3()` 标记片段抽离，保留原同步桥接、`window.renderResourceBasePage`、资源查询 API、原 `refreshTrainingResourceTruthV3` 和前端 Owner。
- 实现：新 `static/modules/training-resource-cards.js` 作为普通脚本在 `app.js` 之前按 HTML 顺序执行，提供被冻结的纯展示渲染器；不新增 `main.mjs` 的异步加载竞态。
- 原有 `app.js` 改为只转发素材到纯展示器；原内联按钮名称和 HTML 结构全部保持。
- 缓存：资源脚本 `42.25.601-13c04b`，`app.js` `42.25.601`；`main.mjs`、CSS 内容及缓存版本不变。
- 回归：Node 通过虚拟 window 验证输出、XSS 转义、按钮、状态更新、无副作用及脚本顺序；Chrome 在正式应用页面验证渲染、补丁刷新、原按钮。
- 该轮是小型安全拆分试点，**不声称首屏/P95 变快**。未更改 SQLite、GT、训练提交、Worker、`app.py`、生产服务。
- 失败时仅回退本次 5 个功能及测试文件的提交，不应重新启用多套 Owner。
- 待核验：新 HEAD 的 CI 及真实浏览器运行；所有结果以准确 commit SHA 记录，不可预先宣称通过。
