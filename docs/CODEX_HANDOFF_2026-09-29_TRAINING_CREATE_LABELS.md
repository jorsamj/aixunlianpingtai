# 2026-09-29 训练任务创建 / 标签统一 / 继承标签 UI 交接

## 1. 当前真实基线

- 仓库：`jorsamj/aixunlianpingtai`
- 长期分支：`feature/external-algorithm-publishing`
- 2026-09-29 交接时远端真实 HEAD：`b3b6d82e3b6c6164e59beb81cb5bddc23410508a`
- HEAD 提交：`docs: hand off simplified training label UI`
- 本轮功能代码主要 cutoff：`dccff9f72ccef03b5937cad7dd29dfe94de60b0b`
- 随后只有测试 guard / 文档交接提交推进 HEAD，没有重新设计标签架构。
- `VERSION.txt = 42.24.0`，禁止修改。
- 本文提交后远端 HEAD 会继续前进；新会话必须重新读取远端 HEAD / checks，不能把本文记录当成未来最新 HEAD。

## 2. 用户这轮的真实需求

用户现场反馈：

> 在创建算法训练任务前，先把一批素材里的多个同义标签统一成一个 canonical 标签；随后打开“创建训练任务”弹窗，仍然能看到以前的旧素材标签。

后续用户进一步明确：

1. 真正训练时，算法 schema 也只能使用**统一后的 canonical 标签**，不能让已 merged 的历史 source label 再进入训练。
2. 创建训练任务弹窗不要承担“素材标签历史审计”。
3. 弹窗要简单，用户不要在训练创建阶段理解 `merged_into / source history / dropped history`。
4. 可以保留“上一版本继承”的标签：
   - 首次训练没有上一版本，因此不显示继承区；
   - 迭代训练自动继承上一成功/verified 版本的 canonical 标签；
   - 继承标签不能由用户取消；
   - 继承标签横向排列，不再纵向堆叠。
5. “本次素材标签”保留，但默认不选；用户需要新增类别时自己明确勾选。
6. UI 要紧凑、对称、美观、有高级感，不要把训练弹窗做成审计后台。
7. 前后端必须一致，不能为了 UI 再造一套标签继承算法或历史治理 owner。

## 3. 已完成：标签统一后的真正训练 schema 由后端唯一决定

当前 canonical owner：

`platform_core/training_label_tasks.py`

正式语义：

1. 上一版本继承 schema 来自上一 verified/current trainable version 的 frozen `label_schema`；必要时兼容读取 legacy snapshot，但不能相信浏览器自行推导。
2. 创建**新的训练任务**时，上一版本 immutable historical schema 会通过当前 project label governance 投影：
   - active label：保留；
   - merged label：沿 `merged_into` 链解析到当前 active target；
   - 多个历史 source 合并到同一个 target：去重，只留下一个 canonical target；
   - inactive 且没有明确 `merged_into`：fail-closed；
   - governance missing：fail-closed。
3. 最终 `effective_label_schema`：
   - `retained inherited canonical labels`
   - 加上用户本次**显式选择**、并且确实存在于 selected/effective training material Ground Truth 的新标签。
4. 最终 training `class_id` 重新压成连续 `0..N-1`；
   `canonical_project_class_id` 继续独立保留用于平台身份与审计。
5. schema 发生变化（含历史 merged label 折叠）时：
   - 继续使用上一版本权重初始化；
   - `strict_resume = false`；
   - optimizer state 不续接。
6. 历史算法版本本身的 `label_schema` 不修改；只影响**新建任务**的 effective schema。

因此：

**如果用户做的是正式“标签统一”，source label 已成功退休为 `merged -> target`，那么新训练任务真正进入模型训练的 schema 只会是统一后的 canonical target，不会再训练旧 source label。**

注意边界：

- 如果只是对“部分素材”做局部 remap，但项目 label governance 里的旧 label 仍然是 active，那么旧 label 仍可能是合法 current label；这和“整项目标签统一并退休 source”不是同一语义。
- 新会话不得把这两个场景混在一起。

关键相关提交：

- `de61947f02c58d3d32c45e4b78df041334ac4fff` — `refactor: make server own training label inheritance`
- `9f7507a5aa240a245c3f342781b3fc494581ec70` — `ci: execute merged training label contract`
- 更早的 merged inheritance / fail-closed 合同继续保留，不得删除。

## 4. 已完成：训练弹窗不再做历史标签审计

当前前端：

`static/modules/training-labels.js`

已明确移除训练创建 UI 对以下历史治理细节的 ownership：

- `resolveInheritedGovernance`
- `merged_into`
- `mergedInherited`
- `droppedInherited`
- `governanceBlockedInherited`
- `inherited_from_codes`
- “历史版本保持不变”等审计型说明

永久测试：

`tests/frontend/training-labels.test.mjs`

测试名：

`training label UI shows only server-resolved canonical inheritance without merge audit ownership`

它会直接检查以上历史 audit token 不能重新进入 training create UI。

训练创建前端现在只消费服务端 canonical preview：

`GET /api/v62/projects/{project_id}/training-labels/inherited?algorithm_id=...&base_version_id=...`

前端只负责**展示服务端返回的 canonical inherited labels**，不再自己计算 merge chain。

关键提交：

- `d55dac1cc7b45a4561c551c17b824086e3bc967f` — `refactor: simplify training label creation UI`
- `d2eab79b1bdba6cbb422deb2c923bc5d2cf202bd` — `test: lock simple training label creation`
- `34c2a3d151cb576937f0899e4bca27a57bb9b514` — `test: align simplified training label UI`

## 5. 已完成：“上一版本继承”标签改成横向高级 UI

后续补充需求已经落地：

- 首次训练：
  - 没有上一版本；
  - 不显示“上一版本继承”区。
- 迭代训练：
  - 服务端返回 canonical inherited labels；
  - UI 显示“上一版本继承”；
  - 标签为横向 pill/chip；
  - `display:flex; flex-wrap:wrap`；
  - 每个标签带圆形 ✓、显示名和 code；
  - 自动换行，不再纵向一条条堆；
  - 继承标签自动保留，不提供取消 checkbox。

当前样式主要位于：

`static/modules/training-labels.js`

关键 class：

- `.training-label-base`
- `.training-label-base-list`
- `.training-label-base-chip`
- `.training-label-material`
- `.training-label-choice`

布局特征：

- 继承区采用 `grid-template-columns:minmax(112px,auto) 1fr`
- 标签容器 `display:flex; flex-wrap:wrap`
- pill 使用圆角、轻阴影、浅边框、统一间距
- 小屏会自动降成一列
- “本次素材标签”与继承区视觉分层，但仍在同一“训练标签”卡片内，避免套娃

关键提交：

- `b9ee4f601105247591d29899c083610e5dd7798c` — `feat: expose canonical inherited training labels`
- `aff49e4449f7368aff70fadb21a930228f54be17` — `feat: polish inherited training labels`
- `dccff9f72ccef03b5937cad7dd29dfe94de60b0b` — `test: lock compact inherited training labels`

Real Chrome case：

`tests/browser/training-create-first-open.spec.mjs`

测试：

`training dialog shows canonical inherited labels horizontally without historical audit`

它验证：

- 能看到“上一版本继承”；
- inherited canonical label 正确；
- merged legacy source 不展示；
- `.training-label-base-list` 为 flex；
- UI 不重新出现历史 audit 信息。

## 6. “本次素材标签”的当前产品语义

仍然保留“本次素材标签”，但保持简单：

- 只显示当前 selected materials 的 active canonical labels；
- 默认**不自动勾选**；
- 用户自己决定本轮是否新增类别；
- 已经由上一版本继承的标签不会在“本次素材标签”里重复让用户选择；
- 当前素材标签都已经被上一版本覆盖时，显示简洁提示：
  `当前素材标签已由上一版本继承，无需重复选择。`
- 用户本轮真正选择的新增标签才会进入 requested new labels；
- 首次训练必须至少选择一个由已选正式 GT 证明的新标签。

永久合同：

`db7c47133d054671ffca2cfd5908df65e185bfbf`
— `test: never auto-select material labels`

禁止恢复：
- “智能猜标签”
- 自动按中文名/alias 替用户选 canonical code
- 首次打开训练弹窗自动全选素材标签

## 7. 之前“统一后弹窗仍看到旧标签”的根因与处理

这一问题不能只归因于一个点，实际排查包含两层：

### 7.1 Training Material Picker owner 曾存在重复/错误路由风险

相关收口提交：

- `be8c25b793b56d16ea3bbb024206eb9f0c3a2d84` — reveal duplicate picker repositories
- `2614ff662aee7e6567704dd92dac6496d12220d6` — inspect effective picker endpoint
- `0ae6b8def40884e5ec00e81b125034bd7fa3a808` — `fix: make training picker a single project-owned route`
- `dcb0319e9405310c6f6368218e6f33fc4b21c316` — align picker with selectable truth
- `1b4d291e5d1220eae08e71f0452de59412b9d7ee` — align full-pool guard

当前要求：

- `selection-summary` 只能有一个 project-owned canonical route；
- 必须读取对应 project 的 `MaterialRepository(materials.sqlite3)`；
- 不得重新挂第二套同 URL owner。

### 7.2 浏览器 selected-material summary 曾可能因同一组 material IDs 复用旧 cache

当前：

`TrainingMaterialSummaryRuntime`

已具备 explicit `invalidate()`。

新训练 session 开始时：
- 主动失效旧 material summary；
- 标签 mutation / unify 完成时也会失效并按需刷新。

Real Chrome 已有场景：

`same selected materials reload canonical labels after a completed label unification`

它模拟：
- 第一次同一批 material IDs 返回旧标签；
- 标签统一完成；
- 第二次仍选同一批 material IDs；
- 必须再次请求服务端；
- 旧 label 不得继续显示。

## 8. 当前 CI 真相（2026-09-29 交接时刻）

当前远端 HEAD：

`b3b6d82e3b6c6164e59beb81cb5bddc23410508a`

当前已确认：

- Label Normalization Contract：
  - HEAD `b3b6d82...` PR run `36502523520`：completed / success。
- Training Input Integrity：
  - HEAD `b3b6d82...` PR run `36502523369`：completed / success。
- Frontend Runtime Stabilization：
  - HEAD `b3b6d82...` push run `36502518169`：交接时仍 in_progress，不能写成通过。
- 上一轮 `ec4fca...` 的 Frontend Runtime failure 属于 cache/build guard 对齐问题，不代表训练标签产品语义失败；后续已有 `9918f15f...`、`ec4fca76...` 等 guard 对齐提交，当前 HEAD 正在重新验证。
- Training Create First Open：
  - 功能代码、永久 source guard、Real Chrome case 均已写入 workflow；
  - 新会话必须重新读取最新 workflow run / jobs，确认 Ubuntu / Windows / Real Chrome 最终终态，不能根据本文静态代码直接宣告全绿。

当前功能层已完成：

1. 正式标签统一后，训练后端 effective schema 只保留 canonical target；
2. 训练弹窗不再显示标签 merge 历史审计；
3. 前端不再自行实现 merge-chain resolver；
4. 首次训练不显示“上一版本继承”；
5. 迭代训练由服务端返回 canonical inherited labels；
6. inherited labels 横向 pills + flex-wrap，美观紧凑；
7. “本次素材标签”默认不选；
8. Training Material Picker 已收敛为单一 project-owned route；
9. 同一批 material IDs 在标签统一后会失效旧 summary，不能继续复用统一前标签缓存。

仍需新会话第一步重新确认：

- 真实 HEAD；
- VERSION；
- Training Create First Open 当前最新 run；
- Frontend Runtime Stabilization 当前最新 run；
- 所有 completed failure 的真实 job log；
- queued / in_progress 不得当作 success。


## 9. 下一会话禁止重复做的事情

不要：
- 再给训练创建 UI 加 `merged_into`、source history、merge audit、历史 schema 审计面板；
- 再在浏览器实现一套 merge-chain resolver；
- 把“上一版本继承”做回纵向长列表；
- 让 inherited label 变成可取消 checkbox；
- 自动勾选“本次素材标签”；
- 修改历史算法版本 schema；
- 创建第二个 TrainingMaterialPicker / TrainingLabel / LabelGovernance owner；
- 为了测试删除/放宽 fail-closed 断言；
- 修改 `VERSION.txt`。

## 10. 下一会话正确工作顺序

1. 先重新读取当前远端真实状态与 CI。
2. 如果所有上述相关 gate 绿：
   - 不再重构该链；
   - 只做生产部署后的真实 UI / 业务 smoke test。
3. 真实 smoke 必须覆盖：
   - 找一个已有旧标签的算法上一版本；
   - 在标签管理把多个同义 source 正式统一到 target；
   - 等 durable unify 任务 SUCCEEDED；
   - 重新打开“创建训练任务”；
   - “上一版本继承”只显示 canonical target，横向 pills；
   - 不显示旧 merged source；
   - 不显示 merge 历史审计；
   - “本次素材标签”默认不选；
   - 创建任务后检查 frozen label contract / job label_schema；
   - 最终 effective schema 只能包含 canonical target + 用户显式选择的新标签。
4. 如果仍出现旧 source label：
   - 先抓 `/training-labels/inherited` 返回；
   - 再抓 `/training-materials/selection-summary` 返回；
   - 再看 frozen `label_contract`；
   - 明确旧 label 是“继承 preview 错”“素材 summary 错”还是“最终 contract 错”，不要只凭 UI 猜。
