# 前端 13A：Owner 审计与导航展示低风险试点

> 2026-11-13；仓库 `jorsamj/aixunlianpingtai`；分支 `feature/external-algorithm-publishing`；审计基线 `d0495182f19383d35cf388fd5aa49aa3f8550fb7`，版本 42.24.592。

## 13A-01 源码责任清单（初版）

| 领域 | 保留的现有 Owner | 本轮/后续 |
|---|---|---|
| classic 前端与兼容入口 | `static/app.js` | 大文件约 1.39MB；先梳理动态 `window.*` 引用，禁止直接改为 ESM 同步导入 |
| 导航/页面/生命周期 | `static/main.mjs` + `navigation-stability.js` | 单一 Page Owner、请求作用域和导航栅栏不变 |
| 导航展示 | 原 `main.mjs` 导航 Chrome / 未知页 | 本次迁入 `navigation-presentation.js`；只注入现有状态、DOM 和高级菜单 |
| 高级导航 | `advanced-navigation.js` | 已存在；不可另建菜单 Manager |
| 弹窗/轮询/请求 | `modal.js`、`poll-registry.js`、`page-request-scope.js` | 13B 核对取消、清理、滚动锁和旧 DOM 写入 |
| 训练批选与提交 | `training-material-picker-runtime.js`、`training-draft-runtime.js`、`training-submit.js` | 不改 selection_ref、GT、角色隔离及 Worker |
| 素材库 | `material-pagination-runtime.js`、`material-batches.js` | 不恢复全库枚举，真实卡顿证据驱动优化 |
| 报告 | `reports.js` | 保留图表懒加载、resize/dispose |
| AI 审核 | `ai-review-route.js`、既有审核 Owner | 不动正式 GT 及用户确认合同 |

实际关系：`index.html` 先同步加载 `app.js`，后加载 `main.mjs`；`main.mjs` 安装 `navigation-stability.js` 与业务模块。classic 到 ESM 的加载边界是直接抽取 `app.js` 函数的主要风险，不为了拆小文件改变初始化时序。

## 13A-02 / 13A-03 实施与回滚

- 原 `renderNavigationChrome` 和 `renderUnknownPage` **展示实现**移入单个 ESM 文件；`main.mjs` 仍唯一负责导航路由、Page Owner 注册、启动/离开页逻辑。
- 新模块没有状态中心、网络请求、计时器、事件绑定，也不设置 `window.*`。DOM 内容、版本显示与未知页文案沿用原实现。
- `index.html` 使用纯数字缓存版本 `42.25.595`，`app.js`、`main.mjs`、`styles.css` 三入口保持一致；正式版本号 `42.24.592` 不变。
- 新增 `navigation-presentation-owner.test.mjs` 定向断言：fallback nav、当前 Tab 样式、服务端版本、未知页面属性过滤及唯一 Owner。
- 若需回退，整体撤销本次提交即可；无数据库或生产数据迁移。

## 证据边界与后续

这是一次**结构等价迁移**，不声称 P95 改善，不重复 20k/30k/200k 压测。全量 `window.*` 动态依赖和 `app.js` 内联 DOM 的消费图仍需后续补齐；不能把初版职责表当完整静态依赖 AST 证明。

待该提交 CI 核对，实际结果另行记录。13B 再处理 Modal 栈、scroll-lock、关闭后事件/请求/轮询销毁。A800、4070 未获授权不得部署、重启或修改数据；不 merge main、不创建 Release、不强推。


## 本轮 CI 失败精准修复（2026-11-13）

首个 13A 提交 `06d341faf299a553a2a58ab90bf1877806f411ad` 触发 37 项工作流：35 成功、2 失败。日志确认：Material Upload Chunking 拒绝带字母的 main.mjs 缓存标识，Frontend Runtime Stabilization 除该问题外还有 AI 审核入口三版本一致性断言和已迁出展示函数的旧源码位置断言。本提交恢复统一纯数字缓存版本 42.25.595，更新测试以审计真实展示 Owner，保留 DOM 交互语义断言；未触碰业务行为、GT/Worker/生产。该修复提交的 CI 尚须另行确认。
