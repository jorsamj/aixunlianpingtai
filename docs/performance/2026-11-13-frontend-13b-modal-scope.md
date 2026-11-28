# 前端第十四轮 13B-01：算法报告弹窗样式作用域精准治理

日期：2026-11-13；前置 CI 通过：`c4c83cf468b813192a02794b20105d4915c0ffad` 36/36 GitHub Actions 成功。唯一允许分支：`feature/external-algorithm-publishing`。

## 实际代码证据

`static/index.html` 先加载 `styles.css`，后加载 `algorithm-report-modal.css`。前者已经包含针对普通弹窗和最小化导入弹窗区分处理的滚动兜底规则；后者意外再次通过 `.modal:not(.hidden)` 对全站可见弹窗统一设置 align-items、overflow 与 modal-card/modal-body 的 flex、max-height 和 scrollbar-gutter。

该晚加载规则也匹配 `.import350-minimized`，可能覆盖最小化弹窗的 overflow 策略；同时影响训练、审核、普通二次确认等非算法报告窗口。源码可以确认 CSS 作用域冲突，**但不能仅由此证明现场偶发无法滚动的唯一根因**。

## 本次最小改动

- 只将 `algorithm-report-modal.css` 中 4 组**未加业务作用域**的弹窗规则改为严格要求 `:has([data-algorithm-report])` 或 `:has([data-algorithm-report-loading])`。
- 已有报告专属高度规则、通用 `styles.css` 规则、沉浸式审核/训练报告/导入弹窗 CSS、原 Modal 栈及状态/请求/GT/Worker 全部不变。
- 仅提升报告专用样式文件的缓存标识 `20261113-modal-scope1`，不变更 app.js、main.mjs、styles.css 三入口纯数字标识及正式 VERSION。
- 调整 `algorithm-report-lightweight.test.mjs` 仍验证 report 固定滚动视口；新增 `modal-style-scope-13b.test.mjs` 静态防回退守卫。
- 在现有 `modal-scroll-stability.spec.mjs` 增加 Chrome 实测：最小化 ZIP、长报告加载、普通嵌套确认、Esc 仅关闭顶层、父弹窗仍可滚动。

## 验收边界与回滚

该专项只解决 CSS 越界，非压测；需对本次准确 SHA 的 CI 独立核验，并查看 Chrome 测试结果。浏览器测试未通过前不得宣称偶发滚动问题已彻底解决，也不得部署 A800 或 4070。

回滚只需整体撤销本专项提交；没有后端迁移、数据修订或生产操作。

## 13B 余下工作

按真实复现证据继续排查：Modal 原生关闭栈的焦点恢复、嵌套关闭前 async 保存期间的 owner 栅栏、AI 审核沉浸层与训练报告的 CSS 布局切换，以及页面请求/轮询的离开页销毁。**不新建第二套 Modal Manager，也不直接替换现有业务关闭入口。**
