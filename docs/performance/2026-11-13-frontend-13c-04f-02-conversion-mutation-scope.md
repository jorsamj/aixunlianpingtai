# 13C-04F-02｜转换展示脚本 DOM 观察范围精准治理

只读审计基线 `e4d0173ec36ac9aa586c27ba8683f5e344bcb0e2`；唯一开发分支 `feature/external-algorithm-publishing`。

## 识别的冗余
`static/modules/conversion-workbench-ui.js` 启动时注册全局 MutationObserver，原版本对任何页面的 DOM childList 变更均触发 `decorate()`，至少运行 3 次全局转换根查询。此为实际执行路径，但不能直接声称真实系统的 P95 卡顿由此造成。

## 精准修改
保留同一观察器和 queueMicrotask 合并逻辑；仅对 record.target 位于 `.convert428-v2,.convert428-create` 内，或 addedNodes 含此根节点的更新启动转换展示扫描。未修改任何转换任务/资源/GT/Worker 逻辑或 API，亦未改变转换弹窗的按钮行为与 Modal owner。

## 回归与证据
新增隔离 Chrome 测试：非转换页做 30 次独立 DOM 插入，核对转换全局查询增加数为 0；随后异步插入转换历史和创建表单，检查自动装饰及补入的源数据提示归位。保留既有 Chrome 转换历史/表单、分页、资源、取消与硬件验证测试。本专项绝不把 0 次无关查询等同生产提速，实际 P95/CPU 耗时需要在统一环境对照。

## 下一步
要考虑延迟加载整个 17,862 字节独立脚本，须先测量实际浏览器的脚本下载、解析、执行开销，并验证 `openConversionNumeric560` 公共兼容入口和快速弹窗切换。默认不执行此迁移。

## 2026-11-13 最终验收记录

- 准确业务/测试提交：`3aecc232b607913973a4ed53a30fbea870643d89`；GitHub Actions 21/21 工作流成功（0 失败、0 未完成）。
- Frontend Runtime Stabilization：[4/4 Job 均通过](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43435335641)。Node 前端单测 **1662/1662** 通过；Chrome 三分片分别 **131、126、125 项**，合计 **382 项**通过。
- 新增浏览器用例验证：在真实 Chrome 中 30 次独立的非转换 DOM 更新不触发新增 `.convert428-v2:not(...)` 全局查询；异步添加转换历史、转换创建弹窗、源模型提示仍能挂载。记录的是被测查询次数，不是生产 CPU 时间或用户 P95。
- 尚未进行同环境前后首屏解析、运行时 CPU/P95 差值测量，无法据此称系统“整体加速”或所有历史 UI 事件都已覆盖。
- 未部署 A800、双 RTX4070；未触及 GT、训练 Worker、真正模型转换或芯片 Runtime。
