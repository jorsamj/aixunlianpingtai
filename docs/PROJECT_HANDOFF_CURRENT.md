<!-- LIVE_HANDOFF_TRAINING_DETAIL_LOG_2026_09_24 -->
> ## 2026-09-24 训练详情 / 日志 / 错误提示最新覆盖
>
> 代码基线：`8e50195f76d0aa58ccf6082bdbd7c93029b528b7`，`VERSION.txt=42.24.0`。已将训练详情与日志收敛到单一 `TrainingRecoveryRuntime`，实时列表/详情通过 `TrainingProgressStream` 接 durable SSE；成功终态不会再被历史 error/recovery 误判；失败任务保留结构化 error type / failure stage；详情展示真实资源档位、Batch/Workers/Cache、设备、GPU/CPU/I/O telemetry、数据版本/快照/Checkpoint/产物及统一技术日志。
>
> 运行中弹窗使用 PollRegistry；terminal SSE 到达后必须再拉一次最终 detail + log 后才停止。详情 GET 已明确为 read-only：不 dispatch 队列、不 rebuild 全局 index、不触发算法版本归档。旧训练详情 renderer / run center owner 已退役，不得恢复第二套 UI。
>
> 详细说明：`docs/CODEX_HANDOFF_2026-09-24_TRAINING_DETAIL_LOGS.md`。文档写入时 88 checks queued、0 completed failure，不得宣称全绿；真实 Linux GPU / Agent 现场仍需验证最终进度、日志和故障证据。
>
<!-- LIVE_HANDOFF_ANNOTATION_TTL_P0_2026_09_23 -->
> ## 2026-09-23 素材标注 P0 修复（最新覆盖）
>
> 修复前远端 HEAD 为 `0a8f5c5f1eb0f2153ec04792cead5fe674c04110`；新的 Linux 预部署代码候选为直接后继 `f50b71da760d5c136010f4d6a4495837e64be795`；`VERSION.txt = 42.24.0`。
>
> **CLOSED：** `素材 → 打开标注` 的 `LABEL_SCHEMA_CACHE_TTL_MS is not defined` 是真实生产回归。唯一 TTL 定义原被封在标签管理 IIFE，后续 annotation workbench IIFE 跨 lexical scope 访问。修复只将该唯一常量提升到两个 IIFE 的共享文件级 lexical scope，未复制 TTL、未暴露到 `window`、未新增 fallback 或第二 owner。`app.js` cache key 已推进到 `42.25.216`。
>
> **Focused evidence：** 基线单例精确复现 `ttl-error`；修复后 4 个标注 browser cases 全部通过，覆盖打开工作台、标签选择/绘制/保存、cache-first → authoritative refresh、“确认无目标”、前后切换与已有框恢复；相关 JS syntax check 通过。
>
> **OPEN：** 当前没有其他已 isolated 确认且尚未修复的 production blocker。Linux 真实 GPU / 正式模型、Paddle、真实 OSS / 新畅联、Agent/RKNN 实板、生产数据增量 migration 继续等待预部署现场验证。没有运行全量 Frontend Runtime / 全仓库测试，也没有修改 `VERSION.txt`、merge main、tag 或 release。
>
<!-- LIVE_HANDOFF_LINUX_PREDEPLOY_AUDIT_2026_09_23 -->
> ## 2026-09-23 Linux 预部署前代码侧 blocker audit（最新覆盖）
>
> 审计基线 / 审计前远端 HEAD：`5345eba592b4bbf48dbe19fb66e4f7458d437eb7`；`VERSION.txt = 42.24.0`。
>
> **CLOSED：** 发现并最小修复 Paddle durable training capability 断层。Web 会合法创建 required capability 为 `training.paddle` 的任务，而 final Worker owner `platform_core/training_runtime_tasks.py::worker_registration` 原先只声明 `training.ultralytics`；现在同一个 `ProductionTrainingHandler` 同时声明两种正式 framework capability，没有新增 handler、fallback 或第二 owner。RED 断言、focused registry、Python syntax 与 training-role Worker check 已验证。
>
> **代码侧未发现其他新预部署 blocker：** Web final entry 为 `app:app`，Worker final entry 为独立 `task_worker.py`；两者共享 DATA_DIR/task DB/artifacts。数据库迁移为 additive / transactional / fail-closed，未发现启动清空或覆盖正式数据。所有 HTML/module 本地引用存在，54 个关键静态 JS/MJS 文件语法通过。正式 Web 监听合同继续是 `127.0.0.1:8010`，不改为 `0.0.0.0`。
>
> **STALE TEST / TEST DEBT：** Remote Conversion / RKNN Actions 仍进入退役“部署转换”页面；ZIP guard 固定旧 main cache key；Label/Training Create 固定旧 source 结构；Frontend Runtime 仍期待“测试发布”“工作台”或使用歧义 locator。不得为这些红灯恢复旧 IA/owner。其余 annotation/source revisit 红灯仍需以后逐条 isolated 分类。
>
> **OPEN / 预部署验证：** Web/Worker 必须共用真实 `MC_TRAIN_DATA_DIR`（或 `MC_DATA_DIR`）并同时运行；Linux 真实 GPU、正式模型、Paddle 环境、真实 OSS / 新畅联、Agent/RKNN 实板和生产数据增量 migration 仍需现场证据。外部依赖缺失不应阻止主平台启动，只应让对应能力 fail closed。
>
> 未运行全仓库测试、67 项 Frontend Runtime 或真实外部 E2E；没有修改 schema、产品 IA、`VERSION.txt`，没有 merge main、tag、release 或操作 `/data/platform/current`。详细 A-J 审计见 `docs/CODEX_HANDOFF_2026-09-23.md` 顶部。
>
<!-- LIVE_HANDOFF_FOCUSED_RUNTIME_FIX_2026_09_23 -->
> ## 2026-09-23 Focused Runtime 修复最新覆盖
>
> 基线 HEAD：`6dc0d7d3856f2a8015b78188ba93f14a2242a85f`。当前本地代码修复提交：`8a29809afb797eeef9bafc946d70797c41ef8830`（`fix: route late UI helpers through final owners`）。`VERSION.txt = 42.24.0`。
>
> **真实根因：** `9839cb46` 把清洗进度逻辑放进后置 IIFE 后仍调用前一 IIFE 的私有 `cleanTaskView427`，触发 `cleanTaskView427 is not defined`。唯一 final owner 为 `PlatformCore.cleaning.cleanTaskView`（`static/modules/cleaning.js`，由 `static/main.mjs` 安装）。后置 helper 已直接调用该 owner；没有暴露旧函数、没有新 fallback、没有第二 owner。
>
> AI Candidate Review 的 focused reproduce 证明分页 edits 已保留，失败实为后置 IIFE 取不到私有 `displayLabel412`，只显示 raw code。AI v60 的标签展示现复用 `PlatformCore.materials.labelDisplay`。本轮 `static/app.js` 共 7 行替换。
>
> **Focused evidence：** JS 语法检查通过；Playwright `2 passed`：remote cleaning progress、AI Candidate Review accept-all。没有运行 67 项 Frontend Runtime 或更大测试范围，不能宣称全绿、正式可上线或生产验收完成。
>
> “工作台 / 总览”后续已 isolated reproduce 为 **compatibility alias 未归一**，不是 stale test。final owner 链路为：`static/modules/navigation-stability.js::normalizeNavigationPage` 将旧“工作台”归一到“总览” → `static/main.mjs` 安装最终 `window.setPage` 并只注册 `总览 -> renderDashboardCanonical422` → `static/app.js::renderTopCanonical413` 显示 canonical `state.page`。最终菜单、持久化恢复和 dashboard extras 守卫均统一到“总览”，没有恢复“工作台”正式入口，也没有第二 dashboard owner。对应 `page-loading-performance.spec.mjs` focused case `1 passed`，三个导航改动文件的 JS 语法检查通过。
> 现有浏览器 cache key 同步推进到 `app.js?v=42.25.215`、`main.mjs?v=42.25.211`、`navigation-stability.js?v=422517`；`VERSION.txt` 不变。
>
> **CLOSED：** `cleanTaskView427` ReferenceError；AI Candidate Review accept-all focused case；“工作台”兼容 route 已归一到唯一 canonical “总览” owner。
>
> **STALE TEST / TEST DEBT：** 算法版本发布测试仍依赖退役“测试发布”页面；旧 RKNN 页面测试仍依赖退役“部署转换 / 部署中心”route。迁移测试，不恢复旧 IA；底层版本发布和 RKNN 转换 / 板端验证能力继续保留。
>
> **OPEN：** 其他 broad 浏览器红灯尚未 focused 分类；Linux 真实 GPU / 正式模型推理 E2E；真实 OSS / 新畅联生产 E2E；Rockchip 实板验收。当前没有其他已 focused 确认且仍未修复的生产 bug。
>
> **下一步最小动作：** 每次 isolated reproduce 一个失败并分类；不为测试恢复退役入口。随后进入 Linux 真实 GPU、正式模型、OSS 与新畅联合同验证。
>
<!-- LIVE_HANDOFF_CONTINUATION_2026_09_23_CODEX_TAKEOVER -->
> ## 2026-09-23 Codex 接手最新覆盖
>
> 文档写入前最后确认代码/测试 HEAD：`c9064dcde055daab926252bf67aea181af6aa0f5`；`VERSION.txt=42.24.0`；当时 **89 个 checks 全 queued、0 completed failure**。接手第一步必须重新读取实时 GitHub，不得把该 SHA 当作现在的 HEAD。
>
> 最新 CLOSED：P0 手动标注 / ZIP / 质量中心模型检测 / clean PollRegistry / AI Review 多页 stale lifecycle；P1 启动与页面回访 cache-first、训练任务 jobs-only、训练提交 scoped refresh、训练设备 24h cache、标签 first-paint、标签/训练资源/组件检测/平台对接/服务节点/存储/素材接入/视频切帧/Dashboard 回访缓存。训练资源与模型提示词 background refresh 已改为局部 patch，不再重建正在填写的表单。
>
> 最新 OPEN：目标 HEAD completed Actions、真实 GPU 推理、真实 OSS + ChangLian Version/Weight 创建/反查/删除/超时幂等生产 E2E。
>
> **接手完整说明优先读：`docs/CODEX_HANDOFF_2026-09-23.md` 顶部“10:xx Codex 接手最终刷新”。**
>
> 可直接给 Codex 的执行提示词已写入：`docs/CODEX_TAKEOVER_PROMPT_2026-09-23.md`。
>

<!-- LIVE_HANDOFF_CONTINUATION_2026_09_23_BATCH3 -->
> ## 2026-09-23 最新续接：缓存首屏 / 回访性能矩阵继续收口
>
> 文档刷新前最后确认代码/测试 HEAD：`0fd99a33bec1527c1d4d3d96a220ac43d3fd999b`；`VERSION.txt=42.24.0`；当时 **51 个 checks 全 queued、0 completed failure**。接手必须先重读实时 GitHub，不能把该 SHA 当作当前 HEAD。
>
> 新增 CLOSED：训练设备 24h cache 跨 reload Chrome；标注标签 stale-cache first-paint + authoritative revalidation Chrome；标签管理、训练资源、组件检测回访缓存 Chrome；模型提示词按需读取；平台对接/服务节点/存储/素材接入/视频切帧回访请求守护；AI Review 54 张/3 页跨页 edits + stale/closed lifecycle fencing。
>
> 仍 OPEN：目标 HEAD completed Actions、真实 GPU 推理、真实 OSS / ChangLian 生产 E2E。不要重复上述 CLOSED 性能工作。
>

<!-- LIVE_HANDOFF_CONTINUATION_2026_09_23_BATCH2 -->
> ## 2026-09-23 最新续接：AI 审核跨页 / stale fencing 已收口
>
> 先读 `docs/CODEX_HANDOFF_2026-09-23.md` 顶部最新续接增量。文档刷新前代码/测试 HEAD：`76fbfdfd5aecce22c32de90f507a1703dbffc21b`，`VERSION.txt=42.24.0`，当时 89 个 checks 全 queued。
>
> 新增重点：真实文件夹检测 Chrome、clean detail PollRegistry 原地 patch、AI Review 54 张/3 页大批量验收、跨页 edits 保留、乱序分页 fencing、提交/关闭后 late response 不复活。真实 GPU / OSS / ChangLian 生产 E2E 仍 OPEN；不得宣称全绿。
>

<!-- LIVE_HANDOFF_CONTINUATION_2026_09_23 -->
> ## 2026-09-23 续接覆盖：9/23 handoff 已更新 Real Chrome / 性能收口现场
>
> 当前接手仍先读 `docs/CODEX_HANDOFF_2026-09-23.md`，并优先看其顶部 **“本轮续接更新（最高优先级覆盖）”**。
>
> 文档刷新前最后确认代码/测试 HEAD：`bb3803167e8cd7ac039cf9766b0b8cfc79c06f2f`；`VERSION.txt=42.24.0`。当时 55 个 checks 全部 queued，不能宣称全绿或可部署。
>
> 新增重点：P0 手动标注 / ZIP / 质量中心检测 Real Chrome 守护已大幅补齐；P1 已收口训练提交 broad refresh、训练任务额外配置请求、启动后二次 extras、标签保存悬空刷新、重复 active nav、退役部署 extras owner、clean detail raw timer。真实 GPU、OSS、ChangLian 生产 E2E 仍 OPEN。
>

<!-- LIVE_HANDOFF_2026_09_23 -->
> ## 2026-09-23 最新覆盖：请先读 `docs/CODEX_HANDOFF_2026-09-23.md`
>
> 当前产品主线已经从 9 月 22 日的“前端 owner 收口 + cache-first”继续推进到：**导航信息架构正式收敛、质量中心模型检测重构、手动标注稳定化、ZIP/批量导入可恢复确认、AI 审核标签批量统一，以及进一步的全站 lazy hydration / stable shell / focused refresh。**
>
> 文档写入前代码/测试基线为 `203948a5ef7b68e4a23fc609a6c4233f09d48e95`，`VERSION.txt` 仍为 `42.24.0`。本次新增 handoff 文档提交为 `13ccdec5d765ed98c0819a4c59f2f339112a150d`。
>
> **不要把上述 SHA 当作当前 HEAD。** 接手第一步必须重新读取 GitHub 真实远端 HEAD、VERSION、最近 commits、最新 Actions，并对任何失败 job 读取真实日志。
>
> 9 月 23 日 handoff 优先于本文后面的 9 月 22 日覆盖、历史 NEXT、旧部署建议和旧产品导航说明。

<!-- LIVE_HANDOFF_2026_09_22 -->
> ## 2026-09-22 最新覆盖：请先读 `docs/CODEX_HANDOFF_2026-09-22.md`
>
> 当前开发已进入“前端 owner 收口后的用户可感知性能优化”阶段。服务节点、训练任务、训练创建、标注工作台、素材分页、模型产物、算法列表等均已连续做 cache-first / snapshot reuse / in-flight dedupe / 原位 patch 收口。
>
> 文档写入前代码/测试基线为 `22e52dc0e86c03ad1b30e5547072d2ec3b388487`；该提交只修正 Model Artifact runtime build marker 的过期测试断言（65003 → 65005）。`VERSION.txt` 仍为 `42.24.0`。
>
> **不要把上述 SHA 当作当前远端 HEAD。** 接手第一步仍须重读 GitHub 真实远端 HEAD、VERSION、最近 commits 与 Actions。新的 9 月 22 日 handoff 优先于本文后面的历史 NEXT / Current priority / 部署建议。

# 畅联云算法训练平台 — 当前接手总览

<!-- OSS_CONNECTION_BINDING_BATCH2_2026_09_21 -->
> ## 2026-09-21 最新覆盖：OSS Connection / Artifact Binding 第二批
>
> `StorageSource` 现在拥有 Endpoint、Bucket、`public_base_url` 和 Secret Store 凭据引用；Artifact Binding 只拥有 `storage_source_id + root_prefix`。统一 builder 生成最终 Bucket-relative `object_key`，Provider 的素材 `prefix` 不会再次拼到算法产物路径。OSS 连接测试为 PUT→STAT→READ→DELETE，并在配置长期地址时 Range GET；删除失败或 URL 不可达均 fail closed。畅联发布在远端 Version/Weight 写入前探测实际 artifact URL。
>
> 最小验证为 Python 20 passed、frontend 9 passed、Real Chrome storage smoke 1 passed。真实 OSS/畅联生产 E2E 仍 OPEN；第三批改数据库前必须先输出字段 owner/migration 表，不得直接 DROP 或长期 dual-write。`VERSION.txt` 仍为 `42.24.0`。

<!-- CHANGLIAN_VERSION_WEIGHT_BATCH1_2026_09_21 -->
> ## 2026-09-21 最新覆盖：新畅联 Version/Weight 第一批
>
> 已从远端 `2ff431a7` 安全继续，未重复修改其 keyring 测试修复。第一批仅收紧新畅联发布合同：Version payload 使用独立 durable `version_name/version_no`；恢复必须唯一匹配 `versionName + versionNo + bound analysisId`；Weight 创建必须具备五字段，恢复必须严格匹配三字段并在远端提供时继续匹配 `filePath`。缺字段、候选多条、空 chip 或冲突 URL 均 fail closed/UNKNOWN，不盲目 POST。
>
> `code=0` 为主合同，`code=200/SUCCESS` 仍是 legacy compatibility / OPEN。最小测试 24 passed（15 新合同 + 9 直接回归），包含 product/analysis 同 ID 去重与 FAILED 修复配置后重新发布；未跑浏览器、全量 pytest/integration 或等待 Actions。OSS 第二批状态以上方最新覆盖为准；`VERSION.txt` 仍为 `42.24.0`。

<!-- CACHE_FIRST_LOADING_2026_09_21 -->
> ## 2026-09-21 最新覆盖：全站 cache-first 性能闭环
>
> `9fff42df` 已收口 v53 request-local project counts、普通 snapshot cache fast path、authoritative snapshot replacement，并把标签 GET 从全量素材/逐图 annotation 扫描改成 MaterialRepository 的 SQLite summary 聚合。
>
> `2e3a726b` 已移除普通启动与导航的 `snapshot?refresh=true`，删除 extras 对 jobs/model_configs 的重复读取，保留显式刷新与各页面现有 runtime/PollRegistry truth；数据集 v61 当前 48 条先绘制，totals 后补。
>
> 实测冷启动 `10 请求 / 2 snapshot / refresh=true / ~998ms` → fresh cache `4 / 1 / false / ~542ms`，snapshot 过期触发页面 owner SWR 时 `8 / 1 / false / ~353ms`；数据集 `6 / ~145ms` → `4 / ~27–30ms`；服务节点仍只请求自己的 API。定向测试共 `5 API + 12 frontend + 4 browser smoke` 全绿。
>
> `VERSION.txt` 仍为 `42.24.0`；未全量测试、未等待 Actions、未 merge/tag/release/deploy。最高优先级细节见 `docs/CODEX_HANDOFF_2026-09-21.md` 第 0A 节；不要执行下方旧 NEXT 中的 broad snapshot refresh 或另建 polling/cache owner。


<!-- P0_OWNER_CLOSURE_2026_09_21 -->
> ## 2026-09-21 最新覆盖：P0 产品可用性最小 owner 收口
>
> 最高优先级细节仍以 `docs/CODEX_HANDOFF_2026-09-21.md` 第 0 节为准。当前本地分支已关闭四项：训练创建 durable identity、正式 page owner 导航、创建训练 immediate shell + 并行 hydration、当前分页素材正式 annotation truth + SVG 原图坐标框。
>
> 已提交：`249a8b89`、`e92d6c00`、`89c04070`；训练素材标注框与本次文档在随后本地提交中。`VERSION.txt` 保持 `42.24.0`，未 merge、tag、release、deploy，也未等待完整 Actions。
>
> 不要执行下方旧 NEXT 中已完成的 owner 改造。接手先重新读取远端 HEAD，核对本地提交是否已 push；浏览器验收只需复核四条主路径，不应再引入前端 durable task 轮询或第二套 annotation / navigation truth。


<!-- CURRENT_HANDOFF_2026_09_21 -->
> ## 2026-09-21 当前 Codex 接手入口
>
> **先读：docs/CODEX_HANDOFF_2026-09-21.md**
>
> 该文件记录了 2026-09-21 当前真实开发现场，包括：最新代码/测试基线、最后两项 integration 状态、AlgorithmSqlStore 并发锁故障、五个 SQLite owner 生命周期收口、素材/标注批处理 truth、Training V3 Dataset Revision、ResourceDiscovery spawn 根因、新畅联合同、部署门槛和 Codex 下一步执行顺序。
>
> 文档写入前最后一个代码/测试 HEAD：bc88fcdfd7a5097499a67596741b8f13018f7645。
> handoff 文档提交：8ab473efbca7cb2c95b032de0858bb7070d8b0af。
>
> **本节与 docs/CODEX_HANDOFF_2026-09-21.md 优先于下面 2026-09-20 的历史 LIVE HANDOFF、历史 NEXT、历史部署建议。**
>
> 当前第一优先级：不要继续扩大生产代码改动；先在最新远端 HEAD 上重跑两个 focused integration，再跑完整 integration。只有 0 failed 后才进入 task_worker.py --check 和部署前 candidate 验收。
>
> 接手仍必须先重新读取远端 HEAD、VERSION.txt、最近 commits 和 Actions；不要假定上述 SHA 仍是当前远端 HEAD。


> **新 AI / 新开发人员先读本文件。**  
> 目标：10 分钟内知道“当前在哪个分支、什么已经做完、什么绝对不能重做、下一步该做什么”。

更新时间：2026-09-20  
仓库：`jorsamj/aixunlianpingtai`  
正式版本：`VERSION.txt = 42.24.0`  
当前持续开发分支：`feature/external-algorithm-publishing`  
历史产品实现基线（不要当作当前 HEAD）：`b22fcf66b8e598fa83cfa2fef47c2ce7c555318b`  

> 本文提交本身可能继续推进分支 HEAD，所以 **不要把上面的实现 SHA 当成 checkout 目标**。接手时必须先读取远端最新 HEAD，从远端真实最新状态继续。

<!-- LIVE_HANDOFF_2026_09_20 -->
# LIVE HANDOFF — 2026-09-20（接手时优先读本节）

> 本节是当前运行现场快照。它优先于本文后面的历史验收 SHA、历史 NEXT、历史 Current Priority。接手者仍必须第一步重新读取 GitHub 远端，因为本文这次文档提交本身会让 branch HEAD 再前进一位。

本次 Live Handoff 记录的代码 HEAD（文档提交前）：`1e796d0dbe97da05e85beba65d2934aeda3560cd`

当前正式版本：`VERSION.txt = 42.24.0`

上述代码 HEAD 的 Actions 快照（2026-09-20 本轮重新核对）：
- total: 18
- queued: 18
- in_progress: 0
- completed success: 0
- completed non-success: 0
- **queued != passed；在当前 HEAD 的永久 workflow 实际完成前，不得写“全绿”，不得部署或切换 `/data/platform/current`。**

GPU 正式服务器当前仍运行上午部署：
- full SHA：`ea1b6f198f81556c05d963f4c3f70d2865f316ff`
- release：`/data/platform/releases/ea1b6f198f81`
- current symlink：`/data/platform/current`
- Web service：`changlian-web.service`
- Worker service：`changlian-worker.service`
- Web listen：`127.0.0.1:8010`
- Windows SSH tunnel：`http://127.0.0.1:18010`
- business DATA_DIR：`/data/platform-data`
- secret env：`/etc/changlian/secret.env`
- encrypted credential store：`/data/platform-data/secure/secrets.enc.json`

**重要：GPU 正式服务器尚未部署上述代码 HEAD；接手时仍必须先重读远端 HEAD，因为后续文档提交也会推进分支。**

## 文档权威顺序

Codex / 新 AI 无旧会话上下文时按下面顺序：
1. GitHub 真实远端 branch HEAD、`VERSION.txt`、当前 Actions。
2. 本文件的 **LIVE HANDOFF**。
3. `docs/CODEX_CURRENT_STATE.md`。
4. 按任务读取 `CHANGLIAN_CORE_INTEGRATION.md`、`NODE_CONTROL_PLANE_V42_25.md`、`BUG_AUDIT_2026-09-17.md`。
5. 历史文档只作证据；若历史“下一主线/Current priority”与 LIVE HANDOFF 冲突，以实时 GitHub + LIVE HANDOFF 为准。

## 绝对约束

- 不 merge `main`。
- `VERSION.txt` 必须保持 `42.24.0`。
- 不 tag。
- 不 release。
- Windows 开发 + NVIDIA Linux 生产同时兼容。
- 不删除测试、不放宽断言、不降阈值来过 CI。
- 前后端必须使用一致的数据结构/状态枚举。
- 正式页面必须使用真实后端接口，不能用假数据冒充生产 truth。
- Durable Task / Ground Truth / Agent execution 继续按现有 fail-closed owner 执行，不建立第二套 truth。

## 新畅联当前事实

新畅联当前 canonical Provider contract：
```text
POST /internal/auth/test-sign
POST /internal/auth/token
GET  /internal/base/category/tree
GET  /internal/base/compute-platform/listAll
GET  /internal/algorithm/product-ai/listAll
GET  /internal/algorithm/algorithm-analysis/listByProduct/{productId}
POST /internal/algorithm/algorithm-version/add
GET  /internal/algorithm/algorithm-version/listByProduct/{productId}
POST /internal/algorithm/algorithm-weight/add
GET  /internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}
```

不得把接口改回旧裸路径：
```text
/compute-platform/listAll
/algorithm-product/listAll
/algorithm-version/add
/algorithm-weight/add
```

业务接口鉴权 Header 必须按各自官方 OpenAPI 逐项绑定；算法产品 `listAll` 已确认使用 `Authorization: Bearer <accessToken>`。

## 当前唯一优先动作

当前第一主线不是继续堆新功能，而是：
```text
重新读取远端 HEAD / VERSION / Actions
→ 为当前 HEAD 创建新的 /data/platform/releases/<sha-short>
→ 不覆盖 ea1b6f198f81 回滚版本
→ 原子切换 /data/platform/current
→ restart changlian-web.service + changlian-worker.service
→ GET http://127.0.0.1:8010/api/health
→ 真实畅联测试：
   test-sign
   → token
   → category
   → product
   → analysis
   → compute-platform
→ 查看真实交互日志和业务码
```

如果 canonical `/internal/base/*` / `/internal/algorithm/*` 已正确但仍出现 HTTP 200 / 业务码 401，下一步检查畅联云侧 AccessKey 应用权限、租户/组织权限、接口授权范围；**不要先把 endpoint 改回旧裸路径。**

真实畅联云生产/联调 E2E 在完成前继续保持 **OPEN / NOT CLOSED**。


---

<!-- CHANGLIAN_CODE_ZERO_ACCESS_TOKEN_2026_09_20 -->
# 最新修复：新畅联 code=0 / 产品 OpenAPI / 完整 API 文档目录

2026-09-20 真实联调确认并修复：

- 畅联返回 `HTTP 200 + code=0 + msg=操作成功` 时，旧代码使用 `body.get("code") or ""`，把数值 `0` 错误变成空字符串，导致交互审计误记为 FAILED。现在 `code=0` 会保留为 `business_code="0"` 并记录 SUCCESS。
- 用户随后提供了完整 31 项 OpenAPI 汇编，现已确认品目、产品、分析方式、算力环境、算法版本、算法权重等内部业务接口统一声明 `Authorization: Bearer <accessToken>`。登出描述里的“Access-Token”是令牌语义，不是 Header 名；旧 `Access-Token` Header 实现已删除。
- `HTTP 200` 但业务码非成功（例如 `99999`）现在会在 HTTP client 边界直接失败，保留真实 business code 与远端 msg，不能继续被上层当成正常数据。
- 历史上已经落库的 code=0 误判记录会在 IntegrationAuditRepository 初始化时做幂等修复：仅修复 HTTP 2xx + 空 business_code + response.code 精确为 0 的旧 FAILED；`99999` 等真实失败绝不改写。
- 用户提供的 **31 个** Apifox 文档条目已完整登记在 `docs/CHANGLIAN_APIFOX_API_CATALOG.md`，平台页面也展示“新畅联接口契约”目录。
- 完整汇编已核实 31 个接口：人员 `POST /login` 仅作参考，其余 30 个内部接口均已进入 Provider contract。算法版本 8 个、算法权重 7 个接口已完整接入；新增/修改/删除由显式 Provider API 调用，连接测试只做只读查询。
- “测试连接”只执行鉴权和只读查询，不自动调用新增、修改、删除等有副作用接口。

当前已绑定主链：

```text
POST /internal/auth/test-sign
POST /internal/auth/token
GET  /internal/base/category/tree
GET  /internal/base/compute-platform/listAll
GET  /internal/algorithm/product-ai/listAll
GET  /internal/algorithm/algorithm-analysis/listByProduct/{productId}
POST /internal/algorithm/algorithm-version/add
GET  /internal/algorithm/algorithm-version/listByProduct/{productId}
POST /internal/algorithm/algorithm-weight/add
GET  /internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}
```

此前对 `GET /internal/algorithm/algorithm-product/listAll + Access-Token` 的真实测试返回 `HTTP 200 / code=99999`。官方 OpenAPI 已证明该请求合同本身错误；当前应使用 `GET /internal/algorithm/product-ai/listAll + Authorization: Bearer <accessToken>` 重新验收。`99999` 仍不得改判成功。

---

<!-- CHANGLIAN_COMPLETE_OPENAPI_2026_09_20 -->
# 最新收口：新畅联完整算法 OpenAPI

用户提供的《新畅联 接口文档汇编》已覆盖 31 个正式接口。当前代码完成：

- 主数据正式路径：`/internal/base/category/*`、`/internal/algorithm/product-ai/*`、`/internal/algorithm/algorithm-analysis/*`、`/internal/base/compute-platform/*`。
- 算法版本 8 个接口完整实现：edit/add/remove/list/listByProduct/listByAnalysis/listAll/getInfo。
- 算法权重 7 个接口完整实现：edit/add/remove/list/listByVersion/listByProduct/getInfo。
- 内部业务 Header 统一按汇编使用 `Authorization: Bearer <accessToken>`。
- 测试连接/诊断增加只读“算法版本 → 算法权重”抽查，不执行新增、修改、删除。
- 本平台新增受控 Provider API：`/api/v63/external-algorithm-platform/provider/versions/*` 与 `provider/weights/*` 等。
- 发布链固定使用官方版本/权重路径，前端不再允许编辑 Provider endpoint。
- 新增版本/权重官方响应 `data` 为整数 ID，发布代码已支持标量 `data` 直接解析，不必依赖反查兜底。
- 删除算法版本会同时删除其权重，保持显式破坏性操作，禁止测试连接/自动同步触发。

权威接口矩阵：`docs/CHANGLIAN_APIFOX_API_CATALOG.md`。

---

<!-- ALGORITHM_LIST_FILTERS_AND_SYNC_CADENCE_2026_09_20 -->
# 算法列表筛选 + 新畅联同步时效

## 本轮 owner 收口（2026-09-20）

算法列表筛选状态已经从 `external-algorithm-platform.js` 的局部状态迁移到 `AlgorithmListRuntime`：

- canonical filter state：`query / selectedCategoryIds[] / source / status`；
- 外部平台模块只负责外部算法元数据、品目数据、readiness 与 UI decorator，不再保存第二套来源/状态/品目筛选 truth；
- 搜索范围补齐真实算法编码、`productCode` / `Product ID` / `external_product_id`，同时保留名称、描述、行业、算法类型；
- 多品目继续 OR 命中，父品目继续包含子品目；
- 新增永久前端测试与 workflow guard，禁止 `selectedSource / selectedTrainingStatus / selectedCategoryIds` 重新回到外部模块成为独立 owner；
- 本轮代码级 V8 语法与关键 helper smoke 已通过；GitHub Actions 当前仍 queued，因此尚未形成部署资格。

算法列表当前新增：

- 算法搜索继续使用正式列表搜索框；
- 来源筛选：全部来源 / 内部算法 / 外部算法；
- 原行业场景、算法类型筛选继续保留；
- 新增训练状态筛选：可训练 / 训练中 / 已有版本 / 尚未训练 / 不可训练；
- 新畅联品目改为列表上方全部展示的可多选标签，父品目选择可匹配子品目；
- “新建算法”与“同步畅联云”并存，不再由外部模式用同步按钮覆盖新建按钮；
- 外部算法主数据仍只读；只有分析明细同时满足 `status=1` 且 `analysisType=1` 才可训练，其他情况全部禁止；训练版本及已完成转换产物继续通过版本/权重发布链同步回新畅联。

完整 31 项 OpenAPI 没有 Webhook、回调、订阅、SSE/WebSocket 等服务端推送能力，因此主数据同步当前只能主动拉取。平台允许配置 60 秒最小轮询间隔，定义为“准实时同步”，不能描述成真正推送式实时同步。

---
<!-- CHANGLIAN_ZERO_STATUS_FIX_2026_09_20 -->
# 部署阻断修复：新畅联 analysis status=0 不得被 falsy 吞掉

`d71ec0b03b44b1056cbb8d6b50b5425167d78dbf` 仍不可部署。服务器预检确认上游 `_analysis_is_enabled()` / `_analysis_summary()` 使用 `_value_from(..., "status") or ""`，导致数值 `0` 被转换成空字符串。

当前修复：

- `_analysis_is_enabled()` 显式区分 `None` 与 `0`；
- 当前最终合同进一步收紧为：**只有 `status=1` 才算启用**；`0`、缺失、空值、布尔值及其他未知值全部按不可训练处理；
- `_analysis_summary()` 对 `status=0` 持久化为字符串 `"0"`，不再变成空字符串；
- 新增参数化永久测试和 numeric-zero summary 测试；
- CI 永久禁止重新出现 `str(_value_from(row, "status") or "")`；
- 既有 SQLite round-trip 测试继续要求 `external_analysis_ids=["vision-on"]` 且 `vision-off.active=false`。

部署仍需等待新 HEAD 的 focused compile/unit tests 为 0 failed 后再继续。

---
<!-- CHANGLIAN_SQL_ANALYSIS_SUBSET_FIX_2026_09_20 -->
# 部署阻断修复：ChangLian 可训练分析 ID SQL round-trip

`017ad42b5c4e59ed86ac98366a54b6f481964410` 不可部署。预检暴露两个问题：

1. `test_external_mirror_preserves_local_and_existing_versions` 的旧预期漏了新增 `status` 字段；正式代码保留 `status`，测试已同步。
2. `AlgorithmSqlStore` 将 `external_analyses` 全量关系表重新投影成 `external_analysis_ids`，破坏“全部分析方式”和“可训练视觉分析 ID 子集”的边界。

当前修复：

- `external_analyses` 继续保存新畅联全部分析方式；
- `external_analysis_ids` 作为 canonical 可训练子集写入 `payload_json`，不再被 `_algorithm_payload()` / `_replace_all()` 丢弃；
- `read_all()` / `_read_one_conn()` 只恢复能够由持久化分析明细证明 `status=1 AND analysis_type=1` 的可训练 ID；旧 ID 列表本身不能绕过明细校验；
- `status=0` 会写成 `algorithm_external_analyses.active=0`；
- 新增永久 round-trip 测试覆盖 `vision-on / llm-on / vision-off`，并覆盖 `mirror → SQLite write → read → replace_all → read`；
- SQL workflow 和 External Algorithm Platform workflow 都加入永久 guard。

部署仍需等新 HEAD 的 compile/unit CI 通过后再继续，不能回到 `017ad42...`。

---
<!-- CHANGLIAN_VISUAL_ANALYSIS_FENCE_2026_09_20 -->
# 最新收口：仅启用视觉分析可进入 YOLO 训练

完整 OpenAPI 定义 `analysisType=1` 为视觉智能分析、`2` 为预留、`3` 为大模型智能分析，且 `status=1` 才表示启用。当前同步会保留全部分析方式详情，但训练候选必须同时满足 `analysisType=1 AND status=1`。字段缺失或仅有旧分析 ID 都不能作为训练依据；前端、后端和 SQL 持久化层统一 fail closed。

---

<!-- PLATFORM_CONFIG_EDIT_LOCK_2026_09_20 -->
# 最新产品规则：平台对接保存后锁定

2026-09-20，平台对接配置交互改为显式 **Save → Locked → Edit → Save**：

- 首次未配置时，URL / AccessKey / AccessSecret 可直接填写并“保存配置”。
- 保存成功后，当前外部平台配置立即进入只读锁定态；URL、平台来源、AccessKey、AccessSecret、同步设置不能直接修改。
- 锁定态只显示“编辑配置”；用户必须先点击“编辑配置”才进入可修改状态。
- 编辑态提供“保存配置”和“取消编辑”；取消编辑会丢弃页面草稿并恢复服务器已保存配置。
- 再次保存成功后立即重新锁定。
- 锁定态“测试连接”继续使用已保存配置；AccessSecret 不回显，后端沿用安全存储中的已保存凭据。
- “立即同步”始终使用服务器已保存配置；未保存编辑草稿不会改变当前平台。
- 当前平台只有在 **编辑 → 保存成功** 后才真正发生变化。

对应永久前端/Real Chrome guard：`tests/frontend/external-algorithm-platform.test.mjs`、`tests/browser/external-algorithm-platform.spec.mjs`。

---

# 最新修复：新畅联 Internal API Namespace

2026-09-20，平台对接真实联调发现旧业务 endpoint 缺少新畅联 internal namespace，典型现象为 HTTP 200 / 业务码 401。当前主数据与发布链已统一改为正式 internal 路径：

```text
/internal/auth/test-sign
/internal/auth/token
/internal/base/category/tree
/internal/base/compute-platform/listAll
/internal/algorithm/product-ai/listAll
/internal/algorithm/algorithm-analysis/listByProduct/{productId}
/internal/algorithm/algorithm-version/add
/internal/algorithm/algorithm-version/listByProduct/{productId}
/internal/algorithm/algorithm-weight/add
/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}
```

兼容边界：
- 仅把平台历史版本曾写入的已知旧裸路径自动迁移到 canonical internal path；
- 其他自定义 endpoint 不强制覆盖；
- 普通用户平台对接页不再暴露 endpoint 编辑，只配置 Base URL / AccessKey / AccessSecret；
- 发布创建与 timeout/UNKNOWN 反查共用同一 canonical internal contract；
- 内部业务接口按完整 OpenAPI 统一使用 `Authorization: Bearer <accessToken>`；
- `VERSION.txt` 继续保持 `42.24.0`。

---

# 最新关闭：Reusable Fixed Benchmark Training v1

2026-09-19，Evaluation Benchmark Scope 已正式接回下一轮 Durable TRAINING，**Reusable Fixed Benchmark Training v1 CLOSED**。

当前 CLOSED 边界：

- 不新增 Benchmark TaskKind、第二套训练 owner、前端评测 owner 或 Agent 权限；仍复用现有 TRAINING → Snapshot / Dataset Revision → Evaluation 链。
- `GET /api/v12/projects/{project_id}/algorithms/{algorithm_id}/benchmark-reuse` 只返回 current version、scope、snapshot、test count 与 binding truth，**不向浏览器下发具体 Test image IDs**。
- 训练提交只绑定 `benchmark_source_version_id + benchmark_scope_id`。服务端会重新验证：
  - source version 仍是当前版本；
  - source Evaluation 已成功；
  - Benchmark Scope 仍为 `bundle_verified`；
  - scope id / snapshot identity / test image content SHA / annotation hash-state / label schema 均未漂移。
- 只有上述校验全部通过后，服务端才从 source Snapshot 解析 exact test IDs，并把本次训练强制落为 independent test split；浏览器不能自己提交另一份 test list。
- 固定 Benchmark 与训练候选发生重叠时，不再把一个用户无法定位的隐藏 Test ID 报错抛回前端。控制面使用与 split leakage guard **同一 component relation truth** 自动保留：
  - exact test material；
  - 同 content SHA 的重复内容；
  - 同 file identity；
  - group / video / source-group / near-duplicate / sequence / camera-session 等不可拆分关联。
- 自动保留发生在 Durable TRAINING payload 冻结前；最终 Snapshot / Dataset Revision 只记录**实际有效训练/验证候选 + 固定 Test cohort**。
- `benchmark_reuse` audit 记录 selected / reserved / effective candidate counts，但不会把被保留的隐藏 Test identities暴露给浏览器。
- 若所选训练候选全部属于固定评测保留范围，后端 fail closed，要求补充其他训练素材；不会静默创建一个无法训练的任务。
- Frontend Impact Review 同批完成：
  - 固定 Benchmark 可用时继续显示 source version / count / “已校验 Test Bundle”；
  - 数据卡改为“训练候选素材”；
  - UI 明确“固定评测素材由系统自动保留，不会混入训练”；
  - experiment/test picker 不再与固定 Benchmark 并存；
  - Real Chrome 验证 browser 不持有 test_image_ids，提交只携带 benchmark identities。
- Agent / Central Scheduler / execution lease / generation fencing / object-storage transport / server-confirm 边界完全不变。

本轮代码：

- `39f05792f5f6a25c74539d7c7dba1cfabff4e34d` — `fix(evaluation): reserve benchmark inputs from training`
- `b22fcf66b8e598fa83cfa2fef47c2ce7c555318b` — `fix(evaluation): align benchmark reservation UX`

验收：

- backend parent HEAD `39f05792...`：30 workflows / 30 success / 0 failure / 0 pending。
- current implementation HEAD `b22fcf66...`：25 workflows / 25 success / 0 failure / 0 pending。
- Training Input Integrity push `35439895596`：Ubuntu + Windows success，包含 fixed benchmark component reservation guard。
- Remote Training Runtime current-head PR `35439898019`：API + Ubuntu + Windows success。
- Training Create First Open push `35439895675`：Ubuntu + Windows contract + Real Chrome success。
- `VERSION.txt = 42.24.0` unchanged。

**仍然 OPEN：**

1. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance；CI 不能替代真实 NPU。
2. 当前没有独立 Benchmark Registry / 主动重评 scheduler owner；本轮关闭的是“下一轮训练复用 current verified benchmark”，不是后台自动重评。
3. `automatic_execution=false` 仍保持：线上 feedback → supplement → training → evaluation 已可追溯，但受控自动迭代策略仍是后续独立阶段，不能靠前端定时器或第二套训练 owner 实现。

---

# 最新关闭：Evaluation Benchmark Scope v1

2026-09-19，独立 Evaluation 已从“各版本自己的 Test 指标”升级为带**固定评测输入身份**的 Benchmark Scope，**Evaluation Benchmark Scope v1 CLOSED**。

当前 CLOSED 边界：

- 不新增 TaskKind、Scheduler、Evaluation 数据库或自动回炉 owner；Benchmark Scope 继续作为 Algorithm Version persisted `evaluation` truth。
- Snapshot v3 仍是测试 cohort / Ground Truth 的唯一来源，冻结：
  - `test_image_ids`
  - 每张 source `content_sha256`
  - `annotation_hash / annotation_state`
  - label schema digest。
- 仅 Snapshot truth 不再足够宣称“严格可比”。Benchmark Scope 明确区分：
  - `binding_level=snapshot_truth`：只有 Snapshot test truth，历史/证据不完整场景只能描述性比较；
  - `binding_level=bundle_verified`：额外绑定实际 materialized Test Bundle。
- `bundle_verified` 会逐张核对 task-owned `work/bundle/manifest.json`：
  - test cohort IDs 必须与 Snapshot 完全一致；
  - `source_content_sha256` 必须与 Snapshot source truth 一致；
  - 实际评测图片 `content_sha256`（包括训练输入规范化后的真实字节）；
  - hidden Ground Truth `label_sha256`；
  - `training_input_policy`；
  - 生成 deterministic `evaluation_input_digest`。
- 因此未来即使同一 source 图片在 materialization/normalization policy 下产生不同实际评测字节，也不会被误判成同一严格 Benchmark。
- Evaluation protocol identity 正式带 `evaluation_protocol_version=1`；protocol ID 把 schema version 与 operating_conf / matching_iou / blind-evaluation mode 一起冻结。
- Feedback Adoption Effectiveness 的 strict 条件现在必须同时满足：
  1. source/new Evaluation 都成功；
  2. 两边 Benchmark Scope ID 相同；
  3. 两边均为 `bundle_verified`；
  4. Evaluation Protocol ID 相同。
- 任一版本缺少实际 Test Bundle binding 时，后端持久化 `benchmark_input_binding_missing`，只能 `comparison_mode=descriptive`，前端不得自己升级为“严格可比”。
- Local TRAINING 与 Remote Agent TRAINING 已使用同一 Benchmark truth：
  - Local 归档从 Durable TRAINING result 白名单投影 `dataset_manifest_ref`，再读取同一 task-owned manifest；
  - overlay 不复制整个 result，只投影该证据引用，避免 legacy job 成为第二套 result truth；
  - Remote server-confirm 直接读取目标 TRAINING task 的 `snapshot.json + work/bundle/manifest.json`，构建完全相同的 `bundle_verified` scope；
  - Agent 不增加权限，也不读取中央 SQLite/NFS。
- Frontend Impact Review 已完成：
  - “独立评测”展示评测基准与“评测输入绑定”；
  - `bundle_verified` 显示“已校验 Test Bundle”；
  - 历史 Snapshot-only 显示“仅 Snapshot truth”；
  - strict/descriptive 与原因全部来自 persisted backend truth，页面不自行计算。
- Benchmark Scope 仍只增强评测严谨性，`automatic_execution=false` 语义不变，不会自动创建下一轮 TRAINING。

- Acceptance code HEAD：`ac8ac782632c3d63cb7ed6a8c807a826451abb5e`。
- Current-head shared regression：23 workflows / 23 success / 0 failure / 0 pending。
- Remote Training Runtime push `35436884535`：API + Ubuntu + Windows success。
- Remote Training Runtime PR `35436887856`：API + Ubuntu + Windows success。
- Parent `6c2c7c92d733176a24438c22cea570bc4786b5a8` 的 Algorithm SQL Store `35436643513`：contracts + Real Chrome lineage success。
- Parent `6c2c7c92d733176a24438c22cea570bc4786b5a8` 的 Training Task Visibility `35436643535`：Unified training job overlay truth + Real Chrome success。
- `VERSION.txt = 42.24.0` unchanged。

**仍然 OPEN：**

1. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance；软件 CI 不能替代现场 NPU 验收。
2. Benchmark v1 已解决“什么时候可以严格比较”，但没有创建独立 Benchmark Registry / 主动重评任务 owner；后续若需要跨不同训练 Snapshot 强制复用固定 Benchmark，应继续复用现有 Evaluation / Durable Task 架构设计，不得让前端自行重算。

# 最新关闭：Feedback Adoption → Iteration Outcome / Effectiveness v1

2026-09-19，已把“实际采用了哪些 feedback”与新版本独立 Evaluation 的结果连接成 Algorithm Version 长期 truth，**Effectiveness v1 CLOSED**。

当前 CLOSED 边界：

- 不新增 task/database owner。效果结果继续由 Algorithm Version 持久化，字段为 `feedback_adoption_outcome`。
- 输入只来自：
  1. source Algorithm Version persisted `evaluation`；
  2. new Algorithm Version persisted `evaluation`；
  3. new version `training_lineage.supplement_provenance`。
- 不读取前端临时 draft，不从 online feedback 列表重新猜 adoption，也不重新计算 Candidate Set。
- source version 不是从 supplement provenance 自证：必须来自真实 `training_lineage.base.version_id`，再与 provenance `version_id` fail-closed 对账。
- outcome 持久化 source/new version、candidate_set_id、adoption_id、action_id、source/new evaluation_id、采用 feedback 数量与 feedback IDs。
- 总体效果保存 Precision / Recall / mAP50 / mAP50-95 的 before / after / delta。
- 弱标签效果以 **source evaluation 的 persisted weak_labels** 为基线，保存逐标签 Precision / Recall / mAP50 / mAP50-95、FP/FN、弱项信号变化与 `improved / declined / unchanged`。
- 如果 source/new evaluation 不存在、未成功或无法形成完整证据，则 outcome 保存为 `not_comparable` 和 reason_codes，而不是伪造改善结论。
- outcome 明确 `descriptive_only=true`、`automatic_execution=false`；**不会自动创建下一轮训练、Candidate Set、Dataset Revision 或任务**。
- SQL Algorithm Version round-trip 已覆盖新字段，历史版本没有该字段时仍兼容。
- Frontend Impact Review 已完成：现有“独立评测”弹窗直接读取 persisted `feedback_adoption_outcome`，展示“补数据效果”、采用反馈数量、总体 delta、原弱标签变化和完整 provenance；页面不自己计算效果。
- 前端明确提示：“仅描述本次采用反馈后的评测变化，不会自动触发下一轮训练。”
- Real Chrome 已验证版本 persisted truth → 独立评测弹窗，无 job refetch、无自动训练副作用。
- 共享 Online Feedback Real Chrome 中发现的两个 project-state race 已通过显式 pin 测试项目 truth 修复；没有为测试修改生产行为。

Acceptance code/test HEAD：`c26b7449b06697fcac52979e9bb8483138ebbbab`。

- Current-head shared regression at `c26b7449b06697fcac52979e9bb8483138ebbbab`: 17 workflows / 17 success / 0 failure / 0 pending.
- Algorithm SQL Store `35432975461`: contracts + Real Chrome lineage success. This run covers the Effectiveness implementation code; later commits only fixed unrelated browser test project setup.
- Online Feedback Runtime push `35433393053`: Ubuntu / Windows / Real Chrome success.
- Online Feedback Runtime PR `35433395739`: Ubuntu / Windows / Real Chrome success.
- Remote Training `35433395670`, Node Agent `35433395713`, Material Import `35433395706`, Cleaning `35433395720`, Conversion `35433395702`, RKNN `35433395700`, Portable Deployment `35433395671`, Central Assignment `35433395650`, Task Runtime Truth `35433395684` all success.
- `VERSION.txt = 42.24.0` unchanged.

**NEXT：Evaluation Benchmark Scope v1。**

当前 Effectiveness v1 是**描述性** before/after：它比较两个版本各自已持久化的独立 Evaluation，但不宣称指标变化由补数据单独造成。下一阶段应基于 Snapshot 已有 `test_image_ids + content_sha256 + annotation_hash` 冻结可复用的 Benchmark Scope identity；只有同一 benchmark / 同一 ground-truth truth 才标记为严格 comparable。这个阶段仍只增强评测严谨性，不自动触发下一轮训练。

Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance 继续独立 OPEN。

# 0. 接手第一分钟必须执行

不要先改代码。先确认真实状态：

```bash
git fetch origin
git switch feature/external-algorithm-publishing
git pull --ff-only
git status
git rev-parse HEAD
git rev-parse origin/feature/external-algorithm-publishing
cat VERSION.txt
```

然后再看：

```text
docs/PROJECT_HANDOFF_CURRENT.md
docs/BUG_AUDIT_2026-09-17.md
docs/CODEX_CURRENT_STATE.md
docs/TECH_DEBT_CLOSURE_V42_25.md
docs/frontend-legacy-audit.md
docs/FRONTEND_OWNER_MAP_V42_25.md
docs/EXTERNAL_ALGORITHM_PUBLISH_PHASE2.md
docs/NODE_CONTROL_PLANE_V42_25.md
```

### 绝对约束

1. **不 merge `main`**，除非用户明确授权。
2. **不修改正式 `VERSION.txt`**，当前必须保持 `42.24.0`。
3. 不 tag。
4. 不 release。
5. 不为了测试通过删除测试、降低阈值、放宽断言、恢复 legacy owner。
6. Windows 开发 + NVIDIA Linux 生产必须同时兼容。
7. 任何“完成”必须有真实代码 + focused test + permanent guard；关键前端运行链路尽量有 Real Chrome。
8. A800 RC / genuine 10k ZIP 性能验收不要擅自恢复，除非用户重新要求。

当前 `main` 最近一次已验证仍为：

```text
2fe9394ccb10068d81cc2113879ac801c4831017
revert: keep external algorithm integration off main
```

如果接手时 `main` 不再是这个 SHA，先查是谁、为什么改，不要自动把 feature 内容合进去。

---


# 最新关闭：Supplement Candidate Set → Dataset Revision / Snapshot / Training Lineage v1

2026-09-19，已冻结的 Feedback Supplement Candidate Set 已正式接入现有 Durable TRAINING 输入与版本溯源链，**Supplement Candidate Adoption / Training Lineage v1 CLOSED**。没有新建训练 owner，也没有允许 Candidate Set 自动发起训练。

当前正式语义：

- 用户仍在现有训练弹窗中最终确认素材范围；Candidate Set 只是可追溯候选来源。
- 前端只有当本次实际选择的训练/测试素材与版本的 frozen Candidate Set 有交集时，才提交 `supplement_candidate_set_id`。
- 后端不信任前端交集结果：
  - 只读取算法当前 verified version 的 persisted Candidate Set；
  - candidate_set_id 必须与版本 truth 完全一致；
  - 对本次实际采用的 material 再读取 MaterialRepository + AnnotationRepository；
  - material content SHA256、annotation_hash、annotation_state 任一变化均 409 fail closed。
- Snapshot / Dataset Revision 基于**最终实际进入快照的素材集合**计算 supplement provenance，而不是把整个 Candidate Set 原样写进去。
- 实际采用子集会冻结：
  - candidate_set_id；
  - deterministic adoption_id；
  - action_id / source algorithm_id / source version_id；
  - adopted_feedback_ids；
  - adopted_material_ids；
  - 每条 candidate_digest / material input SHA / annotation hash/state；
  - source_candidate_count / adopted_candidate_count；
  - `automatic_execution=false`。
- Dataset Revision ID 把 supplement provenance 纳入 immutable identity；同一素材集但采用的 feedback lineage 不同，会形成不同 Revision identity。
- Snapshot 携带同一 adoption provenance。
- Local TRAINING 与 Remote Agent TRAINING 使用同一 provenance：
  - Remote prepare contract 携带 Snapshot 的 supplement provenance；
  - Agent 不自行推算 Candidate Set；
  - server-confirm 将同一 provenance 写入最终 Training Lineage / Algorithm Version。
- Algorithm Version 的 `training_lineage.supplement_provenance` 成为长期 truth；历史 job 清理后仍能追溯“这个版本实际采用了哪些线上反馈素材”。
- 训练继承仍由唯一 current verified version 决定；Candidate Set 所属版本与真实训练 base version 同一版本 owner，不存在前端选历史版本、后端却校验当前版本的双 truth。
- Frontend Impact Review 已完成：
  - 训练摘要显示 Candidate Set 来源数量与实际采用数量；
  - confirmed supplement action 会先恢复 persisted `data_draft` / weak labels；
  - 未冻结 Candidate Set 时进入真实反馈候选复核；
  - 已冻结 Candidate Set 刷新/恢复后直接回到数据集页，不重复打开候选复核或重复请求候选列表；
  - 页面仍明确：冻结候选本身不会创建 Revision / Snapshot / TRAINING。
- Real Chrome 覆盖 persisted confirmed action → feedback candidate review/freeze → transient UI state reset → version truth refresh → Dataset 恢复，以及 Algorithm Version lineage 无历史 job refetch。

Acceptance code HEAD：`49becaf398403b76e4209ed35ca18aaa8ef860a1`。

最终验收：

- 当前 HEAD：18 个相关 workflow，18 success / 0 failure / 0 pending。
- Algorithm SQL Store push `35431356487`：contracts + `real-chrome-lineage` success。
- Online Feedback Runtime push `35431356518`：Ubuntu / Windows contract / Real Chrome success。
- Online Feedback Runtime PR `35431359456`：Ubuntu / Windows contract / Real Chrome success。
- Remote Training Runtime PR `35431359366`：API / Ubuntu / Windows preparation contract success。
- Training Input Integrity `35431359267`：success。
- Node Agent Executor `35431359353`：API / Ubuntu / Windows success。
- Remote Material Import `35431359273`：API / Ubuntu / Windows / Real Chrome success。
- Remote Cleaning `35431359380`、Remote Conversion `35431359264`、Portable Deployment `35431359350`、Central Node Assignment `35431359283`、Task Runtime Truth `35431359289`、RKNN Board Runtime Protocol `35431359317` 均 success。
- `VERSION.txt = 42.24.0` 未修改。

**下一软件主线：Feedback Adoption → Iteration Outcome / Effectiveness v1。**

下一阶段不再改 Candidate Set/Revision/Snapshot owner，而是在新版本完成独立 Evaluation 后，把“采用了哪些 feedback”与“训练前后指标变化”连接起来：

1. 只基于 persisted source version evaluation + new version evaluation + training_lineage.supplement_provenance 生成 outcome。
2. 记录 source/new version、candidate_set_id、adoption_id、before/after evaluation IDs、总体与 adopted weak-label 指标变化。
3. 结果只描述效果，不自动再次训练；下一轮仍必须经过 Iteration Decision → Confirmed Action。
4. 前端版本页展示“这次补数据是否改善了哪些标签”，数据完全来自后端 persisted truth。
5. Rockchip 真实 RK3568 / RK3576 板卡 acceptance 继续独立 OPEN。

# 最新关闭：Feedback → Supplement Data Candidate v1

2026-09-19，已确认线上反馈现在可以进入**版本级补数据候选集**，**Supplement Data Candidate v1 CLOSED**。候选集仍然只是补数据草稿 truth，不会自动创建 Dataset Revision、Snapshot 或训练任务。

当前正式语义：

- 只有 `status=confirmed` 且与当前 algorithm/version 完全一致的 feedback 才进入候选查询；`pending_review / dismissed` 不会出现。
- 每条候选由后端读取当前 MaterialRepository + AnnotationRepository truth，冻结：
  - feedback_id / feedback_type；
  - material_id；
  - algorithm_id / version_id；
  - model SHA256 / input SHA256；
  - 当前 annotation_state / annotation_hash / annotation_scope / labels；
  - confirmed_at / source channel。
- 后端统一给出 `eligible / reason_codes / candidate_digest`；前端不自行判断可用性。
- `needs_correction` 在正式标注仍为 unannotated 时只能显示“待人工标注”，不能加入候选集；人工标注完成后才可成为 eligible。
- 用户在“继续补数据”中显式勾选后提交 `feedback_id + candidate_digest`；冻结时服务端重新读取素材/标注 truth。查看后素材或标注变化会 409 fail closed。
- 冻结结果作为当前 Algorithm Version 的 `supplement_data_candidate_set` 长期保存：
  - deterministic candidate_set_id；
  - action_id；
  - feedback_ids / material_ids；
  - 每条 annotation_hash / candidate_digest / model/input identity；
  - `automatic_execution=false`。
- 同一 candidate set 重试幂等；同一版本若已经冻结另一组 candidate set，拒绝覆盖，避免 lineage 漂移。
- 前端继续复用现有“数据集”页，不新增平行页面：
  - 先展示后端反馈候选；
  - eligible 默认可勾选，未完成标注候选不可勾；
  - “冻结并进入数据集”后展示 Candidate Set；
  - 可切换“仅看反馈候选 / 显示全部素材”；
  - 页面明确提示“尚未生成 Dataset Revision、Snapshot 或训练任务”。
- Candidate v1 不修改 Dataset Revision / Snapshot owner，也不调用 `/train/start`。
- Real Chrome 覆盖：confirmed supplement_data → 候选弹窗 → eligible/ineligible truth → freeze → 数据集页 Candidate Set banner，并永久断言没有自动训练/Revision。

Acceptance HEAD：`a54e0e735b27bde400b205fe1d07ede03903a973`。

- Online Feedback Runtime push `35428464451`：Ubuntu / Windows contract / Real Chrome 全部 success。
- Online Feedback Runtime PR `35428467030`：Ubuntu / Windows contract / Real Chrome 全部 success。
- 当前 code HEAD `a54e0e735b27bde400b205fe1d07ede03903a973`：17 个相关 workflows，0 failure / 0 pending；Node Agent Executor API / Ubuntu / Windows 也全部 success。
- `VERSION.txt = 42.24.0` 未修改。

**下一主线：Supplement Candidate Set → Dataset Revision / Snapshot / Training Lineage v1。**

1. 用户真正提交训练前，必须重新核对 candidate set 中的 material content identity 与 annotation_hash；变化则 fail closed。
2. 新 Dataset Revision / Snapshot 必须携带 candidate_set_id 与 feedback IDs 的可追溯 provenance。
3. Training Lineage / Algorithm Version 必须保存该 candidate set identity，使新模型能反向追到具体反馈。
4. 仍由用户在既有训练配置中确认最终素材范围；candidate set 不能自动发起训练。
5. 若最终训练选择只使用 candidate set 的一部分，必须冻结“实际采用的 feedback/material 子集”，不能把未使用反馈写进 lineage。
6. Rockchip 实机 acceptance 继续独立 OPEN。

# 最新关闭：Online Algorithm Sampling / Feedback v1

2026-09-19，线上算法抽检、测试发布反馈和外部 SaaS / 边缘样本已经接入统一的 **reviewed feedback intake**，**Online Algorithm Sampling / Feedback v1 CLOSED**。没有新增第二套训练 owner，也没有让反馈直接修改 Dataset Revision 或自动启动训练。

当前正式语义：

- 唯一反馈状态为 `pending_review / confirmed / dismissed`；前端不自行推算状态。
- 正式测试发布预测可以提交三类反馈：
  - `correct`
  - `false_positive`
  - `needs_correction`
- 每条反馈冻结并校验：
  - prediction / external sample identity；
  - algorithm_id / version_id；
  - model SHA256；
  - input SHA256；
  - 原预测 detections / confidence / engine；
  - 来源通道、外部来源和外部样本编号。
- 外部 SaaS / 边缘端通过 `/api/v63/projects/{project_id}/online-feedback/external-intake` 上传图片和预测证据：
  - 仅接受真实图片；
  - 大小和 detections JSON 有上限；
  - 必须绑定当前正式算法版本及完全一致的 model SHA；
  - 相同外部样本编号的证据变化会 fail closed；
  - 接入后只进入 `pending_review`，不会直接进入素材库、Dataset Revision 或训练。
- 用户显式确认后才允许 promotion：
  - `correct`：预测框与当前 Annotation truth 不冲突时，可作为正式标注；
  - `false_positive`：必须显式确认“当前启用标签均不存在”，才可形成 confirmed-empty 负样本；
  - `needs_correction`：只进入人工标注/修正状态，不把错误预测自动写成 truth。
- 已有素材按 content SHA256 复用；不存在时才进入现有 MaterialRepository；AnnotationRepository 仍是唯一正式标注 owner。
- 如果素材已有不同正式标注，feedback confirm 不允许覆盖，必须人工处理。
- confirm 后 MaterialRepository 持久化 bounded `online_feedback_refs`，包含 feedback / prediction / algorithm / version / model / input identity。
- dismiss 是显式终止动作：
  - 状态写为 `dismissed`；
  - 不创建素材；
  - 不修改 AnnotationRepository；
  - 不创建 Dataset Revision；
  - 不创建 TRAINING task。
- v42 legacy feedback / automatic iteration write 已退役；旧入口不再偷偷写入新的训练迭代 truth。
- Frontend Impact Review 已完成：
  - 测试发布页使用 v63 reviewed flow；
  - 提交反馈、待复核、确认、忽略、外部接入都来自真实后端；
  - legacy `openAuditConnect42` 只映射到新的 reviewed external intake，不再展示旧 v42 contract；
  - 页面明确提示“不会自动修改素材、数据集、Dataset Revision 或训练任务”；
  - Real Chrome 已覆盖正式预测反馈、误检负样本确认、待复核忽略、external intake contract。

最终 acceptance HEAD：`7a1ade605b6a55e1fe9027a86dc6756af795456b`。

最终验收：

- Online Feedback Runtime push `35427702717`：Ubuntu contract / Windows contract / Real Chrome 全部 success。
- Online Feedback Runtime PR `35427704825`：Ubuntu contract / Windows contract / Real Chrome 全部 success。
- Product code HEAD `05ba04f132e746ac3bd96b05790f0b526acd0236` 的其他共享 workflows 均 success；当时唯一红项是 Online Feedback Runtime，根因仅为 focused CI 缺少 OpenCV 依赖和测试使用了不存在的 MaterialRepository.list()，均已在 acceptance HEAD 修正。
- `VERSION.txt = 42.24.0` 未修改。

**下一软件主线：Feedback → Supplement Data Candidate / Dataset Revision Candidate v1。**

1. 只从 `confirmed` feedback 生成补数据候选，不消费 dismissed / pending_review。
2. 候选必须冻结 feedback_id / material_id / annotation hash / algorithm version / model SHA / source evidence。
3. 支持按算法版本、标签、false-positive / correction / weak label 等筛选和批量加入补数据草稿。
4. 继续复用现有 supplement_data / Dataset Revision / Snapshot owner；用户确认素材范围后才形成新的 Dataset Revision。
5. 不允许 feedback confirm 后自动创建 Dataset Revision，更不允许自动发起训练。
6. 生成的新 revision / snapshot / training lineage 必须能反向追溯到具体 feedback IDs。
7. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance 继续独立 OPEN。

# 最新关闭：Iteration Decision → Confirmed Action v1

2026-09-19，版本级 `iteration_decision` 已正式接入用户显式确认后的产品动作，**Confirmed Action v1 CLOSED**。仍然由算法版本持有唯一长期 truth；没有新增第二套训练 owner、数据 owner 或前端自行推算的动作状态。

当前正式语义：

- 仅算法**当前版本**可以确认下一步动作；请求必须携带当前 persisted `decision_id`，旧版本、旧 decision 或不匹配 action 一律 fail closed。
- 版本持久化 `confirmed_iteration_action.schema_version=1`，同一 action 的重复确认幂等；同一版本已经确认其他 action 时拒绝覆盖。
- 四种 decision 与产品动作一一绑定：
  - `needs_data → supplement_data`
    - 冻结 weak labels、FP/FN problem samples、dataset revision、snapshot；
    - 生成补数据草稿/入口；
    - **不会自动修改 Dataset Revision，也不会自动导入或删除素材**，最终素材范围仍由用户确认。
  - `continue_training → continue_training`
    - 生成确定性的固定 Durable TRAINING task ID；
    - 必须携带 action / decision / evaluation / version / dataset revision / snapshot identity；
    - 只复用既有 Durable TRAINING / Central Scheduler / lease / generation / server-confirm owner；
    - 用户真正点击“开始训练”后才创建任务；重复提交同一固定 task ID 幂等。
  - `ready_for_business_validation → business_validation`
    - 生成 version-owned validation entry；
    - 冻结 decision/evaluation/version/revision/snapshot/model SHA identity；
    - 只进入现有业务验证/测试发布入口，不偷偷改变转换或部署 owner。
  - `review_required → manual_review`
    - 生成正式 `review_entry`；
    - 冻结 reason codes、recommended actions、weak labels 与完整来源 identity；
    - 保持人工处理，不自动执行任何数据或训练动作。
- 后续训练完成后的 `training_lineage` 会携带已确认 action identity，因此下一版本可追溯到“哪一次评测、哪一个决策、哪一次人工确认”。
- confirmed action 明确 `automatic_execution=false`；continue-training 仍要求 user submit，系统不会因为 decision 自动开启下一轮训练。

Frontend Impact Review 已完成：

- “独立评测”弹窗只读取版本持久化 `evaluation / iteration_decision / confirmed_iteration_action`；
- 已确认动作显示“已确认”，而不是刷新后重新出现“确认”按钮；
- 页面刷新、重新进入算法版本后，可直接从 persisted version truth 恢复：
  - “继续补数据”
  - “继续创建训练”
  - “继续业务验证”
  - “查看人工处理记录”
- 补数据 / 业务验证 / 人工处理不再依赖仅存在于当前浏览器生命周期的临时 draft truth；
- continue-training 恢复后仍只打开训练草稿，只有用户点击“开始训练”才真正 POST Durable TRAINING；
- Real Chrome 验证了：确认补数据 → 页面跳转 → 清除临时 state / 重新刷新算法版本 → 显示 persisted “已确认：补数据” → 无需第二次 confirm 即可继续补数据；过程中没有误调用 `/train/start` 或历史 `/jobs`。

最终验收：

- Product code HEAD `d422fc21b3394edd71567a81bc34316d1172c652` shared regressions: 0 pending / 0 shared failure.
- Latest acceptance HEAD `4076f8adb376c24e32db78cf3bd15f83182ebcb4`: Algorithm SQL Store run `35424317881` contracts + Real Chrome success.
- Remote Training Runtime PR `35424280734`: API / Ubuntu / Windows success.
- Node Agent Executor PR `35424280790`: API / Ubuntu / Windows success.
- Remote Material Import PR `35424280896`: API / Ubuntu / Windows / Real Chrome success.
- Remote Cleaning Runtime PR `35424280779`: API / Ubuntu / Windows / Real Chrome success.
- Remote Conversion Runtime PR `35424280823`: control-plane / Ubuntu / Windows / Real Chrome success.
- Portable Deployment `35424280766`, Central Node Assignment `35424280780`, Task Runtime Truth `35424280794`, Training Input Integrity `35424280757`, Remote RKNN Board Runtime Protocol `35424280702`, Storage Cache Governance `35424280744` all success.
- `VERSION.txt = 42.24.0` remains unchanged.

**下一软件主线：Online Algorithm Sampling / Feedback v1。**

线上算法抽检、SaaS/边缘端回流、人工判定的 FP/FN/漏检/误检证据，应作为**可审核的反馈入口**接入现有链：

`线上样本/反馈 → review/confirm → 现有 MaterialRepository / AnnotationRepository → Dataset Revision → Snapshot → Durable TRAINING → Evaluation → Iteration Decision → Confirmed Action`

不得另建“自动回炉训练”owner，也不得让线上反馈直接改 Dataset Revision 或自动训练。每条反馈必须绑定 source algorithm/version/model SHA、样本/判定证据和确认人机动作。Rockchip 真实 RK3568/RK3576 物理板卡 acceptance 继续独立 OPEN。

# 最新关闭：Training Evaluation / Iteration Decision v1

2026-09-19，Dataset Revision → Snapshot → TRAINING → Algorithm Version 之后的正式独立评测与迭代决策已闭环，**Training Evaluation / Iteration Decision v1 CLOSED**。没有创建第二套训练 owner，也没有由前端自行推算结论。

当前正式语义：

- 训练完成后，算法版本继续持久化 frozen test split 的独立评测 truth：
  - overall Precision / Recall / mAP50 / mAP50-95；
  - per-label Precision / Recall / mAP；
  - TP / FP / FN；
  - weak labels；
  - FP/FN 问题样本；
  - evaluation_id / task_id / snapshot_id / dataset_revision_id / model SHA256。
- 新增 version-owned `iteration_decision.schema_version=1`，由后端 `build_iteration_decision()` 从 **persisted evaluation + 原训练 quality_gate** 确定性生成。
- 决策继续复用已有训练门禁语义，不新造阈值体系：
  - 未配置独立评测 / 评测失败 / 指标不可用 / 未配置 stop threshold → `review_required`；
  - 存在 weak labels → `needs_data`；
  - 最终指标低于原 `continue_threshold` → `needs_data`；
  - 指标位于 continue / stop threshold 之间 → `continue_training`；
  - 达到原 `stop_threshold` 且不存在 weak labels → `ready_for_business_validation`。
- decision 同时冻结：
  - metric / metric_key / metric_value；
  - continue_threshold / stop_threshold；
  - weak label 优先顺序；
  - FP / FN / problem sample signals；
  - reason_codes；
  - recommended_actions；
  - deterministic decision_id。
- decision 明确 `automatic_execution=false`、`requires_confirmation=true`：本阶段**只形成正式建议，不自动补数据、不自动创建下一次训练任务、不改变已 CLOSED 的转换触发语义**。
- Algorithm SQL Store round-trip 已覆盖 `iteration_decision`，历史 job 清理后版本仍保留完整决策 truth。
- Frontend Impact Review 已同批完成：
  - “独立评测”弹窗直接读取 `version.evaluation + version.iteration_decision`；
  - 页面不重新读取历史 job，也不按自己的阈值重新计算；
  - 显示“可进入业务验证 / 需补充数据 / 建议继续训练 / 需人工确认”；
  - 显示使用指标、继续训练下限、达标阈值、弱标签建议、FP/FN 问题样本；
  - 明确展示“系统仅给出建议，不会自动发起下一次训练”；
  - Real Chrome 已验证正式算法列表 → 版本 → 独立评测 → 迭代决策链。
- weak label 顺序保持评测侧“更弱优先”的原始顺序，不再被字母排序破坏。

最终代码验收 HEAD：`d11d0e16998e7630bbc5811a937ba3c21395548e`。

最终验收：

- 当前代码 HEAD 共 **17 个 workflow：17 success / 0 failure / 0 pending**。
- Algorithm SQL Store push `35422469494`：contracts + Real Chrome success。
- Remote Training Runtime push `35422469499`：Windows / Ubuntu preparation contracts + API success。
- Training Input Integrity、GPU Runtime Truth、Central Node Assignment、Task Runtime Truth、Node Agent Executor、Portable Deployment、Remote Material Import、Remote Cleaning、Remote Conversion、Remote RKNN Board Runtime Protocol、Storage Cache Governance、External Algorithm Platform / Publish 全部 success。
- Algorithm SQL Store unit 已验证 decision contract、确定性 decision_id、SQL round-trip。
- Real Chrome 已验证 UI 读取 persisted decision truth，且不重新请求历史 `/jobs`。
- `VERSION.txt = 42.24.0` 未修改。

**下一软件主线：Iteration Decision → Confirmed Action v1。**

1. `needs_data`：基于 weak labels + FP/FN 问题样本生成“补数据草稿/入口”，由用户确认素材范围；不得自动改 Dataset Revision。
2. `continue_training`：复用现有算法训练入口，预填当前算法/当前版本/建议关注标签，用户确认后才创建新的 Durable TRAINING。
3. `ready_for_business_validation`：进入业务验证/部署验证入口；不在本阶段偷偷改变既有自动转换 owner/门槛。
4. `review_required`：保持人工确认，不自动执行。
5. 所有动作必须引用原 `decision_id / evaluation_id / dataset_revision_id / snapshot_id / version_id`，形成下一轮 lineage，不建立第二套训练或数据 owner。
6. 后续线上算法抽检/回流仍接入同一 Dataset Revision → TRAINING → Evaluation → Iteration Decision 链。
7. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance 继续独立 OPEN。

# 最新关闭：Training Lineage / Algorithm Version Provenance v1

2026-09-19，Dataset Revision v1 之上的正式训练溯源链已完成，**Training Lineage / Algorithm Version Provenance v1 CLOSED**。

当前正式语义：

- 每个新训练完成后的算法版本持久化 `training_lineage.schema_version=1`，不依赖当前 job 缓存。
- lineage 统一串联：
  - `task_id`
  - `snapshot_id`
  - `dataset_revision_id`
  - framework
  - base version / base model / base selection reason
  - execution mode / worker / Agent node / execution generation
  - requested / assigned / actual device
  - GPU identity（公开安全字段）
  - requested / actual training params
  - verified model artifact identity（role / artifact id / file name / SHA256 / size / object ref）
  - training outcome / completion reason / finished_at。
- 本地训练与 Remote Agent TRAINING 走同一个 `build_training_lineage()` contract，不产生两套 provenance 结构。
- lineage builder 使用 allow-list，只保留公开安全的 primitive 字段；signed URL、secret URL、凭据等不会进入算法版本。
- dataset revision 必须是合法 SHA256；不合法直接 fail closed。
- base model 只持久化安全文件名，不泄露本机绝对路径。
- Algorithm SQL Store round-trip 已验证 `dataset_revision_id / snapshot_id / training_lineage` 不丢失。
- Remote Agent server-confirm 后写入版本时，lineage 与模型 artifact、dataset revision、execution generation 使用同一确认后的 truth。
- Frontend Impact Review 已同批完成：
  - 算法版本稳定 renderer 只有在 `training_lineage` 存在时展示“训练溯源”；
  - 溯源页直接读取算法版本持久化 lineage；
  - 显示数据版本、训练快照、训练任务、基础模型/版本、执行节点/设备、实际训练参数和模型产物；
  - 不通过历史 `/jobs` 二次拼装，历史 task 清理后版本溯源仍成立；
  - Real Chrome 已验证正式算法列表 → 版本 → 训练溯源链。

最终验收 HEAD：`c6c7289b3a13d20053e1a8aed44525a4901f5059`。

- 当前代码 HEAD `c6c7289b3a13d20053e1a8aed44525a4901f5059`：21 个相关 workflow，21 success / 0 failure / 0 pending。
- Training Input Integrity、Remote Training Runtime、Node Agent Executor、Central Node Assignment、Task Runtime Truth、Portable Deployment、Remote Material Import、Remote Cleaning、Remote Conversion、Remote RKNN Board Runtime Protocol 均 success。
- Algorithm SQL Store / Training Task Visibility / External Algorithm Platform / Publish 等共享回归 success。
- Real Chrome 已验证算法版本“训练溯源”来自持久化版本 truth，点击查看不会重新请求历史 job。
- `VERSION.txt = 42.24.0` 未修改。

**下一软件主线：**

1. 基于 Dataset Revision + Snapshot V3 + Training Lineage，进入 **自动评测 / 训练迭代闭环**：
   - 训练完成；
   - 使用冻结 test split 做正式评测；
   - 产出总体指标 + 标签级 Precision / Recall / mAP；
   - 识别弱标签、FP/FN 和问题样本；
   - 不达标时进入明确的“需补数据 / 需继续训练 / 人工确认”决策，不新建第二套训练 owner。
2. 后续再把线上算法抽检/回流接到同一个 Dataset Revision → Training → Evaluation → Version lineage 链。
3. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance 继续独立 OPEN。

# 最新关闭：Dataset Snapshot / Revision v1 — 训练数据可复现性

2026-09-19，现有 **Snapshot V3** 已扩展出正式 **Dataset Revision v1**，CLOSED。没有新建第二套 snapshot owner。

当前正式语义：

- `dataset_revision_id` 描述“本次训练选择的数据 truth”，与 train / validation / test 的具体随机分配解耦。
- 同一批素材、同一平台标注、同一 Canonical Annotation source truth、同一 label schema，即使 split seed 不同，`dataset_revision_id` 保持不变；对应 `snapshot_id` 会因 split / seed / role truth 不同而变化。
- Dataset Revision v1 冻结：
  - image/material identity；
  - dataset/source reference；
  - content SHA256；
  - storage source/type/object key；
  - AnnotationRepository state/scope/hash；
  - source annotation state / labels / box count；
  - Canonical Annotation Schema v1 external provenance（source format / source digest / source object identity / split / review state）；
  - locked label schema。
- `persist_dataset_revision()` 使用 revision id 作为不可变文件名；同 ID 内容不一致时 fail closed。
- Snapshot V3 同时记录：
  - `dataset_revision_schema_version=1`
  - `canonical_annotation_schema_version=1`
  - `dataset_revision_id`
  - 原有 `snapshot_id` / split / duplicate exclusion / negative-scope truth。
- Legacy V1/V2 portable snapshot 仍可确定性补算 revision，不修改历史 `snapshot_id`，保持兼容。
- Remote TRAINING portable contract 已升级：
  - 新 contract 必须携带合法 SHA256 `dataset_revision_id`；
  - Agent 下载 bundle 后同时校验 `snapshot_id` 与 `dataset_revision_id`；
  - revision 不一致直接 fail closed，不能训练错误数据版本。
- server-confirm / remote result / model artifact metadata / algorithm version metadata 全部保留同一个 `dataset_revision_id`。
- durable job overlay、缓存和 jobs API 不再丢 revision truth。
- Frontend Impact Review 已同批完成：
  - 训练运行中心明确显示“数据版本”和“训练快照”；
  - 展示值来自真实 durable job/snapshot truth，不做前端推算；
  - 页面局部刷新、暂停/恢复等不会把 revision 字段覆盖掉；
  - Real Chrome 已验证 revision / snapshot 在正式训练任务链可见。

最终验收 HEAD：`5e330fd3de9a958c2eac1ad1f18c11cf81b381b6`。

- Training Task Visibility push `35415738121`：visibility-contracts + Real Chrome success。
- 父代码 HEAD `5e2a0959a3a822f5725f684bd9351350b150a6b1`：Remote Training、Training Input Integrity、Node Agent Executor、Central Node Assignment、Task Runtime Truth、Portable Deployment、Remote Material Import、Remote Cleaning、Remote Conversion、RKNN Board Runtime 等共享回归 success。
- Dataset Revision / Snapshot focused unit、API、frontend identity/cache tests success。
- `VERSION.txt = 42.24.0` 未修改。

**下一软件主线：**

1. 基于 Dataset Revision + Snapshot V3 完成 **Training Lineage / Algorithm Version Provenance**：算法版本必须可反查 dataset revision、snapshot、base model、训练参数、节点、模型 artifact。
2. 在 lineage 稳定后进入 **自动评测 / 训练迭代闭环**：训练 → 测试集评测 → 标签级指标 → 不达标回炉/补数据，而不是先新造第二套训练系统。
3. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance 继续独立 OPEN。

# 最新关闭：Canonical Annotation Schema v1

2026-09-19，YOLO / COCO / Pascal VOC 已共享的外部标注 evidence 已正式收敛为 **Canonical Annotation Schema v1**，CLOSED。

关键约束与实现：

- 新增 `platform_core/annotation_schema.py`，统一拥有 schema version、source format/status 校验、source object identity、normalized bbox、class catalog digest、稳定 source digest。
- Parser owner 未变化：YOLO / COCO / VOC 仍只负责各自格式发现与解析；Canonical Schema 不重写 parser。
- `ImportCandidateStore.annotation_source_evidence()` 不再自行拼接/计算 schema，而统一调用 canonical builder。
- v1 保持旧 evidence **字段集合与 source_digest 计算语义兼容**；历史已同步 annotation 不会因本次抽象层升级被整体误判为 CHANGED。
- source object identity 仍冻结 key 对应的 size / ETag / SHA256；bbox 继续使用 normalized `cx/cy/w/h`。
- consumer-side fencing 已补齐：
  - 构建 annotation delta 前验证 canonical evidence；
  - apply 到 AnnotationRepository 前再次验证 schema / digest；
  - source_format 与当前 durable rescan request 必须一致；
  - evidence object_key 与 delta object_key 必须一致；
  - 被篡改、损坏或错格式 task artifact fail closed。
- Canonical schema 仍与平台 AnnotationRepository truth 分离；它描述的是外部来源 evidence，不成为第二个 annotation owner。
- Frontend Impact Review：**无需 UI 修改**。公共 task/API 字段、状态枚举、mapping/quality/confirmation 结构均未变化；Real Chrome 回归通过。

最终代码 HEAD：`e262819dd7c4eb7a245e43eefc91bc452a4060fc`。

验收：

- Remote Material Import push：Ubuntu / Windows / API / Real Chrome success。
- Canonical schema builder/validator 在 Ubuntu + Windows contract 中通过。
- source_digest legacy compatibility 对 YOLO / COCO / VOC 均通过。
- Consumer-side tamper / format mismatch fencing 通过。
- Node Agent Executor、Remote Cleaning、Remote Training、Remote Conversion、Central Assignment、Portable Deployment、RKNN Board Runtime 等共享回归全部 success。
- 当前代码 HEAD 共 16 个相关 workflow：16 success / 0 failure / 0 pending。
- `VERSION.txt = 42.24.0` 未修改。

**下一主线：**

1. 复用现有 `platform_core/snapshots.py` / Snapshot V3，扩展 Dataset Snapshot / Revision，而不是新建第二套 snapshot。
2. 下一版 snapshot 要把训练使用的 canonical annotation schema/source truth 与现有 content SHA / annotation_hash / split / label_schema 一起冻结。
3. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance 继续独立 OPEN。

# 最新关闭：Remote storage_rescan Phase 2C — Pascal VOC Annotation Delta

2026-09-19，现有 `MATERIAL_IMPORT + mode=storage_rescan` 已完成 **Pascal VOC XML 标注增量同步**，Phase 2C CLOSED。至此 Phase 2 的 YOLO / COCO / Pascal VOC 三种 annotation delta 均进入同一 durable owner、同一 review/confirm/repository truth。

已关闭范围：

- Local 与 Agent 都支持 `import_format=images|yolo|coco|voc`；preflight、API schema、前端下拉、确认策略使用同一后端 truth。
- VOC 继续复用现有 `DetectionDatasetScanner`，没有新增 VOC Parser owner、TaskKind 或 AnnotationRepository。
- Agent 通过 execution-fenced broker + short-lived GET 读取真实 XML/image bytes；不访问中央 SQLite/NFS，不接收长期对象存储凭据。
- portable review 冻结 XML source object identity：object key / size / ETag / SHA256，并保存 split、external class catalog、normalized boxes、quality issues 与 per-image `source_digest`。
- 图片与标注 delta 分开：
  - 图片：`NEW/MISSING/CHANGED/UNCHANGED/INVALID/SKIPPED`
  - 标注：`ANNOTATION_NEW/CHANGED/REMOVED/UNCHANGED/CONFLICT/INVALID`
- XML 删除、XML 内容变化但图片未变、类别/bbox/split 变化都会进入 annotation delta。
- 外部 source evidence 与平台 AnnotationRepository truth 分离；review→confirm 间发生人工修改时 stale-write fencing fail closed，要求重新扫描。
- 新增图片继续由既有 MATERIAL_IMPORT indexer 建正式 Material/Annotation truth；rescan 只补 external provenance。
- VOC ambiguity fail closed：同一图片被多个 Pascal VOC XML 文档引用时拒绝。
- 用户确认复用统一的 label mapping / create_labels / quality acceptance / removal policy / conflict policy，并保持“先冻结 durable intent → 再创建标签 → 再 resume task”。
- Frontend Impact Review 同批完成：
  - “重新扫描 / 恢复”新增“图片 + Pascal VOC 标注”；
  - YOLO data.yaml 仍只在 YOLO 模式启用；
  - VOC 图片增量、标注增量、quality、label mapping、删除/冲突策略全部来自真实后端 task；
  - Real Chrome 覆盖 Agent VOC request → review truth → mapping → confirmation body。

最终代码 HEAD：`5a1c18c8fc18c783a95d55f4f6a3ad826ffef69a`。

最终验收：

- Remote Material Import push `35412658236`：API / Ubuntu / Windows / Real Chrome success。
- Remote Material Import PR `35412660855`：API / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor push `35412658140` / PR `35412660966`：success。
- Central Node Assignment push `35412658117` / PR `35412660834`：success。
- Task Runtime Truth `35412660757`：success。
- Remote Training Runtime push `35412658157` / PR `35412660756`：success。
- Remote Conversion Runtime push `35412658182` / PR `35412660808`：success。
- Remote Cleaning Runtime push `35412658119` / PR `35412660762`：success。
- Portable Deployment push `35412658228` / PR `35412660767`：success。
- Remote RKNN Board Runtime Protocol push `35412658162` / PR `35412660872`：success。
- Storage Cache Governance `35412660802`：success。
- 当前代码 HEAD 共 28 个相关 workflow：28 success / 0 failure / 0 pending。
- `VERSION.txt = 42.24.0` 未修改。

**下一主线：**

1. Canonical Annotation Schema v1：把当前 YOLO/COCO/VOC 已共享 evidence 正式版本化成平台 contract，不重写 Parser。
2. Dataset Snapshot / Revision：冻结素材、标注版本、split 和对象 SHA，保证训练可复现。
3. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance 继续独立 OPEN。
4. TensorRT / Sophon / Ascend 继续暂缓。

# 最新关闭：Remote storage_rescan Phase 2B — COCO Annotation Delta

2026-09-19，现有 `MATERIAL_IMPORT + mode=storage_rescan` 在 Phase 2A YOLO 基础上完成 **COCO annotation JSON 增量同步**，Phase 2B CLOSED。没有新增 TaskKind、COCO Parser owner、AnnotationRepository 或第二套 rescan。

已关闭范围：

- 同一个“重新扫描 / 恢复”入口现在使用一套真实格式 truth：
  - 仅图片；
  - 图片 + YOLO 标注；
  - 图片 + COCO 标注；
  - 执行位置仍为中央 Worker / 远程 Agent。
- API `StorageRescanCreateReq`、Agent preflight、durable request、前端格式选项和 worker 能力声明统一支持 `images|yolo|coco`；`dataset_yaml` 仍严格只属于 YOLO。
- COCO 复用既有 `DetectionDatasetScanner`，不新写 parser。Local 与 Agent 都把证据落进同一个 task-owned `ImportCandidateStore`。
- Agent 继续只通过 execution-fenced broker / short-lived GET 读取 OSS/S3/MinIO；不访问中央 SQLite/NFS，也不接收长期对象存储凭据。
- COCO annotation source 会读取真实 JSON bytes，并冻结：
  - annotation JSON object key；
  - size / ETag / SHA256；
  - split；
  - external category id/name catalog；
  - normalized bbox / annotation status / issues；
  - per-image external `source_digest`。
- rescan 会保留**完整源图片 inventory**，包括没有被 COCO JSON 引用的图片，因此不会因为 annotation JSON 未引用某张图片就误判该图片 MISSING。
- 图片对象继续统一分类 `NEW/MISSING/CHANGED/UNCHANGED/INVALID/SKIPPED`；COCO 标注继续复用 Phase 2A 的 `ANNOTATION_NEW/CHANGED/REMOVED/UNCHANGED/CONFLICT/INVALID`。
- 平台人工 AnnotationRepository truth 与外部 COCO source evidence 分离：
  - JSON 变化不会直接覆盖人工标注；
  - JSON 删除某图标注进入 REMOVED/CONFLICT，由用户策略决定 clear/keep；
  - review 后平台标注又发生人工修改时，stale-write fencing fail closed，要求重新扫描。
- 新增图片仍只由既有 MATERIAL_IMPORT indexer 建正式 Material/Annotation truth；rescan 后续只补 `external_annotation` provenance / synced hash，不重复写第二套正式标注。
- COCO source ambiguity 永久 fail closed：
  - 同一 category id 映射不同名称 → 拒绝；
  - 同一图片跨多个 split → 拒绝；
  - 同一图片被多个 COCO annotation document 引用 → 拒绝；
  - 同一 COCO metadata 内重复引用同一 object key → 拒绝。
- COCO rescan 使用 `deduplicate_images=False`，保持 object-key identity；不同 key 即使内容 hash 相同，也不会因为普通素材去重语义被吞掉。
- 用户确认继续复用同一套 label mapping / create_labels / quality acceptance / removal policy / conflict policy，并保持“先冻结 durable intent → 再创建标签 → 再 resume task”的顺序。
- Frontend Impact Review 同批完成：
  - 前端新增“图片 + COCO 标注”；
  - YOLO data.yaml 输入只在 YOLO 模式启用；
  - 图片增量、标注增量、quality、external class mapping、删除/冲突策略都来自真实后端 task；
  - Real Chrome 覆盖 Agent COCO request → review truth → mapping → confirmation body。

最终代码 HEAD：`ac1470c9049f7151fb6ae78daf6d21802ea6a263`。

最终验收：

- Remote Material Import push `35411646993`：API / Ubuntu / Windows / Real Chrome success。
- Remote Material Import PR `35411650317`：success。
- Node Agent Executor `35411650294`：success。
- Central Node Assignment `35411650355`：success。
- Task Runtime Truth `35411650324`：success。
- Remote Training Runtime `35411650292`：success。
- Remote Conversion Runtime `35411650281`：success。
- Remote Cleaning Runtime `35411650314`：API / Ubuntu / Windows / Real Chrome success。
- Portable Deployment `35411650458`：success。
- Remote RKNN Board Runtime Protocol `35411650309`：API / Ubuntu / Windows / Real Chrome success。
- Storage Cache Governance `35411650330`：success。
- Training Input Integrity `35411650297`：success。
- 当前代码 HEAD 共 16 个相关 workflow：16 success / 0 failure / 0 pending。
- `VERSION.txt = 42.24.0` 未修改。

**仍然 OPEN：**

1. `storage_rescan Phase 2C`：Pascal VOC XML annotation delta。
2. Canonical Annotation Schema versioning：正式版本化当前 YOLO/COCO/VOC 已共享的 evidence schema，不重写既有 Parser。
3. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance。
4. TensorRT / Sophon / Ascend 继续暂缓。

# 最新关闭：Remote storage_rescan Phase 2A — YOLO Annotation Delta

2026-09-19，现有 `MATERIAL_IMPORT + mode=storage_rescan` 在 Phase 1 图片对象增量基础上完成 **YOLO 标注增量同步**，Phase 2A CLOSED。没有新增 TaskKind、Parser owner 或第二套 AnnotationRepository。

已关闭范围：

- 同一个“重新扫描 / 恢复”入口支持：
  - 扫描内容：仅图片 / 图片 + YOLO 标注；
  - 执行位置：中央 Worker / 远程 Agent；
  - YOLO 可显式选择 `data.yaml`，也可按现有规则自动发现。
- Local 与 Agent 使用同一请求 truth：`execution_mode + import_format + dataset_yaml`；Agent preflight 只暴露后端真实支持格式。
- Agent 继续复用现有 broker / short-lived GET / execution lease / generation fencing / server-confirm；不访问中央 SQLite/NFS，不接收长期对象存储凭据。
- YOLO review 不只保存归一化 bbox，还冻结外部来源身份：
  - label `.txt` object key / size / ETag / SHA256；
  - `data.yaml` object key / size / ETag / SHA256；
  - split；
  - external class catalog digest；
  - normalized boxes / quality issues；
  - per-image `source_digest`。
- 因此可识别“图片没变，但 label sidecar / data.yaml / split / class / bbox 变化”的真实 annotation delta。
- 统一分类：
  - `ANNOTATION_NEW`
  - `ANNOTATION_CHANGED`
  - `ANNOTATION_REMOVED`
  - `ANNOTATION_UNCHANGED`
  - `ANNOTATION_CONFLICT`
  - `ANNOTATION_INVALID`
- 平台人工标注 truth 与外部 YOLO source evidence 分离；历史素材没有可信 external baseline 时不会假装“已同步”，而按冲突/新增规则进入用户确认。
- 用户确认策略与后端完全一致：
  - 已有图片：是否同步新增/变化标注；
  - 外部标注删除：清空 / 保留；
  - 人工修改冲突：覆盖 / 保留；
  - external class → 平台标签 mapping/create_labels；
  - quality report acceptance。
- 新增图片仍走既有 MATERIAL_IMPORT indexing owner，并按冻结映射导入对应 YOLO 标注；UI 已明确写明这一语义。
- 新增图片完成 indexing 后会补正式 `external_annotation` provenance 和 `synced_annotation_hash`，不会被误标为“待复核”。
- 已有图片写入前增加 stale-annotation fencing：review 后如果平台标注又被人工修改，确认阶段 fail closed，要求重新扫描，不能覆盖用户的新修改。
- 新平台标签创建顺序已修正为：**先冻结 durable rescan intent → 再幂等创建标签 → 再 resume task**，避免确认冲突失败却提前产生标签副作用。
- Frontend Impact Review 同批完成：
  - 图片增量与标注增量分别展示；
  - 标注映射、质量、删除策略、冲突策略全部来自后端 task truth；
  - 修复 YOLO review 渲染的 `key is not defined`；
  - Phase 1 文案与 Phase 2A 正式 UI 文案统一；
  - Real Chrome 覆盖 Agent YOLO 请求、review 计数、mapping、冲突策略和确认 body。

最终代码 HEAD：`6505c51e1916a8aab5d506387b51d01e413b7775`。

最终验收：

- Remote Material Import push `35410155924`：API / Ubuntu / Windows / Real Chrome success。
- Remote Material Import PR `35410158432`：API / Ubuntu / Windows / Real Chrome success。
- 父层 UI/确认顺序回归：
  - `9e8ada…` push Remote Material Import `35409879583` 全绿。
  - `c6ee2ab…` push/PR Remote Material Import 全绿。
- `VERSION.txt = 42.24.0` 未修改。

**仍然 OPEN：**

1. `storage_rescan Phase 2B`：COCO annotation JSON delta。
2. `storage_rescan Phase 2C`：Pascal VOC XML delta。
3. Canonical Annotation Schema versioning：把当前 YOLO/COCO/VOC 已共享的 evidence 正式版本化，不重写 Parser。
4. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance。

# 最新关闭：Remote MATERIAL_IMPORT Phase 2

2026-09-18，第四个真实跨机器 task kind 的第二阶段已 CLOSED。

已完成范围：

```text
MATERIAL_IMPORT
server_zip + execution_mode=agent
import_format=images | yolo
```

Phase 2 新增真实能力：

- Agent 复用 `YoloImportScanner` 解析 `data.yaml / images / labels`。
- review ZIP 新增 `yolo/annotations.jsonl`，包含 split、label sidecar、annotation status、normalized boxes、issues。
- 控制面在进入待确认前重新校验 classes / dataset_yaml / boxes / normalized 坐标 / candidate 覆盖完整性。
- task-owned ImportCandidateStore 保存 external classes 和 annotation evidence。
- 用户确认时冻结 `label_mapping/create_labels/quality acceptance`。
- local indexer 发布选中图片后，将 YOLO normalized boxes 转为像素坐标并写 AnnotationRepository。
- `confirmed_empty` 作为正式负样本写入；invalid/missing sidecar 不会擦除已有标注。
- Agent YOLO API 已作为支持能力，不再被旧测试当成 unimplemented。
- 永久 CI 增加源码 guard 和 Agent YOLO→label mapping→AnnotationRepository 端到端 integration。

最终验收：

- Remote Material Import `35311171823`：API / Ubuntu / Windows 全绿。
- 临时 draft PR #17 已关闭，未 merge。
- `VERSION.txt = 42.24.0` 未修改。

Phase 1 的 `import_format=images` 闭环和其验收 `35308672897` 继续有效，不重做。

# 最新关闭：Remote MATERIAL_IMPORT Phase 3 — staging object lifecycle / GC

2026-09-18 已完成 remote input/review staging object 治理：

- server-confirm 后写 durable cleanup ledger，等外层 result state durable 后再删除。
- AWAITING_CONFIRMATION 的 staging 对象由 storage Worker heartbeat hook 精确回收。
- FAILED/CANCELLED/BLOCKED 默认保留 7 天后再 GC。
- orphan generation 从 `remote-results/N/upload.json` 恢复 exact object ref。
- 删除前重新验证 task-owned prefix + storage source + size + SHA256。
- mismatch = CONFLICT，不删除；provider 故障 = PENDING，可重试。
- 不做 prefix list/delete；不触碰正式 MaterialRepository 目标对象。
- GC 使用现有 WorkerInstance renew hook，5 分钟节流、分页 cursor，无第二套 timer/scheduler。

验收：

- Remote Material Import `35312109805`：API / Ubuntu / Windows 全绿。
- Task Runtime Truth `35312109707`：Ubuntu / Windows 全绿。
- Storage Cache Governance `35312109834`：全绿。
- `VERSION.txt=42.24.0` 未修改。

# 最新关闭：Remote MATERIAL_IMPORT Phase 4 — Agent storage_scan

2026-09-18，`MATERIAL_IMPORT + mode=storage_scan + execution_mode=agent` 已完成真实跨机器闭环并 CLOSED。

当前真实能力：

- 前端“对象存储目录”只展示已启用 OSS / S3 / MinIO 存储源，真实提交 `storage_scan + execution_mode=agent + prefix + recursive + import_format/dataset_yaml`。
- 前端、专用任务 API、统一 PollRegistry 共享同一 task status / phase / execution_mode truth；刷新恢复仍保留 Agent 身份。
- canonical task status 优先于 stale stage；`AWAITING_CONFIRMATION` 不再错误显示“正在检查素材内容”。
- 控制面继续持有长期对象存储凭据；Agent **不接收 accessKey/accessSecret，也不访问中央 SQLite/NFS**。
- Agent 通过 execution lease fenced broker 分页获取 prefix 对象列表，并按需获取短期 GET contract。
- broker 和 Agent 双重约束 durable prefix；prefix 外对象、重复 cursor、超过 250000 个对象均 fail closed。
- Agent 每次读取对象都会重新校验 Content-Length / ETag，并在可用时校验 SHA256；YOLO 继续复用 `YoloImportScanner`。
- storage_scan review ZIP 为 metadata / annotation evidence only，不重新打包原始图片，避免大规模素材被“下载后再整包上传”。
- server-confirm 后控制面重新校验 review truth；用户确认后 local indexer 对原对象再次 `exists/stat`，校验 size / ETag / SHA256 后直接建立 MaterialRepository / AnnotationRepository truth，不复制原对象。
- Phase 3 GC 仍只删除 task-owned staging input/review exact refs，不会触碰 storage_scan 的正式源素材对象。
- classic `static/app.js` 新增永久 `node --check`；本轮发现并修复两条 dangling `=async function` 生产语法错误。
- Remote Material Import 专项已覆盖 API、Ubuntu、Windows、前端 Node contract 与 Real Chrome 真实页面流。

最终验收（代码 HEAD `639cded30a6a2fed67275f19450cb70b4e0a9128`）：

- Remote Material Import `35316129031`：API / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35316128986`：全绿。
- Central Node Assignment `35316128928`：全绿。
- Portable Deployment `35316129051`：全绿。
- Remote Training Runtime `35316128920`：全绿。
- Remote Conversion Runtime `35316129033`：全绿。
- Task Runtime Truth `35316128916`：全绿。
- `VERSION.txt = 42.24.0` 未修改。

# 最新关闭：Remote MATERIAL_IMPORT Phase 6 — COCO / Pascal VOC Agent server_zip

2026-09-18，COCO / Pascal VOC 的 **Agent server_zip** portable import 已完成真实闭环并 CLOSED。Phase 5 的 storage_scan annotation truth 继续复用，本批没有创建第二套 COCO/VOC 导入链。

真实闭环：

- `server_zip + execution_mode=agent + import_format=coco|voc` 与 images / YOLO 共用同一个 `MATERIAL_IMPORT` durable task、assignment / execution lease 和 object-storage-v1 transport。
- 控制面只接受安全相对 ZIP 路径；Agent ZIP 目标必须是已启用 OSS / S3 / MinIO，不允许把中央本地目录/NFS 当成远程共享盘。
- 中央端把原 ZIP 以 size/SHA256 证据暂存为 task-owned input object；Agent 只拿短期 GET，不获得长期对象存储凭据。
- Agent 继续使用既有安全 ZIP extraction，随后复用 `DetectionDatasetScanner` 解析 COCO / Pascal VOC。
- detection ZIP review 与 storage_scan 使用同一 candidate / normalized box / split / issue / external-class schema；ZIP 模式仅额外把用户确认后需要入库的 IMPORTABLE 图片作为 `files/...` payload 嵌入 task-owned review。
- review 上传继续走 generation-scoped immutable PUT；server-confirm 重新核对 review ZIP、候选图片 size/SHA256/尺寸、embedded payload、annotation coverage、class/box/issue 约束。
- 用户仍必须确认外部类别 → 平台标签映射；确认后 local Storage Worker 把已验证 payload 写入正式对象存储，并写现有 MaterialRepository / AnnotationRepository truth。
- `dataset_yaml` 仍只属于 YOLO；COCO/VOC ZIP 提交 dataset_yaml 会 fail closed。
- 产品“服务器 ZIP”新增执行位置：**中央 Worker / 远程 Agent**。中央 Worker 保持旧本地导入行为且不开放 COCO/VOC；切到远程 Agent 后目标存储改为 OSS/S3/MinIO，并开放 COCO/VOC。
- Agent ZIP 不允许 `import_format=auto`，用户必须明确选择 images / YOLO / COCO / VOC。
- Real Chrome 已覆盖：服务器 ZIP 默认中央 Worker → COCO 禁用 → 切换远程 Agent → 对象存储目标 → 选择 COCO → 提交真实 `execution_mode=agent` request → 等待确认。

最终验收（代码 HEAD `3f5c34ae587aee04971e8e5160073898f288cba4`）：

- Remote Material Import `35357183468`：API / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35357183397`：全绿。
- Central Node Assignment `35357183504`：全绿。
- Task Runtime Truth `35357183682`：全绿。
- Portable Deployment `35357183477`：全绿。
- Remote Training Runtime `35357183476`：全绿。
- Remote Conversion Runtime `35357183564`：全绿。
- Remote Cleaning Runtime `35357183532`：全绿。
- Remote RKNN Board Runtime Protocol `35357183788`：API / Ubuntu / Windows / Real Chrome 全绿。
- `VERSION.txt = 42.24.0` 未修改。

# 最新关闭：Remote MATERIAL_IMPORT Phase 5 — COCO / Pascal VOC

2026-09-18，COCO / Pascal VOC 已接入真实远程 `MATERIAL_IMPORT + storage_scan + Agent` 闭环并 CLOSED。

Phase 5 当时 CLOSED 的范围为 **对象存储目录的 Agent storage_scan**；Agent server_zip 已在上方 Phase 6 正式 CLOSED。

真实闭环：

- 新增项目数据库无关的 bounded `DetectionDatasetScanner`，只读取 brokered StorageProvider，写 task-owned ImportCandidateStore evidence，不在 Agent 侧创建平台标签、Material 或 Annotation。
- COCO 支持 categories / images / annotations、多 annotation JSON 与 train/val/test split 识别；外部 category id 原样保留到确认阶段。
- Pascal VOC 支持 XML object/bndbox、split 识别与稳定外部 class id；含 DOCTYPE / ENTITY 的 XML fail closed。
- 格式层使用真实图片尺寸归一化检测框；越界框可裁剪并记录 warning，无效框进入质量问题，不直接污染正式标注。
- 永久边界包含：最多 250000 个对象、5000000 个标注框、COCO JSON 单文件 64 MiB、VOC XML 单文件 2 MiB。
- Agent review ZIP 仍是 metadata / annotation evidence only，不重新打包对象存储中的原始图片。
- 控制面 server-confirm 后重新验证 candidate / class / box / split / issue evidence，生成 external class mapping suggestions。
- 用户必须确认外部类别 → 平台标签映射；确认后 local Storage Worker 再次 stat 原对象并验证 size / ETag / SHA256，再写正式 MaterialRepository / AnnotationRepository。
- 正式索引阶段沿用统一 annotation truth：normalized evidence 转回实际像素坐标；COCO/VOC 不走旧 `ensure_label + add_image_record` 直写逻辑。
- 前端“对象存储目录”已正式开放 **COCO 检测标注 / Pascal VOC 检测标注**；Phase 6 又开放了远程 Agent 的服务器 ZIP。中央 Worker 本地目录/本地 ZIP仍不开放 COCO/VOC；dataset YAML 仍只属于 YOLO。
- Real Chrome 已验证页面真实选择 COCO 并提交 `storage_scan + execution_mode=agent + import_format=coco`。

最终验收（代码 HEAD `9fb67096718e5ece1b72a2acf601662fe337e1d7`）：

- Remote Material Import `35318574008`：API / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35318574014`：全绿。
- Central Node Assignment `35318574002`：全绿。
- Task Runtime Truth `35318573876`：全绿。
- Portable Deployment `35318573871`：全绿。
- Remote Training Runtime `35318573869`：全绿。
- Remote Conversion Runtime `35318573929`：全绿。
- Storage Cache Governance `35318573935`：全绿。
- `VERSION.txt = 42.24.0` 未修改。

# 最新关闭：Remote MATERIAL_BATCH/CLEAN Phase 1 — Agent 清洗 / 去重

2026-09-18，远程清洗已按现有唯一 owner `TaskKind.MATERIAL_BATCH + operation=CLEAN` 完成真实 Agent 闭环并 CLOSED；**没有新增或恢复并行 `TaskKind.CLEANING` handler**。

真实闭环：

- 本地清洗默认行为保持不变；只有用户显式选择 `execution_mode=agent` 才进入远程节点链路。
- 后端 preflight 以真实 selection 校验素材与节点，不让前端自行猜测：所选素材必须有 `object_key + size + SHA256`，存储源必须是已启用 OSS / S3 / MinIO，且至少存在 online + agent + effective `cleaning` capability 节点。
- preflight 不可用时，Agent 选项在 UI 中禁用；绕过 UI 直接请求 Agent 也会 fail closed，并保证不会残留 durable task。
- prepare / publish / retry 全部从持久化 request 恢复执行方式；Agent CLEAN 使用 `agent.remote` capability，中央 Materials Worker 无法静默抢走远程任务。
- 控制面通过 execution-lease-fenced broker 分页暴露**冻结 selection 中的精确 material refs**；不是 prefix 扫描，未选中 image_id 无法读取。
- Agent 不读取中央 SQLite/NFS、不拿长期对象存储凭据；逐图取得短期 GET contract，并校验 size / SHA256 后进行本地分析。
- Agent 复用 `CleaningAnalysisRuntime` 做真实图片解码、尺寸、dHash、模糊度、亮度、熵等分析，只产出 task-owned metrics review evidence。
- 重复图 / 近重复图 / 阈值规则仍由控制面使用现有 `metric_issues + DurableHashIndex` 重新评估，Agent 不能自行决定正式删除结果。
- Agent review 经 immutable object upload + size/SHA256 server-confirm 后，控制面才把结果提交回现有 `selection.sqlite3 / clean_results` 与 MaterialRepository clean projection；没有第二套清洗结果库。
- durable `SUCCEEDED` 且尚未用户确认时，v47 兼容投影继续显示“待确认”；用户仍通过原有“建议删除 / 保留 → 确认应用清洗”流程完成最终变更。
- 产品弹窗新增“执行位置”：默认 **中央 Worker**；满足后端 preflight 时才允许选择 **远程清洗节点**。任务列表标识实际执行方式，远程阶段均映射为中文真实进度。
- 永久专项覆盖 Agent runtime、portable transport、assignment、API fail-closed、前端 Node contract 与 Real Chrome 执行位置选择。

最终验收（代码 HEAD `b41f784a3765e09a2184453e03e895a1cda0271d`）：

- Remote Cleaning Runtime `35324894972`：API / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35324894991`：API / Ubuntu / Windows 全绿。
- Central Node Assignment `35324894963`：全绿。
- Task Runtime Truth `35324895005`：全绿。
- Portable Deployment `35324894993`：全绿。
- Remote Material Import `35324894988`：全绿。
- Remote Conversion Runtime `35324894962`：全绿。
- Remote Training Runtime `35324895079`：API / Ubuntu / Windows 全绿。
- `VERSION.txt = 42.24.0` 未修改。

2026-09-18 probe hardening（代码 HEAD `b20470c8f57ee99fcde3ff0da5f26a5be4b7124f`）：

- RKNN-Toolkit2 capability 从“版本阈值推断”收紧为真实 `RKNN.config(target_platform=...)` 探测。
- Remote Conversion Runtime `35344315905`：control-plane / Ubuntu / Windows / Real Chrome 全绿。
- Remote RKNN Board Runtime Protocol `35344315931`：API / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35344315955`、Central Node Assignment `35344316219`：全绿。
- Task Runtime Truth `35344315903`、Portable Deployment `35344315907`：全绿。
- Remote Training `35344315916`、Remote Material Import `35344315983`、Remote Cleaning `35344315908`：全绿。

# 最新关闭：Remote storage_rescan Phase 1 — 图片对象增量同步

2026-09-19，现有 `MATERIAL_IMPORT + mode=storage_rescan` owner 已扩展为真实 Remote Agent portable flow，**Phase 1（图片对象增量同步）CLOSED**。没有新增 TaskKind，也没有复制 storage_scan / import owner。

当前 CLOSED 边界：

- 前端“重新扫描 / 恢复”支持 **中央 Worker / 远程 Agent** 执行位置；远程选项只来自后端 preflight 的真实在线 effective `material-import` 节点。
- Agent rescan 使用显式 `intent=storage_rescan`。只有这个 intent 才允许扫描对象存储根范围；普通 `storage_scan` 仍要求显式 prefix，不能借 rescan 放宽目录边界。
- 控制面在 durable task 创建前冻结当前 MaterialRepository 的 source baseline 到 task-owned artifact；Agent 不访问中央 SQLite/NFS。
- 长期 OSS/S3/MinIO 凭据仍只在控制面。Agent 通过 execution-lease-fenced broker 分页列举对象，并按需拿短期 GET contract 做真实图片 decode / size / SHA256 / ETag 核验。
- rescan 是“对象身份核对”而不是素材去重：两个不同 object key 即使内容 SHA256 相同，也必须作为两个独立对象进入增量比较，不能被普通导入 dedup 逻辑吞掉。
- Agent review 经 immutable upload + size/SHA256 + server-confirm 后，中央端把当前清单与冻结 baseline 分类为：
  - `NEW`
  - `MISSING`
  - `CHANGED`
  - `UNCHANGED`
  - 以及 `INVALID / SKIPPED` 质量证据。
- `CHANGED` 同时比较 content SHA256、size 和 ETag；仅 ETag 变化也不会被误报为 UNCHANGED。
- 用户仍必须确认恢复策略：新增建索引、缺失标记 unavailable、变化更新；不会自动删除源对象或素材记录。
- 用户确认后 durable task 释放回现有中央 `storage.rescan` Worker owner 做正式 Repository commit；Agent 不直接写 MaterialRepository / AnnotationRepository。
- 对 Agent review 的二次防变更检查只做对象 `stat` identity（size + ETag + 可用 SHA 元数据），**不会在中央端重新下载整批图片再 decode/hash**；图片重 I/O 留在 Agent。
- 变化素材保留原有标注 truth，并设置需要复核；缺失素材只标记源不可用。
- UI 使用真实 task status / worker / resource_wait_reason / counts，刷新后继续恢复同一 durable task；Real Chrome 已覆盖 Remote Agent preflight → 创建 → review → 待确认链路。

Phase 1 最终代码 HEAD：`64dc87c6e295429f79adfc813093bff33ce61587`。

最终验收：

- Remote Material Import `35408027919`：API / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor `35408027776`：API / Ubuntu / Windows success。
- Central Node Assignment `35408027804`：success。
- Task Runtime Truth `35408027769`：success。
- Portable Deployment `35408027802`：success。
- Remote Training Runtime `35408027815`：success。
- Remote Conversion Runtime `35408027785`：success。
- Remote Cleaning Runtime `35408027775`：API / Ubuntu / Windows / Real Chrome success。
- Remote RKNN Board Runtime Protocol `35408027782`：API / Ubuntu / Windows / Real Chrome success。
- Storage Cache Governance `35408027828`：success。
- `VERSION.txt = 42.24.0` 未修改。

**仍然 OPEN：**

1. `storage_rescan Phase 2`：YOLO `.txt / data.yaml`、COCO annotation JSON、Pascal VOC XML 的新增/删除/替换和增量 AnnotationRepository 更新。
2. Canonical Annotation Schema：把现有 YOLO / COCO / VOC review evidence 正式版本化，而不是重写已有 Parser。
3. Rockchip 真实 RK3568 / RK3576 物理板卡 acceptance 仍未发生；软件 CI 不能替代现场 NPU 验收。

# 最新关闭：Remote MODEL_CONVERSION Phase 2 — Rockchip RKNN

2026-09-18，远程 Rockchip RKNN 转换已完成真实 Agent 闭环并 CLOSED。

当前 CLOSED 范围：

- 远程目标为 `target=rockchip`，当前 portable Agent 正式支持 **RK3568 / RK3576**。
- 早先 handoff 中的“RK3578”已纠正：Rockchip 官方 RKNN-Toolkit2 当前支持平台列出 RK3576 Series，而不是 RK3578。若现场设备铭牌/采购型号确实写 RK3578，必须先读取真实 SoC compatible / 芯片信息再映射，平台不得直接把 RK3578 当 RK3576。
- 当前远程 RKNN 只关闭 **FP16、batch=1、静态输入**；INT8 calibration transport 尚未关闭，不允许假装支持。

真实闭环：

- 服务节点新增细粒度 `conversion.rknn` capability；通用 `conversion` 继续服务已 CLOSED 的 ONNX，二者不能互相冒充。
- Node Agent 只有在真实 Python 环境可导入 `rknn.api.RKNN`，并且至少一个目标芯片通过真实 `RKNN.config(target_platform=...)` 探测后才上报 `conversion.rknn`。
- heartbeat runtime 持久化 `rknn_toolkit2.available/version/supported_chips`；控制面只把 online + agent + effective `conversion.rknn` + probe 可用的节点作为 Rockchip 资源。
- Toolkit capability 不再按版本号猜测：Node Agent 会在节点本机真实调用 `RKNN.config(target_platform='rk3568'/'rk3576')`，只有实际 config probe 成功的芯片才进入 `supported_chips`；`conversion.rknn` 至少有一个支持目标时才可上报。
- MODEL_CONVERSION 调度按目标细分 capability：Agent ONNX → `conversion`，Agent Rockchip → `conversion.rknn`。
- portable contract 只接受 RK3568 / RK3576、FP16、batch=1、静态 shape，并保留 mean / rknn_std 等 RKNN 参数；不支持的芯片/INT8/dynamic/batch>1 在任务持久化前 fail closed。
- Agent 下载 verified model object 后在节点本地执行现有 `deployment_worker.py` + RKNN-Toolkit2，生成唯一非空 `.rknn`。
- RKNN 成功状态必须是 `converted_unverified`；Agent 不得把“成功转换”伪装成“板端硬件已验证”。
- 输出重新计算 size/SHA256，经 generation-scoped immutable PUT、server-confirm 后，控制面重新下载并复核，再写回既有：
  - `deploy/jobs/<task>/artifacts/model_<chip>.rknn`
  - `manifest.json`
  - `job.json`
- RKNN job 明确写 `runtime_verified=false`、`hardware_verified=false`、`validation_status=converted_unverified`，产品提示“等待目标板 Runtime 实机验证”。
- 前端部署转换已补齐 RK3576 选项，并只根据后端 resource truth 暴露可用 RKNN Agent，不在无真实 RKNN 节点时假装可用。
- Real Chrome 已覆盖 RKNN Agent 资源配置/展示与 Rockchip 芯片选项。

最终验收（代码 HEAD `5a02aa5ba03e94cc731bfd0e62437c57738efab1`）：

- Remote Conversion Runtime `35330889750`：control-plane / Ubuntu Agent / Windows Agent / Real Chrome 全绿。
- Node Agent Executor `35330889657`：全绿。
- Central Node Assignment `35330889375`：全绿。
- Task Runtime Truth `35330889784`：全绿。
- Portable Deployment `35330889497`：全绿。
- Remote Material Import `35330889535`：全绿。
- Remote Training Runtime `35330889384`：全绿。
- Remote Cleaning Runtime `35330889291`：全绿。
- `VERSION.txt = 42.24.0` 未修改。

# 最新关闭：Rockchip 板端 Runtime 验证协议 / 产品闭环

2026-09-18，Rockchip RKNN 板端 Runtime 验证的软件协议、Agent runner、控制面提交和产品入口已完成闭环并 CLOSED。

当前真实能力：

- 服务节点新增独立 `deployment-test.rknn` capability，不从普通 `deployment-test` 或 `conversion.rknn` 推断板卡 Runtime 可用。
- Node Agent 仅在 Linux arm64/aarch64 上读取 `/proc/device-tree/compatible`，真实识别 RK3568/RK3566 family 或 RK3576，并且当前 Python 可导入 `rknnlite.api.RKNNLite` 后才上报该 capability。
- heartbeat runtime 持久化 `rknn_board.available/chip/architecture/compatible/rknn_lite_version`；控制面只允许芯片完全匹配的 online Agent 接受板端任务。
- 板端验证复用既有 `DEPLOYMENT_TEST` durable truth；任务仍受 assignment lease / execution lease / generation fencing 约束，Agent 不访问中央 SQLite/NFS。
- 控制面在创建任务前重新校验原 RKNN conversion manifest 与 `.rknn` 文件 size/SHA256，随后把模型和测试图以 portable object contract 送到匹配板端节点。
- 节点真实执行 `predict_rknn_lite_runner.py`：
  - `RKNNLite.load_rknn`
  - `RKNNLite.init_runtime`
  - 图片预处理
  - 至少一次 `RKNNLite.inference`
  - 回传 `inference_ms / output_count / output_shapes`
- Agent runner 明确只做 **hardware runtime verification**，不把“能跑一次”冒充为检测准确率验收，也不解析模型特定 YOLO 输出。
- result 继续走本地 hash → immutable upload → server-confirm；控制面在最终提交前再次确认 conversion job/chip/model SHA256 未变化。
- 只有 runtime evidence 满足 `engine=rknn-lite2 + runtime_format=rknn + chip match + output_count>0` 后，原 conversion `manifest.json/job.json` 才允许写：
  - `runtime_verified=true`
  - `hardware_verified=true`
  - `validation_status=hardware_verified`
- 部署中心对 `rockchip + converted_unverified` 任务展示“板端验证”；用户上传测试图后轮询真实 durable task，成功后刷新为“实机已验证”，并展示芯片、推理耗时和输出数量；已验证任务不重复显示验证按钮。
- Real Chrome 已覆盖：未验证 RKNN 任务 → 板端验证入口 → 上传图片 → durable task success → UI 刷新 `hardware_verified` 状态。

软件闭环最终验收（代码 HEAD `05c7b93339414ac028214fd3d046dfdf7977c0a1`）：

- Remote RKNN Board Runtime Protocol `35335720990`：API / Ubuntu / Windows / Real Chrome 全绿。
- Remote Conversion Runtime `35335720906`：control-plane / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35335720915`：全绿。
- Central Node Assignment `35335720909`：全绿。
- Task Runtime Truth `35335720969`：全绿。
- Portable Deployment `35335720910`：全绿。
- Remote Material Import `35335720921`：全绿。
- Remote Training Runtime `35335720913`：全绿。
- Remote Cleaning Runtime `35335721027`：全绿。
- `VERSION.txt = 42.24.0` 未修改。

**重要边界：以上是软件协议/产品闭环验收，不等于你们手上的真实 RK3568 / RK3576 设备已经完成硬件验收。** CI 没有真实 Rockchip NPU 板卡；实际设备接入 Agent 后仍需至少执行一次真实板端任务，才能对该具体模型写入 `hardware_verified=true`。

# 最新关闭：Rockchip RKNN INT8 calibration portable transport

2026-09-18，Remote RKNN INT8 calibration 已完成真实 portable Agent 闭环并 CLOSED。

当前真实能力：

- Rockchip Agent 资源通过后端 `supported_precisions` 暴露真实可用精度；当前远程 RKNN 正式支持 **FP16 / INT8**，不再由前端自行猜测。
- 用户选择 INT8 时必须明确校准数据集、split 与图片数量；创建任务前控制面冻结 calibration snapshot。
- snapshot 持久化：
  - dataset_id / split
  - MaterialRepository revision
  - 精确 image_id / storage_source_id / object_key
  - size_bytes / SHA256 / ETag
  - requested_count / item_count
- calibration image 必须来自可 portable 的 OSS / S3 / MinIO；本地路径、缺 SHA256/size、对象内容变化都会在 durable task 创建前 fail closed。
- Agent start payload 不包含控制面本地目录、SQLite/NFS 或长期对象存储凭据；每张校准图只获得短期 GET contract。
- Agent 逐张下载并校验 size / SHA256，写入本次 generation workdir 的 calibration 目录。
- Agent 再校验 `calibration_snapshot + calibration_count + 实际文件数` 一致后，才允许启动 node-local `deployment_worker.py`。
- `deployment_worker.py` 从冻结图片生成 `rknn_dataset.txt`，真实执行 RKNN-Toolkit2 INT8 build；没有真实校准图片时拒绝转换。
- INT8 输出仍走既有 generation-scoped immutable upload → size/SHA256 → server-confirm → deployment job commit，不产生第二套 RKNN 产物 truth。
- INT8 与 FP16 的转换结果都保持 `converted_unverified / hardware_verified=false`；必须经过已 CLOSED 的匹配 Rockchip 板端 RKNNLite 任务后才能升级为 `hardware_verified=true`。
- 部署中心已正式开放 RKNN Agent INT8：仅资源 truth 包含 `int8` 时可选；UI 展示校准数据集、分组、数量，并真实提交到后端。
- Real Chrome 已覆盖：选择 Rockchip Agent → INT8 → 校准数据集/split/count → 创建 durable conversion task。

最终验收（代码 HEAD `314757c1601420640acedc074e9aeb795e8a2097`）：

- Remote Conversion Runtime `35340943761`：control-plane / Ubuntu / Windows / Real Chrome 全绿。
- Remote RKNN Board Runtime Protocol `35340943851`：API / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35340943850`：全绿。
- Central Node Assignment `35340943861`：全绿。
- Task Runtime Truth `35340943758`：全绿。
- Portable Deployment `35340943913`：全绿。
- Remote Material Import `35340943781`：全绿。
- Remote Training Runtime `35340943764`：全绿。
- Remote Cleaning Runtime `35340943815`：全绿。
- `VERSION.txt = 42.24.0` 未修改。

# 最新关闭：Rockchip 实机接入软件工具链

2026-09-18，Rockchip 板端 Node Agent 的安装、严格预检和服务节点产品入口已完成软件闭环并 CLOSED。

当前真实能力：

- `node_agent.py` 新增严格 `--doctor`：请求的任一 capability 无法真实上报时返回非零，并输出 `doctor.ready / issues`；原有 `--check` 语义不变。
- 新增 `tools/install_rockchip_agent.sh`：仅 Linux/systemd；安装前执行 strict doctor；默认只启用 `deployment-test.rknn`。
- Agent Token 不进入安装命令或 systemd `ExecStart`；只保存到 root-owned、`0600` 的 EnvironmentFile。
- `ExecStartPre` 在每次服务启动前再次 doctor；SoC/RKNNLite 环境失效时不会假装上线。
- 服务节点页面新增 `conversion.rknn → 瑞芯微 RKNN 转换`、`deployment-test.rknn → 瑞芯微板端验证` 中文标签。
- 新增 Rockchip 板端快捷预设，一键选择远程 Agent + `deployment-test.rknn`。
- 节点卡片显示真实 `rknn_board.chip / RKNNLite version` 与 RKNN-Toolkit2 runtime truth。
- 一次性 Token 弹窗针对板端节点额外展示 strict doctor 与 systemd 安装命令；生成的 systemd 安装命令不包含 Token。
- 普通 Linux/Windows Agent 启动方式保持兼容。
- 当前工具链仍只认真实 RK3568/RK3566 family 或 RK3576；现场若写“RK3578”，必须先读取真实 `/proc/device-tree/compatible`。

最终软件验收（代码 HEAD `b8caf7753994988d5161321c2536ae75e64d3252`）：

- Service Node UI `35342366446`：Ubuntu / Windows contract + Real Chrome 全绿。
- Remote RKNN Board Runtime Protocol `35342366573`：API / Ubuntu / Windows / Real Chrome 全绿。
- Remote Conversion Runtime `35342369723`：control-plane / Ubuntu / Windows / Real Chrome 全绿。
- Node Agent Executor `35342369838`：API / Ubuntu / Windows 全绿。
- Central Node Assignment `35342369780`：API / Ubuntu / Windows 全绿。
- Remote Training Runtime `35342369831`：API / Ubuntu / Windows 全绿。
- Remote Material Import `35342369794`：API / Ubuntu / Windows / Real Chrome 全绿。
- Task Runtime Truth `35342369798`：全绿。
- Portable Deployment `35342369765`：全绿。
- `VERSION.txt = 42.24.0` 未修改。

**重要边界：这次 CLOSED 的是“实机接入的软件工具链”，不是你们手上某一台真实 Rockchip 板卡已经通过硬件验收。**

**当前主线：Rockchip 真实板卡 acceptance。**

下一步需要一台真实 RK3568 / RK3576（或先识别实际 SoC 的设备）运行本仓库 Node Agent。软件侧只继续做验收辅助：doctor → 节点 ONLINE/effective `deployment-test.rknn` → 选择一个 `converted_unverified` RKNN 模型 → 真板执行 RKNNLite inference → 只有成功后该具体模型才写 `hardware_verified=true`。CI、mock 或 x86 runner 都不能替代这一步。

# 最新关闭：Remote MODEL_CONVERSION / ONNX Runtime

2026-09-18，第三个真实跨机器 task kind 已 CLOSED：`MODEL_CONVERSION` 的 **ONNX** 目标。

当前 Agent 真实执行能力：

```text
deployment-test
training
conversion（当前只闭环 ONNX）
```

完整闭环：

- 部署资源新增显式 `mode=agent`；状态直接来自 Service Node Registry。
- 只有在线、enabled、allowed+reported 后形成 effective `conversion` 的 Agent 节点才可用。
- Agent ONNX 任务使用 portable verified model object，不把控制面 `stored_path/job_dir/worker_path/python_path` 发到节点执行。
- durable task 使用 Agent-only Worker capability fence，legacy local ConversionHandler 不会与中央 assignment 抢同一任务。
- Agent 下载模型并校验 Content-Length / size / SHA256。
- 节点本地调用本机 `deployment_worker.py` 与本机 Python；真实 ONNX export 后由 ONNX Runtime 做 runtime verification。
- subprocess 继续使用 persisted ProcessIdentity；cancel / lease loss / Agent shutdown 精确终止进程树。
- runner cleanup 不安全时动态撤销 conversion capability；没有 runner/effective capability 时在 `start_execution` **之前** fail closed。
- 输出本地计算 hash/size → prepare → generation-scoped immutable PUT → confirm。
- server-side finalization gate 后，控制面重新下载 ONNX 并再次校验 hash/size。
- 已验证 ONNX 写回原有 `deploy/jobs/<task>/artifacts/model.onnx`、`manifest.json` 和 `job.json`，部署中心现有产物列表/下载继续可用。
- 显式 Agent staging 失败禁止静默回退本机。
- TensorRT / RKNN / Sophon / Ascend 等厂商转换**尚未因为 ONNX closure 自动变成远程可用**。

最终验收：

- Remote Conversion Runtime `35306100598`：control-plane / Ubuntu / Windows 全绿。
- Node Agent Executor `35306100599`：API / Ubuntu / Windows 全绿。
- Central Node Assignment `35306100621`：API / Ubuntu / Windows 全绿。
- Portable Deployment `35306100612`：production API / Ubuntu / Windows 全绿。
- Remote Training Runtime `35306100615`：production API / Ubuntu / Windows 全绿。
- 临时 draft PR #15 已关闭，未 merge。
- `VERSION.txt` 仍为 `42.24.0`。

**当前主线：Remote MATERIAL_IMPORT Runtime。**

优先把大 ZIP / 图片素材导入从控制面重 IO 中拆到素材导入 Agent：安全解包、格式识别、标签转换/基础清洗、对象存储上传都在节点完成；中央端只在 server-confirm 后提交 MaterialRepository metadata。绝不能让远程素材节点直接访问中央 SQLite/NFS。

# 最新关闭：Remote TRAINING Runtime

2026-09-18，第二个真实跨机器 task kind 已 CLOSED：`TRAINING`。

当前 Agent **真实可执行**：

```text
deployment-test
training
```

其中 `training` 不是静态虚报：若 Agent 启动恢复时无法安全处理遗留训练进程，`AgentTrainingRunner.ready=false`，heartbeat 会动态移除 training capability。

完整闭环：

- remote train 创建同一个 durable TRAINING task，并创建独立 `TRAINING_PREPARE` 后台任务。
- prep Worker 锁定 split/snapshot，生成/复用 verified portable bundle。
- bundle 安全 ZIP 归档，持久化 SHA256 / size / member_count / snapshot_id，上传 OSS/S3/MinIO 后服务端再次校验。
- `target=remote` 在 READY 前不会回退本机 Worker。
- 首次官方模型只保存 allow-listed reference；算法迭代继续强制使用最新可训练上一版本，并转为 verified model object。
- Agent 下载并校验 bundle / object model，使用节点本地 `train_worker.py` 和节点本地 Python 启动真实 subprocess。
- heartbeat / progress / bounded logs 回到中央 execution truth。
- cancel / fence / Agent shutdown 终止精确进程树；进程树清理不可证明时 fail closed。
- best / last 作为独立 immutable model objects 上传并确认。
- training result 为 manifest-only bundle，不重复塞模型二进制。
- result/model 全部 server-confirm 后才允许 finalization，并写回统一 ModelArtifact / 算法版本 truth。
- Agent runtime 仍不打开中央 SQLite、不依赖 NFS。
- 已修复 portable 参数缺失时 `None` 未回退默认值导致 `int(None)` 的真实执行问题。

最终验收：

- Remote Training Runtime `35303815439`：Ubuntu / Windows / API 全绿。
- Node Agent Executor `35303815460`：Ubuntu / Windows / API 全绿。
- Central Node Assignment `35303815499`：Ubuntu / Windows / API 全绿。
- Portable Deployment `35303815438`：Ubuntu / Windows / production API 全绿。
- 临时 draft PR #14 已关闭，未 merge。
- `VERSION.txt` 仍为 `42.24.0`。

**当前主线：Remote MODEL_CONVERSION Runtime。**

现有 conversion handler 仍带中央 `job_dir / worker_path / python_path`，不能直接远程执行。下一步要把输入改为 verified model object，转换工具/SDK 由节点本地 capability 决定，输出走 generation-scoped immutable upload + server confirm；不能退回共享 SQLite/NFS。

# 最新关闭：服务节点控制面 + 中央分配 + Executor 控制协议 + Remote Portability

2026-09-18 已完成并验收：

- 服务节点 registry / heartbeat / 一次性 Agent Token / Windows+Linux 本机资源探测。
- 服务节点管理 UI，包含 CPU / RAM / disk / GPU / VRAM / Torch / CUDA / Worker / durable task 状态。
- 中央 durable task → node assignment truth。
- active assignment partial unique fence + legacy Worker `CENTRAL_NODE_ASSIGNED` 自抢保护。
- HTTP Agent Executor 控制协议：claim / start / heartbeat / log / begin-finalization / finish。
- Node Token、Assignment Lease Token、Execution Lease Token + generation 三层 fencing。
- Agent-side database-free HTTP client / isolated workdir / lease monitor。
- Remote portability gate：`agent` 节点只有遇到显式、版本化 portable contract 才允许调度；legacy path-bound task 不会误发远程。
- Scheduler 仅持久化 sanitized remote contract 元数据，不保存任务携带的 signed URL / credential / 中央路径。
- 生产 `app.py` 已正式、且只挂载一次 `training_recovery_router`；service-node / scheduler / executor 不再只存在于 focused test。
- Portability gate 验收：Central `35290891091`、Agent `35290891208`，均 API / Ubuntu / Windows 全绿。
- Production mount 验收：Central `35291195275`、Agent `35291195262`，均 API / Ubuntu / Windows 全绿。

权威设计：

`docs/NODE_CONTROL_PLANE_V42_25.md`

**下一步主线：第一个真正 portable 的远程 task kind。优先部署测试。**
需要复用已有模型资产统一 OSS/S3/MinIO 存储，建立远程输入/输出 transport，让 `node_agent.py` 真正 claim → start → 本机执行 → heartbeat/log/cancel → 上传结果 → finish。训练/素材的大文件仍不得退回共享 SQLite/NFS。

# 最新关闭：Portable Deployment Transport + Hash-bound Result Publication

2026-09-18 已进一步完成：

- 部署测试 durable task 可保存 version-1 `object-storage-v1` portable contract。
- 输入与项目模型通过统一 OSS / S3 / MinIO 模型资产和对象存储传输；官方模型保持 allow-listed reference。
- Agent start payload 不包含中央 `input_path / model_path / runner_path / python_path`。
- 输出 PUT 不在 start 阶段签发；Agent 必须先在本机计算结果 SHA256 + size，再通过 `result-upload/prepare` 申请短期 PUT。
- S3 / OSS presign 会绑定 Content-Length、SHA256 metadata 和禁止覆盖条件。
- 结果对象按 execution generation 隔离，旧代 PUT 无法占用新代结果 key。
- `result-upload/confirm` 由控制面 stat 并验证 size/hash；通过后再走 finalization 原子闸门。
- cancel 与 result publication 不能同时获胜。
- `finish(SUCCEEDED)` 不信任 Agent 自报 result_ref，强制使用当前 generation 的 server-confirmed result。
- signed URL 从不进入 Scheduler truth 或 durable result state。

验收：

- Portable transport：`35292400487` 全绿。
- Hash-bound result publication：Agent `35295427105`、Portable `35295427110`、Central `35295427100` 全绿。
- CI 临时 PR #11 / #12 均已关闭，未 merge。
- `VERSION.txt` 始终保持 `42.24.0`。

# 最新关闭：Agent-side Real Deployment Runtime

2026-09-18 已完成第一个真实跨机器 task kind：

- `node_agent.py` 已接入 database-free `NodeExecutorClient`。
- 仅上报当前 build 真正可执行的 `deployment-test` 远程能力，不虚报 training/conversion。
- 单并发 executor loop 真实 claim → start → dispatch。
- 输入与对象模型下载后逐字节校验 size/SHA256；官方模型只接受 allow-list reference。
- 推理使用节点本地 Python 与节点本地 runner，不解释控制面绝对路径。
- heartbeat/cancel/lease fencing 真实作用于节点本地 subprocess。
- cancel、lease loss、Agent shutdown 均通过 ProcessIdentity 终止精确进程树。
- 结果执行本地 hash → prepare → generation-scoped PUT → confirm → finalization → finish。
- workdir 在终态/fence 后清理。
- Agent executor 只在首次控制面 heartbeat 成功后启动。
- `node_agent.py` / executor loop / entrypoint 测试已进入永久 CI。

最新验收：

- Node Agent Executor `35297453169`：API / Ubuntu / Windows 全绿。
- Portable Deployment `35297453136`：production API / Ubuntu / Windows 全绿。
- `VERSION.txt` 仍为 `42.24.0`。

> 上述 Agent Deployment Runtime 段落是 2026-09-18 当时的关闭快照；Remote TRAINING 此后已按本文件更上方“最新关闭”完成。当前主线以最上方为准。


# 1. 产品定位

产品：**畅联云算法训练平台**。

当前优先目标不是做一个好看的 Demo，而是形成真实可用链路：

```text
素材导入
→ 数据清洗 / 标注
→ 训练配置
→ durable training task
→ 模型版本
→ 模型转换
→ 部署/发布
→ 线上算法回流
→ 评测
→ 低准确率算法再次迭代
```

当前主要算法框架：

```text
Ultralytics / YOLO
Paddle（兼容扩展）
OpenCV 等辅助能力
```

长期生产架构目标：

```text
Web / API
Scheduler
Training Worker
AI Label Worker
Video Worker
Model Conversion Worker
Deployment Test Worker
Publish Worker
```

Windows 负责开发、页面、普通 CPU 测试、素材/标注、视频切帧、小规模训练、ONNX 等；正式 GPU 训练/转换统一考虑 NVIDIA Linux。

---

# 2. 当前数据 owner / truth

这是最容易被新接手者弄乱的部分。

## 2.1 算法资产

**当前 authoritative store：SQL。**

主文件：

```text
platform_core/algorithm_sql_store.py
platform_core/algorithms.py
```

项目级存储目前为：

```text
algorithms.sqlite3
```

旧：

```text
algorithms.json
```

仅作为历史迁移源；首次迁移会保留：

```text
algorithms.json.pre-sql-migration-backup
```

### 重要：普通 CRUD 已经是 row-level SQL

不要再做一次“把 create/update/delete/version attach 从全量 replace 改为 SQL CRUD”的重复工作。

当前普通 owner 已经调用：

```text
AlgorithmSqlStore.create_algorithm
AlgorithmSqlStore.patch_algorithm
AlgorithmSqlStore.delete_algorithm
AlgorithmSqlStore.attach_version
AlgorithmSqlStore.patch_version
AlgorithmSqlStore.rollback_version
AlgorithmSqlStore.delete_version_with_operation
```

外部平台镜像也调用：

```text
AlgorithmSqlStore.sync_external_algorithms
```

`save_algorithms()` 仍保留用于兼容路径/测试，不代表主业务仍把 JSON 当数据库。

## 2.2 Durable Task

任务真实状态以后端 TaskRepository / durable task runtime 为准。

前端不能自己“猜”任务已经结束、排队第几名或剩余百分比。

当前已关闭的核心任务 truth 包括：

```text
Training
AI annotation
material batch
storage scan/import
server ZIP import
resource discovery
video processing
deployment tests
```

公共 task projection 的 authoritative 字段优先级参见 `docs/CODEX_CURRENT_STATE.md`。

## 2.3 上传任务用户可见 owner

现在统一是：

```text
static/modules/upload-task-center.js
```

右下角显示：

```text
普通图片上传
ZIP 分片上传
ZIP 合并/校验
后台导入
标签映射
标注写入
素材索引
```

旧单任务 `zipImportDurableDock` 只保留兼容/详情 owner；当统一 Task Center 存在时应保持隐藏，不能再恢复第二套可见浮窗。

---

# 3. ZIP 上传 / 标签导入当前实现

这是 2026-09-17 最新重点批次。

## 3.1 ZIP 网络上传

主文件：

```text
static/modules/zip-import-runtime.js
platform_core/zip_multipart.py
app.py
```

当前：

```text
part size:        8 MiB
max concurrency:  4
part retries:      2
```

服务器每个 part 独立持久化，最终 assemble：

```text
确认所有 part 完整
→ 合并
→ 精确检查 assembled bytes
→ 计算完整 ZIP SHA256
→ 标记 multipart completed
→ 清理 parts 目录
```

浏览器续传 fingerprint 已不再只用 filename/size/mtime，而加入文件头/中/尾采样内容摘要，降低误复用另一个 ZIP 分片的风险。

### 刷新时

如果刷新发生在 browser File 还在上传的阶段：

```text
任务状态显示：上传已暂停，等待继续
```

用户重新选择同一个 ZIP 后，浏览器重新计算 fingerprint，服务器返回已完成 parts，仅继续缺失部分。

不能在刷新后继续显示“正在传输字节”，因为浏览器已经没有原 File stream。

## 3.2 ZIP 整体进度

必须区分：

- 网络上传百分比；
- 整个 ZIP 导入任务百分比。

当前整体进度：

```text
网络上传：       0 → 35
服务器合并：     36
ZIP 校验：       37
等待后台导入：   38
后台任务：       38 → 99
全部完成：       100
```

实际网络上传百分比继续显示在文本详情。

禁止恢复“上传 100%，然后后台又退回 8%”的旧表现。

## 3.3 YOLO 标签映射 / 索引

主文件：

```text
platform_core/storage/import_tasks.py
```

标签确认后 durable 阶段包含：

```text
mapping_labels
writing_annotations
indexing
```

当前索引事务批次：

```text
INDEX_BATCH_SIZE = 50
```

不要再改回 500 张一个大批次。用户之前 500 张转换时长时间无反馈，核心原因之一就是一个超大的落库批次。

---

# 4. 训练任务当前实现

## 4.1 创建训练

训练弹窗必须直接带：

```text
算法名称
本次训练任务 ID
```

任务 ID 格式：

```text
train_<16~32 hex>
```

前端唯一网络 owner：

```text
TrainingSubmitRuntime
static/modules/training-submit.js
```

后端：

```text
/api/v12/projects/{project_id}/train/start
```

同一个 planned task ID 如果因为响应丢失被再次 POST：

- 同项目；
- 已存在 task kind = TRAINING；

则返回已有 task，不能创建第二个训练任务。

## 4.2 迭代训练

已有算法继续训练时，必须基于该算法**当前/最新成功、产物完整性已验证、框架匹配**的模型版本。

禁止因为上一轮失败就悄悄回到母算法重新训练。

相关：

```text
platform_core/algorithms.py
choose_algorithm_iteration_base()
resolve_current_version_id()
```

## 4.3 用户对训练弹窗的明确偏好

不要重新加回：

```text
预计时长
训练完成后通知
大量提示性废话
标签缩略图
标签右侧 xx 张
```

需要：

```text
算法名称默认带入
任务 ID
数据质量按钮
本次训练标签选择
训练摘要：轮次 / imgsz / batch / 阶段检查 / 转换等
```

---

# 5. 新畅联平台交互

## 5.1 Domain 关系

当前按：

```text
品目
→ 产品
→ 分析方式
→ 算法版本
→ 权重文件
→ 算力环境
```

外部算法主数据同步到本平台后：

```text
source_type = EXTERNAL
provider_type = CHANG_LIAN
master_data_readonly = true
```

本地已有算法不能因此消失。

外部产品从远端消失时：

```text
external_active = false
```

保留历史训练/版本，只阻止新训练。

多分析方式产品创建训练时必须明确绑定本次 `external_analysis_id`。

## 5.2 当前认证事实

现在不是最终 production canonical signing。

当前明确：

```text
/internal/auth/test-sign
→ /internal/auth/token
→ data.accessToken
→ 各业务接口按各自官方 OpenAPI 选择鉴权 Header
```

已确认的算法产品不分页接口：

```text
GET /internal/algorithm/product-ai/listAll
Authorization: Bearer <accessToken>
```

UI/API 明确暴露：

```text
auth_mode = test_sign_bridge
```

后续不能把这个事实改写成“正式签名已经确认”。

## 5.3 发布

已经实现 Phase 2：

```text
训练版本/转换产物
→ artifact index / object storage
→ stable download gateway
→ 新畅联创建算法版本
→ 新畅联创建权重
→ 保存 remote IDs
```

核心原则：

- 发布失败不能破坏本地已验证模型；
- 有 idempotence / retry / UNKNOWN 处理；
- HTTP timeout 后不能盲目重复创建远端对象。

详细见：

```text
docs/EXTERNAL_ALGORITHM_PUBLISH_PHASE2.md
```

---

# 6. 2026-09-17 BUG 审计结论

完整记录：

```text
docs/BUG_AUDIT_2026-09-17.md
```

本轮已经修复并进入永久测试：

```text
FIX-01 Linux 无 Keyring backend 导致 config 500
FIX-02 ZIP 整体进度 100 → 0/8 倒退
FIX-03 multipart 上传途中刷新后假装仍在上传
FIX-04 multipart fingerprint 元数据碰撞风险
FIX-05 Real Chrome 仍验证退休的单任务 dock
```

永久 workflow 最新本轮验收：

```text
ZIP Import Durable Runtime
Run ID: 35213047885
```

该 run：

```text
Ubuntu contracts                 PASS
Windows contracts                PASS
backend persistence              PASS
SecretStore contracts            PASS
multipart contracts              PASS
bounded 10k hot-state            PASS
Real Chrome refresh recovery     PASS
```

---

# 7. 当前 OPEN 项目

这部分不能在汇报里包装成“已完成”。

## CLOSED — Headless Linux Secret 持久化

状态：**CLOSED（代码与永久合同完成；真实生产主机仍需部署验收）**。

当前 SecretStore 已形成三层安全策略，禁止明文 JSON 回退：

```text
1. 环境变量只读注入（优先）
   MC_CHANGLIAN_ACCESS_KEY
   MC_CHANGLIAN_ACCESS_SECRET

2. 系统 Keyring
   Windows Credential Locker / Linux SecretService 等可用 backend

3. Headless Linux 加密文件 fallback
   MC_SECRET_MASTER_KEY
   → Fernet 加密
   → <data_dir>/secure/secrets.enc.json
```

`MC_SECRET_MASTER_KEY` 是服务器主密钥，必须由部署环境/Secret Manager 注入，不能写进仓库、普通 JSON 或前端。

配置页面会明确显示当前凭据后端：

```text
环境变量 / 系统密钥环 / 服务器加密文件 / 不可用
```

如果安全 backend 不可用，真实 Secret 写入继续 fail-closed，不会降级为明文保存。

相关主文件：

```text
platform_core/secrets.py
static/modules/external-algorithm-platform.js
requirements.txt
```

永久测试覆盖环境变量优先级、加密文件 round-trip、密文不包含明文 Secret、backend public state 和无 backend 安全降级。

## CLOSED — Multipart session TTL / GC

状态：**CLOSED**。

未完成 ZIP multipart session 现在包含：

```text
created_at
updated_at
expires_at
```

当前项目策略：

```text
默认 TTL：24 小时
每成功写入一个 part：刷新 updated_at / expires_at
completed session：不参与过期 GC
```

右下角 UploadTaskCenter 会轮询 v19 导入任务列表；该服务端入口会调用：

```text
cleanup_expired_if_due(interval_seconds=60)
```

因此正常使用平台时最多每 60 秒尝试一次 GC，而不是每次页面轮询都扫描磁盘。GC 记录：

```text
removed_uploads
released_bytes
last_run_at
```

新建/恢复 multipart session 时也会执行过期清理兜底。

## P1 — 真实 500 张 ZIP benchmark

代码结构已优化，但尚未用用户原先那个真实场景重新量化。

部署后必须拆阶段测：

```text
network
merge
validation
extract
format parse
annotation write
material index
total
```

## P1 — 新畅联 live contract 最终确认

仍需要真实环境确认：

```text
production canonical signature
filePath
chipCode
algoVersionId response
weight remote final state
remote commit recovery
```

## P2 — UploadTaskCenter 常驻 project switch interval

当前仍有：

```text
setInterval(switchProject, 1500)
```

后续应由 NavigationStability / project owner 主动通知，不应该长期轮询项目 ID。

## P2 — 外部平台 auto-sync 在 Web 进程 daemon thread

当前实现：daemon thread **每 5 秒只检查一次 due**，真正的新畅联 Provider 主数据拉取由服务端固定 **60 秒间隔**限流；FileLock 避免同共享数据目录并发执行同一轮同步。单进程/当前部署可用，但多 API worker / 多机后应迁到现有 Scheduler/Worker。

不要因此新造第二套 scheduler。

## 架构演进 — PostgreSQL

当前 algorithm SQL 是 per-project SQLite。

它是当前单机/开发可用方案，不代表适合 NFS 多机器中央事务数据库。

未来保留 Repository abstraction，新增 PostgreSQL backend；不要把 SQLite over NFS 当最终答案。

---

# 8. 当前最重要代码索引

## 算法 / SQL

```text
platform_core/algorithm_sql_store.py
platform_core/algorithms.py
tests/unit/test_algorithm_sql_store.py
tests/unit/test_algorithms.py
.github/workflows/algorithm-sql-store.yml
```

## 上传 / 导入

```text
platform_core/zip_multipart.py
platform_core/storage/import_tasks.py
static/modules/zip-import-runtime.js
static/modules/upload-task-center.js
static/modules/storage-import-progress.js
static/zip-import-bootstrap.mjs
app.py
```

测试：

```text
tests/unit/test_zip_multipart.py
tests/unit/test_secrets.py
tests/frontend/zip-import-durable-runtime.test.mjs
tests/frontend/zip-multipart-upload.test.mjs
tests/frontend/upload-task-center.test.mjs
tests/frontend/storage-import-progress.test.mjs
tests/browser/zip-import-refresh-recovery.spec.mjs
tests/api/test_v19_job_atomic_persistence.py
tests/api/test_v19_import_scalability.py
```

永久 CI：

```text
.github/workflows/zip-import-durable-runtime.yml
```

## 训练

```text
static/modules/training-draft.js
static/modules/training-draft-runtime.js
static/modules/training-submit.js
static/modules/training-task-runtime.js
static/modules/training-task-visibility-runtime.js
platform_core/algorithms.py
app.py
```

永久 CI：

```text
.github/workflows/training-task-visibility.yml
```

## 新畅联

```text
platform_core/external_algorithm_platform.py
platform_core/external_algorithm_publish.py
static/modules/external-algorithm-platform.js
static/modules/external-algorithm-publish.js
docs/EXTERNAL_ALGORITHM_PUBLISH_PHASE2.md
```

## Secret

```text
platform_core/secrets.py
tests/unit/test_secrets.py
```

---

# 9. 不要重复的 CLOSED 工作

除非你找到新的、可复现证据，否则不要重新开启：

```text
training mirror fields
/train/start single owner
/jobs duplicate race
training metrics SQLite FD leak
training / AutoLabel / video / source polling owner
setupPagePolling legacy timer cleanup
classic setPage owner cleanup
Task Runtime Truth
Worker Runtime Truth
Training Queue Readiness Truth
Training Bundle Snapshot Cache
algorithm JSON → SQL migration
algorithm row-level CRUD migration
external algorithm mirror preserving local algorithms
external inactive preservation
external multi-analysis training binding
external publish Phase 2 base implementation
ZIP durable runtime owner
ZIP resumable multipart base implementation
training planned task id identity
```

如果某个 CLOSED 项目现在失败：

1. 先给出复现；
2. 找 regression commit；
3. 修 regression；
4. 不要把旧架构整体重写一遍。

---

# 10. 推荐下一批实际工作

如果用户没有重新指定其他方向，建议按：

```text
1. Headless Linux SecretStore 正式方案
2. Multipart session TTL / GC
3. 真实 500 张 ZIP 分阶段 benchmark + 性能热点优化
4. 新畅联 live API 最终合同验证
5. UploadTaskCenter 去除 project-switch 常驻 interval
6. External auto-sync 迁入现有 durable scheduler/worker
7. 多机前再做 PostgreSQL Repository backend
```

其中第 3 项必须用真实 ZIP，不能根据单元测试估算“优化了多少倍”。

---

# 11. 每次交付最低检查

至少：

```bash
cat VERSION.txt
git status
git rev-parse HEAD
git diff --check
```

按涉及模块跑 focused tests。

上传链路至少确认：

```text
Ubuntu contract
Windows contract
backend persistence
Real Chrome refresh recovery
```

训练链路至少确认：

```text
TrainingSubmitRuntime 单 owner
planned task ID = backend durable task ID
刷新后任务可见
重复提交幂等
```

算法 SQL 至少确认：

```text
legacy JSON 迁移不丢 ID
本地算法不被 external sync 删除
row-level CRUD
version current pointer
rollback/delete transaction
```

最后再确认：

```text
main 未被误改
VERSION.txt 仍为 42.24.0
无临时 one-shot helper/workflow 残留
```

---

# 12. 给下一位 AI 的一句话

**不要从头重构。先读取远端真实 HEAD 和本文件，从当前已验证 owner / SQL / durable task / upload runtime 上继续，把 OPEN 项逐个关闭；任何“性能更快”必须用真实阶段数据证明，任何“可恢复”必须经过刷新/中断测试证明。**


## CLOSED — Training label filter task-derived negatives

2026-09-17 product rule: selected materials stay in the training task. The training label checkbox defines the positive schema. If all source boxes are excluded by that schema, the task projection becomes an auditable background sample (`negative_origin=filtered_by_training_labels`) without mutating source annotations. Mixed-label images retain selected boxes. Explicit `确认无目标` remains distinct.

## 2026-09-20 — 标注统一 + 显式新建平台标签（IMPLEMENTED / CI PENDING）

产品规则已澄清：批量导入或 AI 候选复核时，如果平台没有合适标签，**允许用户在当前确认流程中显式创建新的正式平台标签**；但外部数据集类别名不得因为上传/确认而被系统隐式创建成 canonical label。

当前合同：

- YOLO / COCO / VOC 等外部类别先进入“外部类别 → 平台标签”人工确认；支持多对一，例如 `toukui1`、`toukui2` → `helmet`。
- ZIP、Storage Import、Storage Rescan、AI Candidate Review 都提供“＋ 新建平台标签”。
- 新建动作复用配置中心标签管理的 canonical API：`POST /api/projects/{project_id}/labels`；后端同时校验 canonical code 只能以英文字母开头，并由英文、数字、`_`、`-` 组成。
- 新建成功只会新增标签元数据并自动选中当前映射；**不会直接写 Ground Truth**。用户仍必须点击当前导入/AI 审核确认，之后才进入正式入库。
- 导入/审核确认 payload 继续保持 mapping-only；旧 `create_labels` 确认旁路继续 fail-closed，禁止通过外部名字静默 `ensure_label()`。
- 映射确认成功后才学习别名；例如新建 `helmet` 并确认 `toukui1`、`toukui2` → `helmet` 后，这两个外部名称才成为 `helmet.aliases`。
- AI 仍保持 Candidate → `AWAITING_CONFIRMATION` → Human Review → Durable Commit → AnnotationRepository；候选结果不会绕过人工确认直接写正式标注。
- 标签转换 / 导入等长任务的进度仍以现有 Durable Task / v19 backend truth 为准，不新增浏览器自造进度 owner。
- `VERSION.txt` 继续保持 `42.24.0`；未 merge main、未 tag、未 release。

本批主要实现提交从 `ecb466a` 起，包含四入口 UI、canonical API 复用、API/前端测试、缓存版本和 Label Normalization Contract 永久守卫。最终 GitHub Actions 结论必须以最新 HEAD 的实际 run 为准；queued 不等于通过。



---

<!-- CHANGLIAN_AUTOMATIC_DELIVERY_2026_09_20 -->
# 最新收口：训练成果自动交付 + 删除式回退 + 统一存储配置

2026-09-20 本轮按产品需求收口以下合同：

- **算法回退 = 删除当前版本并回到目标历史版本**。外部新畅联算法会先调用官方 `GET /internal/algorithm/algorithm-version/remove/{algoVersionIds}`；远端删除失败时本地不删除。直接删除历史外部版本同样先删远端，再删本地。
- 训练成功版本先落本平台算法版本库；原始训练模型进入统一 Model Artifact 库并自动上传已配置存储。新畅联同步随后创建算法版本并登记权重，保存远端 `algoVersionId / weightId`。
- 转换结果（当前包括 ONNX / RKNN 等）完成后进入同一 Model Artifact 库并自动上传；如果远端版本已经存在，只向同一 `algoVersionId` 追加新权重，不重复建版本，也不重复登记已存在权重。
- Model Artifact 本地数据库新增稳定 `public_url` truth；新畅联 `filePath` 使用“存储配置 → 算法与转换结果存储”的 OSS Bucket / CDN 长期访问域名，不把会过期的临时签名 URL 写入远端数据库。
- 原“素材存储配置”页面统一改名为 **存储配置**：保留“素材存储”，新增“算法与转换结果存储”。算法产物存储选择现有存储源并配置对象前缀与长期访问域名；训练/转换结果自动归档为平台强制规则，不能被前端关闭。
- 新畅联当前无 Webhook / subscription 合同，因此外部模式固定 **每 60 秒主动拉取主数据**；前端不允许关闭或改成更长间隔。调度线程每 5 秒检查 due，但真正 Provider 请求仍由 60 秒条件限流。
- 自动发布不再只依赖训练结束瞬间的 `external_publish_requested_at` 标记；后台会恢复成功且 `artifact_verified=true` 的外部训练版本，防止一次钩子失败造成永久漏单。
- 新畅联业务接口鉴权继续遵循完整 31 项 OpenAPI 汇编：`Authorization: Bearer <accessToken>`。不要把旧 `Access-Token` Header 结论恢复回来。

仍需生产/live E2E 验证：真实 OSS `filePath` 可访问性、新建版本/权重真实返回、删除版本真实副作用、以及超时后的远端反查恢复。

- 训练准入已做 API 级 fail-closed：新畅联算法必须从完整 `external_analyses` 详情中证明 `status=1 AND analysisType=1`；缺字段、停用视觉、预留分析、大模型分析均不可训练。Durable Training、旧 `/api/projects/.../train/start` 与旧 `/api/v12/.../train/start` 都必须走同一后端 gate，不能依赖前端禁用按钮。
- 分析方式训练资格的**权威真值来自** `GET /internal/algorithm/algorithm-analysis/getInfo/{analysisId}`。同步流程先用 `listByProduct/{productId}` 获取 analysisId，再逐条读取 getInfo；详情中的 `status / analysisType` 覆盖列表摘要。详情缺少这两个字段、analysisId 不一致或 productId 冲突时本轮同步 fail-closed，保留上一轮成功缓存。测试连接/诊断也只读抽查 getInfo，避免“连接测试成功但正式同步失败”。
- 新畅联发布同样 fail-closed：每个训练版本必须自身持久化 `external_analysis_id`，且当前同步详情仍证明该 ID 满足 `status=1 AND analysisType=1`。发布不允许从算法当前默认 analysisId 补写历史版本，也不允许退化成 `productId` 创建远端版本；版本级血缘缺失时返回 `EXTERNAL_VERSION_ANALYSIS_MISSING`，不产生远端写入。
- 本地训练归档和 Durable/Agent 远程训练归档都必须把训练任务 truth 中的 `external_analysis_id` 写入新版本。远程归档幂等重放若发现同一 task 已生成版本但漏字段，只允许从该 task payload 回填，不能从算法当前默认 analysisId 推断。

- 远程 MODEL_CONVERSION 结果当前可能落在 `deploy/jobs`，历史/本地转换主要落在 `deployment/jobs`。Model Artifact 与 ChangLian 发布发现器必须同时扫描两者并按 job id 去重；远程提交必须持久化 `source_trace.algorithm_id/version_id`，否则 RKNN/ONNX 虽已完成也会漏掉自动归档和远端权重追加。
- 远程 TRAINING 已上传并校验到当前统一模型存储的同 SHA 主模型，在畅联云发布时直接复用已有对象与 `public_url`，禁止为了 `original` 语义重复占一份 OSS 对象。
- “算法与转换结果存储”只把真正可部署模型当算法产物：ONNX=`.onnx`、Rockchip=`.rknn` 等；`manifest.json` 保留为任务证据，不计作模型权重资产。
- “测试存储”同时验证凭据读写和最终长期 `filePath` 的实际可读性。OSS 能写但长期 URL 返回 403/404/网络不可达时必须阻止误判为“配置可用”；不要把会过期的临时签名 URL 写入新畅联。


---

<!-- CHANGLIAN_DELIVERY_HARDENING_2026_09_20 -->
## 2026-09-20 — 新畅联自动交付链可靠性加固

在“训练成果自动交付 + 删除式回退 + 统一存储配置”基础上，继续关闭以下一致性缺口：

- `rollback_algorithm_version()` 服务层已强制 **rollback = delete current version**。保留旧参数仅为调用兼容，即使旧内部调用显式传 `delete_current_version=False`，也不能恢复 pointer-only rollback。API 继续使用 `Literal[True]`。
- 外部算法回退/历史版本删除都先调用新畅联官方 version remove；远端失败时本地不动。若远端已经返回删除成功，但本地 SQLite 原子事务随后失败，分别返回：
  - `ALGORITHM_ROLLBACK_LOCAL_COMMIT_FAILED_AFTER_REMOTE_DELETE`
  - `ALGORITHM_DELETE_LOCAL_COMMIT_FAILED_AFTER_REMOTE_DELETE`
  明确标记“远端已删、本地未落库”，不得再次盲删或重建远端。
- MODEL_CONVERSION 发现器必须同时扫描 `deployment/jobs` 与 `deploy/jobs`，按 job id 去重；Agent 提交必须持久化 `source_trace.algorithm_id/version_id`。
- 远程 TRAINING 已经上传并校验到 canonical Model Artifact Storage 的同 SHA 模型，发布到新畅联时复用原对象和 `public_url`，不重复上传一份 `original`。
- Model Artifact 只把真正部署产物归档为模型资产；`manifest.json` 等任务证据不作为新畅联权重文件。
- 存储测试现在不仅验证 OSS 凭据写/查/删，还用最终长期 URL 读取临时对象。长期 URL 403/404/网络不可达时返回 `MODEL_ARTIFACT_PUBLIC_URL_UNREACHABLE`，避免“OSS 能写但畅联云 filePath 不能读”的假成功。
- 算法产物自动归档为后端强制规则；前端不存在关闭开关。新畅联主数据外部模式固定 60 秒拉取，前端不存在间隔选择器。
- 正式环境“算法与转换结果存储”选择器仅展示已启用 OSS；旧开发环境若已保存非 OSS，仅保留“开发兼容”项用于迁移。素材存储仍支持现有本地 / OSS / S3 / 服务器等来源。
- Real Chrome `tests/browser/storage-source.spec.mjs` 已补统一存储页验收：必须同时看到“素材存储”和“算法与转换结果存储”，以及自动归档、长期 URL、从 OSS 生成入口。
- 自动成果发布 Worker 当前每 30 秒扫描一次。该扫描涉及模型发现/校验，暂不降到 5 秒；主数据同步 thread 每 5 秒仅检查 due，Provider 请求仍严格 60 秒限流。
- `VERSION.txt` 仍必须保持 `42.24.0`；当前 CI 结论以最新 HEAD 实际 Actions 为准，queued 不等于通过。

---

<!-- CHANGLIAN_REMOTE_CONVERSION_COLLISION_2026_09_20 -->
## 2026-09-20 — Agent 转换 dual-root 同 ID 冲突已加固

- 真实 Agent 转换会先在 `deployment/jobs/{task_id}` 写控制面 job，durable 结果提交后再在 `deploy/jobs/{task_id}` 写包含真实输出的 committed job；两者 **task/job id 相同**。
- Model Artifact 与 External Publish 发现器继续同时兼容两个根，但去重时必须优先读取 `deploy/jobs`。如果旧 `deployment/jobs` 先被加入 `seen`，其陈旧 `queued` / 空 outputs 会遮住 durable `done` / RKNN 输出，造成远程转换结果漏归档、漏追加畅联云权重，并可能把已完成转换误显示为仍在进行。
- 当前已把两个发现器的 root 顺序固定为：`deploy/jobs` → `deployment/jobs`，同 ID 时 durable committed result 为权威结果，旧根只作兼容兜底。
- 新增永久回归：
  - `test_auto_upload_prefers_durable_remote_conversion_when_job_id_exists_in_both_roots`
  - `test_publish_prefers_durable_remote_conversion_when_job_id_exists_in_both_roots`
- `External Algorithm Publish` CI 已固定 root precedence 和两条回归测试名称，禁止后续又退回旧根优先。
- 这次属于后端结果发现/同步修复，不改变前端字段或交互；`VERSION.txt` 仍为 `42.24.0`。
- 当前 GitHub Actions 仍必须以最新 HEAD 的实际 completed 结果为准；queued 不等于通过，也不具备部署资格。
