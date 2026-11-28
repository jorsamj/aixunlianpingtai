# 2026-11-09｜5 项 Chrome CI 红灯的契约对齐

## 准确基线与失败证据

- 唯一分支：`feature/external-algorithm-publishing`；起始 HEAD `60db6cb8467a8e78e6c2678b896d1e2ddbf24add`；正式 `VERSION.txt=42.24.561`，本批不改版本号。
- 该 SHA 的 39 项 Actions：34 success / 5 failure。失败均落在真实 Chrome 步骤，Node/后端合同步骤已通过；不是 5 个独立的生产故障证明。
- 原始运行：Online Feedback `42485597442`、Frontend Runtime `42485592762`、Training Material Picker `42485592788`、Algorithm SQL Store `42485592844`、Training Create First Open `42485592830`。
- 失败共 9 次测试报告，其中训练溯源用例在 Frontend/Algorithm SQL 两个工作流重复执行，唯一失败用例约 8 个。

## 定向原因与修复

| 症状 | 已核源码事实 | 本批修复/不变合同 |
| --- | --- | --- |
| 算法列表刷新为空、训练溯源卡片不出现 | `AlgorithmListRuntime.refresh()` 正式 GET `algorithms?summary_only=true`、`jobs?summary_only=true`；旧 Playwright mock 仅拦截无 query URL | 原浏览器场景改拦截摘要 GET，保留卡片真值、请求次数、无全量 Bootstrap、无额外 jobs 的断言；CRUD POST 继续拦截原不带 query 的写接口 |
| 反馈候选弹窗不出现 | 补数据场景的版本/动作 mock 同样未命中算法摘要 GET | 仅修 GET mock，保留候选资格、冻结、无 Dataset Revision/Snapshot/训练副作用的断言 |
| 迭代训练误显示“首次训练” | 版本 Read-side fixture 未命中摘要 GET；实际初始化因此读不到模拟的 verified latest version | 只修 mock，不放宽成功/verified/trainable 继承闸门及母模型禁编辑断言 |
| 训练创建后期望 jobs GET +1，实际 0 | `TrainingSubmitRuntime.refreshCreatedLists` 从“算法列表”走原 AlgorithmListRuntime 摘要回读；旧 jobs mock 未覆盖 query | 让 mock 精确拦截同项目 jobs 根路径及其 query；保留任务已持久可见、列表刷新、无重复提交等校验 |
| 素材已处理标签搜索不存在 | 当前标签搜索位于 `<details class="material-filters549">`，默认折叠；旧用例直接填隐藏字段 | 按真实用户动作展开“筛选”，再验证 person/vehicle 标签多选与两张实际图片结果 |
| 选材初始 `#trV3TrainingLabels` 不存在 | 当前 Picker 已移除冗余标签/角色计数框，角色筛选为 `#trV3RoleFilter`，首屏角色计算按需 | 改验真实角色选项、点击后候选背景范围、原 person 框、草稿选择和 GT 不变；不恢复旧占位 DOM 或首屏全量统计 |

## 范围与验收

- 本批仅改现有 Chrome 回归测试与进度说明；不改产品运行时、API、GT/Task/模型/数据库/Worker、缓存或请求 Owner，不重构。
- 本地 `npm ci`、完整 Node `1572/1572`、相关 Node `71/71`、JS 语法、47 个 Playwright 用例发现及 diff 检查通过；真实 Chrome 在本工作容器缺 Google Chrome，`playwright install chrome` 的 apt 权限失败、`install chromium` 下载非完整 ZIP，因此 **LOCAL CHROME NOT VERIFIED**。
- 最终必须以本批**准确新 SHA** 的 GitHub Actions 5 个红项和全部工作流为准；若仍失败，读取新日志再针对真实问题修复，不能借旧绿灯宣称全绿。4070/A800/生产 20 万素材 P95 与完整业务训练仍为 `NOT VERIFIED`。
- 不部署生产、不合并 main、不 tag/release、不 force push；后续如涉及真实生产代码修改，必须重新核对业务事实。
