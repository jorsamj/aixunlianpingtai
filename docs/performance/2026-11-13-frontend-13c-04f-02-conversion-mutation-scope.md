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
