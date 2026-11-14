# P0｜批量选材执行中禁止单图复选框竞争（2026-11-13）

**只读审计基线：** `6b6bf11b6928b548c9323018b08bc6f3356e69c0`，`VERSION.txt=42.24.592`，准确 GitHub Actions **37/37 completed/success**，Frontend Node **1664/1664**，Training Material Picker/contracts 与 real-chrome-picker 全部成功。

**范围：** 沿用 `TrainingMaterialPickerRuntime` 的既有 `picker.selected` / `picker.reference` Owner 与 `bulkPending`，只解决异步批量请求与单图复选框变更的确定性竞争；不调整筛选/冻结合同、GT、Train/Test 分流、任务提交、Worker 或数据库。

## 代码复现

1. `bulkAction()` 开始后 `bulkPending=true`，`syncPickerActions()` 原本只禁用批量按钮与确认按钮，不影响当前页素材卡里的 `input[type=checkbox]`。
2. `toggle(id,on,checkbox)` 原本只检查 `reviewPending`，不检查 `bulkPending`。因此批量 API 尚未返回时，用户仍可取消/勾选单张素材，改变 `picker.selected`；若当时是冻结引用，甚至可能解除 `picker.reference`。这破坏请求发起时的选择意图与请求返回后的选择状态一致性。
3. 隔离运行原函数分支：`bulkPending=true`、`selected={'a'}`，调用 `toggle('a',false,...)` 后集合变为 0；该代码缺陷可复现，不是假定的生产性能问题。

## 采用的成熟做法

- 将**当前页复选框**视作批量异步请求的互斥控件，`syncPickerActions()` 在 `bulkPending` 时禁用可勾选项；只对本次禁用的控件使用 `data-bulk-selection-locked` 私有标记，完成、失败或取消时恢复，严格保留原有策略禁用状态。查看图片等不涉及选中状态的功能不受影响。
- `toggle()` 另有函数级 `bulkPending` 守卫：若迟到事件仍进入，按 `picker.selected` 或冻结清单在当前页的 `selection_member` 还原复选框状态，既不改变 ID 集合也不解除引用。
- `renderPage()` 重建卡片后再调用原动作同步函数，防止批量请求与重绘交错时出现新复选框短暂可操作。
- 保留 `AbortController`、当前 Picker Owner / 项目 / 过滤签名检验，不新增事务 Owner、第二套数据存储或前端框架；没有对服务器写入路径做任何修改。
- 参考成熟组件对选中 ID 与当前页 DOM 分离的做法（[TanStack Table Row Selection](https://tanstack.com/table/v8/docs/guide/row-selection)）。不使用对整个素材网格设置 `inert` 的方案，避免同时屏蔽原图预览和对辅助技术隐藏内容（[MDN inert](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Global_attributes/inert)）。

## 验证矩阵

| 场景 | 自动化断言 | 影响边界 |
| --- | --- | --- |
| 正在批量选择，已勾选图的迟到取消事件 | Node 真实 `toggle()` 分支执行，原 ID 不丢、复选框恢复 | 无任务提交、无 GT 变更 |
| 正在批量选择，已有冻结引用的迟到变更 | 冻结 `selection_ref` 不解除，按 `selection_member` 还原勾选 | 保留冻结 Manifest Owner |
| 批量执行中启用临时禁用 | 原可选复选框锁定、数据集策略已禁用项保持禁用 | 不覆盖历史/GT 禁用规则 |
| 批量操作结束 | 原可选复选框恢复，普通 `toggle()` 再次生效 | 不额外刷新全库 |
| 请求中间重绘素材卡 | `renderPage()` 末尾重用锁定函数 | 每页最多几十个可见复选框 |
| 延迟批量 HTTP 返回 | 真实 Chrome 拦截并延迟 `bulk-selection`；等待时确认和卡片复选框不可点，直接调用迟到事件仍不改变选择，完成后恢复并显示正确数量 | **隔离 Chrome**，非生产 20k 性能证据 |
| 前端入口缓存 | 同步 `styles.css`、`app.js`、`main.mjs` 的纯数字缓存键为 `42.25.606`，选择器 ESM 模块导入匹配；保留全部版本守卫 | `VERSION.txt` 不变 |

新增单测与 Chrome 回归跟随本次代码提交；准确 CI **待新 SHA 完成后核验**。不因为单测通过而直接宣布发布合格。

## 仍待现场验收

- 真实 A800 或双 4070 已创建训练任务的**只读** `selection_ref/count`、父任务 `payload.json`、`input-request-selection.json`、Worker `selection_counts` 和 `input-freeze.json` 数量/身份对照，按阶段采样 P50/P95。
- 有证据的合理差异须解释为排队期间删除、正式 GT 未准备好、训练资格/重复图冲突等，禁止静默补选，不能将 20k / 30k 隔离模拟等同生产正式 GT。
- 无用户授权绝不部署、重启、启动生产训练或变更正式 GT。分支仅 `feature/external-algorithm-publishing`，不合并 main / force push / Release。
