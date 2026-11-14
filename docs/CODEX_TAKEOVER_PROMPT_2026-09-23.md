# Codex Takeover Prompt — 2026-09-23

把下面整段原样交给 Codex。它是当前 `jorsamj/aixunlianpingtai` / `feature/external-algorithm-publishing` 的续接执行指令。

---

继续处理 GitHub 仓库：

`jorsamj/aixunlianpingtai`

长期开发分支：

`feature/external-algorithm-publishing`

项目：

**畅联云算法训练平台**

这是上一轮超长开发会话的续接。不要重新设计架构，不要重复已经 CLOSED 的工作，不要根据本提示中的 SHA 直接假定当前状态。

## 1. 开始前必须重新读取 GitHub 当前真实状态

不要一上来修改代码。

第一步必须重新确认：

1. `origin/feature/external-algorithm-publishing` 当前真实 HEAD。
2. `VERSION.txt`，必须继续是 `42.24.0`。
3. 最近至少 30 个 commits。
4. 当前 GitHub Actions / check-runs。
5. 所有 completed failure 的真实 job log。
6. 当前相关生产代码与测试。

文档写入前最后一次确认的代码/测试 HEAD 是：

`c9064dcde055daab926252bf67aea181af6aa0f5`

当时 `VERSION.txt=42.24.0`，89 个 checks 全部 queued，0 completed failure。

**这只是交接参考。必须以你接手时 GitHub 当前远端真实 HEAD 为准。**

如果远端 HEAD 在你工作期间变化，立即停止写入，重新读取并 compare 后再继续。禁止 force push。

## 2. 文档读取顺序

先完整阅读：

1. `docs/CODEX_HANDOFF_2026-09-23.md` 顶部最新覆盖
2. `docs/PROJECT_HANDOFF_CURRENT.md`
3. `docs/CODEX_CURRENT_STATE.md`
4. `docs/CODEX_TAKEOVER_PROMPT_2026-09-23.md`

然后按需要再读：

5. `docs/CODEX_HANDOFF_2026-09-22.md`
6. `docs/CODEX_HANDOFF_2026-09-21.md`
7. `docs/CHANGLIAN_CORE_INTEGRATION.md`
8. `docs/CHANGLIAN_APIFOX_API_CATALOG.md`
9. `docs/NODE_CONTROL_PLANE_V42_25.md`
10. `docs/BUG_AUDIT_2026-09-17.md`

冲突优先级：

**实时 GitHub > 2026-09-23 最新 handoff 顶部覆盖 > 当前 final owner 代码/测试 > 旧 handoff**

不要执行旧文档中已被新 handoff 覆盖的 NEXT。

## 3. 绝对规则

- 不 merge `main`
- `VERSION.txt` 必须保持 `42.24.0`
- 不 tag
- 不 release
- 不 force push
- Windows 11 开发与 NVIDIA Linux 生产兼容
- 不删除测试来通过 CI
- 不降低正确行为断言
- 不恢复已经退役的旧产品入口
- 不建立第二套 Durable Task / Annotation / ModelArtifact / External Publication truth
- polling 必须继续由 PollRegistry / final runtime owner 管理
- 禁止重新引入散落 raw timer
- 正式页面不得使用假数据、假进度、假延迟
- 前端和后端字段、状态、API 合同必须一致
- Actions queued 时可以继续独立工作，但“全绿 / 部署候选 / 正式上线”必须以目标 HEAD 的真实 completed checks 为准

## 4. 已 CLOSED，禁止重复

### 产品信息架构

普通状态一级导航只有：
- 总览
- 算法生成
- 数据中心

高级配置、服务节点、平台对接等只有展开高级功能后显示。

“测试评测 / 测试发布 / standalone 检测台”已退役。
检测能力正式位置：

**总览 → 质量中心 → 模型检测**

“部署中心”产品导航已退役，但训练后转换、ModelArtifact、OSS、RKNN、新畅联权重同步等底层能力必须保留。

### 手动标注

已经完成并有守护：
- 标签 cache first-paint + authoritative revalidation
- keyed box DOM patch
- 拖动 / resize / 删除 / 撤销
- 鼠标滚轮缩放 / 100% / 适应窗口
- 上一张 / 下一张自动保存
- stale annotation response fencing
- 空标注只能显式“确认无目标”→ `confirmed_empty`
- 连续空图 Real Chrome

不要另建第三套 annotation owner。

### ZIP / 批量导入

已经完成：
- exact canonical code 自动复用
- 合法英文文件标签可显式新增正式平台标签
- 正式标签 API → refresh labels → mapping → durable ZIP start
- modal 关闭不丢任务
- Unified Upload Task Center 可重新打开
- refresh recovery
- 最终仍需人工确认才能进入 Ground Truth

不要恢复旧 `create_labels` 静默创建旁路。

### AI 自动标注审核

保持：

Candidate → Human Review → Durable Commit → AnnotationRepository

已经完成：
- 可搜索正式标签
- 来源标签筛选
- 全部来源统一映射
- 勾选图片批量统一候选框标签
- 人工编辑 boxes
- accept-all 保留人工 edits
- 多页 candidate review
- 跨页 edits 保留
- 分页乱序 stale fencing
- 关闭 / 提交后的 late response fencing
- 大量标签 + 多页候选 Real Chrome

不要让 AI Candidate 自动绕过人工确认写正式 Ground Truth。

### 质量中心模型检测

已完成：
- A/B 两侧模型
- builtin / 任意算法 / 各版本
- 分组与搜索
- A/B、A-only、B-only
- confidence
- 单图 / 多图 / 文件夹
- 非图片过滤
- durable `DEPLOYMENT_TEST`
- 批次历史恢复
- 人工核验
- v64 detection → v63 feedback evidence
- 正式模型 SHA stale fail closed
- 真实目录 input Real Chrome

注意：现有浏览器推理可以是受控测试替身，只证明 UI/API/durable-task 合同；不要把它宣称为真实 GPU E2E。

### 性能 / owner

已经 CLOSED：
- 导航无 full-material page owner
- startup 不再二次 broad extras + render
- 训练创建后不再 broad `loadRelated()`
- 训练任务页 jobs-only
- 训练设备 24h browser cache
- 标签管理 / 训练资源 / 组件检测 / 平台对接 / 服务节点 / 存储 / 素材接入 / 视频切帧 / Dashboard revisit cache
- 模型 prompt templates 按需
- 重复点击当前 active nav no-op
- 退役部署 page-extras owner 清除
- clean detail PollRegistry 原地 patch
- page-loading performance Real Chrome 已入 CI
- 训练资源 background refresh 只 patch resource cards，不重建输入表单
- 模型 prompt background refresh 只 patch prompt 区域，不重建 model config 表单

不要恢复：

`页面进入 → broad loadAll() → 清页面 → loading → 全量 render`

正确方向继续是：

`cache-first + stale-while-revalidate + in-flight dedupe + scoped refresh + DOM patch`

## 5. 仍 OPEN

当前最高优先级：

### P0-1 — Actions 真结果

重新读取最新目标 HEAD 的 Actions。
对每个 completed failure 必须读取真实 job log。

优先判断：
- stale exact-string guard
- stale asset cache key
- 旧 route 测试
- 测试隔离
- 真产品行为问题

只有真产品行为问题才修改生产行为。

### P0-2 — 真实 GPU / 正式模型推理 E2E

必须真实验证：
- builtin vs algorithm version
- algorithm version vs algorithm version
- A/B / A-only / B-only
- confidence
- durable task/result truth
- 正式模型真实推理
- GPU runtime

不能用 mock 成功代替。

### P0-3 — 真实 OSS / 新畅联生产 E2E

必须真实验证：
- 训练原始模型 ModelArtifact
- OSS 上传
- 长期 public URL 可读
- ChangLian Version 创建
- Weight 创建
- 转换完成后追加同一 Version 下 Weight
- 远端反查
- 删除 / 回退
- 网络超时与重试后的幂等恢复
- 不重复创建版本
- 不产生 dual-write truth

## 6. 新畅联 / OSS 合同不要破坏

继续保持：
- 新畅联业务接口 `Authorization: Bearer <accessToken>`
- 训练资格：`status == 1 AND analysisType == 1`
- ModelArtifact 是 canonical artifact truth
- StorageSource 管 connection
- Artifact config 只管 storage binding
- ExternalPublicationRepository 管远端发布状态
- 不恢复 AlgorithmSqlStore dual-write
- 训练成功：模型版本 → ModelArtifact → OSS → ChangLian Version/Weight
- 转换成功：转换产物 → OSS → 同一 ChangLian Version 下 Weight
- 回退 = 删除当前版本，不是简单 pointer switch
- 无 webhook 时使用受控主动同步，不伪称 server push

## 7. 工作方式

按以下顺序推进：

`真实状态 → final owner → canonical truth → 最小正确修复 → focused test → Real Chrome → CI`

不要一次性大改。
不要为了有提交而改代码。
不要根据旧函数名判断 owner。
不要因旧测试恢复退役产品入口。
不要机械删除 compatibility bridge。
不要在 Actions queued 时傻等；可以做独立审计，但周期性回来看 completed failure。

如果你发现真实失败：
先读日志，再判断原因，再做最小正确修复。

如果目前没有失败：
优先做真实 GPU / OSS / ChangLian E2E 准备与验收，或继续全站性能 profile 找真实 duplicate fetch / repaint / stale owner；不要重复 CLOSED 工作。

