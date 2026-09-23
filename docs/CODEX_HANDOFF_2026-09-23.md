# Codex / AI 接手交接 — 2026-09-23

> ## 2026-09-23 10:xx Codex 接手最终刷新（最高优先级覆盖）
>
> **本节是当前最高优先级交接。接手后第一步仍必须重新读取 GitHub 远端真实状态，不能把下面 SHA 当作当前 HEAD。**
>
> 文档写入前最后确认代码/测试 HEAD：
> `c9064dcde055daab926252bf67aea181af6aa0f5`
>
> `VERSION.txt = 42.24.0`。
>
> 该 HEAD 写文档前的 GitHub check-runs：**89 个 queued、0 completed、0 completed failure**。因此：
> - queued 绝不等于通过；
> - 不能据此宣称“全绿 / 部署候选 / 可以正式上线”；
> - 后续只要出现 completed failure，必须先读取该 job 的真实日志，再决定是 stale guard、测试隔离、旧 route 断言，还是产品行为问题。
>
> ### 这轮已经 CLOSED，不要重复做
>
> **P0 Real Chrome / 产品合同**
> - 手动标注：标签 first-paint、画框、拖框、四角 resize、删除、撤销、滚轮缩放、100%、适应窗口、连续空图显式“确认无目标”、上一张/下一张自动保存、stale response fencing。
> - ZIP / 批量导入：exact canonical code 自动复用、合法英文文件标签显式新增、正式标签 API → refresh → mapping → durable start、关闭重开、Unified Upload Task Center 恢复、浏览器 refresh recovery。
> - 质量中心模型检测：builtin / algorithm version、A/B、A-only、B-only、confidence、单图/多图、真实目录 input、非图片过滤、durable `DEPLOYMENT_TEST`、批次历史、人工核验、Online Feedback evidence bridge、stale model SHA fail closed。
> - 自动清洗运行中详情：已从裸 timer 迁到 PollRegistry；同一个弹窗原地 patch，关闭/切页停止，进入待确认后自动切正式结果详情；有 Real Chrome handoff 守护。
> - AI Candidate Review：已覆盖大量正式标签和多页候选；跨页人工 edits 保留、乱序分页 stale fencing、关闭/提交后的 late response lifecycle fencing；人工 edits 不会在翻页后视觉回退。
>
> **P1 cache-first / revisit / 页面稳定性**
> - 导航不再声明 full-material page owner；完整素材池只允许在明确用户动作边界 lazy hydrate。
> - `page-loading-performance.spec.mjs` 已进入正式 Frontend Runtime Stabilization Real Chrome。
> - 启动 bootstrap snapshot 首屏画完后不再无条件做第二轮 broad extras + render。
> - 训练创建成功后不再 broad `loadRelated()`；算法列表 / 训练任务各自 scoped refresh。
> - 训练任务页 jobs-only；不会顺手读取 `training_options` / `models`。
> - 标签保存不再调用不存在的 `refreshImages414()`；只刷新 authoritative label schema。
> - 重复点击当前已激活导航不会产生第二次 navigation epoch / page owner。
> - 退役的部署转换 / 部署产物已从 final page-extras owner 移除；底层转换、ModelArtifact、OSS、RKNN、新畅联同步能力仍保留。
> - 训练设备 24h 浏览器 cache 已有 reload Chrome 守护。
> - 标注标签 stale cache first-paint + authoritative revalidation 已有 Chrome。
> - 标签管理、训练资源、组件检测、平台对接、服务节点、存储、素材接入、视频切帧、Dashboard 等回访缓存已经有守护。
> - 训练资源 authoritative background refresh 只 patch resource cards，不重建用户正在填写的接入表单。
> - 模型配置 prompt templates 改为按需读取；background refresh 只 patch prompt 区域，不重建 model config 表单。
>
> ### 当前 final asset / runtime 参考
>
> 文档写入前：
> - `static/index.html`：`app.js?v=42.25.214`
> - `static/index.html`：`main.mjs?v=42.25.210`
> - `VERSION.txt` 仍必须保持 `42.24.0`
>
> 上述 asset key 是当前代码现场参考；后续如果改对应 runtime，必须同步现有永久 guard，不允许出现“源码改了但浏览器继续命中旧 asset”的情况。
>
> ### 已核对但不要机械删除 / 恢复
>
> - 训练素材旧 V3 全量 `/images` picker 是 compatibility fallback；final TrainingMaterialPickerRuntime 使用 server-paged training-materials。
> - 算法列表旧展开 / 旧 render 仍可能存在定义，但 final AlgorithmListRuntime 已覆盖；不要因为字符串存在就误判正式 owner。
> - ZIP legacy interval 是 compatibility bridge；正式 ZipImportRuntime 安装后用 sentinel 阻止第二 polling owner。
> - `pollAnnotationIndex412` 当前无调用点。
> - AI / 清洗结果只在明确用户动作且返回项缺 URL 时按需 `ensureFullPool()`。
> - TrainingTaskRuntime 已覆盖插队 / 暂停 / 继续 / 停止 / 删除；旧函数里的 broad reload 不是 final owner。
> - 不要恢复“测试发布 / standalone 检测台 / 部署中心”来兼容旧测试。
>
> ### 当前仍 OPEN
>
> 1. **当前目标 HEAD 的 GitHub Actions 真实 completed 结果**。这是下一任接手者第一优先级。
> 2. **真实 GPU / 正式模型推理 E2E**。浏览器中受控推理替身只能证明 UI / durable-task / API 合同，不能当生产 GPU 验收。
> 3. **真实 OSS 长期 URL + ChangLian Version/Weight 生产 E2E**：
>    - 原始训练模型上传；
>    - 转换产物上传；
>    - Version / Weight 创建；
>    - 远端反查；
>    - 删除 / 回退；
>    - 网络超时后的幂等恢复；
>    - URL 长期可读性。
> 4. P0 Real Chrome/CI 真正 completed 后，再继续全站 performance profile；只修真实 duplicate fetch / whole-root repaint / stale response / double owner。
>
> ### Codex 下一步执行顺序
>
> ```text
> 1. 重新读取 origin/feature/external-algorithm-publishing 当前真实 HEAD
> 2. 读取 VERSION.txt，必须仍为 42.24.0
> 3. 读取最近至少 30 个 commits
> 4. 读取目标 HEAD 的 check-runs / Actions
> 5. 对所有 completed failure 读取真实 job log
> 6. 完整阅读本文件顶部最新覆盖 + PROJECT_HANDOFF_CURRENT + CODEX_CURRENT_STATE
> 7. 只处理真实 failure / 真实可达 owner，不重复 CLOSED 工作
> 8. Actions 大量 queued 时可继续独立审计，但部署结论必须等目标 HEAD completed checks
> 9. 若远端 HEAD 期间前进，立即停止写入，重新 compare 后再继续
> 10. 不 merge main、不 tag、不 release、不 force push、不修改 VERSION.txt
> ```
>
> ### 下一任最重要的判断原则
>
> `真实状态 → final owner → canonical truth → 最小正确修复 → focused test → Real Chrome → CI`
>
> 不要先看到旧函数就删；不要先看到旧测试就恢复旧产品入口；不要用 mock 成功替代真实 GPU / OSS / ChangLian 生产 E2E。
>
> ## 2026-09-23 09:xx 续接增量（最高优先级覆盖）
>
> 文档刷新前最后确认代码/测试 HEAD：`0fd99a33bec1527c1d4d3d96a220ac43d3fd999b`；`VERSION.txt = 42.24.0`。该 HEAD 当时 **51 个 checks 全部 queued、0 completed failure**，因此仍不能宣称全绿、部署候选或可上线。接手后必须重新读取实时 GitHub，不能把本段 SHA 当作当前 HEAD。
>
> 本轮新增 CLOSED / 永久守护：
> - 训练设备 inventory 的 **24h 浏览器缓存**已有 Real Chrome：首次训练弹窗读取 `/api/v62/training-devices` 并持久化；整页 reload 后再次打开训练弹窗直接复用缓存，不重复探测硬件。
> - 手动标注标签 first-paint 已有 Real Chrome：即使正式标签 API 被延迟，过期本地 schema 也会先立即显示；authoritative 响应返回后再更新 UI 与缓存，保证“快但不 stale forever”。
> - 标签管理 usage schema 回访缓存已有 Chrome：首次进入读取，短时间离开/返回不重复请求。
> - 训练资源页 page-extras 回访缓存已有 Chrome：首次进入允许读取 training options，短时间返回不重复加载。
> - 组件检测终态 snapshot 回访缓存已有 Chrome：返回页面不重复 `/components/latest`，更不会自动 POST 新扫描；真正扫描仍只由用户点击触发。
> - 模型配置提示词模板已改为按需读取并有回访缓存；平台对接、服务节点、存储配置、素材接入、视频切帧也已增加回访不重复请求守护。
> - AI Candidate Review 已完成 54 张候选 / 34 标签 / 3 页 Chrome，跨页人工 edits 保留、乱序分页 stale fencing、关闭/提交后的 late response lifecycle fencing 均已收口。
>
> 已再次核对且不要重复：
> - 数据集返回页已经是 cached page first-paint + background scoped refresh；已有 Real Chrome。
> - 自动标注页存在 RUNNING 任务时必须恢复 PollRegistry，不允许为了“0 请求”破坏实时进度真值。
> - 训练资源首屏的 targets / inference env / recommendation 已由 v53 bootstrap snapshot 提供；手动“刷新”才做更强 authoritative refresh。
> - 组件检测页面进入不会自动扫描；实际扫描只由按钮触发。
>
> 当前仍 OPEN：
> - 目标 HEAD 的真实 completed Actions；任何 completed failure 必须先读真实 job log。
> - 真实 GPU / 正式模型推理 E2E。
> - 真实 OSS 长期 URL + ChangLian Version/Weight 创建/反查/删除 + 超时幂等恢复生产 E2E。
>
> 不要因旧测试恢复已退役的测试发布 / standalone 检测台 / 部署中心 owner；不要再重复上述 cache/revisit/first-paint CLOSED 工作。
>
> ## 2026-09-23 08:xx 续接增量（覆盖前一轮续接状态）
>
> 文档刷新前最后确认代码/测试 HEAD：`76fbfdfd5aecce22c32de90f507a1703dbffc21b`；`VERSION.txt = 42.24.0`。该 HEAD 当时 **89 个 checks 全部 queued、0 completed failure**，因此仍不能宣称全绿、部署候选或可上线。
>
> 本轮继续完成：
> - 质量中心“选择文件夹”已有真实 Chrome 目录输入：递归两张图片 + 非图片过滤，并实际创建 A/B durable detection tasks。
> - 自动清洗运行中详情从裸 `setTimeout` 收口到 PollRegistry page owner；弹窗原地 patch，待确认后自动切结果详情，并有 Real Chrome handoff 守护。
> - AI Candidate Review 大批量 Chrome 已扩大到 **54 张候选 / 34 个正式标签 / 3 页**，覆盖批量映射、显式新建标签、批量统一标签、单框坐标/标签人工修改、accept-all 保留人工 edits。
> - 修复 AI Review 跨页人工 edits 视觉回退：分页重新读取服务端 candidate 后会重新叠加当前 review session 的人工 edits。
> - 修复 AI Review 分页乱序 stale response：`pageRequestEpoch` 只允许最后一次分页请求更新 UI。
> - 修复审核 session 关闭/提交后的 late response 复活：加入 `closed + ownerPage + request epoch` fencing；提交或“暂不处理”后旧分页响应不能重开弹窗。
>
> 已再次核对且不要重复：
> - TrainingTaskRuntime 已覆盖插队/暂停/继续/停止/删除，旧 `promoteTrain428 -> loadRelated()` 只是 legacy 定义。
> - ZIP legacy interval 由 ZipImportRuntime sentinel 阻止成为第二 polling owner。
> - 质量中心批量检测离页后 durable task 可继续，DOM patch 在页面不存在时 no-op；不应为了离页强制取消真实任务。
>
> 仍 OPEN：
> - 目标 HEAD 的真实 completed Actions。
> - 真实 GPU / 正式模型推理 E2E。
> - 真实 OSS 长期 URL + ChangLian Version/Weight 创建/反查/删除 + 超时幂等恢复生产 E2E。
>
> 后续若 Actions 出现 completed failure，必须先读真实 job log；不要因旧测试恢复退役的测试发布/检测台/部署中心 owner。
>
> ## 2026-09-23 本轮续接更新（最高优先级覆盖）
>
> **本节覆盖本文后面较早的 P0 / NEXT 状态。接手仍必须先读取实时 GitHub，不能把下面 SHA 当作当前 HEAD。**
>
> 本轮文档刷新前最后确认的代码/测试 HEAD：
> `bb3803167e8cd7ac039cf9766b0b8cfc79c06f2f`
>
> `VERSION.txt = 42.24.0`，未 merge `main`、未 tag、未 release、未 force push。
>
> 文档刷新前该 HEAD 的 GitHub check-runs 为 **55 个 queued、0 个 completed failure**。因此当前只能说“代码/测试守护已继续收口”，**不能宣称全绿、部署候选或可以上线**；后续一旦出现 completed failure，必须先读真实 job log。
>
> ### P0 Real Chrome 守护已经继续补齐
>
> 手动标注浏览器合同现在覆盖：
> - 标签 first paint / 正式标签选择。
> - 画框、拖框、四角 resize。
> - 删除、撤销。
> - 鼠标滚轮缩放、100%、适应窗口。
> - 连续两张空图都必须显式“确认无目标”，服务端状态为 `confirmed_empty`。
> - 上一张 / 下一张自动保存当前未保存标注。
> - stale annotation response fencing，旧图片晚返回不能覆盖新图片。
>
> ZIP / 批量导入浏览器合同现在覆盖：
> - 文件标签 code 与平台 canonical code 完全一致时自动复用，不重复建标签。
> - 平台不存在且文件标签为合法英文 code 时，显式选择“使用文件标签并新增”。
> - 新增必须先调用正式标签 API，再提交 `label_mapping` / durable import start。
> - modal 关闭、Unified Upload Task Center 重新打开、浏览器 refresh 后恢复待确认任务。
> - 仍然保持“人工确认后才进入正式 Ground Truth”，不恢复 `create_labels` 静默旁路。
>
> 质量中心模型检测浏览器合同现在覆盖：
> - builtin / algorithm version 分组与搜索。
> - A/B、A-only、B-only。
> - confidence。
> - 单图、多图、非图片过滤。
> - **真实目录 input**：递归选择文件夹中的图片、自动忽略 txt 等非图片。
> - durable `DEPLOYMENT_TEST` task、批次历史、人工核验。
> - 质量概览 ↔ 模型检测切换复用 test_models / inference env，手动“刷新模型”才强制重拉。
> - v64 detection → v63 Online Feedback evidence bridge 已有 Real Chrome；正式模型 SHA stale fail-closed 已有 API 回归。
>
> 注意：质量中心浏览器用例中的模型推理响应仍是受控测试替身，用于验证前端/任务/API 合同，**不等于真实 GPU / 真实模型生产推理 E2E**。
>
> ### 本轮 P1 性能 / owner 收口
>
> 已完成并加永久守护：
> - 导航不再声明任何 full-material page owner；完整素材池只能在明确用户动作边界 lazy hydrate。
> - `page-loading-performance.spec.mjs` 已正式接入 Frontend Runtime Stabilization Real Chrome。
> - 训练创建成功后不再 broad `loadRelated()`；算法列表只 scoped refresh 算法 owner，训练任务只刷新 TrainingTaskRuntime。
> - 训练任务页现在是 jobs-only；进入页面不再顺手拉 `training_options` / `models`，训练配置由 TrainingCreateHydrationRuntime 在点击训练时按需并行读取。
> - 启动 bootstrap snapshot 首屏绘制后不再无条件追加一轮 page extras + 二次 render。
> - 标签保存修复了不存在的 `refreshImages414()` 调用；保存后只刷新 authoritative label schema，并有 Real Chrome 新建/编辑/落库/无全量 images 请求守护。
> - 质量中心模型检测 extras 使用独立 TTL/in-flight owner；切 tab 不重复请求。
> - 重复点击当前已激活菜单不会再次触发导航 epoch / page owner。
> - 退役的 `部署转换` / `部署产物` 已从 final navigation page-extras owner 清除；底层转换、ModelArtifact、OSS、RKNN、新畅联权重同步能力继续保留。
> - 自动清洗运行中详情已从裸 `setTimeout` 迁到 PollRegistry；同一个弹窗原地 patch 进度，关闭/切页即停止，进入待确认后切正式结果详情，并有 Real Chrome handoff 守护。
>
> ### 已核对但不要机械修改
>
> - 训练素材旧 V3 全量 `/images` picker 是 compatibility fallback；final TrainingMaterialPickerRuntime 已覆盖并使用 v62 server-paged training-materials。
> - 算法列表旧展开函数会请求 algorithms，但 final AlgorithmListRuntime 已覆盖；现有 Chrome 明确守住展开/收起 0 次算法 API。
> - ZIP 旧 `setInterval` 是 compatibility bridge；ZipImportRuntime 安装后用 sentinel 阻止它成为第二 polling owner。
> - `pollAnnotationIndex412` 当前无调用点。
> - AI / 清洗结果只有在明确用户动作且返回项缺 URL 时才按需 `ensureFullPool()`。
>
> ### 当前仍 OPEN
>
> - 最新目标 HEAD 的 Actions 尚未 completed；任何部署判断必须等目标 HEAD 的真实 completed checks。
> - 真实 GPU / 正式模型推理 E2E。
> - 真实 OSS 长期 URL、ChangLian Version/Weight 创建/反查/删除、超时幂等恢复的生产 E2E。
> - P0 全部 CI/Real Chrome 真正执行结果出来后，再继续全站 performance profile 和 AI 审核大批量交互验收。
>
> ### 下一步顺序
>
> ```text
> 1. 重新读取当前真实 HEAD / VERSION / check-runs
> 2. 任何 completed failure：先读真实 job log，再判断 stale guard / 测试隔离 / 产品行为
> 3. 优先处理 P0 Real Chrome 的真实失败，不因旧测试恢复退役 owner
> 4. P0 completed success 后做全站 profile：duplicate fetch / whole-root repaint / stale response / double owner
> 5. 再做 AI 审核大量标签与大批候选的真实浏览器交互验收
> 6. OSS / ChangLian / 真实 GPU E2E 单独验收，mock 不能替代
> ```
>

> **当前最高优先级交接入口。**
>
> 新会话 / 新 Codex / 新开发人员接手 `jorsamj/aixunlianpingtai` 时，必须先读取 GitHub 当前真实远端状态，再读本文件。
>
> 本文件记录的是**文档写入前**的代码/测试基线；创建本文件和刷新 pointer 文档会继续推进分支 HEAD，所以绝对不能把本文中的 SHA 当成“现在仍然是 HEAD”。
>
> 权威顺序：**GitHub 实时远端 → 本文件 → 当前 owner 代码/测试 → PROJECT_HANDOFF_CURRENT / CODEX_CURRENT_STATE → 2026-09-22 及更早历史 handoff**。

## 1. 当前基础信息

- 仓库：`jorsamj/aixunlianpingtai`
- 长期开发分支：`feature/external-algorithm-publishing`
- 项目：**畅联云算法训练平台**
- 正式版本：`VERSION.txt = 42.24.0`
- 文档写入前真实代码/测试 HEAD：
  `203948a5ef7b68e4a23fc609a6c4233f09d48e95`
- 该 HEAD 提交信息：`ci: align final navigation asset keys`
- 不 merge `main`
- 不 tag
- 不 release
- Windows 11 开发与 NVIDIA Linux 生产继续双兼容

### 接手后的第一步必须重新读取

1. `origin/feature/external-algorithm-publishing` 当前真实 HEAD。
2. `VERSION.txt`。
3. 最近至少 30 个 commits。
4. 当前 GitHub Actions / check-runs。
5. 任何失败 job 的**真实日志**。
6. 本文件。
7. `docs/PROJECT_HANDOFF_CURRENT.md`。
8. `docs/CODEX_CURRENT_STATE.md`。

不要根据本文 SHA、旧会话 SHA 或历史 CI 状态直接假定当前状态。

---

## 2. 绝对约束

这些规则仍然有效，接手者不要因为本轮 UI / 性能工作而破坏：

- **`VERSION.txt` 必须保持 `42.24.0`。**
- **不 merge `main`、不 tag、不 release。**
- 不删除测试、不靠放宽行为断言、不降低阈值来“让 CI 变绿”。
- GitHub Actions 排队时可以继续做独立开发，但**部署候选 / 全绿声明必须以目标 HEAD 的真实 completed check 为准**。
- 前后端字段、状态、API 合同必须统一。
- 正式页面不得用假数据、假进度、假延迟冒充 truth。
- Durable Task、Annotation Ground Truth、ModelArtifact、ExternalPublicationRepository 等 canonical truth 不允许再建第二套。
- polling 继续由 PollRegistry / 现有 runtime lifecycle 管理，不重新引入散落 raw timer。
- cache-first 不等于 stale forever：缓存负责立即可用，后台 authoritative refresh 负责最终真值。
- 若远端 HEAD 在工作过程中前进，必须先 compare / re-read，再继续；禁止 force push 或覆盖并发改动。

---

## 3. 2026-09-23 产品信息架构已经发生的重要变化

用户明确提出：

1. 不要“测试评测”整块产品内容，包括原“测试发布”。
2. 检测能力必须保留，但迁到 **总览 → 质量中心 → 模型检测**。
3. 部署中心整块从产品导航拿掉。
4. 收起高级功能后一级菜单只保留：
   - **总览**
   - **算法生成**
   - **数据中心**

### 当前已经完成的方向

分支中已经完成并继续收口：

- standalone `测试发布` / `检测台` page owner 退役。
- 旧 `测试发布` / `检测台` 导航别名统一归一到 `质量中心`。
- standalone `部署中心` 产品入口退役。
- 旧部署页面导航 alias / page owner / owner metadata 后续也继续被清理。
- 浏览器旧部署导航测试已迁移为“退役路由不得重新暴露”。
- 收起高级功能时，正常产品导航固定为三组：
  - `总览`
  - `算法生成`
  - `数据中心`
- 高级配置、系统/节点/外部平台等只在“展开高级功能”后出现。
- **底层训练后转换、ModelArtifact、OSS 上传、瑞芯微等转换、畅联同步能力没有被删除。**
  删除的是旧产品“部署中心”导航/页面 owner，不是底层产物与交付链。

### 不要回退

不要为了兼容旧测试重新把“测试评测 / 测试发布 / 部署中心”加回菜单。
旧 route 兼容只允许归一到新产品位置，不允许重新成为正式用户入口。

---

## 4. 质量中心 / 模型检测：当前实现状态

本轮已经把用户要求的检测台从旧“测试发布”迁到质量中心，并完成较完整的新工作台。

### 已完成

#### 4.1 A / B 模型选择

质量中心模型检测支持两侧模型浏览：

- A 模型
- B 模型
- 两侧都可以选择：
  - 原始 / 基础模型
  - 任意算法
  - 该算法下可用版本
  - 现有允许推理的项目/本机模型
- 算法版本在选择器中按所属算法分组。
- 支持搜索算法、版本、模型名称。
- 不使用无限增长的普通单层 select 作为最终产品体验。

#### 4.2 检测模式

已实现三类产品意图：

- A/B 同图对比
- 只测 A
- 只测 B

置信度由用户设置。

#### 4.3 图片输入

已支持：

- 单张图片
- 多张批量选择
- 选择文件夹（Chromium `webkitdirectory`）
- 非图片文件会过滤
- 当前批次有图片队列和预览

#### 4.4 批量真实推理

批量检测不是前端假结果：

- 每张图片真正创建持久 `DEPLOYMENT_TEST`。
- A/B 模型按需要分别运行。
- 批量执行按图片顺序受控推进，避免浏览器一次性把同一 Runtime/GPU 打爆。
- 每个真实任务附带：
  - `detection_batch_id`
  - `detection_item_index`
  - `detection_item_total`
  - `detection_side`
  - 模型 identity
  - 原始文件名
- 前端继续读取真实 task truth / result truth。

#### 4.5 检测批次持久化

新增 durable 检测批次查询：

- 最近检测批次
- 单批次详情
- 图片级 A/B 结果
- 原图地址
- 检测图
- detections
- inference / elapsed timing
- 失败状态
- 人工核验结果

刷新质量中心后，最近检测批次可从服务端重新读取，不再只存在浏览器内存。

#### 4.6 人工核验

检测结果详情支持人工标记：

- 正确
- 漏检
- 误检
- 框不准
- 类别错误

人工核验为**检测质量记录**，不会直接成为 Annotation Ground Truth。
后端也限制：任务未结束或没有真实成功推理结果时，不允许提前保存核验。

#### 4.7 线上抽检 / 反馈桥

旧“测试发布”的 v63 线上抽检闭环没有被删掉，而是迁移到质量中心语义：

- 正式算法版本的成功持久检测可以显式生成 review evidence。
- 只有 `algorithm_version` 才允许进入反馈 evidence。
- 后端绑定并校验正式版本模型 SHA。
- stale / 不一致模型 evidence 会 fail closed。
- detection 本身不会自动进入 Ground Truth。
- 用户显式提交后继续走原有：
  `prediction/evidence → pending_review → 人工复核 → confirmed/dismissed`
- 原有 false positive 的“确认全标签不存在”等安全语义继续保留。
- 外部抽检 intake 继续使用 v63 人工复核合同。

相关连续提交包括：
- `babac6cf` — promote quality detections to review evidence
- `0865d736` — connect quality detection to feedback review
- `7425f936` — cover quality detection feedback evidence
- `d8c477b8` — migrate feedback review to quality center
- `d9ce6f9e` — guard quality feedback review bridge
- `574116aa` — bind feedback evidence to tested model sha
- `8236ce18` / `5f3f02ce` — model SHA / stale evidence regression guards

### 后续又完成的性能收口

在检测功能完成后，分支还继续做了：

- quality detection shell 保持稳定，不重复整页重建。
- quality center 不再因为进入页面就 hydrate full material pool。
- material / quality runtime cache key 与永久 CI guard 已同步。
- 当前不要再恢复“质量中心进入就拉全部素材”的旧行为。

---

## 5. 手动标注：本轮已处理的核心问题

用户反馈：

- 标签有时十几秒才出来。
- 标注框拖动/删除会乱跳。
- “确认无目标”点了没反应。
- 页面太丑。
- 图片缺少好用的滚轮缩放。

### 已完成

#### 5.1 标签立即可用 + 后台真值重验

- 标签 schema 增加浏览器短缓存，用于标注工作台立即显示。
- 缓存只负责 first paint。
- 超 TTL 后仍会后台请求 authoritative label truth。
- 不把 localStorage 变成长期 canonical truth。

#### 5.2 标注框改为 keyed DOM patch

旧行为会在移动/缩放/删除时：

`删除全部 box DOM → 重新创建全部 box`

这正是视觉跳动的重要来源。

当前已经改为：

- 按 box identity / index keyed patch。
- 未变化 box DOM 保持。
- active 状态、位置、尺寸、tag、handles 只更新当前节点。
- 删除只删缺失 box，不再把所有 box 全部卸载重建。

#### 5.3 侧边框列表不再整体重建

- box row 改为 keyed patch。
- 标签 option 有 signature。
- 未变化时不重新生成。
- 删除/切换 label 不再无条件重建整块 sidebar。

#### 5.4 “确认无目标”

- 改为显式 async canonical action。
- 点击后显示“确认中…”。
- 最终仍走 `confirmEmpty:true` / `confirmed_empty` 语义。
- 不允许用普通空 boxes 保存绕过显式确认。

#### 5.5 缩放与工作区

当前 stable annotation workbench 已补：

- 鼠标滚轮缩放
- `+`
- `-`
- `100%`
- `适应窗口`
- 固定画布 / sidebar / queue 的更专业布局
- 图片坐标真值仍是原始坐标，不用缩放后的屏幕坐标做 Ground Truth

### 尚需接手者做真实浏览器验收

虽然已经有 source/browser guard，但最新 HEAD Actions 尚未完成，因此接手者仍应重点人工/Real Chrome 验收：

1. 首次打开标签是否即时出现。
2. 连续拖动框是否无抖动。
3. 删除框是否不导致其他框跳位。
4. 连续切上一张/下一张是否无 stale response 覆盖。
5. 滚轮缩放后框坐标是否稳定。
6. “确认无目标”是否真正完成后端保存并即时反馈。

---

## 6. ZIP / 批量导入：用户要求与当前实现

用户要求：

- 标签可使用文件自己的标签。
- 文件英文标签与平台标签库英文 code 一一对应时自动套用。
- 平台不存在时允许显式新增标签。
- 确认按钮必须有真实状态。
- 弹窗关闭后要能重新打开。
- 任务不能因为 modal 生命周期而丢失。

### 已完成

#### 6.1 自动复用

ZIP 外部类别：

- 如果外部标签名与平台 active label code 精确一致：
  - 自动复用平台标签。
- 如果不一致但已有 suggested target：
  - 按正式映射展示。

#### 6.2 文件标签显式新增

如果文件外部标签：

- 是合法 canonical 英文 code；
- 当前标签库不存在；

则确认 UI 提供：

`使用文件标签“xxx”并新增`

确认时：

1. 先通过正式平台标签 API 创建标签。
2. 刷新标签库。
3. 再提交 mapping。
4. 最后启动 durable ZIP import。

仍然禁止把外部类别通过旧 `create_labels` 旁路静默写入标签库。

#### 6.3 明确确认状态

按钮状态会显示：

- 正在确认
- 正在创建平台标签
- 正在启动后台导入
- 失败错误

避免以前“点了没反应”。

#### 6.4 可恢复弹窗

ZIP durable task 与 modal 生命周期已经分离：

- 关闭弹窗不终止任务。
- Unified Upload Task Center 中 ZIP task row 可点击。
- 可重新打开同一个 durable import task。
- refresh recovery browser guard 已加入。

相关提交：
- `d6325c2b` — recoverable ZIP label confirmation
- `016acd75` — reopen ZIP imports from task center
- `852355b9` / `bb0b2401` / `e651b525` — unit + task-center + browser guards

---

## 7. AI 自动标注人工审核：本轮 UI 收口

用户此前要求 AI 自动标注必须：

- Candidate
- Human Review
- Durable Commit
- 才能进入 Ground Truth

这个合同继续保持。

### 本轮新增体验

AI Review 标签处理已经优化：

- 平台标签使用可搜索 datalist/combobox，不再只有超长 select。
- 来源标签列表支持筛选。
- 支持“所有来源标签 → 一个目标标签”的批量映射。
- 支持勾选多张候选图片后：
  - 把这些图片中的全部候选框统一为一个平台标签。
- “全部接受”时，如果某些图片已经人工改过 boxes，会把 edits 一起提交，不能丢掉人工修改。
- 映射 renderer 增加 signature，未变化时不重复重建。
- 仍然走原来的 authoritative `label_mapping + decisions + commit` 后端合同。

相关提交：
- `61a804d1`
- `659a52a3`
- `9b8756c1`

### 后续性能收口

随后分支又完成：

- AI full-material hydration 改为按需。
- 自动标注页面进入时不再为了某些动作直接 hydrate 全素材池。
- 只有真正需要素材 truth 的动作才触发。
- permanent CI guard 已增加。

不要恢复 auto-label page entry → full material pool 的旧路径。

---

## 8. 数据集 / 素材性能：本轮 CLOSED 项

### 8.1 当前数据集卡片 keyed patch

旧 `renderData412Cards()` 会：

`grid.innerHTML = rows.map(card).join('')`

每次搜索、选中、翻页、标注变化都会重建当前页全部卡片。

现在已经改为：

- 按 material id keyed patch。
- 未变化卡片 DOM 保持。
- signature 变化才替换单卡。
- 离开当前页的卡片才移除。
- Storage badge / selection / annotation overlay 仍保持。
- Real Chrome guard 检查 unchanged card DOM identity。

相关：
- `bcffbc69`
- `7b7cf0bf`
- `be383af5`

### 8.2 full material pool 继续减少

在本轮后续提交中：

- quality center 已禁止 full material hydration。
- AI material hydration 已改 lazy/on-demand。
- 仍不要机械删除 `material-pagination-runtime` 兼容桥。
- 接下来只需要继续审计剩余 legacy full-pool consumer，而不是恢复 broad load。

---

## 9. 平台对接页性能：本轮 CLOSED 项

`static/modules/external-algorithm-platform.js` 原来即使缓存命中，也会：

`view.innerHTML = configFormHtml(config)`

导致整页 DOM remount。

现在已经改为：

- stable root。
- 顶层 section 按 key patch。
- config draft 编辑中可 preserve。
- 后台诊断/同步刷新不会冲掉未保存编辑。
- input dirty listener 有 bound guard，避免重复绑定。
- Real Chrome guard 检查 page root identity 保持。

相关：
- `4878d960`
- `8acd15d4`
- `8060b23b`

---

## 10. Dashboard / 导航 / 启动性能：最新额外收口

文档写入前最近一批提交还继续处理：

### Dashboard

- 工作台 background refresh 改为 focused owner。
- startup dashboard 不再走不必要 broad owner。
- 对应 browser/source guard 和 asset key 已同步。

相关：
- `9e92808c`
- `90cbb37a`
- `b0f598be`
- `d54cb20c`

### AI lazy material

- full materials 只在 AI 动作真正需要时 hydrate。
- 不在页面进入时提前加载。
- CI 永久 guard 已加。

相关：
- `13451d84`
- `31ae302c`
- `740ad534`
- `ed572d9d`
- `3a04e4da`

### Deployment route retirement

部署中心产品入口移除后，后续又继续收口：

- retired deployment navigation entries
- normalize retired deployment routes
- retire deployment page owners
- retire deployment routes from browser navigation
- remove retired deployment owner metadata

相关：
- `ef65392a`
- `64548af9`
- `08c7cc3c`
- `14479d26`
- `10eaf8f7`
- `dba79910`

### 当前最终导航 asset keys

最新代码/测试基线：
- `203948a5` — align final navigation asset keys

接手者不要再把旧导航 asset key guard 当产品行为失败；读真实 job log。

---

## 11. 9 月 22 日旧 P0 两个红灯已经处理，不要重复

上一 handoff 曾记录两个明确失败：

1. Frontend workflow 仍 grep `model-artifacts-65003`，实际 runtime 已 `65005`。
2. auto-label browser test 强制要求瞬时 `2/4`，但真实 polling 已合法前进到 `3/4`。

本轮已经处理：

- workflow marker 对齐 `65005`。
- auto-label 测试改为验证 truthful monotonic progress，而不是把生产 polling 人为减速。

不要再把 runtime 改回 `65003`，也不要为了测试把 auto-label polling 调慢。

---

## 12. 本轮曾出现的回归红灯与修复结论

这些是历史过程，不代表当前 HEAD 仍失败。

### 12.1 Label Normalization Contract 旧 asset key

曾失败因为 workflow 仍期待：

- `app.js?v=42.25.194`
- `main.mjs?v=42.25.194`

而新前端已 bump。

已修：
- `530b85f5` — align label contract asset cache keys

### 12.2 Detection batch API 测试错误队列假设

测试曾错误假定 `claim_next()` 下一条一定是当前 case 刚创建的 task。
共享 durable repository 中可能还有 earlier task。

已修：
- `46fe1d70` — 先通过真实 `promote(task_id)` 隔离目标 task，再 claim。

这是测试隔离问题，不是生产 queue 语义修改。

### 12.3 Online Feedback Real Chrome 仍指向旧“测试发布”

旧 browser spec 曾继续：
`setPage('测试发布')`
并寻找旧 `predFile / 开始测试`。

正确修法不是恢复旧页面。

后续已经完成：

- 质量中心 detection → feedback evidence bridge
- 旧 browser flow 迁到质量中心
- model SHA binding
- stale evidence reject
- quality feedback permanent guard

相关提交见第 4.7 节。

---

## 13. 当前 CI / Actions 状态

**文档写入前 HEAD：**
`203948a5ef7b68e4a23fc609a6c4233f09d48e95`

当时读取 GitHub check-runs：

- API 报告 total：`52`
- 当前返回的第一页有 `30` 个 check
- 这 30 个当时全部为 `queued`
- 当时没有 completed failure 可供判定

因此：

- **不能说当前全绿。**
- 也**不能说当前存在产品红灯**。
- 当前真实结论只是：最新代码 HEAD 的 CI 尚未给出完成结果。

创建本 handoff / pointer 文档后 HEAD 会继续改变，接手时必须重新读 check-runs。

### CI 工作原则

如果出现 failure：

1. 先读 job log。
2. 判断：
   - stale exact-string / asset-key guard
   - stale old-route browser expectation
   - 测试隔离问题
   - 真实产品行为回归
3. 只有第 4 类才改生产行为。
4. 不允许为了全绿恢复已退役产品入口或旧 broad loader。

---

## 14. 当前 P0 / P1 未完成清单

这里是新会话真正该继续的内容。

### P0-1 — 最新 HEAD CI 收口

重新读取最新 HEAD 的所有 check-runs。
优先处理 completed failure。

要求：

- 真实日志。
- 不靠猜。
- 不恢复旧导航/旧部署中心/旧测试发布。
- 不降低正确测试语义。

### P0-2 — 手动标注 Real Chrome 完整验收

代码已大改，但还需要在最新 HEAD 实际验收：

- 标签 first paint。
- “确认无目标”。
- 连续拖框。
- 删除框。
- resize handles。
- 图片切换。
- 滚轮缩放。
- 100% / 适应窗口。
- stale annotation response fencing。

如发现问题，继续在 canonical stable workbench 修，不再恢复旧 render owner。

### P0-3 — ZIP / 批量导入 Real Chrome 完整验收

重点验证：

- exact code 自动匹配。
- 不存在 code 时显式新增。
- 确认按钮 loading/success/failure。
- modal 关闭。
- Task Center 重新打开。
- refresh 后继续恢复。
- 最终 mapping-only Ground Truth 安全合同。

### P0-4 — 质量中心真实模型批量检测验收

至少验收：

- 原始模型 vs 算法版本。
- 算法版本 vs 算法版本。
- 单图。
- 多图。
- 文件夹。
- A/B 对比。
- A-only。
- B-only。
- confidence。
- durable batch history。
- 图片详情。
- 人工核验。
- 正式算法版本 → 线上抽检反馈。
- stale model evidence reject。

模拟测试通过不等于真实 GPU/模型生产 E2E。

### P1-1 — 全站剩余“点一下像没反应 / 闪一下” Real Chrome profile

前面已经大幅收口：

- 服务节点 cache-first
- 训练设备 24h cache + backend final validation
- 训练任务 snapshot
- 算法列表 snapshot
- dataset card keyed patch
- annotation stable workbench
- external platform stable shell
- quality shell stable
- quality full-pool hydration retired
- AI full-pool lazy
- dashboard focused refresh

下一步不是再做 broad refactor，而是 Real Chrome 逐页 profile：

1. duplicate fetch
2. page entry loading repaint
3. whole-root innerHTML
4. stale response
5. double owner
6. forced full material hydration

### P1-2 — 剩余 legacy full-material consumers

`material-pagination-runtime` 仍是必要兼容桥。
不要机械删除。

只继续找真正剩余的：

`page entry → loadFullPool → whole render`

并逐个迁到：
- current-page truth
- lazy hydration
- scoped action hydration

### P1-3 — 自动标注审核真实交互验收

新的可搜索标签映射 / bulk mapping / selected-image bulk label 已实现。
仍需要浏览器实际检查：

- 标签很多时是否好用。
- 新建平台标签后 combobox 是否立即更新。
- 部分采用 / 全部接受的 edits 是否都保留。
- 大批量候选时 DOM 是否仍流畅。

---

## 15. 已 CLOSED，不要重复做

以下不要重新开工：

- 服务节点 snapshot / PollRegistry / cache-first。
- 训练硬件设备前端长 TTL + 后端 final validation。
- TrainingTaskRuntime canonical owner。
- training visibility legacy render fallback。
- 训练创建 delayed repaint retirement。
- NegativeSample legacy wrappers。
- Annotation workbench close 保留短时 cache。
- Model Artifact config/audit TTL + in-flight dedupe。
- algorithm list recent snapshot reuse。
- dataset 当前页 keyed card patch。
- external platform stable shell。
- quality center full-material hydration retirement。
- AI page entry full-material hydration retirement。
- dashboard broad startup refresh 收口。
- standalone 测试发布 / 检测台 page owner。
- 部署中心导航 / page owner。
- old deployment navigation aliases。
- ZIP modal 生命周期和 durable task 绑定问题。
- AI label mapping 长 select-only UI。

---

## 16. 新畅联 / OSS / ModelArtifact 合同继续有效

当前产品主线虽是 UI/性能，也不能破坏：

- 新畅联业务接口当前使用：
  `Authorization: Bearer <accessToken>`
- 训练资格：
  `status=1 AND analysisType=1`
- ModelArtifact 是模型/转换产物 canonical truth。
- StorageSource 管 connection。
- Artifact config 只管 binding：
  `storage_source_id + root_prefix`
- ExternalPublicationRepository 管外部发布状态。
- 不恢复 AlgorithmSqlStore dual-write。
- 训练成功：
  `训练版本 → ModelArtifact → OSS → ChangLian Version/Weight`
- 转换成功：
  `Conversion Artifact → OSS → 同一 Version 下新增 Weight`
- 回退仍是删除当前版本语义。
- OpenAPI 无 webhook 时仍是受控主动拉取，不伪称 push realtime。
- mock/focused test 不等于真实 OSS / 畅联生产 E2E。

---

## 17. 推荐新会话执行顺序

```text
1. 重新读取真实 HEAD / VERSION / 最近 30 commits
2. 读取本 handoff + PROJECT_HANDOFF_CURRENT + CODEX_CURRENT_STATE
3. 读取最新 check-runs
4. 对 completed failure 逐个读真实日志
5. 先修 P0 CI / 行为回归
6. 做手动标注 Real Chrome 验收
7. 做 ZIP/批量导入 Real Chrome 验收
8. 做质量中心真实模型批量检测 + feedback bridge 验收
9. 若 P0 清零，再继续全站性能 profile
10. 每一批修改都加 focused permanent regression
11. 分支前进就 re-read，绝不 force push
```

---

## 18. 建议新会话优先阅读文件

1. `docs/CODEX_HANDOFF_2026-09-23.md` — **最高优先级**
2. `docs/PROJECT_HANDOFF_CURRENT.md`
3. `docs/CODEX_CURRENT_STATE.md`
4. `docs/CODEX_HANDOFF_2026-09-22.md` — 上一阶段历史
5. `docs/CODEX_HANDOFF_2026-09-21.md`
6. `docs/CHANGLIAN_CORE_INTEGRATION.md`
7. `docs/CHANGLIAN_APIFOX_API_CATALOG.md`
8. `docs/NODE_CONTROL_PLANE_V42_25.md`
9. `docs/BUG_AUDIT_2026-09-17.md`

如果旧文档 NEXT / old priority 与本文件或实时 GitHub 冲突，以：

**实时 GitHub → 2026-09-23 handoff → 当前代码/测试**

为准。
