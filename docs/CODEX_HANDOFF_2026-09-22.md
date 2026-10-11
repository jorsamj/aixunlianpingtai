# Codex / AI 接手交接 — 2026-09-22

> **当前最高优先级交接入口。**
>
> 新会话 / 新 Codex / 新开发人员接手 `jorsamj/aixunlianpingtai` 时，必须先读取 GitHub 当前真实远端状态，再读本文件。
> 本文件记录的是文档写入前的代码/测试基线；文档提交本身会继续推进分支 HEAD，所以绝对不能把本文中的 SHA 当成“现在仍然是 HEAD”的假设。
>
> 权威顺序：**GitHub 实时远端 → 本文件 → 当前 owner 代码/测试 → PROJECT_HANDOFF_CURRENT / CODEX_CURRENT_STATE → 历史 handoff**。

## 1. 当前基础信息

- 仓库：`jorsamj/aixunlianpingtai`
- 长期开发分支：`feature/external-algorithm-publishing`
- 项目：**畅联云算法训练平台**
- 正式版本：`VERSION.txt = 42.24.0`
- 本文件写入前最后一个代码/测试提交：`22e52dc0e86c03ad1b30e5547072d2ec3b388487`
- 该提交只修正一个过期前端测试 marker：`model-artifacts-65003 → 65005`，不改变 runtime 行为。
- 上一个产品性能代码 HEAD：`dd320563c2b2d1155640d1cc39e84d58144be5d6`（`perf: reuse algorithm page snapshot`）。

**接手后第一步必须重新读取：**

1. `origin/feature/external-algorithm-publishing` 当前真实 HEAD。
2. `VERSION.txt`。
3. 最近至少 20 个 commits。
4. 当前 GitHub Actions / check-runs，失败必须看真实日志，不允许仅看红灯名称猜原因。
5. 本文件、`docs/PROJECT_HANDOFF_CURRENT.md`、`docs/CODEX_CURRENT_STATE.md`。
6. 如果涉及部署，再重新核对服务器 `/data/platform/current` 与 systemd 服务；不要沿用历史文档里的旧 symlink 结论。

## 2. 绝对约束

这些规则仍然有效：

- **不 merge `main`**。
- **`VERSION.txt` 必须保持 `42.24.0`**。
- **不 tag，不 release**。
- Windows 11 开发端 + NVIDIA Linux 生产端必须同时兼容。
- 不删除测试、不放宽真实行为断言、不降低阈值来“让 CI 变绿”。
- 前端/后端必须使用统一字段、状态枚举和 API 合同。
- 正式页面必须读取真实后端，不得用假数据、假延迟、假进度冒充生产 truth。
- Durable Task、Ground Truth、Artifact、External Publication 等已有 canonical owner 不允许建立第二套 truth。
- 页面轮询继续由 PollRegistry / 已有 runtime lifecycle 管理；不要重新引入散落的 raw timer。
- 用户明确希望减少等待感：优先 cache-first / stale-while-revalidate / in-flight dedupe / scoped refresh / DOM patch；不要在每次导航上恢复 broad `loadAll()` 或全页“加载中”。

## 3. 2026-09-22 本轮主线：前端 owner 清理已基本结束，正在做用户可感知性能收口

此前重点是解决“套娃 owner / wrapper / render 后又 fetch / 页面每次点击都加载”的技术债。

### 已经 CLOSED，不要重复做

- `static/app.js` 大量 public `window.*` owner wrapper 已收口；不要为了“capture 数量归零”机械删除剩余兼容引用。
- StorageCacheRuntime 已从“renderer 触发请求”改为 decorator + 显式 refresh；storage source / workers 使用缓存和 in-flight dedupe。
- TrainingTaskRuntime 已成为训练任务列表/动作 canonical owner；visibility runtime 不再 monkey-patch `runtime.refresh`。
- 训练任务 broad-loader 覆盖/消失问题已收口到 data-load boundary。
- Negative Sample 旧 wrapper / delayed timer 已退役，改为 decorator-only。
- Training Material Picker 的 `legacyConfirm.apply(...)` wrapper 已退役；训练/测试素材互斥由 canonical runtime 更新 draft。
- Training task visibility 的 legacy render fallback 已退役。
- Annotation workbench 关闭时现在 cancel pending apply，但保留短时 cache，不再每次关闭都 invalidate + 置空。
- Model Artifact config / audit log 请求已有 TTL + in-flight dedupe；空日志结果也缓存。
- startup duplicate canonical paint、startup page extras 重复请求、entry cache-bust guard 等已多轮修复。

### 仍保留、不要机械拆掉

以下引用是有目的的兼容/拦截层，不等于运行时“套娃”：

- `algorithm-list-runtime.js` 中少量 original toggle 引用：用于 destroy / hot-unload 恢复，不是正常调用链 owner。
- `material-pagination-runtime.js` 的 base renderer/action 捕获：当前仍是 server paging 与旧 full-pool 页面之间的兼容桥。没有替代方案前不要删。
- `navigation-stability.js` 的 original `setPage`：导航兼容入口。
- `page-request-scope.js` 的 original `fetch`：请求作用域拦截层。
- `training-submit.js` 的 original submit：主要用于 destroy 恢复。

## 4. 最近一轮 cache-first / 导航性能提交

从 `2f24086...` 之后，主线已经连续针对用户可见等待做收口。接手者应先确认这些提交仍在远端历史里：

- `c3a1fcc9` — operational page revisit cache-first。
- `d966e9e1` — annotation workbench 关闭保留短时缓存。
- `aaca339c` — cached external training preflight 不再重复画 loading shell。
- `6691bdc5` — 退役训练弹窗 delayed repaint。
- `305e8442` — 合并 training dialog first paint。
- `a8441670` — ready navigation 保持同步快速路径。
- `06097e83` — annotation 前明确等待 dataset navigation owner。
- `7625fd47` — navigation chrome 原位 patch，不重建。
- `d3c1903d` — operational page recent snapshot reuse。
- `feeda4b9` — annotation 命中缓存时跳过 loading repaint。
- `f34a7157` — full material pool 跨导航复用。
- `b5127ed5` — auto-label task refresh owner 统一。
- `64577fe9` — deploy artifact page snapshot 复用。
- `e1db87f8` — 空 audit log refresh 去重。
- `14c67f23` — startup extras snapshot 复用。
- `dd320563` — algorithm page snapshot 30 秒复用。
- `22e52dc0` — 修复 model artifact runtime build marker 的陈旧测试断言。

### 当前产品方向

用户的明确痛点：

1. 页面点击经常先显示“加载中”，观感差。
2. 切到别的页面再回来，又重新等待。
3. 感觉有时需要点两次。
4. 服务节点明明刚加载过，再回来仍不该阻塞。
5. 创建训练时设备/硬件信息不会频繁变化，不应该每次打开都阻塞获取。
6. 标注弹窗首开/重开偏慢。
7. 整体要有成熟 SaaS 的即时反馈感，而不是“点击 → 空白/加载 → 重画”。

正确优化方向：

```text
已有缓存/快照
→ 立即画可用 UI
→ 后台 scoped refresh
→ 新数据回来只 patch 变化区域

同一请求
→ in-flight dedupe

页面离开
→ 取消/忽略 stale response
→ 不破坏短时有效缓存

轮询
→ PollRegistry 单 owner
→ page-scoped lifecycle
```

不要把“性能优化”理解为增加更多定时器、更多缓存 owner 或延长假 loading。

## 5. 训练相关当前事实

- 创建训练已经有 immediate modal shell + 并行 hydration。
- 正式创建返回必须包含 durable `task_id/kind/task_type/status`，再交给唯一 `TrainingTaskRuntime`。
- 训练任务页面优先使用现有 `state.jobs` / runtime snapshot 绘制，不应先清空成 loading。
- 服务端/Worker 执行前仍必须做 authoritative device/resource validation。
- 设备硬件前端缓存方向是长 TTL（现有设计约 24h）+ 后台刷新；不能因为前端缓存而取消 Worker 最终校验。
- 训练素材 picker 已解决 train/test selection mutual exclusion，并补过确认后“数据质量”按钮状态不刷新的浏览器回归。
- 不恢复 `legacyConfirm`、legacy render fallback、前端 durable confirmation polling。

## 6. 标注 / 素材当前事实

- Manual annotation canonical save 对空标注明确 fail closed；“确认无目标”必须走显式 `confirmEmpty:true`。
- NegativeSampleRuntime 现在只负责 decorate，不包裹 save/prev/next/render。
- Annotation workbench 有短时 cache；关闭只 cancel stale apply，保留 cache。
- 当前分页素材的标注框来自真实 AnnotationRepository truth，使用原图坐标 + contain/SVG。
- full material pool 已增加跨导航复用；`material-pagination-runtime` 仍是兼容桥，不要在没有替换方案时删。
- ZIP / Storage Import / AI Candidate Review 的标签统一规则仍是：外部类别先人工映射；允许显式创建平台标签；**确认前不得写 Ground Truth**。

## 7. 新畅联 / OSS / Artifact 当前事实

不要因为当前主线是性能就破坏这些已完成合同：

- 新畅联内部业务接口按当前 31 项 OpenAPI 使用 `Authorization: Bearer <accessToken>`。
- 只有 `status=1 AND analysisType=1` 的分析方式可进入 YOLO 训练。
- 训练成功 / 转换成功的产物经 canonical ModelArtifact + StorageSource 上传，再同步新畅联 Version/Weight。
- `StorageSource` 管 connection；ModelArtifact config 只管 artifact binding（`storage_source_id + root_prefix`）。
- Artifact 的最终 `object_key/public_url` 由 canonical builder/owner 生成。
- Version/Weight remote IDs/status 已迁到 ExternalPublicationRepository；不要重新写回 AlgorithmSqlStore 形成 dual-write。
- 回退语义仍是“删除当前版本”，不是简单切 current pointer。
- 新畅联没有 webhook 时，主数据准实时同步继续使用受控主动拉取，不要伪称服务端推送。

真实 OSS + 畅联生产 E2E 是否完成，接手时必须重新核对实时文档、日志和环境；不要根据历史 mock / focused test 宣称生产闭环。

## 8. 当前 CI / Actions 交接事实

在 `dd320563...` 上曾观测到：

- check-runs 总数：84
- 当时：9 success / 3 in_progress / 17 queued / 1 failure（其余尚未生成或状态未完成）
- 唯一已知 failure：`contract`
- 日志证明失败来自测试仍期待 `build: 'model-artifacts-65003'`，而 runtime 已是 `65005`；不是产品行为回归。
- 该 stale marker 已在 `22e52dc0` 修正。

**重要：** 文档提交会产生新的 HEAD / 新 Actions；接手者必须重新读取最新 check-runs。不要把上面的快照写成“现在全绿”或“现在仍失败”。

用户此前明确表示：大量 Actions 排队时，不需要为了等待全部跑完而停住开发；但任何部署候选声明都必须以目标 HEAD 的真实门禁为准。

## 9. 下一位接手者建议执行顺序

```text
A. 重新读取远端 HEAD / VERSION / 最近 commits / Actions
B. 若最新 HEAD 有 failure：
   → 先读真实 job log
   → 区分 stale exact-string guard 与真实行为回归
   → 不靠放宽测试解决
C. 若无新的真实阻断：
   → 继续“用户可见加载/导航性能”审计
   → 优先查 service-node / algorithm list / dataset/material / training create / annotation modal
D. 每个页面检查：
   1) 是否有缓存却先画“加载中”
   2) revisit 是否强制 fetch
   3) 同一个 API 是否有重复请求
   4) refresh 是否 broad load
   5) 是否整页 innerHTML 重建而非 patch
   6) 页面离开后 stale response 是否还能覆盖当前页
E. 修改必须加/更新 focused regression test
F. 经常检查远端 HEAD；分支若被并发推进，先 compare/re-read，绝不 force push
```

## 10. 暂不建议做的事

- 不重新设计整体架构。
- 不继续做“capture count 必须为 0”的机械 owner 清理。
- 不删除 `material-pagination` compatibility bridge。
- 不把所有页面都改成长时间不刷新；cache-first 不等于 stale forever。
- 不恢复 broad startup `snapshot?refresh=true`。
- 不恢复每次导航 `loadAll()`。
- 不新增第二套 training/jobs/annotation/artifact truth。
- 不因 Actions 排队就重复触发大量 workflow。
- 不部署、切 `/data/platform/current`、tag/release，除非用户明确进入部署流程且目标 HEAD 门禁满足。

## 11. 相关文档

接手时建议按以下顺序读：

1. `docs/CODEX_HANDOFF_2026-09-22.md`（本文件，最高优先级）
2. `docs/PROJECT_HANDOFF_CURRENT.md`
3. `docs/CODEX_CURRENT_STATE.md`
4. `docs/CODEX_HANDOFF_2026-09-21.md`（上一阶段详细历史）
5. `docs/CHANGLIAN_CORE_INTEGRATION.md`
6. `docs/CHANGLIAN_APIFOX_API_CATALOG.md`
7. `docs/NODE_CONTROL_PLANE_V42_25.md`
8. `docs/BUG_AUDIT_2026-09-17.md`

历史文档里如果存在旧 NEXT / old priority / old deployment candidate，与实时 GitHub 或本文件冲突时，以实时 GitHub + 本文件为准。
