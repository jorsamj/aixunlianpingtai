# 第十四轮 13B-02：异步标注关闭旧请求不得误关复用弹窗

日期：2026-11-13；唯一长期分支：`feature/external-algorithm-publishing`。

## 之前验收

13B-01 提交 `143fa906982e59761fc50c8d6e812dc2a2f588b0` 的 GitHub Actions **36/36 全部成功**，包括 Frontend Runtime Stabilization 的浏览器回归。仅是代码/CI 验收，并非 4070、A800 现场验收。

## 确认的竞态根因

`static/app.js` 的 `closeModalCanonical420()` 对脏标注执行 `await window.saveAnn(true)`。完成后原先只检查 `currentTop===top`。但平台基础弹窗通过同一个 `#modal` 节点复用；若旧保存期间底层调用 `closeModalCore424()` 关闭旧弹窗，并迅速打开另一业务弹窗，新旧 `top` 均为相同 DOM 节点，旧关闭续体可能把新弹窗误关。

已有 v424 `ModalContentRuntime.captureOwner()` 使用 modalIntentEpoch、页面、项目、当前图层等核对身份；不需要新建锁、轮询、状态或第二套 Modal 管理器。

## 本轮最小改动

- 在 `closeModalCanonical420` 开始时获取既有 `captureOwner` 租约。
- 仅在真实脏标注保存成功后、执行任何旧关闭清理前检查 `closeOwner.isCurrent()`；已关闭/复用/切页时直接返回 false，不碰新弹窗及 GT。
- 原有保存失败阻断、顶部图层校验、关闭清理和训练回退路由全部保留。
- 更新 `index.html` 中 app.js/main.mjs/styles.css 的统一纯数字缓存标识至 `42.25.596`，不变更后端正式 VERSION。
- 原 `modal-close-owner-retirement.test.mjs` 补充 owner 使用位置及先保存、再验证、最后关闭的源码断言；`modal-scroll-stability.spec.mjs` 新增真实 Chrome 可控延迟保存、旧弹窗退场、同节点新窗口重开的竞态回归，不触发真实 GT 写入。
- 同步维护两项已有缓存标识守卫，不削弱任何业务/滚动/训练断言。

## 结果与风险

本轮提交不代表已经完成准确 SHA 的 CI；必须单独检查新提交工作流和浏览器回归。未访问或部署 A800/4070，未更改 GT、素材、训练、Worker、数据库。

回滚：整体撤销本轮提交；无数据迁移。后续 13B 再核对其他不经过公共关闭接口的旧弹窗关闭路径与焦点恢复，发现实际可复现的回归才做小补丁。
